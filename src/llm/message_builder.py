from typing import Dict, List, Optional


class ChatMessageBuilder:
    """Build chat messages with prompt-caching-friendly ordering."""

    def __init__(self, llm_client: object):
        self.llm_client = llm_client

    def build_chat_messages(
        self,
        current_context: List[Dict[str, str]],
        retrieved_summaries: List[str],
        retrieved_conversations: List[str],
        recent_summaries: Optional[List[str]] = None,
        custom_user_message: Optional[str] = None,
    ) -> List[Dict[str, str]]:
        """Build the final chat payload for the LLM."""
        messages: List[Dict[str, str]] = []

        messages.append(
            {
                "role": "system",
                "content": self.llm_client._get_cacheable_system_prompt(
                    recent_summaries
                ),
            }
        )

        if current_context:
            history = current_context[:-1]
            messages.append(
                {
                    "role": "system",
                    "content": "BEGINNING OF THE CURRENT CONVERSATION.",
                }
            )
            messages.extend(history)
            messages.append(
                {
                    "role": "system",
                    "content": "END OF THE CURRENT CONVERSATION.",
                }
            )

        if retrieved_summaries:
            messages.append(
                {
                    "role": "system",
                    "content": "## Related Historical Summaries\n\n"
                    + "\n\n".join(retrieved_summaries),
                }
            )

        if retrieved_conversations:
            messages.append(
                {
                    "role": "system",
                    "content": "## Related Historical Conversations\n\n"
                    + "\n\n".join(retrieved_conversations),
                }
            )

        messages.append(
            {
                "role": "system",
                "content": "END OF ALL CONTEXT.\n\n**Current Time**: "
                + self.llm_client._get_current_time_str(),
            }
        )

        if custom_user_message:
            messages.append({"role": "user", "content": f"{custom_user_message}"})
        elif current_context:
            current_user_message = current_context[-1]
            messages.append(
                {
                    "role": current_user_message["role"],
                    "content": "Now continue the conversation. Please respond to "
                    "the following input based on all context provided.\n\n"
                    "⚡ [Current Request]\n\n"
                    f"{current_user_message['content']}",
                }
            )

        return messages
