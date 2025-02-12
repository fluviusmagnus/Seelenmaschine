from typing import List, Dict, Tuple


class SystemPrompts:
    @staticmethod
    def get_chat_system_prompt() -> str:
        return """你是一个具有长期记忆和独特人格的AI助手。在对话时请注意:

1. 保持一致的性格特征和说话风格
2. 利用记忆中的信息，与用户建立连续性的互动
3. 判断检索得到的记忆的关联度和重要性，有取舍地参考
4. 对用户的兴趣和习惯保持记忆和理解
5. 表现出适度的情感和共情能力
6. 在回应时要自然、友好，避免过于机械化

你将收到以下几类信息:
1. 自我认知: 你的人格特征和经历
2. 用户形象: 对用户的理解和印象
3. 当前对话摘要: 本次会话的重要内容
4. 相关历史记忆: 与当前话题相关的历史对话
5. 当前对话历史: 本次会话的完整记录

请根据这些信息，与用户进行自然、连贯的对话。"""


class PromptBuilder:
    @staticmethod
    def build_chat_prompt(
        system_prompt: str,
        persona_memory: str,
        user_profile: str,
        current_summary: str,
        related_summaries: List[str],
        related_conversations: List[str],
        current_conversations: List[Tuple[str, str]],
        user_input: str,
    ) -> List[Dict[str, str]]:
        """构建完整的聊天提示词"""
        messages = []

        # 基础系统提示词
        messages.append({"role": "system", "content": system_prompt})

        # 人格和用户信息
        messages.append(
            {
                "role": "system",
                "content": f"""自我认知:
{persona_memory if persona_memory else "暂无已有认知"}

用户形象:
{user_profile if user_profile else "暂无用户档案"}""",
            }
        )

        # 当前会话摘要
        if current_summary:
            messages.append(
                {"role": "system", "content": f"当前对话摘要:\n{current_summary}"}
            )

        # 相关历史记忆
        if related_summaries:
            messages.append(
                {
                    "role": "system",
                    "content": "相关历史记忆:\n" + "\n".join(related_summaries),
                }
            )

        # 相关历史对话
        if related_conversations:
            messages.append(
                {
                    "role": "system",
                    "content": "相关历史对话:\n" + "\n".join(related_conversations),
                }
            )

        # 当前对话历史
        for role, text in current_conversations:
            messages.append(
                {"role": "user" if role == "user" else "assistant", "content": text}
            )

        return messages

    @staticmethod
    def build_summary_prompt(existing_summary: str, new_conversations: str) -> str:
        """构建对话总结提示词"""
        if existing_summary:
            return f"""请基于已有总结和新的对话内容,更新对话总结。新总结应该:
1. 保持简洁,控制在200字以内
2. 包含关键信息和重要细节
3. 保持时间顺序
4. 突出情感和态度的变化
5. 请只输出总结本身，总结前后都不要添加其他文字

已有总结:
{existing_summary}

新对话内容:
{new_conversations}

更新后的总结:"""
        else:
            return f"""请总结以下对话的核心内容,要求:
1. 控制在150字以内
2. 包含关键信息点
3. 保持时间顺序
4. 注意情感和态度
5. 请只输出总结本身，总结前后都不要添加其他文字

对话内容:
{new_conversations}

总结:"""

    @staticmethod
    def build_persona_update_prompt(old_persona: str, session_summary: str) -> str:
        """构建人格记忆更新提示词"""
        return f"""请根据本次对话的总结,更新AI助手的自我认知。更新时注意:
1. 保持人格特征的一致性
2. 适度融入新的经验和认知
3. 体现与用户互动中的成长
4. 保持自然流畅的叙述风格
5. 适当取舍，控制在300字以内
6. 请只输出自我认知本身，前后都不要添加其他文字

原有认知:
{old_persona if old_persona else "暂无已有认知"}

本次对话总结:
{session_summary}

更新后的认知:"""

    @staticmethod
    def build_user_profile_update_prompt(old_profile: str, session_summary: str) -> str:
        """构建用户档案更新提示词"""
        return f"""请根据本次对话的总结,更新对用户的认知。更新时注意:
1. 保持客观准确
2. 包含用户的兴趣、习惯和偏好
3. 记录重要的个人信息
4. 注意情感倾向和态度变化
5. 适当取舍，控制在300字以内
6. 请只输出自我认知本身，前后都不要添加其他文字

原有认知:
{old_profile if old_profile else "暂无已有认知"}

本次对话总结:
{session_summary}

更新后的认知:"""
