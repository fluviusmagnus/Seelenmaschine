"""Message handlers for Telegram bot"""

from typing import Any, Callable, List, Optional

from adapter.telegram.commands import TelegramCommands
from adapter.telegram.delivery import send_segmented_text
from adapter.telegram.files import TelegramFiles
from adapter.telegram.formatter import TelegramResponseFormatter
from adapter.telegram.messages import TelegramMessages
from adapter.telegram.tool_bridge import TelegramToolBridge
from core.approval import ApprovalService, PendingApprovalRequest
from core.bot import CoreBot, CoreToolHost
from core.config import Config
from core.database import DatabaseManager
from core.tools import ToolExecutor
from core.scheduler import TaskScheduler
from llm.chat_client import LLMClient
from llm.embedding import EmbeddingClient
from llm.reranker import RerankerClient
from memory.manager import MemoryManager
from telegram import Update
from telegram.ext import ContextTypes
from utils.logger import get_logger

logger = get_logger()

__all__ = [
    "MessageHandler",
    "Config",
    "DatabaseManager",
    "EmbeddingClient",
    "RerankerClient",
    "MemoryManager",
    "TaskScheduler",
    "LLMClient",
]


class MessageHandler:
    """Handles incoming messages and commands"""

    @staticmethod
    def _resolve_handler_component(handler: Any, getter_name: str) -> Any:
        """Resolve a helper component through the real getter, even on mocked handlers."""
        getter = getattr(MessageHandler, getter_name).__get__(handler, type(handler))
        return getter()

    @staticmethod
    def _call_handler_component_method(
        handler: Any, getter_name: str, method_name: str, *args: Any, **kwargs: Any
    ) -> Any:
        """Call a method on a lazily resolved helper component."""
        component = MessageHandler._resolve_handler_component(handler, getter_name)
        method = getattr(component, method_name)
        return method(*args, **kwargs)

    @staticmethod
    def _get_or_create_component(
        handler: Any,
        attr_name: str,
        expected_type: Any,
        factory: Callable[[], Any],
    ) -> Any:
        """Return a cached helper component or create and cache a replacement."""
        component = getattr(handler, attr_name, None)
        if isinstance(component, expected_type):
            return component

        component = factory()
        try:
            setattr(handler, attr_name, component)
        except Exception:
            pass
        return component

    @staticmethod
    def _preview_text(text: Optional[str], max_length: int = 120) -> str:
        """Build a compact single-line preview for logs."""
        if text is None:
            return ""

        normalized = " ".join(str(text).split())
        if len(normalized) <= max_length:
            return normalized
        return f"{normalized[:max_length]}..."

    @staticmethod
    def _format_exception_for_user(error: Exception) -> str:
        """Build a concise user-facing error summary."""
        message = str(error).strip() or type(error).__name__
        if len(message) > 300:
            message = f"{message[:297]}..."
        return message

    def _initialize_core_dependencies(self, core_bot: Optional[CoreBot]) -> None:
        """Attach the root core bot."""
        self.core_bot = core_bot or CoreBot()

    @property
    def tool_runtime_state(self) -> Any:
        """Expose the core-owned tool runtime bookkeeping."""
        return self.core_bot.tool_runtime_state

    @property
    def tool_trace_store(self) -> Any:
        """Expose the tool trace store for compatibility."""
        return self.tool_runtime_state.tool_trace_store

    @property
    def tool_trace_query_tool(self) -> Any:
        """Expose the tool trace query tool for compatibility."""
        return self.tool_runtime_state.tool_trace_query_tool

    @property
    def _tool_registry(self) -> Any:
        """Expose the legacy tool registry mirror for compatibility."""
        return self.tool_runtime_state.legacy_registry

    def _initialize_telegram_helpers(self) -> None:
        """Create Telegram-facing helpers and approval state."""
        self._telegram_formatter = TelegramResponseFormatter()
        self._files = TelegramFiles(
            config=self.core_bot.config,
            memory=self.core_bot.memory,
        )
        self._tool_bridge = TelegramToolBridge(self)
        self._tool_host = self.core_bot.create_tool_host(
            self,
            get_tool_bridge=self._tool_bridge_component,
        )
        self._commands = TelegramCommands(self)
        self._messages = TelegramMessages(self)
        self._approval_service = ApprovalService()
        self._approval_service.set_state_listener(self._set_pending_approval)
        self._pending_approval: Optional[PendingApprovalRequest] = None
        self._approval_lock = self._approval_service.lock

    def _initialize_application_services(self) -> None:
        """Wire high-level services after tool runtime state is available."""
        self._tool_host.setup_tools()
        self.core_bot.create_conversation_service(
            memory_search_tool=self.tool_runtime_state.memory_search_tool,
            mcp_client=self.tool_runtime_state.mcp_client,
            ensure_mcp_connected=self._ensure_mcp_connected,
            preview_text=self._preview_text,
        )
        self.core_bot.create_session_service(
            tool_trace_store=self.tool_runtime_state.tool_trace_store,
            memory_search_tool=self.tool_runtime_state.memory_search_tool,
        )
        self._tool_executor_service = self._tool_host.get_tool_executor_service()

    def __init__(self, core_bot: Optional[CoreBot] = None):
        """Initialize message handler"""
        self._initialize_core_dependencies(core_bot)
        self.telegram_bot = None
        self.core_bot.create_tool_runtime_state(
            get_current_session_id=self.core_bot.memory.get_current_session_id,
        )
        self._initialize_telegram_helpers()

        self._tool_host.register_scheduled_task_tool()
        self._tool_host.register_send_file_tool()
        self._tool_host.register_builtin_tools()
        self._initialize_application_services()

        # Setup scheduler callback (will be started as Application job in bot.py)
        self.core_bot.scheduler.set_message_callback(self._handle_scheduled_message)
        logger.info("Task scheduler callback registered")

        logger.info("MessageHandler initialized")

    def set_telegram_bot(self, bot: Any) -> None:
        """Inject Telegram bot instance for proactive file sending."""
        self.telegram_bot = bot
        tool_executor = getattr(self, "_tool_executor_service", None)
        if isinstance(tool_executor, ToolExecutor):
            tool_executor.telegram_bot = bot
        logger.info("Telegram bot instance injected into MessageHandler")

    async def _handle_scheduled_message(
        self, message: str, task_name: str = "Scheduled Task"
    ) -> str:
        """Handle messages from scheduled tasks."""
        return await self._messages_component().handle_scheduled_message(
            message, task_name
        )

    def _set_pending_approval(self, request: Optional[PendingApprovalRequest]) -> None:
        """Keep the latest pending approval available on the handler."""
        self._pending_approval = request

    def _get_telegram_formatter(self) -> TelegramResponseFormatter:
        """Lazily resolve the Telegram formatter."""
        return MessageHandler._get_or_create_component(
            self,
            "_telegram_formatter",
            TelegramResponseFormatter,
            TelegramResponseFormatter,
        )

    def _telegram_formatter_component(self) -> TelegramResponseFormatter:
        """Return the Telegram formatter component."""
        return self._get_telegram_formatter()

    def _get_files(self) -> TelegramFiles:
        """Lazily resolve Telegram file operations."""
        return MessageHandler._get_or_create_component(
            self,
            "_files",
            TelegramFiles,
            lambda: TelegramFiles(
                config=self.core_bot.config,
                memory=self.core_bot.memory,
            ),
        )

    def _files_component(self) -> TelegramFiles:
        """Return the Telegram file helper."""
        return self._get_files()

    def _get_commands(self) -> TelegramCommands:
        """Lazily resolve the Telegram command helper."""
        return MessageHandler._get_or_create_component(
            self,
            "_commands",
            TelegramCommands,
            lambda: TelegramCommands(self),
        )

    def _commands_component(self) -> TelegramCommands:
        """Return the Telegram command helper."""
        return self._get_commands()

    def _get_messages(self) -> TelegramMessages:
        """Lazily resolve the Telegram message helper."""
        return MessageHandler._get_or_create_component(
            self,
            "_messages",
            TelegramMessages,
            lambda: TelegramMessages(self),
        )

    def _messages_component(self) -> TelegramMessages:
        """Return the Telegram message helper."""
        return self._get_messages()

    def _get_tool_bridge(self) -> TelegramToolBridge:
        """Lazily resolve the Telegram bridge used by tool execution."""
        return MessageHandler._get_or_create_component(
            self,
            "_tool_bridge",
            TelegramToolBridge,
            lambda: TelegramToolBridge(self),
        )

    def _tool_bridge_component(self) -> TelegramToolBridge:
        """Return the Telegram tool bridge."""
        return self._get_tool_bridge()

    def _get_tool_host(self) -> CoreToolHost:
        """Lazily resolve the core-owned tool host."""
        existing_host = getattr(getattr(self, "core_bot", None), "tool_host", None)
        if isinstance(existing_host, CoreToolHost):
            return existing_host

        return MessageHandler._get_or_create_component(
            self,
            "_tool_host",
            CoreToolHost,
            lambda: self.core_bot.create_tool_host(
                self,
                get_tool_bridge=self._tool_bridge_component,
            ),
        )

    async def _send_intermediate_response(self, text: str) -> None:
        """Stream intermediate assistant text to Telegram when available."""
        if not text.strip():
            return
        if not getattr(self, "telegram_bot", None):
            return

        formatted = self._format_response_for_telegram(text)
        segments = self._split_message_into_segments(formatted)
        try:
            await send_segmented_text(
                segments=segments,
                send_html=lambda segment: self.telegram_bot.send_message(
                    chat_id=self.core_bot.config.TELEGRAM_USER_ID,
                    text=segment,
                    parse_mode="HTML",
                ),
                send_plain=lambda segment: self.telegram_bot.send_message(
                    chat_id=self.core_bot.config.TELEGRAM_USER_ID,
                    text=segment,
                ),
                html_warning_template=(
                    "HTML parsing failed for intermediate segment {index}, "
                    "sending as plain text: {error}"
                ),
                fatal_error_template=(
                    "Failed to send intermediate segment {index}: {error}"
                ),
            )
        except Exception as error:
            logger.error(f"Failed to send intermediate response: {error}")

    def _format_response_for_telegram(self, text: str) -> str:
        """Format response text for Telegram HTML"""
        formatter = MessageHandler._get_telegram_formatter.__get__(self, type(self))()
        return formatter.format_response(
            text, debug_mode=self.core_bot.config.DEBUG_MODE
        )

    def _split_message_into_segments(
        self, text: str, max_length: int = 4000
    ) -> List[str]:
        """Split message into Telegram-safe segments."""
        formatter = MessageHandler._get_telegram_formatter.__get__(self, type(self))()
        return formatter.split_message_into_segments(text, max_length=max_length)

    async def _ensure_mcp_connected(self):
        """Ensure MCP client is connected"""
        await self.core_bot.ensure_mcp_connected()

    async def handle_approve(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle /approve command to authorize a pending dangerous action."""
        await MessageHandler._get_tool_bridge.__get__(
            self, type(self)
        )().handle_approve(
            update,
            context,
        )

    async def _execute_tool(self, tool_name: str, arguments_json: str) -> str:
        """Execute a tool call from LLM"""
        return await self.core_bot.execute_tool(tool_name, arguments_json)

    async def handle_message(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle regular text messages."""
        await MessageHandler._call_handler_component_method(
            self,
            "_get_messages",
            "handle_message",
            update,
            context,
        )

    async def handle_file(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle incoming Telegram attachments by saving them and notifying the LLM."""
        await MessageHandler._call_handler_component_method(
            self,
            "_get_messages",
            "handle_file",
            update,
            context,
        )

    async def handle_new_session(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle /new command."""
        await MessageHandler._call_handler_component_method(
            self,
            "_get_commands",
            "handle_new_session",
            update,
            context,
        )

    async def handle_reset_session(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle /reset command."""
        await MessageHandler._call_handler_component_method(
            self,
            "_get_commands",
            "handle_reset_session",
            update,
            context,
        )

    async def _process_message(self, user_message: str) -> str:
        """Process a user message through memory and the LLM."""
        return await self.core_bot.process_message(
            user_message,
            intermediate_callback=self._send_intermediate_response,
        )

    async def _process_scheduled_task(
        self, task_message: str, task_name: str = "Scheduled Task"
    ) -> str:
        """Process a scheduled task message through the LLM."""
        return await self.core_bot.process_scheduled_task(
            task_message,
            task_name,
            intermediate_callback=self._send_intermediate_response,
        )
