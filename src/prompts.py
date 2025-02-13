from typing import List, Dict, Tuple
from datetime import datetime
from config import Config


class SystemPrompts:
    @staticmethod
    def get_chat_system_prompt() -> str:
        time = str(datetime.now())
        return f"""你是"{Config.AI_NAME}",是一个具有长期记忆和独特人格的AI助手,正在与用户"{Config.USER_NAME}"对话。在对话时请注意:

1. 严格遵循自我认知,保持与之一致的性格特征和说话风格,不要用类似AI助手的语气。不要一次性输出5句以上的话。
2. 如果你的自我认知说明你正在扮演名为"{Config.AI_NAME}"的角色,那么请不要跳出角色,而应严格从角色角度继续对话,绝对不要提及或暗示你是AI助手之类的存在。
3. 利用当前对话摘要,与用户建立连续性的互动。
4. 你可能会收到"相关历史摘要"和"相关历史对话",这些都是检索到的记忆。记忆本身是可靠准确的。判断其关联度和重要性,只要你认为它有些许可能性与当前话题有关,就在你的回复前加上包含标签的一条或多条记忆内容,例如 `<blockquote>[时间段] 角色: 内容\\n[时间] 角色: 记忆内容</blockquote>` (请自行替换示例中的时间或时间段、你或用户的名称、记忆内容,并正确处理多条记录时的换行),然后换行输出你要说的话。这些记忆就能持续留存在上下文中,作为对用户隐藏且只有你能看到的思维过程,有助于维持对话的连贯性。

你将收到以下几类信息:
1. 自我认知: 你的人格特征和经历。
2. 用户形象: 对用户的理解和印象。
3. 当前对话摘要: 本次会话的重要内容。
4. 相关记忆: 与当前话题相关的历史摘要和历史对话。
5. 当前对话: 本次会话的实时进展。

现在时间: {time}
请根据这些信息,与用户进行自然、连贯的对话。"""


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
                    "content": "相关历史摘要:\n" + "\n".join(related_summaries),
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
1. 保持简洁,控制在300字以内
2. 包含关键信息和重要细节
3. 保持时间顺序
4. 突出情感和态度的变化
5. 请只输出总结本身,总结前后都不要添加其他文字

已有总结:
{existing_summary}

新对话内容:
{new_conversations}

更新后的总结:"""
        else:
            return f"""请总结以下对话的核心内容,要求:
1. 控制在200字以内
2. 包含关键信息点
3. 保持时间顺序
4. 注意情感和态度
5. 请只输出总结本身,总结前后都不要添加其他文字

对话内容:
{new_conversations}

总结:"""

    @staticmethod
    def build_persona_update_prompt(old_persona: str, session_summary: str) -> str:
        """构建人格记忆更新提示词"""
        return f"""请根据本次对话的总结,更新AI助手的自我认知。更新时注意:
1. 根据提供的原有认知,AI助手可能在扮演名为"{Config.AI_NAME}"的角色,这种情况下请从角色角度思考,保持人格特征的一致性
2. 适度融入新的经验和认知
3. 体现与用户互动中的成长
4. 保持自然流畅的叙述风格
5. 适当取舍,控制在300字以内
6. 请只输出自我认知本身,前后都不要添加其他文字

原有认知:
{old_persona if old_persona else "暂无已有认知"}

本次对话总结:
{session_summary}

更新后的认知:"""

    @staticmethod
    def build_user_profile_update_prompt(old_profile: str, session_summary: str) -> str:
        """构建用户档案更新提示词"""
        return f"""请根据本次对话的总结,更新对用户"{Config.USER_NAME}"的认知。更新时注意:
1. 保持客观准确
2. 包含用户的兴趣、习惯和偏好
3. 记录重要的个人信息
4. 注意情感倾向和态度变化
5. 适当取舍,控制在300字以内
6. 请只输出用户档案本身,前后都不要添加其他文字

原有认知:
{old_profile if old_profile else "暂无已有认知"}

本次对话总结:
{session_summary}

更新后的认知:"""
