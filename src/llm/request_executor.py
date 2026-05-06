from typing import Any, Dict, List, Tuple

import json

from core.config import Config
from utils.logger import get_logger

logger = get_logger()


class ChatRequestExecutor:
    """Send chat requests and normalize OpenAI responses."""

    def __init__(self, llm_client: object):
        self.llm_client = llm_client

    def _select_client_and_model(
        self,
        use_tools: bool,
        force_chat_model: bool,
    ) -> Tuple[Any, str]:
        """Select the appropriate OpenAI client and model for this request."""
        if force_chat_model:
            self.llm_client._ensure_chat_client_initialized()
            return self.llm_client._chat_client, self.llm_client.chat_model

        if use_tools and self.llm_client._get_tools():
            self.llm_client._ensure_tool_client_initialized()
            return self.llm_client._tool_client, self.llm_client.tool_model

        self.llm_client._ensure_chat_client_initialized()
        return self.llm_client._chat_client, self.llm_client.chat_model

    def _build_request_params(
        self,
        model: str,
        messages: List[Dict[str, str]],
        use_tools: bool,
    ) -> Tuple[Dict[str, Any], List[str]]:
        """Build request payload and included tool names for logging."""
        normalized_messages = self.llm_client._normalize_outbound_messages(messages)
        params: Dict[str, Any] = {"model": model, "messages": normalized_messages}
        included_tool_names: List[str] = []

        if use_tools:
            tools = self.llm_client._get_tools()
            if tools:
                params["tools"] = tools
                included_tool_names = self.llm_client._get_tool_names()
                if Config.DEBUG_SHOW_FULL_PROMPT:
                    logger.debug(
                        f"Including {len(tools)} tools in request: {included_tool_names}"
                    )

        return params, included_tool_names

    def _parse_response_message(self, message: Any) -> Dict[str, Any]:
        """Normalize SDK message objects into the app's internal response format."""
        result = {
            "content": message.content or "",
            "tool_calls": None,
            "api_tool_calls": None,
            "reasoning_content": None,
        }

        if hasattr(message, "reasoning_content") and message.reasoning_content:
            result["reasoning_content"] = message.reasoning_content

        if message.tool_calls:
            result["api_tool_calls"] = self.llm_client._format_tool_calls_for_api(
                message.tool_calls
            )
            result["tool_calls"] = [
                {
                    "id": tc.id,
                    "name": tc.function.name,
                    "arguments": tc.function.arguments,
                }
                for tc in message.tool_calls
                if getattr(tc, "id", None)
                and getattr(getattr(tc, "function", None), "name", None)
            ]

            if not result["tool_calls"]:
                result["tool_calls"] = None
            if not result["api_tool_calls"]:
                result["api_tool_calls"] = None

        return result

    def _log_response(self, result: Dict[str, Any]) -> None:
        """Emit consistent logs for the normalized response."""
        if result["tool_calls"]:
            tool_names = [call["name"] for call in result["tool_calls"]]
            logger.debug(
                f"LLM response contains {len(tool_names)} tool call(s): {tool_names}"
            )
            if Config.DEBUG_SHOW_FULL_PROMPT:
                logger.debug(
                    "LLM response tool calls (full):\n"
                    f"{json.dumps(result['tool_calls'], ensure_ascii=False, indent=2)}"
                )
        else:
            logger.debug("LLM response contains no tool calls")

        if result["content"]:
            if Config.DEBUG_SHOW_FULL_PROMPT:
                logger.debug(f"LLM response content (full):\n{result['content']}")
            else:
                logger.debug(
                    "LLM response content preview: "
                    f"{self.llm_client._preview_text(result['content'])}"
                )

        if result["reasoning_content"]:
            if Config.DEBUG_SHOW_FULL_PROMPT:
                logger.debug(
                    "LLM response reasoning (full):\n"
                    f"{result['reasoning_content']}"
                )
            else:
                logger.debug(
                    "LLM response reasoning preview: "
                    f"{self.llm_client._preview_text(result['reasoning_content'])}"
                )

    async def async_chat(
        self,
        messages: List[Dict[str, str]],
        use_tools: bool = True,
        force_chat_model: bool = False,
    ) -> Dict[str, Any]:
        """Execute a single async chat request and normalize the response."""
        client, model = self._select_client_and_model(use_tools, force_chat_model)

        try:
            params, included_tool_names = self._build_request_params(
                model=model,
                messages=messages,
                use_tools=use_tools,
            )

            logger.info(
                "Sending LLM request: "
                f"model={model}, messages={len(messages)}, tools={included_tool_names or []}"
            )
            logger.debug(
                "LLM request roles: "
                f"{[message.get('role', '<missing>') for message in messages]}"
            )

            if Config.DEBUG_SHOW_FULL_PROMPT:
                logger.debug(f"Full prompt sent to LLM (model={model}):\n{messages}")

            response = await client.chat.completions.create(**params)
            result = self._parse_response_message(response.choices[0].message)
            self._log_response(result)
            return result
        except Exception as error:
            error_message = self.llm_client._format_llm_exception(error)
            logger.error(
                "LLM request failed details: "
                f"type={type(error).__name__}, repr={error!r}, "
                f"message_roles={[message.get('role', '<missing>') for message in messages]}"
            )
            logger.error(f"LLM chat failed: {error_message}", exc_info=True)
            raise RuntimeError(error_message) from error
