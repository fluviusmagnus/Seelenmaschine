import os
import logging
from datetime import datetime
from config import Config
from memory import MemoryManager
from llm import LLMClient
from prompts import PromptBuilder, SystemPrompts
import utils


class ChatBot:
    def __init__(self):
        self.memory = MemoryManager()
        self.llm = LLMClient()
        self.prompt_builder = PromptBuilder()
        self.session_id, self.start_time, self.current_conv_count = (
            self.memory.get_or_create_session()
        )
        self.persona_memory = self.memory.get_persona_memory()
        self.user_profile = self.memory.get_user_profile()

    def reset_session(self):
        """重置当前会话"""
        self.memory.reset_session(self.session_id)
        self.current_conv_count = 0
        logging.debug(f"会话 {self.session_id} 已重置")
        return self.get_session_info()

    def finalize_session(self):
        """结束当前会话,更新记忆,并创建新会话"""
        logging.debug(f"正在归档会话 {self.session_id}")
        # 首先清理数据库中的cite标签
        self.memory.close_session(self.session_id)

        # 获取清理后的对话记录用于生成总结
        conversations = self.memory.get_recent_conversations(
            self.session_id, self.current_conv_count
        )
        conv_text = "\n".join(
            [
                f"{Config.AI_NAME if role == 'assistant' else Config.USER_NAME}: {text}"
                for role, text in conversations
            ]
        )

        # 生成最终总结
        current_summary = self.memory.get_current_summary(self.session_id)
        final_summary = self.llm.generate_response(
            Config.TOOL_MODEL,
            [
                {
                    "role": "user",
                    "content": self.prompt_builder.build_summary_prompt(
                        current_summary, conv_text
                    ),
                }
            ],
        )
        self.memory.update_summary(
            self.session_id,
            final_summary + " 对话结束于: " + utils.date_str(utils.now_tz()),
        )

        # 更新人格记忆
        updated_persona = self.llm.generate_response(
            Config.TOOL_MODEL,
            [
                {
                    "role": "user",
                    "content": self.prompt_builder.build_persona_update_prompt(
                        self.persona_memory, final_summary
                    ),
                }
            ],
        )
        self.memory.update_persona_memory(updated_persona)
        self.persona_memory = self.memory.get_persona_memory()

        # 更新用户档案
        updated_profile = self.llm.generate_response(
            Config.TOOL_MODEL,
            [
                {
                    "role": "user",
                    "content": self.prompt_builder.build_user_profile_update_prompt(
                        self.user_profile, final_summary
                    ),
                }
            ],
        )
        self.memory.update_user_profile(updated_profile)
        self.user_profile = self.memory.get_user_profile()

        # 清理embedding缓存
        self.memory.embedding_cache = {}

        # 清理向量数据库
        self.memory.clean_vector_db()

        # 创建新会话
        self.session_id, self.start_time, self.current_conv_count = (
            self.memory.get_or_create_session()
        )
        logging.debug(f"创建新会话 {self.session_id}")
        return self.get_session_info()

    def _update_summaries(self) -> None:
        """更新对话总结"""
        # 当对话轮数超过MAX_CONV_NUM时,总结较早的REFRESH_EVERY_CONV_NUM轮对话
        if self.current_conv_count > Config.MAX_CONV_NUM:
            logging.debug(
                f"对话轮数 {self.current_conv_count} 超过最大限制 {Config.MAX_CONV_NUM}，开始更新总结"
            )
            # 获取最早的REFRESH_EVERY_CONV_NUM轮对话
            conversations_to_summarize = self.memory.get_recent_conversations(
                self.session_id, self.current_conv_count
            )[: Config.REFRESH_EVERY_CONV_NUM]

            if conversations_to_summarize:
                # 清理blockquote标签
                cleaned_conversations = [
                    (
                        role,
                        (
                            utils.remove_blockquote_tags(text)
                            if role == "assistant"
                            else text
                        ),
                    )
                    for role, text in conversations_to_summarize
                ]
                conv_text = "\n".join(
                    [
                        f"{Config.AI_NAME if role == 'assistant' else Config.USER_NAME}: {text}"
                        for role, text in cleaned_conversations
                    ]
                )
                current_summary = self.memory.get_current_summary(self.session_id)

                # 生成新的总结
                new_summary = self.llm.generate_response(
                    Config.TOOL_MODEL,
                    [
                        {
                            "role": "user",
                            "content": self.prompt_builder.build_summary_prompt(
                                current_summary, conv_text
                            ),
                        }
                    ],
                )
                self.memory.update_summary(self.session_id, new_summary)
                logging.debug(f"更新会话 {self.session_id} 的总结")

                # 在memory中更新current_conv_count
                self.current_conv_count = self.memory.update_conv_count(
                    self.session_id, -Config.REFRESH_EVERY_CONV_NUM
                )
                logging.debug(f"更新后的对话轮数: {self.current_conv_count}")

    def get_session_info(self):
        """获取当前会话信息"""
        # 从数据库获取最新数据
        self.session_id, self.start_time, self.current_conv_count = (
            self.memory.get_or_create_session()
        )

        return {
            "session_id": self.session_id,
            "start_time": self.start_time,
            "current_conv_count": self.current_conv_count,
        }

    def get_conversation_history(self, count=None):
        """获取对话历史"""
        if count is None:
            count = self.current_conv_count
        return self.memory.get_recent_conversations(self.session_id, count)

    def process_user_input(self, user_input):
        """处理用户输入并获取响应"""
        logging.debug(f"处理用户输入: {user_input}")
        # 保存用户对话并更新计数
        self.memory.add_conversation(self.session_id, "user", user_input)
        self.current_conv_count = self.memory.get_conv_count(self.session_id)
        logging.debug(f"当前对话轮数: {self.current_conv_count}")

        # 更新对话总结
        self._update_summaries()

        # 获取相关记忆
        related_summaries, related_conversations = self.memory.search_related_memories(
            user_input, self.session_id
        )
        logging.debug(
            f"找到 {len(related_summaries)} 条相关摘要和 {len(related_conversations)} 条相关对话"
        )

        # 获取当前对话历史
        current_conversations = self.memory.get_recent_conversations(
            self.session_id, self.current_conv_count
        )
        current_summary = self.memory.get_current_summary(self.session_id)

        # 构建完整提示并获取响应
        messages = self.prompt_builder.build_chat_prompt(
            system_prompt=SystemPrompts.get_chat_system_prompt(),
            persona_memory=self.persona_memory,
            user_profile=self.user_profile,
            current_summary=current_summary,
            related_summaries=related_summaries,
            related_conversations=related_conversations,
            current_conversations=current_conversations,
            user_input=user_input,
        )

        response = self.llm.generate_response(Config.CHAT_MODEL, messages)

        # 保存AI响应并更新计数
        self.memory.add_conversation(self.session_id, "assistant", response)
        self.current_conv_count = self.memory.get_conv_count(self.session_id)

        return response
