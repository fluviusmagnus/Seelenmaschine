import asyncio
from typing import Any, Callable, Dict, List, Optional

from core.config import Config
from utils.logger import get_logger

logger = get_logger()


class MemoryClient:
    """Handle summary and long-term memory generation prompts."""

    def __init__(self, llm_client: Any):
        self.llm_client = llm_client

    def generate_summary(
        self,
        existing_summary: Optional[str],
        new_conversations: List[Dict[str, str]],
        prompt_builder: Callable[[Optional[str], str], str],
    ) -> str:
        """Generate a summary from conversation messages."""
        conv_text = self.llm_client._format_conversation_messages(new_conversations)
        prompt = prompt_builder(existing_summary, conv_text)

        async def get_summary() -> str:
            self.llm_client._ensure_tool_client_initialized()

            if Config.DEBUG_SHOW_FULL_PROMPT:
                logger.debug(
                    f"Summary prompt sent to tool_model ({self.llm_client.tool_model}):\n{prompt}"
                )

            response = await self.llm_client._tool_client.chat.completions.create(
                model=self.llm_client.tool_model,
                messages=[
                    {"role": "system", "content": "You are a conversation summarizer."},
                    {"role": "user", "content": prompt},
                ],
            )

            result = response.choices[0].message.content or ""
            if Config.DEBUG_SHOW_FULL_PROMPT:
                logger.debug(f"Summary result from tool_model:\n{result}")
            return result

        loop = self.llm_client._get_event_loop()
        try:
            return loop.run_until_complete(get_summary())
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            return loop.run_until_complete(get_summary())

    async def generate_summary_async(
        self,
        existing_summary: Optional[str],
        new_conversations: List[Dict[str, str]],
        prompt_builder: Callable[[Optional[str], str], str],
    ) -> str:
        """Async version of generate_summary."""
        conv_text = self.llm_client._format_conversation_messages(new_conversations)
        prompt = prompt_builder(existing_summary, conv_text)

        self.llm_client._ensure_tool_client_initialized()

        if Config.DEBUG_SHOW_FULL_PROMPT:
            logger.debug(
                f"Summary (async) prompt sent to tool_model ({self.llm_client.tool_model}):\n{prompt}"
            )

        response = await self.llm_client._tool_client.chat.completions.create(
            model=self.llm_client.tool_model,
            messages=[
                {"role": "system", "content": "You are a conversation summarizer."},
                {"role": "user", "content": prompt},
            ],
        )

        result = response.choices[0].message.content or ""
        if Config.DEBUG_SHOW_FULL_PROMPT:
            logger.debug(f"Summary (async) result from tool_model:\n{result}")
        return result

    def generate_memory_update(
        self,
        messages: List[Dict[str, str]],
        current_seele_json: str,
        prompt_builder: Callable[[str, str, Optional[int], Optional[int]], str],
        first_timestamp: Optional[int] = None,
        last_timestamp: Optional[int] = None,
    ) -> str:
        """Synchronous wrapper for memory update generation."""
        conv_text = self.llm_client._format_conversation_messages(messages)
        prompt = prompt_builder(
            conv_text, current_seele_json, first_timestamp, last_timestamp
        )

        try:
            asyncio.get_running_loop()
            raise RuntimeError(
                "generate_memory_update() called from async context. Use await generate_memory_update_async() instead."
            )
        except RuntimeError as e:
            if "no running event loop" not in str(e).lower():
                raise

            async def get_update() -> str:
                self.llm_client._ensure_tool_client_initialized()

                if Config.DEBUG_SHOW_FULL_PROMPT:
                    logger.debug(
                        f"Memory update prompt sent to tool_model ({self.llm_client.tool_model}):\n{prompt}"
                    )

                response = await self.llm_client._tool_client.chat.completions.create(
                    model=self.llm_client.tool_model,
                    messages=[
                        {
                            "role": "system",
                            "content": "You generate JSON patches for memory updates.",
                        },
                        {"role": "user", "content": prompt},
                    ],
                )

                result = response.choices[0].message.content or ""
                if Config.DEBUG_SHOW_FULL_PROMPT:
                    logger.debug(f"Memory update result from tool_model:\n{result}")
                return result

            return self.llm_client._get_event_loop().run_until_complete(get_update())

    async def generate_memory_update_async(
        self,
        messages: List[Dict[str, str]],
        current_seele_json: str,
        prompt_builder: Callable[[str, str, Optional[int], Optional[int]], str],
        first_timestamp: Optional[int] = None,
        last_timestamp: Optional[int] = None,
    ) -> str:
        """Async version of generate_memory_update."""
        conv_text = self.llm_client._format_conversation_messages(messages)
        prompt = prompt_builder(
            conv_text, current_seele_json, first_timestamp, last_timestamp
        )

        self.llm_client._ensure_tool_client_initialized()

        if Config.DEBUG_SHOW_FULL_PROMPT:
            logger.debug(
                f"Memory update (async) prompt sent to tool_model ({self.llm_client.tool_model}):\n{prompt}"
            )

        response = await self.llm_client._tool_client.chat.completions.create(
            model=self.llm_client.tool_model,
            messages=[
                {
                    "role": "system",
                    "content": "You generate JSON patches for memory updates.",
                },
                {"role": "user", "content": prompt},
            ],
        )

        result = response.choices[0].message.content or ""
        if Config.DEBUG_SHOW_FULL_PROMPT:
            logger.debug(f"Memory update (async) result from tool_model:\n{result}")
        return result

    def generate_complete_memory_json(
        self,
        messages: List[Dict[str, str]],
        current_seele_json: str,
        error_message: str,
        prompt_builder: Callable[
            [str, str, str, Optional[int], Optional[int]], str
        ],
        first_timestamp: Optional[int] = None,
        last_timestamp: Optional[int] = None,
    ) -> str:
        """Synchronous wrapper for full-memory regeneration."""
        conv_text = self.llm_client._format_conversation_messages(messages)
        prompt = prompt_builder(
            conv_text,
            current_seele_json,
            error_message,
            first_timestamp,
            last_timestamp,
        )

        try:
            asyncio.get_running_loop()
            raise RuntimeError(
                "generate_complete_memory_json() called from async context. Use await generate_complete_memory_json_async() instead."
            )
        except RuntimeError as e:
            if "no running event loop" not in str(e).lower():
                raise

            async def get_complete_json() -> str:
                self.llm_client._ensure_tool_client_initialized()

                if Config.DEBUG_SHOW_FULL_PROMPT:
                    logger.debug(
                        f"Complete memory JSON prompt sent to tool_model ({self.llm_client.tool_model}):\n{prompt}"
                    )

                response = await self.llm_client._tool_client.chat.completions.create(
                    model=self.llm_client.tool_model,
                    messages=[
                        {
                            "role": "system",
                            "content": "You generate complete seele.json objects for memory updates.",
                        },
                        {"role": "user", "content": prompt},
                    ],
                )

                result = response.choices[0].message.content or ""
                if Config.DEBUG_SHOW_FULL_PROMPT:
                    logger.debug(
                        f"Complete memory JSON result from tool_model:\n{result}"
                    )
                return result

            return self.llm_client._get_event_loop().run_until_complete(
                get_complete_json()
            )

    async def generate_complete_memory_json_async(
        self,
        messages: List[Dict[str, str]],
        current_seele_json: str,
        error_message: str,
        prompt_builder: Callable[
            [str, str, str, Optional[int], Optional[int]], str
        ],
        first_timestamp: Optional[int] = None,
        last_timestamp: Optional[int] = None,
    ) -> str:
        """Async version of generate_complete_memory_json."""
        conv_text = self.llm_client._format_conversation_messages(messages)
        prompt = prompt_builder(
            conv_text,
            current_seele_json,
            error_message,
            first_timestamp,
            last_timestamp,
        )

        self.llm_client._ensure_tool_client_initialized()

        if Config.DEBUG_SHOW_FULL_PROMPT:
            logger.debug(
                f"Complete memory JSON (async) prompt sent to tool_model ({self.llm_client.tool_model}):\n{prompt}"
            )

        response = await self.llm_client._tool_client.chat.completions.create(
            model=self.llm_client.tool_model,
            messages=[
                {
                    "role": "system",
                    "content": "You generate complete seele.json objects for memory updates.",
                },
                {"role": "user", "content": prompt},
            ],
        )

        result = response.choices[0].message.content or ""
        if Config.DEBUG_SHOW_FULL_PROMPT:
            logger.debug(f"Complete memory JSON (async) result from tool_model:\n{result}")
        return result

