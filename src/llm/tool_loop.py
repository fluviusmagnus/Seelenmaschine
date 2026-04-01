import asyncio
from typing import Any, Awaitable, Callable, Dict, List, Optional

from core.config import Config
from utils.logger import get_logger

logger = get_logger()


ConversationEvent = Dict[str, str]


class ToolLoop:
    """Run the assistant/tool exchange loop until a final answer is produced."""

    def __init__(self, llm_client: object):
        self.llm_client = llm_client

    async def run_chat_with_tool_loop(
        self,
        messages: List[Dict[str, str]],
        intermediate_callback: Optional[Callable[[str], Awaitable[None]]] = None,
    ) -> Dict[str, Any]:
        """Run chat completion loop with tool execution and collect assistant texts."""
        assistant_messages: List[str] = []
        tool_context_messages: List[str] = []
        conversation_events: List[ConversationEvent] = []
        iteration = 1

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
                conversation_events.append(
                    {"role": "assistant", "content": assistant_text}
                )
                if not Config.DEBUG_SHOW_FULL_PROMPT:
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
                    logger.debug(
                        f"Tool '{call['name']}' completed with response preview: "
                        f"{self.llm_client._preview_text(sanitized_response)}"
                    )
                    if isinstance(response, dict) and response.get("context_message"):
                        tool_context_messages.append(response["context_message"])
                        conversation_events.append(
                            {
                                "role": "system",
                                "content": response["context_message"],
                            }
                        )
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
            conversation_events.append({"role": "assistant", "content": final_text})

        if Config.DEBUG_SHOW_FULL_PROMPT:
            logger.debug(
                "LLM tool loop finished: "
                f"assistant_messages={len(assistant_messages)}"
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
