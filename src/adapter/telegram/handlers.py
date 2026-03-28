"""Message handlers for Telegram bot"""

import asyncio
import random
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from telegram import Update
from telegram.ext import ContextTypes

from adapter.telegram.formatter import TelegramResponseFormatter
from adapter.telegram.commands import TelegramCommands
from core.approval import ApprovalService, PendingApprovalRequest
from core.config import Config
from core.conversation import ConversationService
from core.database import DatabaseManager
from core.scheduler import TaskScheduler
from core.tools import ToolExecutor, ToolRegistry, ToolRuntime
from llm.embedding import EmbeddingClient
from llm.chat_client import LLMClient
from llm.reranker import RerankerClient
from memory.manager import MemoryManager
from adapter.telegram.files import TelegramFiles
from tools.memory_search import MemorySearchTool
from tools.mcp_client import MCPClient
from tools.scheduled_tasks import ScheduledTaskTool
from tools.send_telegram_file import SendTelegramFileTool
from tools.tool_trace import ToolTraceStore, ToolTraceQueryTool
from tools.file_io import (
    ReadFileTool,
    WriteFileTool,
    ReplaceFileContentTool,
    AppendFileTool,
)
from tools.file_search import GrepSearchTool, GlobSearchTool
from tools.shell import ShellCommandTool, is_dangerous_command
from adapter.telegram.messages import TelegramMessages
from utils.logger import get_logger

logger = get_logger()


class MessageHandler:
    """Handles incoming messages and commands"""

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

    def __init__(self):
        """Initialize message handler"""
        self.config = Config()
        self.db = DatabaseManager()

        # Initialize embedding and reranker clients
        self.embedding_client = EmbeddingClient()
        self.reranker_client = RerankerClient()

        # Initialize memory manager with proper dependencies
        self.memory = MemoryManager(
            db=self.db,
            embedding_client=self.embedding_client,
            reranker_client=self.reranker_client,
        )

        # Initialize scheduler
        self.scheduler = TaskScheduler(self.db)
        self.scheduled_task_tool_cls = ScheduledTaskTool
        self.send_telegram_file_tool_cls = SendTelegramFileTool

        self.scheduled_task_tool = None
        self.scheduled_task_tool_def = None

        self.send_telegram_file_tool = None
        self.send_telegram_file_tool_def = None
        self.telegram_bot = None

        # Initialize tool trace logging and query tool
        self.tool_trace_store = ToolTraceStore(self.config.DATA_DIR)
        self.tool_trace_query_tool = ToolTraceQueryTool(
            self.tool_trace_store, self.memory.get_current_session_id
        )

        # Initialize LLM client
        self.llm_client = LLMClient()

        # Tool registry: maps tool_name -> tool instance (for fast dispatch)
        self._tool_registry: Dict[str, Any] = {}
        self._tool_registry_service = ToolRegistry()

        # Initialize builtin system tools
        self.read_file_tool = None
        self.write_file_tool = None
        self.replace_file_content_tool = None
        self.append_file_tool = None
        self.grep_search_tool = None
        self.glob_search_tool = None
        self.shell_command_tool = None
        self.read_file_tool_cls = ReadFileTool
        self.write_file_tool_cls = WriteFileTool
        self.replace_file_content_tool_cls = ReplaceFileContentTool
        self.append_file_tool_cls = AppendFileTool
        self.grep_search_tool_cls = GrepSearchTool
        self.glob_search_tool_cls = GlobSearchTool
        self.shell_command_tool_cls = ShellCommandTool

        # Telegram formatting and HITL approval state
        self._telegram_formatter = TelegramResponseFormatter()
        self._files = TelegramFiles(
            config=self.config,
            memory=self.memory,
        )
        self._tool_runtime = ToolRuntime(
            handler=self,
            memory_search_tool_cls=MemorySearchTool,
            mcp_client_cls=MCPClient,
        )
        self._commands = TelegramCommands(self)
        self._messages = TelegramMessages(self)
        self._approval_service = ApprovalService()
        self._approval_service.set_state_listener(self._set_pending_approval)
        self._pending_approval: Optional[PendingApprovalRequest] = None
        self._approval_lock = self._approval_service.lock

        self._register_scheduled_task_tool()
        self._register_send_telegram_file_tool()
        self._register_builtin_tools()

        # Initialize attributes
        self.memory_search_tool = None
        self.mcp_client = None
        self._mcp_connected = False

        # Setup tools for LLM
        self._setup_tools()
        self._conversation_service = ConversationService(
            config=self.config,
            memory=self.memory,
            embedding_client=self.embedding_client,
            llm_client=self.llm_client,
            memory_search_tool=self.memory_search_tool,
            mcp_client=self.mcp_client,
            ensure_mcp_connected=self._ensure_mcp_connected,
            preview_text=self._preview_text,
        )
        self._tool_executor_service = ToolExecutor(
            config=self.config,
            tool_registry=self._tool_registry_service,
            mcp_client=self.mcp_client,
            ensure_mcp_connected=self._ensure_mcp_connected,
            is_mcp_connected=lambda: self._mcp_connected,
            is_dangerous_action=self._is_dangerous_action,
            request_approval=self._request_approval,
            record_tool_trace=self._record_tool_trace,
            infer_tool_trace_status=self._infer_tool_trace_status,
            notify_approved_action_finished=self._notify_approved_action_finished,
            notify_approved_action_failed=self._notify_approved_action_failed,
            preview_text=self._preview_text,
            telegram_bot=self.telegram_bot,
        )

        # Setup scheduler callback (will be started as Application job in bot.py)
        self.scheduler.set_message_callback(self._handle_scheduled_message)
        logger.info("Task scheduler callback registered")

        logger.info("MessageHandler initialized")

    def _register_scheduled_task_tool(self):
        """Register the scheduled task tool with scheduler instance"""
        self._get_tool_runtime().register_scheduled_task_tool()

    def _register_send_telegram_file_tool(self):
        """Register the Telegram file sending tool."""
        self._get_tool_runtime().register_send_telegram_file_tool()

    def set_telegram_bot(self, bot: Any) -> None:
        """Inject Telegram bot instance for proactive file sending."""
        self.telegram_bot = bot
        tool_executor = getattr(self, "_tool_executor_service", None)
        if isinstance(tool_executor, ToolExecutor):
            tool_executor.telegram_bot = bot
        logger.info("Telegram bot instance injected into MessageHandler")

    @staticmethod
    def _make_tool_def(tool: Any) -> Dict[str, Any]:
        """Build an OpenAI-format tool definition from a tool instance."""
        return ToolRegistry.make_tool_def(tool)

    def _register_builtin_tools(self):
        """Register builtin file and shell tools."""
        self._get_tool_runtime().register_builtin_tools()

    async def _handle_scheduled_message(
        self, message: str, task_name: str = "Scheduled Task"
    ) -> str:
        """Handle messages from scheduled tasks."""
        messages = MessageHandler._get_messages.__get__(self, type(self))()
        return await messages.handle_scheduled_message(message, task_name)

    def _set_pending_approval(
        self, request: Optional[PendingApprovalRequest]
    ) -> None:
        """Keep the latest pending approval available on the handler."""
        self._pending_approval = request

    def _get_telegram_formatter(self) -> TelegramResponseFormatter:
        """Lazily resolve the Telegram formatter."""
        formatter = getattr(self, "_telegram_formatter", None)
        if formatter is None:
            formatter = TelegramResponseFormatter()
            try:
                self._telegram_formatter = formatter
            except Exception:
                pass
        return formatter

    def _get_conversation_service(self) -> ConversationService:
        """Lazily resolve the conversation orchestrator."""
        service = getattr(self, "_conversation_service", None)
        if service is None:
            service = ConversationService(
                config=getattr(self, "config", None),
                memory=self.memory,
                embedding_client=getattr(self, "embedding_client", None),
                llm_client=self.llm_client,
                memory_search_tool=self.memory_search_tool,
                mcp_client=getattr(self, "mcp_client", None),
                ensure_mcp_connected=getattr(self, "_ensure_mcp_connected", None),
                preview_text=self._preview_text,
            )
            try:
                self._conversation_service = service
            except Exception:
                pass
        return service

    def _get_tool_executor_service(self) -> ToolExecutor:
        """Lazily resolve the tool executor."""
        executor = getattr(self, "_tool_executor_service", None)
        if not isinstance(executor, ToolExecutor):
            registry_service = getattr(self, "_tool_registry_service", None)
            if not isinstance(registry_service, ToolRegistry):
                registry_service = ToolRegistry()
                for registered_name, tool in getattr(self, "_tool_registry", {}).items():
                    registry_service.register_named(registered_name, tool)

            executor = ToolExecutor(
                config=getattr(self, "config", None),
                tool_registry=registry_service,
                mcp_client=getattr(self, "mcp_client", None),
                ensure_mcp_connected=getattr(self, "_ensure_mcp_connected", None),
                is_mcp_connected=lambda: getattr(self, "_mcp_connected", False),
                is_dangerous_action=MessageHandler._is_dangerous_action.__get__(
                    self, type(self)
                ),
                request_approval=MessageHandler._request_approval.__get__(
                    self, type(self)
                ),
                record_tool_trace=MessageHandler._record_tool_trace.__get__(
                    self, type(self)
                ),
                infer_tool_trace_status=MessageHandler._infer_tool_trace_status.__get__(
                    self, type(self)
                ),
                notify_approved_action_finished=(
                    MessageHandler._notify_approved_action_finished.__get__(
                        self, type(self)
                    )
                ),
                notify_approved_action_failed=(
                    MessageHandler._notify_approved_action_failed.__get__(
                        self, type(self)
                    )
                ),
                preview_text=self._preview_text,
                telegram_bot=getattr(self, "telegram_bot", None),
            )
            try:
                self._tool_registry_service = registry_service
                self._tool_executor_service = executor
            except Exception:
                pass
        return executor

    def _get_files(self) -> TelegramFiles:
        """Lazily resolve Telegram file operations."""
        files = getattr(self, "_files", None)
        if not isinstance(files, TelegramFiles):
            files = TelegramFiles(
                config=getattr(self, "config", None),
                memory=self.memory,
            )
        return files

    def _get_tool_runtime(self) -> ToolRuntime:
        """Lazily resolve the tool runtime helper."""
        runtime = getattr(self, "_tool_runtime", None)
        if not isinstance(runtime, ToolRuntime):
            runtime = ToolRuntime(
                handler=self,
                memory_search_tool_cls=MemorySearchTool,
                mcp_client_cls=MCPClient,
            )
        return runtime

    def _get_commands(self) -> TelegramCommands:
        """Lazily resolve the Telegram command helper."""
        commands = getattr(self, "_commands", None)
        if not isinstance(commands, TelegramCommands):
            commands = TelegramCommands(self)
            try:
                self._commands = commands
            except Exception:
                pass
        return commands

    def _get_messages(self) -> TelegramMessages:
        """Lazily resolve the Telegram message helper."""
        messages = getattr(self, "_messages", None)
        if not isinstance(messages, TelegramMessages):
            messages = TelegramMessages(self)
            try:
                self._messages = messages
            except Exception:
                pass
        return messages

    async def _send_intermediate_response(self, text: str) -> None:
        """Stream intermediate assistant text to Telegram when available."""
        if not text.strip():
            return

        formatted = self._format_response_for_telegram(text)
        segments = self._split_message_into_segments(formatted)
        for i, segment in enumerate(segments):
            try:
                if hasattr(self, "telegram_bot") and self.telegram_bot:
                    await self.telegram_bot.send_message(
                        chat_id=self.config.TELEGRAM_USER_ID,
                        text=segment,
                        parse_mode="HTML",
                    )
                    if i < len(segments) - 1:
                        await asyncio.sleep(random.uniform(1.0, 2.0))
            except Exception:
                try:
                    if hasattr(self, "telegram_bot") and self.telegram_bot:
                        await self.telegram_bot.send_message(
                            chat_id=self.config.TELEGRAM_USER_ID,
                            text=segment,
                        )
                except Exception as e2:
                    logger.error(f"Failed to send intermediate segment: {e2}")

    def _format_response_for_telegram(self, text: str) -> str:
        """Format response text for Telegram HTML"""
        formatter = getattr(self, "_telegram_formatter", None)
        if not isinstance(formatter, TelegramResponseFormatter):
            formatter = TelegramResponseFormatter()
        return formatter.format_response(text, debug_mode=Config.DEBUG_MODE)

    def _split_message_into_segments(
        self, text: str, max_length: int = 4000
    ) -> List[str]:
        """Split message into Telegram-safe segments."""
        formatter = getattr(self, "_telegram_formatter", None)
        if not isinstance(formatter, TelegramResponseFormatter):
            formatter = TelegramResponseFormatter()
        return formatter.split_message_into_segments(text, max_length=max_length)

    def _collect_builtin_tool_defs(self) -> List[Dict[str, Any]]:
        """Collect OpenAI-format tool definitions for all registered builtin tools."""
        return self._get_tool_runtime().collect_builtin_tool_defs()

    def _setup_tools(self):
        """Setup tool system for LLM"""
        self._get_tool_runtime().setup_tools()

    def _setup_basic_tools(self):
        """Setup basic (non-MCP) tools and register executor in LLM client."""
        self._get_tool_runtime().setup_basic_tools()

    async def _ensure_mcp_connected(self):
        """Ensure MCP client is connected"""
        await self._get_tool_runtime().ensure_mcp_connected()

    def _is_path_outside_allowed_dirs(self, target_path: str) -> bool:
        """Check whether a path resolves outside workspace/media allowed dirs."""
        if not target_path:
            return False
        try:
            candidate = Path(target_path).expanduser()
            if not candidate.is_absolute():
                candidate = Path(self.config.WORKSPACE_DIR) / candidate
            resolved = candidate.resolve(strict=False)
            allowed_dirs = [
                Path(self.config.WORKSPACE_DIR).resolve(),
                Path(self.config.MEDIA_DIR).resolve(),
            ]

            for allowed_dir in allowed_dirs:
                try:
                    resolved.relative_to(allowed_dir)
                    return False
                except ValueError:
                    continue

            return True
        except Exception as e:
            logger.error(f"Error checking path bounds: {e}")
            return True  # If we can't resolve, assume dangerous

    def _is_file_outside_workspace(self, arguments: dict) -> bool:
        """Check if a file tool targets a path outside WORKSPACE_DIR."""
        return self._is_path_outside_allowed_dirs(arguments.get("file_path", ""))

    def _is_dangerous_action(self, tool_name: str, arguments: dict) -> tuple[bool, str]:
        """Determine if a tool call requires user approval.

        Returns:
            (needs_approval, reason)
        """
        _PATH_GUARDED_TOOLS = {
            "write_file": "file_path",
            "replace_file_content": "file_path",
            "append_file": "file_path",
            "read_file": "file_path",
            "grep_search": "path",
            "glob_search": "path",
        }

        # Shell command: check against threat signatures
        if tool_name == "execute_shell_command":
            cmd = arguments.get("command", "")
            dangerous, category = is_dangerous_command(cmd)
            if dangerous:
                return True, f"shell_threat:{category}"

            cwd = arguments.get("cwd", "")
            if cwd and self._is_path_outside_allowed_dirs(cwd):
                return True, "file_outside_workspace"

        # Path-based tools: require approval when target resolves outside workspace/media.
        path_argument = _PATH_GUARDED_TOOLS.get(tool_name)
        if path_argument:
            if self._is_path_outside_allowed_dirs(arguments.get(path_argument, "")):
                return True, "file_outside_workspace"

        return False, ""

    async def _request_approval(
        self, tool_name: str, arguments: dict, reason: str
    ) -> bool:
        """Send an approval request to the user via Telegram."""
        commands = MessageHandler._get_commands.__get__(self, type(self))()
        return await commands.request_approval(tool_name, arguments, reason)

    async def _send_status_message(
        self, text: str, parse_mode: Optional[str] = None
    ) -> None:
        """Best-effort Telegram status notification."""
        commands = MessageHandler._get_commands.__get__(self, type(self))()
        await commands.send_status_message(text, parse_mode=parse_mode)

    async def _notify_approved_action_finished(
        self, tool_name: str, result: str
    ) -> None:
        """Inform user that an approved action finished running."""
        commands = MessageHandler._get_commands.__get__(self, type(self))()
        await commands.notify_approved_action_finished(tool_name, result)

    async def _notify_approved_action_failed(
        self, tool_name: str, error: Exception
    ) -> None:
        """Inform user that an approved action failed unexpectedly."""
        commands = MessageHandler._get_commands.__get__(self, type(self))()
        await commands.notify_approved_action_failed(tool_name, error)

    async def handle_approve(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle /approve command to authorize a pending dangerous action."""
        commands = MessageHandler._get_commands.__get__(self, type(self))()
        await commands.handle_approve(update, context)

    async def _execute_tool(self, tool_name: str, arguments_json: str) -> str:
        """Execute a tool call from LLM"""
        registry_service = getattr(self, "_tool_registry_service", None)
        if isinstance(registry_service, ToolRegistry):
            for registered_name, tool in getattr(self, "_tool_registry", {}).items():
                registry_service.register_named(registered_name, tool)

        executor = MessageHandler._get_tool_executor_service.__get__(self, type(self))()
        executor.mcp_client = getattr(self, "mcp_client", None)
        executor.telegram_bot = getattr(self, "telegram_bot", None)
        return await executor.execute_tool(tool_name, arguments_json)

    def _get_elapsed_ms(self, start_time: float) -> int:
        """Convert a perf_counter start time into an integer millisecond duration."""
        return int((time.perf_counter() - start_time) * 1000)

    def _infer_tool_trace_status(self, result: Any) -> str:
        """Classify a tool result into success/error for logging."""
        result_text = str(result)
        if result_text.startswith("Error:") or result_text.startswith("Command failed"):
            return "error"
        return "success"

    async def _record_tool_trace(
        self,
        *,
        tool_name: str,
        arguments: Dict[str, Any],
        result: Any,
        status: str,
        duration_ms: int,
        approval_required: bool,
        approved_by_user: bool,
    ) -> None:
        """Persist a tool execution trace unless the tool is the trace query tool itself."""
        if tool_name == "query_tool_history":
            return

        try:
            session_id = None
            if hasattr(self, "memory") and self.memory is not None:
                session_id = self.memory.get_current_session_id()

            self.tool_trace_store.append_trace(
                session_id=session_id,
                tool_name=tool_name,
                arguments=arguments,
                result=result,
                status=status,
                duration_ms=duration_ms,
                approval_required=approval_required,
                approved_by_user=approved_by_user,
            )
        except Exception as e:
            logger.warning(f"Failed to persist tool trace for {tool_name}: {e}")

    async def handle_message(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle regular text messages."""
        messages = MessageHandler._get_messages.__get__(self, type(self))()
        await messages.handle_message(update, context)

    def _sanitize_filename(self, filename: str) -> str:
        """Sanitize filename for safe local storage."""
        messages = MessageHandler._get_messages.__get__(self, type(self))()
        return messages.sanitize_filename(filename)

    def _guess_extension(
        self, original_name: Optional[str], mime_type: Optional[str], file_type: str
    ) -> str:
        """Guess a suitable file extension."""
        messages = MessageHandler._get_messages.__get__(self, type(self))()
        return messages.guess_extension(original_name, mime_type, file_type)

    def _build_media_file_path(
        self,
        original_name: Optional[str],
        file_unique_id: str,
        mime_type: Optional[str],
        file_type: str,
    ) -> Path:
        """Build a unique path for a Telegram attachment."""
        messages = MessageHandler._get_messages.__get__(self, type(self))()
        return messages.build_media_file_path(
            original_name,
            file_unique_id,
            mime_type,
            file_type,
        )

    def _extract_file_info_from_update(
        self, update: Update
    ) -> Optional[Dict[str, Any]]:
        """Extract normalized file information from a Telegram update."""
        messages = MessageHandler._get_messages.__get__(self, type(self))()
        return messages.extract_file_info_from_update(update)

    async def _download_telegram_file(
        self, context: ContextTypes.DEFAULT_TYPE, file_id: str, destination: Path
    ) -> Path:
        """Download a Telegram file to the configured media directory."""
        messages = MessageHandler._get_messages.__get__(self, type(self))()
        return await messages.download_telegram_file(context, file_id, destination)

    def _format_saved_media_path(self, saved_path: Path) -> str:
        """Format saved path for user-facing/system-facing messages."""
        files = MessageHandler._get_files.__get__(self, type(self))()
        return files.format_saved_media_path(saved_path)

    def _resolve_telegram_file_path(self, file_path: str) -> Path:
        """Resolve a tool-provided file path against the workspace."""
        files = MessageHandler._get_files.__get__(self, type(self))()
        return files.resolve_telegram_file_path(file_path)

    def _is_allowed_telegram_file_path(self, resolved_path: Path) -> bool:
        """Check that the path is inside the allowed directories."""
        files = MessageHandler._get_files.__get__(self, type(self))()
        return files.is_allowed_telegram_file_path(resolved_path)

    def _detect_telegram_delivery_method(
        self, resolved_path: Path, file_type: str = "auto"
    ) -> str:
        """Detect which Telegram API should be used for the file."""
        files = MessageHandler._get_files.__get__(self, type(self))()
        return files.detect_telegram_delivery_method(resolved_path, file_type=file_type)

    def _build_sent_file_event_message(
        self, sent_path: Path, delivery_method: str, caption: Optional[str] = None
    ) -> str:
        """Build assistant-role system-tone event text for sent files."""
        files = MessageHandler._get_files.__get__(self, type(self))()
        return files.build_sent_file_event_message(
            sent_path,
            delivery_method,
            caption,
        )

    async def _send_telegram_file_to_user(
        self,
        file_path: str,
        caption: Optional[str] = None,
        file_type: str = "auto",
    ) -> Dict[str, Any]:
        """Send a local file to the Telegram user and record the event in memory."""
        files = MessageHandler._get_files.__get__(self, type(self))()
        return await files.send_file_to_user(
            telegram_bot=getattr(self, "telegram_bot", None),
            file_path=file_path,
            caption=caption,
            file_type=file_type,
        )

    def _build_file_event_message(
        self, file_info: Dict[str, Any], saved_path: Path
    ) -> str:
        """Build the synthetic user message describing the uploaded file."""
        messages = MessageHandler._get_messages.__get__(self, type(self))()
        return messages.build_file_event_message(file_info, saved_path)

    async def handle_file(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle incoming Telegram attachments by saving them and notifying the LLM."""
        messages = MessageHandler._get_messages.__get__(self, type(self))()
        await messages.handle_file(update, context)

    async def handle_new_session(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle /new command."""
        commands = MessageHandler._get_commands.__get__(self, type(self))()
        await commands.handle_new_session(update, context)

    async def handle_reset_session(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle /reset command."""
        commands = MessageHandler._get_commands.__get__(self, type(self))()
        await commands.handle_reset_session(update, context)

    async def _process_message(self, user_message: str) -> str:
        """Process a user message through memory and the LLM."""
        messages = MessageHandler._get_messages.__get__(self, type(self))()
        return await messages.process_message(user_message)

    async def _process_scheduled_task(
        self, task_message: str, task_name: str = "Scheduled Task"
    ) -> str:
        """Process a scheduled task message through the LLM."""
        messages = MessageHandler._get_messages.__get__(self, type(self))()
        return await messages.process_scheduled_task(task_message, task_name)



