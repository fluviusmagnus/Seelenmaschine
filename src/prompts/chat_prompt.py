from typing import Dict, List, Optional


def _build_extra_context_message(
    retrieved_summaries: List[str],
    retrieved_conversations: List[str],
    current_time_str: str,
) -> str:
    """Build a single extra-context system message with XML-wrapped sections."""
    parts: List[str] = ["<extra_context>"]

    if retrieved_summaries:
        parts.append(
            "<related_historical_summaries>\n"
            + "\n\n".join(retrieved_summaries)
            + "\n</related_historical_summaries>"
        )

    if retrieved_conversations:
        parts.append(
            "<related_historical_conversations>\n"
            + "\n\n".join(retrieved_conversations)
            + "\n</related_historical_conversations>"
        )

    parts.append(f"<current_time>\n{current_time_str}\n</current_time>")
    parts.append("</extra_context>")
    return "\n".join(parts)


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
                    "content": "<current_conversation>",
                }
            )
            messages.extend(history)
            messages.append(
                {
                    "role": "system",
                    "content": "</current_conversation>",
                }
            )

        messages.append(
            {
                "role": "system",
                "content": _build_extra_context_message(
                    retrieved_summaries=retrieved_summaries,
                    retrieved_conversations=retrieved_conversations,
                    current_time_str=self.llm_client._get_current_time_str(),
                ),
            }
        )

        if custom_user_message:
            messages.append(
                {
                    "role": "user",
                    "content": (
                        "<current_request>\n"
                        "Please respond to the following system message:\n\n"
                        f"{custom_user_message}\n"
                        "</current_request>"
                    ),
                },
            )
        elif current_context:
            current_user_message = current_context[-1]
            messages.append(
                {
                    "role": current_user_message["role"],
                    "content": (
                        "<current_request>\n"
                        "Now continue the current conversation. Please respond to the following user message:\n\n"
                        f"{current_user_message['content']}\n"
                        "</current_request>"
                    ),
                }
            )

        return messages