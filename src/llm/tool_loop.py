import asyncio
import json
from typing import Any, Awaitable, Callable, Dict, List, Optional

from core.config import Config
from utils.logger import get_logger

logger = get_logger()


ConversationEvent = Dict[str, str]


class ToolLoop:
    """Run the assistant/tool exchange loop until a final answer is produced."""

    def __init__(self, llm_client: object):
        self.llm_client = llm_client

    @staticmethod
    def _append_event(
        conversation_events: List[Dict[str, Any]],
        *,
        event_index: int,
        role: str,
        content: str,
        message_type: str,
    ) -> int:
        """Append an ordered conversation event and return the next index."""
        conversation_events.append(
            {
                "event_index": event_index,
                "role": role,
                "content": content,
                "message_type": message_type,
            }
        )
        return event_index + 1

    async def run_chat_with_tool_loop(
        self,
        messages: List[Dict[str, str]],
        intermediate_callback: Optional[Callable[[str], Awaitable[None]]] = None,
    ) -> Dict[str, Any]:
        """Run chat completion loop with tool execution and collect assistant texts."""
        assistant_messages: List[str] = []
        tool_context_messages: List[str] = []
        conversation_events: List[Dict[str, Any]] = []
        iteration = 1
        event_index = 0

        result = await self.llm_client._async_chat(
            messages, use_tools=True, force_chat_model=True
        )

        while result["tool_calls"]:
            logger.debug(
                f"LLM tool loop iteration {iteration}: received {len(result['tool_calls'])} tool call(s)"
            )
            assistant_text = self.llm_client._extract_assistant_text_from_result(result)
            if assistant_text:
                assistant_messages.append(assistant_text)
                event_index = self._append_event(
                    conversation_events,
                    event_index=event_index,
                    role="assistant",
                    content=assistant_text,
                    message_type="conversation",
                )
                if Config.DEBUG_SHOW_FULL_PROMPT:
                    logger.debug(
                        "LLM emitted intermediate assistant text before tool execution (full):\n"
                        f"{assistant_text}"
                    )
                else:
                    logger.debug(
                        "LLM emitted intermediate assistant text before tool execution: "
                        f"{self.llm_client._preview_text(assistant_text)}"
                    )
                if intermediate_callback:
                    await intermediate_callback(assistant_text)

            if self.llm_client._tool_executor is None:
                logger.warning("Tool calls but no executor registered")
                break

            tool_responses = []
            for call in result["tool_calls"]:
                if Config.DEBUG_SHOW_FULL_PROMPT:
                    logger.debug(
                        "Executing tool call (full):\n"
                        f"{json.dumps(call, ensure_ascii=False, indent=2)}"
                    )
                else:
                    logger.debug(f"Executing tool: {call['name']}")
                try:
                    response = self.llm_client._tool_executor(
                        call["name"], call["arguments"]
                    )
                    if asyncio.iscoroutine(response):
                        response = await response
                    response_text = (
                        response.get("result", "") if isinstance(response, dict) else response
                    )
                    sanitized_response = (
                        self.llm_client._sanitize_tool_response_for_prompt(response_text)
                    )
                    if Config.DEBUG_SHOW_FULL_PROMPT:
                        logger.debug(
                            f"Tool '{call['name']}' raw response (full):\n{response_text}"
                        )
                        logger.debug(
                            f"Tool '{call['name']}' sanitized response (full):\n{sanitized_response}"
                        )
                    else:
                        logger.debug(
                            f"Tool '{call['name']}' completed with response preview: "
                            f"{self.llm_client._preview_text(sanitized_response)}"
                        )
                    context_message = (
                        response.get("context_message") if isinstance(response, dict) else None
                    )
                    if context_message:
                        event_index = self._append_event(
                            conversation_events,
                            event_index=event_index,
                            role="system",
                            content=context_message,
                            message_type="tool_call",
                        )
                    event_message = (
                        response.get("event_message") if isinstance(response, dict) else None
                    )
                    if event_message:
                        event_index = self._append_event(
                            conversation_events,
                            event_index=event_index,
                            role="assistant",
                            content=event_message,
                            message_type="conversation",
                        )
                    if isinstance(response, dict) and response.get("context_message"):
                        if Config.DEBUG_SHOW_FULL_PROMPT:
                            logger.debug(
                                f"Tool '{call['name']}' context message (full):\n"
                                f"{response['context_message']}"
                            )
                        tool_context_messages.append(response["context_message"])
                    tool_responses.append(
                        {
                            "tool_call_id": call["id"],
                            "role": "tool",
                            "content": sanitized_response,
                        }
                    )
                except Exception as error:
                    error_text = f"{type(error).__name__}: {error}"
                    logger.error(f"Tool execution failed: {error_text}")
                    tool_responses.append(
                        {
                            "tool_call_id": call["id"],
                            "role": "tool",
                            "content": f"Error: {error_text}",
                        }
                    )

            assistant_message = self.llm_client._build_assistant_message_from_result(
                result
            )
            messages.append(assistant_message)
            messages.extend(tool_responses)

            result = await self.llm_client._async_chat(
                messages, use_tools=True, force_chat_model=True
            )
            iteration += 1

        final_text = self.llm_client._extract_assistant_text_from_result(result) or ""
        if final_text:
            assistant_messages.append(final_text)
            event_index = self._append_event(
                conversation_events,
                event_index=event_index,
                role="assistant",
                content=final_text,
                message_type="conversation",
            )

        if Config.DEBUG_SHOW_FULL_PROMPT:
            logger.debug(
                "LLM tool loop finished: "
                f"assistant_messages={len(assistant_messages)}"
            )
            logger.debug(f"LLM tool loop final_text (full):\n{final_text}")
            logger.debug(
                "LLM tool loop conversation_events (full):\n"
                f"{json.dumps(conversation_events, ensure_ascii=False, indent=2)}"
            )
        else:
            logger.debug(
                "LLM tool loop finished: "
                f"assistant_messages={len(assistant_messages)}, "
                f"final_text={self.llm_client._preview_text(final_text)}"
            )

        return {
            "final_text": final_text,
            "assistant_messages": assistant_messages,
            "tool_context_messages": tool_context_messages,
            "conversation_events": conversation_events,
        }
