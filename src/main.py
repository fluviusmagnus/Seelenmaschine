import os
import logging
from datetime import datetime
from config import Config
from memory import MemoryManager
from llm import LLMClient
from prompts import PromptBuilder, SystemPrompts
from utils import remove_cite_tags


class ChatBot:
    def __init__(self):
        self._init_logging()
        self.memory = MemoryManager()
        self.llm = LLMClient()
        self.prompt_builder = PromptBuilder()
        self.session_id, self.start_time, self.current_conv_count = (
            self.memory.get_or_create_session()
        )
        self.persona_memory = self._load_persona_memory()
        self.user_profile = self._load_user_profile()

        # 加载现有会话数据
        existing_conv = self.memory.get_recent_conversations(
            self.session_id, self.current_conv_count
        )
        print(f"\n当前会话ID: {self.session_id}")
        print(f"开始时间: {self.start_time}")
        if existing_conv:
            print(f"\n最后{len(existing_conv)}条历史对话:")
            for role, text in existing_conv:
                # 非调试模式下显示清理后的文本
                display_text = (
                    remove_cite_tags(text)
                    if role == "assistant" and not Config.DEBUG_MODE
                    else text
                )
                print(f"{role}: {display_text}")
        print("\n输入消息开始对话(输入 /help 查看可用命令)")

    def _init_logging(self):
        os.makedirs(os.path.dirname(Config.LOG_PATH), exist_ok=True)

        # 配置根日志记录器
        logging.basicConfig(
            filename=Config.LOG_PATH,
            level=logging.DEBUG if Config.DEBUG_MODE else logging.INFO,
            format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        )

        # 设置网络通信的日志级别为WARNING
        for logger_name in [
            "httpx",
            "httpcore",
            "httpcore.http11",
            "httpcore.connection",
            "openai",
        ]:
            logging.getLogger(logger_name).setLevel(logging.WARNING)

    def _load_persona_memory(self) -> str:
        if os.path.exists(Config.PERSONA_MEMORY_PATH):
            with open(Config.PERSONA_MEMORY_PATH, "r", encoding="utf-8") as f:
                return f.read()
        return ""

    def _load_user_profile(self) -> str:
        if os.path.exists(Config.USER_PROFILE_PATH):
            with open(Config.USER_PROFILE_PATH, "r", encoding="utf-8") as f:
                return f.read()
        return ""

    def _handle_command(self, command: str) -> bool:
        if command == "/help":
            print("\n可用命令:")
            print("/reset - 重置当前会话")
            print("/save  - 保存并归档当前会话,开始新会话")
            print("/exit  - 保存当前状态并退出程序")
            print("/help  - 显示此帮助信息")
            return True
        elif command == "/reset":
            self.memory.reset_session(self.session_id)
            self.current_conv_count = 0
            print("\n当前会话已重置")
            return True
        elif command == "/save":
            self._finalize_session()
            self.session_id, self.start_time, self.current_conv_count = (
                self.memory.get_or_create_session()
            )
            print(f"\n新会话已创建")
            print(f"ID: {self.session_id}")
            print(f"开始时间: {self.start_time}")
            return True
        elif command == "/exit":
            print("\n会话已保存,下次启动将恢复当前状态")
            exit()
        return False

    def _finalize_session(self) -> None:
        """结束当前会话,更新记忆"""
        # 首先清理数据库中的cite标签
        self.memory.close_session(self.session_id)

        # 获取清理后的对话记录用于生成总结
        conversations = self.memory.get_recent_conversations(
            self.session_id, self.current_conv_count
        )
        conv_text = "\n".join([f"{role}: {text}" for role, text in conversations])

        # 生成最终总结
        current_summary = self.memory.get_current_summary(self.session_id)
        final_summary = self.llm.generate_response(
            [
                {
                    "role": "user",
                    "content": self.prompt_builder.build_summary_prompt(
                        current_summary, conv_text
                    ),
                }
            ]
        )
        self.memory.update_summary(self.session_id, final_summary)

        # 更新人格记忆
        updated_persona = self.llm.generate_response(
            [
                {
                    "role": "user",
                    "content": self.prompt_builder.build_persona_update_prompt(
                        self.persona_memory, final_summary
                    ),
                }
            ]
        )
        self.memory.update_persona_memory(updated_persona)
        self.persona_memory = updated_persona

        # 更新用户档案
        updated_profile = self.llm.generate_response(
            [
                {
                    "role": "user",
                    "content": self.prompt_builder.build_user_profile_update_prompt(
                        self.user_profile, final_summary
                    ),
                }
            ]
        )
        self.memory.update_user_profile(updated_profile)
        self.user_profile = updated_profile

        # 清理向量数据库
        self.memory.clean_vector_db()

    def _update_summaries(self) -> None:
        """更新对话总结"""
        # 当对话轮数超过MAX_CONV_NUM时,总结较早的REFRESH_EVERY_CONV_NUM轮对话
        if self.current_conv_count > Config.MAX_CONV_NUM:
            # 获取最早的REFRESH_EVERY_CONV_NUM轮对话
            conversations_to_summarize = self.memory.get_recent_conversations(
                self.session_id, Config.REFRESH_EVERY_CONV_NUM
            )

            if conversations_to_summarize:
                # 清理cite标签
                cleaned_conversations = [
                    (role, remove_cite_tags(text) if role == "assistant" else text)
                    for role, text in conversations_to_summarize
                ]
                conv_text = "\n".join(
                    [f"{role}: {text}" for role, text in cleaned_conversations]
                )
                current_summary = self.memory.get_current_summary(self.session_id)

                # 生成新的总结
                new_summary = self.llm.generate_response(
                    [
                        {
                            "role": "user",
                            "content": self.prompt_builder.build_summary_prompt(
                                current_summary, conv_text
                            ),
                        }
                    ]
                )
                self.memory.update_summary(self.session_id, new_summary)

                # 在memory中更新current_conv_count
                self.current_conv_count = self.memory.update_conv_count(
                    self.session_id, -Config.REFRESH_EVERY_CONV_NUM
                )

    def run(self) -> None:
        """运行聊天机器人"""
        while True:
            try:
                user_input = input("> ").strip()
                if not user_input:
                    continue

                # 处理命令
                if user_input.startswith("/"):
                    if self._handle_command(user_input):
                        continue

                # 保存用户对话并更新计数
                self.memory.add_conversation(self.session_id, "user", user_input)
                self.current_conv_count = self.memory.get_conv_count(self.session_id)

                # 更新对话总结
                self._update_summaries()

                # 获取相关记忆
                related_summaries, related_conversations = (
                    self.memory.search_related_memories(user_input, self.session_id)
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

                if Config.DEBUG_MODE:
                    logging.debug(f"Session: {self.session_id} 完整提示词: {messages}")

                response = self.llm.generate_response(messages)
                # 非调试模式下显示清理后的文本
                display_text = (
                    remove_cite_tags(response) if not Config.DEBUG_MODE else response
                )
                print(f"\nAI: {display_text}")

                # 保存AI响应并更新计数
                self.memory.add_conversation(self.session_id, "assistant", response)
                self.current_conv_count = self.memory.get_conv_count(self.session_id)

            except KeyboardInterrupt:
                exit()
            except Exception as e:
                logging.error(f"运行时错误: {str(e)}")
                print("发生错误,请检查日志文件")


if __name__ == "__main__":
    bot = ChatBot()
    bot.run()
