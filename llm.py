import os
import json
from typing import List, Dict, Any, Optional
import openai
from openai import OpenAI


class LLMInterface:
    """处理与大语言模型的所有交互"""

    def __init__(
        self, config_path: str = "config.txt", prompts_path: str = "prompts.txt"
    ):
        """初始化LLM接口

        Args:
            config_path: 配置文件路径
            prompts_path: 提示词模板文件路径
        """
        # 加载配置
        self.config = self._load_config(config_path)
        self.prompts = self._load_prompts(prompts_path)

        # 设置OpenAI客户端
        self.client = OpenAI(
            api_key=self.config["OPENAI_API_KEY"],
            base_url=self.config["OPENAI_API_BASE"],
        )

    def _load_config(self, path: str) -> Dict[str, Any]:
        """加载配置文件"""
        config = {}
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    key, value = line.split("=", 1)
                    config[key.strip()] = value.strip()
        return config

    def _load_prompts(self, path: str) -> Dict[str, str]:
        """加载提示词模板"""
        prompts = {}
        current_key = None
        current_content = []

        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                if line.startswith("#"):
                    continue
                if "=" in line and not current_key:
                    key, content = line.split("=", 1)
                    current_key = key.strip()
                    if '"""' in content:
                        current_content = [content.split('"""', 1)[1]]
                    else:
                        prompts[current_key] = content.strip()
                        current_key = None
                elif current_key:
                    if '"""' in line:
                        current_content.append(line.split('"""')[0])
                        prompts[current_key] = "\n".join(current_content)
                        current_key = None
                        current_content = []
                    else:
                        current_content.append(line)

        return prompts

    def get_embedding(self, text: str) -> List[float]:
        """获取文本的向量表示

        Args:
            text: 输入文本

        Returns:
            文本的向量表示
        """
        response = self.client.embeddings.create(
            model=self.config["EMBEDDING_MODEL"], input=text
        )
        return response.data[0].embedding

    def chat(
        self,
        user_input: str,
        self_perception: str,
        user_perception: str,
        conversation_summary: Optional[str],
        relevant_memories: List[Dict[str, Any]],
        current_conversation: List[Dict[str, str]],
    ) -> str:
        """生成对话回复

        Args:
            user_input: 用户输入
            self_perception: 自我认知
            user_perception: 用户形象
            conversation_summary: 当前会话的总结(如果有)
            relevant_memories: 相关的历史记忆
            current_conversation: 当前会话历史

        Returns:
            AI助手的回复
        """
        # 构建消息列表
        messages = [{"role": "system", "content": self.prompts["SYSTEM_PROMPT"]}]

        # 添加人格记忆
        messages.append(
            {
                "role": "system",
                "content": f"你的自我认知:\n{self_perception}\n\n用户形象:\n{user_perception}",
            }
        )

        # 添加当前会话总结(如果有)
        if conversation_summary:
            messages.append(
                {"role": "system", "content": f"当前会话总结:\n{conversation_summary}"}
            )

        # 添加相关记忆
        if relevant_memories:
            memory_text = "相关的历史记忆:\n"
            for memory in relevant_memories:
                if "summary" in memory:
                    memory_text += f"会话总结: {memory['summary']}\n"
                if "conversations" in memory:
                    memory_text += "具体对话:\n"
                    for conv in memory["conversations"]:
                        memory_text += f"{conv['text']}\n"
            messages.append({"role": "system", "content": memory_text})

        # 添加当前会话历史
        for message in current_conversation:
            messages.append(
                {
                    "role": "user" if message["role"] == "user" else "assistant",
                    "content": message["text"],
                }
            )

        # 添加当前用户输入
        messages.append({"role": "user", "content": user_input})

        # 调用API获取回复
        response = self.client.chat.completions.create(
            model=self.config["CHAT_MODEL"], messages=messages
        )

        return response.choices[0].message.content

    def generate_summary(
        self,
        conversations: List[Dict[str, str]],
        existing_summary: Optional[str] = None,
    ) -> str:
        """生成对话总结

        Args:
            conversations: 需要总结的对话列表
            existing_summary: 已有的总结(如果有)

        Returns:
            生成的总结
        """
        # 构建对话文本
        conv_text = "\n".join(f"{msg['role']}: {msg['text']}" for msg in conversations)

        # 构建提示词
        prompt = self.prompts["SUMMARY_PROMPT"].format(
            conversations=conv_text, existing_summary=existing_summary or "暂无总结"
        )

        # 调用API生成总结
        response = self.client.chat.completions.create(
            model=self.config["CHAT_MODEL"],
            messages=[{"role": "user", "content": prompt}],
        )

        return response.choices[0].message.content

    def update_personality(
        self,
        current_self_perception: str,
        current_user_perception: str,
        session_summary: str,
    ) -> tuple[str, str]:
        """更新人格记忆

        Args:
            current_self_perception: 当前的自我认知
            current_user_perception: 当前的用户形象
            session_summary: 当前会话的总结

        Returns:
            更新后的(自我认知, 用户形象)
        """
        # 更新自我认知
        self_prompt = self.prompts["SELF_UPDATE_PROMPT"].format(
            current_self_perception=current_self_perception,
            session_summary=session_summary,
        )
        self_response = self.client.chat.completions.create(
            model=self.config["CHAT_MODEL"],
            messages=[{"role": "user", "content": self_prompt}],
        )
        new_self_perception = self_response.choices[0].message.content

        # 更新用户形象
        user_prompt = self.prompts["USER_UPDATE_PROMPT"].format(
            current_user_perception=current_user_perception,
            session_summary=session_summary,
        )
        user_response = self.client.chat.completions.create(
            model=self.config["CHAT_MODEL"],
            messages=[{"role": "user", "content": user_prompt}],
        )
