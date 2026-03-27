"""Message handlers for Telegram bot"""

import asyncio
from dataclasses import dataclass
import html
import json
import mimetypes
import random
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from telegram import Update
from telegram.ext import ContextTypes

from config import Config
from core.database import DatabaseManager
from core.memory import MemoryManager
from core.scheduler import TaskScheduler
from llm.embedding import EmbeddingClient
from llm.reranker import RerankerClient
from tools.memory_search import MemorySearchTool
from tools.mcp_client import MCPClient
from tools.scheduled_task_tool import ScheduledTaskTool
from tools.send_telegram_file_tool import SendTelegramFileTool
from tools.tool_trace import ToolTraceStore, ToolTraceQueryTool
from tools.file_io import (
    ReadFileTool,
    WriteFileTool,
    ReplaceFileContentTool,
    AppendFileTool,
)
from tools.file_search import GrepSearchTool, GlobSearchTool
from tools.shell import ShellCommandTool, is_dangerous_command
from tools.file_io import _resolve_file_path
from llm.client import LLMClient
from utils.logger import get_logger

logger = get_logger()


@dataclass
class PendingApprovalRequest:
    """Represents a dangerous action waiting for user approval."""

    tool_name: str
    arguments: Dict[str, Any]
    reason: str
    future: asyncio.Future
    created_at: float


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

        # Initialize scheduled task tool with scheduler
        self.scheduled_task_tool = None
        self.scheduled_task_tool_def = None
        self._register_scheduled_task_tool()

        # Initialize Telegram file sending tool
        self.send_telegram_file_tool = None
        self.send_telegram_file_tool_def = None
        self.telegram_bot = None
        self._register_send_telegram_file_tool()

        # Initialize tool trace logging and query tool
        self.tool_trace_store = ToolTraceStore(self.config.DATA_DIR)
        self.tool_trace_query_tool = ToolTraceQueryTool(
            self.tool_trace_store, self.memory.get_current_session_id
        )

        # Initialize LLM client
        self.llm_client = LLMClient()

        # Tool registry: maps tool_name -> tool instance (for fast dispatch)
        self._tool_registry: Dict[str, Any] = {}

        # Initialize builtin system tools
        self.read_file_tool = None
        self.write_file_tool = None
        self.replace_file_content_tool = None
        self.append_file_tool = None
        self.grep_search_tool = None
        self.glob_search_tool = None
        self.shell_command_tool = None
        self._register_builtin_tools()

        # HITL approval state
        self._pending_approval: Optional[PendingApprovalRequest] = None
        self._approval_lock = asyncio.Lock()

        # Initialize attributes
        self.memory_search_tool = None
        self.mcp_client = None
        self._mcp_connected = False

        # Setup tools for LLM
        self._setup_tools()

        # Setup scheduler callback (will be started as Application job in bot.py)
        self.scheduler.set_message_callback(self._handle_scheduled_message)
        logger.info("Task scheduler callback registered")

        logger.info("MessageHandler initialized")

    def _register_scheduled_task_tool(self):
        """Register the scheduled task tool with scheduler instance"""
        try:
            self.scheduled_task_tool = ScheduledTaskTool(self.scheduler)
            self.scheduled_task_tool_def = {
                "type": "function",
                "function": {
                    "name": self.scheduled_task_tool.name,
                    "description": self.scheduled_task_tool.description,
                    "parameters": self.scheduled_task_tool.parameters,
                },
            }
            logger.info("Registered scheduled_task tool with scheduler")
        except Exception as e:
            logger.error(f"Failed to register scheduled_task tool: {e}")
            self.scheduled_task_tool = None
            self.scheduled_task_tool_def = None

    def _register_send_telegram_file_tool(self):
        """Register the Telegram file sending tool."""
        try:
            self.send_telegram_file_tool = SendTelegramFileTool(
                self._send_telegram_file_to_user
            )
            self.send_telegram_file_tool_def = {
                "type": "function",
                "function": {
                    "name": self.send_telegram_file_tool.name,
                    "description": self.send_telegram_file_tool.description,
                    "parameters": self.send_telegram_file_tool.parameters,
                },
            }
            logger.info("Registered send_telegram_file tool")
        except Exception as e:
            logger.error(f"Failed to register send_telegram_file tool: {e}")
            self.send_telegram_file_tool = None
            self.send_telegram_file_tool_def = None

    def set_telegram_bot(self, bot: Any) -> None:
        """Inject Telegram bot instance for proactive file sending."""
        self.telegram_bot = bot
        logger.info("Telegram bot instance injected into MessageHandler")

    @staticmethod
    def _make_tool_def(tool: Any) -> Dict[str, Any]:
        """Build an OpenAI-format tool definition from a tool instance."""
        return {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.parameters,
            },
        }

    def _register_builtin_tools(self):
        """Register builtin file and shell tools."""
        try:
            self.read_file_tool = ReadFileTool()
            self.write_file_tool = WriteFileTool()
            self.replace_file_content_tool = ReplaceFileContentTool()
            self.append_file_tool = AppendFileTool()
            self.grep_search_tool = GrepSearchTool()
            self.glob_search_tool = GlobSearchTool()
            self.shell_command_tool = ShellCommandTool()

            # Build registry and tool defs
            builtin_tools = [
                self.read_file_tool,
                self.write_file_tool,
                self.replace_file_content_tool,
                self.append_file_tool,
                self.grep_search_tool,
                self.glob_search_tool,
                self.shell_command_tool,
            ]
            for tool in builtin_tools:
                self._tool_registry[tool.name] = tool

            logger.info("Registered builtin file and shell tools")
        except Exception as e:
            logger.error(f"Failed to register builtin tools: {e}")

    async def _handle_scheduled_message(
        self, message: str, task_name: str = "Scheduled Task"
    ) -> str:
        """Handle messages from scheduled tasks - trigger LLM conversation

        This method is called when a scheduled task triggers. It:
        1. Wraps the task message with [SYSTEM_SCHEDULED_TASK] marker
        2. Does NOT save the task message to database (transient)
        3. Calls LLM to generate a response
        4. Saves the LLM response to database (part of session)
        5. Returns the LLM response for sending to user

        Args:
            message: Raw task message from scheduler
            task_name: Name of the scheduled task for context

        Returns:
            LLM generated response to send to user
        """
        logger.info(f"Processing scheduled task '{task_name}': {message[:50]}...")
        return await self._process_scheduled_task(message, task_name)

    def _format_response_for_telegram(self, text: str) -> str:
        """Format response text for Telegram HTML"""
        # We are switching to HTML parse mode as it is more robust for our needs
        # We need to escape special HTML characters in the text, but PRESERVE our blockquote tags
        # and other formatting if we want to support it.

        # However, the LLM outputs markdown-like text (e.g. **bold**) and our specific blockquotes.
        # So we need a comprehensive formatter:
        # 1. Escape HTML special chars in the whole text (except our tags? No, that's hard).
        # Better approach:
        # 1. Split text by our known tags (blockquote).
        # 2. For the non-tag parts, escape HTML (<, >, &).
        # 3. For the tag parts, keep them as is (Telegram supports <blockquote> in HTML mode).
        # 4. Also handle markdown bold/italic if possible, OR just strip them/convert them.

        # Simplified approach consistent with user request:
        # User wants blockquotes to be CODE BLOCKS to avoid issues.
        # So we will convert <blockquote>...</blockquote> to <pre>...</pre> (which is code block in HTML).

        # Helper to escape text but preserve code blocks we create
        # But wait, if we use HTML, we can just use <pre> tag!

        # Strategy:
        # 1. Replace <blockquote>...</blockquote> with a temporary unique placeholder
        # 2. Escape the rest of the text
        # 3. Replace placeholder with <pre>...escaped_content...</pre>
        # 4. Handle **bold** -> <b>bold</b> conversions manually or just leave as is?
        #    If we switch to HTML, **bold** won't render as bold unless we convert it.
        #    We should try to support basic markdown bold.

        from config import Config
        from utils.text import strip_blockquotes

        if not Config.DEBUG_MODE:
            text = strip_blockquotes(text)

        # Step 1: Extract blockquotes and fenced code blocks
        placeholders = []

        def _save_preformatted_block(content: str) -> str:
            placeholders.append(content)
            return f"PREFORMATTEDPLACEHOLDER{len(placeholders) - 1}END"

        def save_fenced_code_block(match):
            content = match.group(2)
            if content is None:
                content = ""
            return _save_preformatted_block(content.strip())

        def save_blockquote(match):
            content = match.group(1).strip()
            return _save_preformatted_block(content)

        text_with_fenced_placeholders = re.sub(
            r"```([^\n`]*)\n(.*?)```",
            save_fenced_code_block,
            text,
            flags=re.DOTALL,
        )

        text_with_placeholders = re.sub(
            r"<\s*blockquote[^>]*>(.*?)<\s*/\s*blockquote\s*>",
            save_blockquote,
            text_with_fenced_placeholders,
            flags=re.DOTALL | re.IGNORECASE,
        )

        # Step 2: Escape HTML in the main text
        escaped_text = html.escape(text_with_placeholders)

        # Step 3: Convert Markdown to HTML
        # Bold (**text**) -> <b>text</b>
        escaped_text = re.sub(r"\*\*(.*?)\*\*", r"<b>\1</b>", escaped_text)

        # Italic (*text* or _text_) -> <i>text</i>
        # Note: we use _text_ for italics but __text__ for underline to match Telegram expectations
        escaped_text = re.sub(
            r"(?<!\*)\*(?!\*)(.*?)(?<!\*)\*(?!\*)", r"<i>\1</i>", escaped_text
        )
        escaped_text = re.sub(
            r"(?<!_)_(?!_)(.*?)(?<!_)_(?!_)", r"<i>\1</i>", escaped_text
        )

        # Underline (__text__) -> <u>text</u>
        escaped_text = re.sub(r"__(.*?)__", r"<u>\1</u>", escaped_text)

        # Inline code (`code`) -> <code>code</code>
        escaped_text = re.sub(r"`(.*?)`", r"<code>\1</code>", escaped_text)

        # Strikethrough (~~text~~ or ~text~) -> <s>text</s>
        escaped_text = re.sub(r"~~(.*?)~~", r"<s>\1</s>", escaped_text)

        # Spoiler (||text||) -> <tg-spoiler>text</tg-spoiler>
        escaped_text = re.sub(
            r"\|\|(.*?)\|\|", r"<tg-spoiler>\1</tg-spoiler>", escaped_text
        )

        # Links ([text](url)) -> <a href="url">text</a>
        escaped_text = re.sub(
            r"\[(.*?)\]\((.*?)\)", r'<a href="\2">\1</a>', escaped_text
        )

        # Step 4: Restore preformatted content as <pre> blocks
        # We need to escape the content inside the block too, because it's going into HTML
        def restore_preformatted_block(match):
            idx = int(match.group(1))
            original_content = placeholders[idx]
            escaped_content = html.escape(original_content)
            return f"<pre>{escaped_content}</pre>"

        final_text = re.sub(
            r"PREFORMATTEDPLACEHOLDER(\d+)END",
            restore_preformatted_block,
            escaped_text,
        )

        return final_text

    def _split_message_into_segments(
        self, text: str, max_length: int = 4000
    ) -> List[str]:
        """Split message into segments, keeping code blocks and blockquotes intact.

        Args:
            text: Formatted text for Telegram (HTML)
            max_length: Maximum length per segment (Telegram limit is ~4096)

        Returns:
            List of message segments
        """
        segments: List[str] = []

        def _append_segment(content: str) -> None:
            if content and content.strip():
                segments.append(content.strip())

        def _split_long_text(content: str, limit: int) -> List[str]:
            if len(content) <= limit:
                return [content]

            chunks: List[str] = []
            remaining = content

            while len(remaining) > limit:
                slice_text = remaining[:limit]
                split_index = max(slice_text.rfind("\n"), slice_text.rfind(" "))
                if split_index <= 0:
                    split_index = limit

                chunk = remaining[:split_index].strip()
                if chunk:
                    chunks.append(chunk)

                remaining = remaining[split_index:].lstrip()

            if remaining:
                chunks.append(remaining.strip())

            return chunks

        # Pattern to match code blocks (<pre>...</pre>) and blockquotes (<blockquote>...</blockquote>)
        # These should never be split
        pattern = r"(<pre>.*?</pre>|<blockquote>.*?</blockquote>)"

        # Split by the pattern, keeping delimiters
        parts = re.split(pattern, text, flags=re.DOTALL)

        for part in parts:
            if not part:
                continue

            # Check if this part is a code block or blockquote
            is_code_block = part.startswith("<pre>") and part.endswith("</pre>")
            is_blockquote = part.startswith("<blockquote>") and part.endswith(
                "</blockquote>"
            )

            if is_code_block or is_blockquote:
                # Always keep blocks intact as their own segments
                _append_segment(part)
                continue

            # Regular text - split by paragraph and send each paragraph separately
            paragraphs = [p for p in part.split("\n\n") if p.strip()]

            for para in paragraphs:
                paragraph_pieces = _split_long_text(para, max_length)
                for piece in paragraph_pieces:
                    _append_segment(piece)

        return [seg for seg in segments if seg]

    def _collect_builtin_tool_defs(self) -> List[Dict[str, Any]]:
        """Collect OpenAI-format tool definitions for all registered builtin tools."""
        defs = []
        for tool in self._tool_registry.values():
            defs.append(self._make_tool_def(tool))
        return defs

    def _setup_tools(self):
        """Setup tool system for LLM"""
        # Add MCP tools (will be initialized async later)
        if self.config.ENABLE_MCP:
            self.mcp_client = MCPClient()
            self._mcp_connected = False
        else:
            self.mcp_client = None
            self._mcp_connected = False

        self._setup_basic_tools()

    def _setup_basic_tools(self):
        """Setup basic (non-MCP) tools and register executor in LLM client."""
        tools: List[Dict[str, Any]] = []

        if self.scheduled_task_tool_def:
            tools.append(self.scheduled_task_tool_def)
            logger.info("Added scheduled_task tool")

        if self.send_telegram_file_tool_def:
            tools.append(self.send_telegram_file_tool_def)
            logger.info("Added send_telegram_file tool")

        if self.tool_trace_query_tool:
            self._tool_registry[self.tool_trace_query_tool.name] = (
                self.tool_trace_query_tool
            )
            logger.info("Added query_tool_history tool")

        # Add builtin tools from registry
        tools.extend(self._collect_builtin_tool_defs())

        # Add memory search tool
        session_id = self.memory.get_current_session_id()
        if not hasattr(self, "memory_search_tool") or self.memory_search_tool is None:
            self.memory_search_tool = MemorySearchTool(
                session_id=str(session_id),
                db=self.db,
                embedding_client=self.embedding_client,
                reranker_client=self.reranker_client,
            )
        # Register memory/scheduled/telegram tools in the registry too
        self._tool_registry[self.memory_search_tool.name] = self.memory_search_tool
        if self.scheduled_task_tool:
            self._tool_registry[self.scheduled_task_tool.name] = (
                self.scheduled_task_tool
            )
        if self.send_telegram_file_tool:
            self._tool_registry[self.send_telegram_file_tool.name] = (
                self.send_telegram_file_tool
            )

        tools.append(self._make_tool_def(self.memory_search_tool))
        logger.info("Added memory_search tool")

        # Set tools and executor in LLM client
        self.llm_client.set_tools(tools)
        self.llm_client.set_tool_executor(self._execute_tool)

        logger.info(f"Basic tools registered: {len(tools)}")

    async def _ensure_mcp_connected(self):
        """Ensure MCP client is connected"""
        if self.mcp_client and not self._mcp_connected:
            try:
                await self.mcp_client.__aenter__()
                self._mcp_connected = True

                # Get and register MCP tools
                mcp_tools = await self.mcp_client.list_tools()
                logger.info(f"Connected MCP client with {len(mcp_tools)} tools")
                for tool in mcp_tools:
                    tool_func = tool.get("function", {})
                    name = tool_func.get("name", "Unknown")
                    desc = tool_func.get("description", "No description")
                    logger.debug(f"  - [MCP Tool] {name}: {desc}")

                # Rebuild all tools list
                all_tools: List[Dict[str, Any]] = []

                # 1. Add all locally registered tools (builtin, memory_search, scheduled_task, send_telegram_file etc.)
                all_tools.extend(self._collect_builtin_tool_defs())

                # 2. Add MCP tools last - keep them at the end of the tool list
                all_tools.extend(mcp_tools)

                self.llm_client.set_tools(all_tools)
                logger.info(
                    f"Updated tools: {len(all_tools)} total including {len(mcp_tools)} MCP tools"
                )
            except Exception as e:
                logger.error(f"Failed to connect MCP client: {e}")
                self._mcp_connected = False
                # Ensure we still have basic tools even if MCP fails
                self._setup_basic_tools()

    def _is_file_outside_workspace(self, arguments: dict) -> bool:
        """Check if a file tool targets a path outside WORKSPACE_DIR."""
        file_path = arguments.get("file_path", "")
        if not file_path:
            return False
        try:
            resolved = Path(_resolve_file_path(file_path)).resolve()
            workspace = Path(self.config.WORKSPACE_DIR).resolve()
            try:
                resolved.relative_to(workspace)
                return False  # Inside workspace
            except ValueError:
                # Check MEDIA_DIR as well
                media_dir = Path(self.config.MEDIA_DIR).resolve()
                try:
                    resolved.relative_to(media_dir)
                    return False  # Inside media dir
                except ValueError:
                    return True  # Outside both
        except Exception as e:
            logger.error(f"Error checking path bounds: {e}")
            return True  # If we can't resolve, assume dangerous

    def _is_dangerous_action(self, tool_name: str, arguments: dict) -> tuple[bool, str]:
        """Determine if a tool call requires user approval.

        Returns:
            (needs_approval, reason)
        """
        _FILE_IO_TOOLS = {
            "write_file",
            "replace_file_content",
            "append_file",
            "read_file",
        }

        # Shell command: check against threat signatures
        if tool_name == "execute_shell_command":
            cmd = arguments.get("command", "")
            dangerous, category = is_dangerous_command(cmd)
            if dangerous:
                return True, f"shell_threat:{category}"

        # File I/O tools: check if path is outside workspace
        if tool_name in _FILE_IO_TOOLS:
            if self._is_file_outside_workspace(arguments):
                return True, "file_outside_workspace"

        return False, ""

    async def _request_approval(
        self, tool_name: str, arguments: dict, reason: str
    ) -> bool:
        """Send an approval request to the user via Telegram and wait for /approve or rejection.

        Returns:
            True if approved, False if rejected.
        """
        async with self._approval_lock:
            loop = asyncio.get_running_loop()
            pending_request = PendingApprovalRequest(
                tool_name=tool_name,
                arguments=dict(arguments),
                reason=reason,
                future=loop.create_future(),
                created_at=loop.time(),
            )
            self._pending_approval = pending_request

            # Build notification message
            args_str = html.escape(json.dumps(arguments, ensure_ascii=False)[:800])
            msg = (
                f"⚠️ <b>DANGEROUS ACTION DETECTED</b> ⚠️\n\n"
                f"<b>Tool:</b> <code>{html.escape(tool_name)}</code>\n"
                f"<b>Reason:</b> <code>{html.escape(reason)}</code>\n"
                f"<b>Arguments:</b>\n<pre>{args_str}</pre>\n\n"
                f"Reply <b>/approve</b> to execute.\n"
                f"Any other message will <b>ABORT</b> this action."
            )

            if hasattr(self, "telegram_bot") and self.telegram_bot:
                try:
                    await self.telegram_bot.send_message(
                        chat_id=self.config.TELEGRAM_USER_ID,
                        text=msg,
                        parse_mode="HTML",
                    )
                except Exception as e:
                    logger.error(f"Failed to send approval request: {e}")
                    self._pending_approval = None
                    return False

            logger.info(
                "Approval request created for dangerous action: "
                f"tool={tool_name}, reason={reason}, args={arguments}"
            )

            # Wait for user response (timeout: 600 seconds)
            try:
                approved = await asyncio.wait_for(pending_request.future, timeout=600.0)
            except asyncio.TimeoutError:
                approved = False
                logger.warning(
                    "Approval request timed out: " f"tool={tool_name}, reason={reason}"
                )
                if hasattr(self, "telegram_bot") and self.telegram_bot:
                    try:
                        await self.telegram_bot.send_message(
                            chat_id=self.config.TELEGRAM_USER_ID,
                            text="⏰ Approval timed out. Action aborted.",
                        )
                    except Exception:
                        pass
            finally:
                if self._pending_approval is pending_request:
                    self._pending_approval = None

            return approved

    async def _send_status_message(
        self, text: str, parse_mode: Optional[str] = None
    ) -> None:
        """Best-effort Telegram status notification."""
        if not hasattr(self, "telegram_bot") or not self.telegram_bot:
            return

        try:
            kwargs: Dict[str, Any] = {
                "chat_id": self.config.TELEGRAM_USER_ID,
                "text": text,
            }
            if parse_mode:
                kwargs["parse_mode"] = parse_mode
            await self.telegram_bot.send_message(**kwargs)
        except Exception as e:
            logger.warning(f"Failed to send status message: {e}")

    async def _notify_approved_action_finished(
        self, tool_name: str, result: str
    ) -> None:
        """Inform user that an approved action finished running."""
        result_preview = html.escape(self._preview_text(result, max_length=300))
        if result.startswith("Error:") or result.startswith("Command failed"):
            prefix = "⚠️ <b>Approved action finished with an error-like result</b>"
        else:
            prefix = "✅ <b>Approved action finished</b>"

        msg = (
            f"{prefix}\n\n"
            f"<b>Tool:</b> <code>{html.escape(tool_name)}</code>\n"
            f"<b>Result preview:</b> <pre>{result_preview}</pre>"
        )
        await self._send_status_message(msg, parse_mode="HTML")

    async def _notify_approved_action_failed(
        self, tool_name: str, error: Exception
    ) -> None:
        """Inform user that an approved action failed unexpectedly."""
        error_preview = html.escape(self._format_exception_for_user(error))
        msg = (
            "❌ <b>Approved action failed unexpectedly</b>\n\n"
            f"<b>Tool:</b> <code>{html.escape(tool_name)}</code>\n"
            f"<b>Error:</b> <pre>{error_preview}</pre>"
        )
        await self._send_status_message(msg, parse_mode="HTML")

    async def handle_approve(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle /approve command to authorize a pending dangerous action."""
        if not update.effective_user or not update.message:
            return
        if update.effective_user.id != self.config.TELEGRAM_USER_ID:
            return

        pending_request = self._pending_approval
        if pending_request and not pending_request.future.done():
            pending_request.future.set_result(True)
            logger.info(
                "Approval received from user: "
                f"tool={pending_request.tool_name}, reason={pending_request.reason}"
            )
        else:
            await update.message.reply_text("No pending action to approve.")

    async def _execute_tool(self, tool_name: str, arguments_json: str) -> str:
        """Execute a tool call from LLM"""
        start_time = time.perf_counter()
        try:
            arguments = json.loads(arguments_json)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse tool arguments: {e}")
            return f"Error: Invalid JSON arguments: {e}"

        logger.info(f"Executing tool: {tool_name} with args: {arguments}")

        # HITL: Check if this action requires user approval
        dangerous, reason = self._is_dangerous_action(tool_name, arguments)
        approval_granted = False

        # Send generic tool notification only for non-dangerous actions to avoid
        # spamming the user with duplicate status messages.
        if not dangerous and hasattr(self, "telegram_bot") and self.telegram_bot:
            try:
                msg = f"🔧 <b>Tool execution:</b> <code>{tool_name}</code>\n"
                args_str = html.escape(json.dumps(arguments, ensure_ascii=False)[:500])
                msg += f"<b>Arguments:</b> <pre>{args_str}</pre>"

                # Using create_task so it doesn't block evaluation
                asyncio.create_task(
                    self.telegram_bot.send_message(
                        chat_id=self.config.TELEGRAM_USER_ID,
                        text=msg,
                        parse_mode="HTML",
                    )
                )
            except Exception as e:
                logger.warning(f"Failed to send tool execute notification: {e}")

        if dangerous:
            logger.warning(f"Dangerous action detected: {tool_name} reason={reason}")
            approved = await self._request_approval(tool_name, arguments, reason)
            if not approved:
                logger.info(f"User rejected dangerous action: {tool_name}")
                result = (
                    f"Error: Action was rejected by the user (reason: {reason}). "
                    "Do NOT retry this action."
                )
                await self._record_tool_trace(
                    tool_name=tool_name,
                    arguments=arguments,
                    result=result,
                    status="rejected",
                    duration_ms=self._get_elapsed_ms(start_time),
                    approval_required=True,
                    approved_by_user=False,
                )
                return result
            logger.info(f"User approved dangerous action: {tool_name}")
            approval_granted = True

        try:
            # Dispatch via tool registry (covers builtins, memory search,
            # scheduled task, send_telegram_file)
            tool_instance = self._tool_registry.get(tool_name)
            if tool_instance is not None:
                result = await tool_instance.execute(**arguments)
                logger.info(
                    f"Tool execution finished: {tool_name}, preview={self._preview_text(result)}"
                )
                await self._record_tool_trace(
                    tool_name=tool_name,
                    arguments=arguments,
                    result=result,
                    status=self._infer_tool_trace_status(result),
                    duration_ms=self._get_elapsed_ms(start_time),
                    approval_required=dangerous,
                    approved_by_user=approval_granted,
                )
                if approval_granted:
                    await self._notify_approved_action_finished(tool_name, result)
                return result

            # Fallback: check MCP tools
            if self.mcp_client:
                await self._ensure_mcp_connected()

                if self._mcp_connected:
                    mcp_tools = self.mcp_client.get_tools_sync()
                    if any(t["function"]["name"] == tool_name for t in mcp_tools):
                        result = await self.mcp_client.call_tool(tool_name, arguments)
                        logger.info(
                            f"MCP tool execution finished: {tool_name}, preview={self._preview_text(result)}"
                        )
                        await self._record_tool_trace(
                            tool_name=tool_name,
                            arguments=arguments,
                            result=result,
                            status=self._infer_tool_trace_status(result),
                            duration_ms=self._get_elapsed_ms(start_time),
                            approval_required=dangerous,
                            approved_by_user=approval_granted,
                        )
                        if approval_granted:
                            await self._notify_approved_action_finished(
                                tool_name, result
                            )
                        return result

            result = f"Error: Tool not found: {tool_name}"
            await self._record_tool_trace(
                tool_name=tool_name,
                arguments=arguments,
                result=result,
                status="error",
                duration_ms=self._get_elapsed_ms(start_time),
                approval_required=dangerous,
                approved_by_user=approval_granted,
            )
            if approval_granted:
                await self._notify_approved_action_finished(tool_name, result)
            return result
        except Exception as e:
            logger.error(
                f"Tool execution raised exception after approval state={approval_granted}: {tool_name} - {e}",
                exc_info=True,
            )
            await self._record_tool_trace(
                tool_name=tool_name,
                arguments=arguments,
                result=f"{type(e).__name__}: {e}",
                status="error",
                duration_ms=self._get_elapsed_ms(start_time),
                approval_required=dangerous,
                approved_by_user=approval_granted,
            )
            if approval_granted:
                await self._notify_approved_action_failed(tool_name, e)
            raise

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
        """Handle regular text messages

        Args:
            update: Telegram update object
            context: Telegram context
        """
        if not update.effective_user or not update.message or not update.message.text:
            return

        user_id = update.effective_user.id

        # Check authorization
        if user_id != self.config.TELEGRAM_USER_ID:
            await update.message.reply_text("Unauthorized access.")
            logger.warning(f"Unauthorized message from user {user_id}")
            return

        user_message = update.message.text
        logger.info(f"Received message: {user_message[:50]}...")

        # HITL: If there's a pending approval and user sends a non-/approve message, reject it
        pending_request = self._pending_approval
        if pending_request and not pending_request.future.done():
            pending_request.future.set_result(False)
            logger.info(
                "Pending approval aborted by non-/approve user message: "
                f"tool={pending_request.tool_name}, reason={pending_request.reason}"
            )
            await update.message.reply_text("❌ Pending action aborted.")
            return

        async def _keep_typing_indicator():
            """Background task to keep typing indicator active"""
            while True:
                try:
                    await context.bot.send_chat_action(
                        chat_id=update.effective_chat.id, action="typing"
                    )
                    await asyncio.sleep(3)  # Send typing action every 3 seconds
                except Exception as e:
                    logger.warning(f"Typing indicator failed: {e}")
                    await asyncio.sleep(3)

        try:
            # Start background task to keep typing indicator active
            typing_task = asyncio.create_task(_keep_typing_indicator())

            try:
                # Process message through memory and LLM
                response = await self._process_message(user_message)
                logger.info(
                    "Prepared final text for Telegram reply: "
                    f"{self._preview_text(response)}"
                )

                # Send response using HTML parse mode
                # We always use HTML now because we rely on it for <pre> blockquotes
                # Split long messages into segments, keeping code blocks intact
                formatted_response = self._format_response_for_telegram(response)
                segments = self._split_message_into_segments(formatted_response)

                logger.debug(f"Response split into {len(segments)} segments")
                logger.info(
                    f"Sending {len(segments)} Telegram segment(s) for text message"
                )

                for i, segment in enumerate(segments):
                    try:
                        logger.debug(
                            f"Sending Telegram text segment {i + 1}/{len(segments)}: "
                            f"{self._preview_text(segment)}"
                        )
                        await update.message.reply_text(
                            segment,
                            parse_mode="HTML",
                        )
                        logger.debug(
                            f"Sent segment {i + 1}/{len(segments)} ({len(segment)} chars)"
                        )

                        # Add delay between segments (except after the last one)
                        if i < len(segments) - 1:
                            delay = random.uniform(1.0, 2.0)
                            logger.debug(f"Waiting {delay:.1f}s before next segment")
                            await asyncio.sleep(delay)
                    except Exception as e:
                        # If HTML parsing fails for this segment, try sending as plain text
                        error_msg = str(e)
                        logger.warning(
                            f"HTML parsing failed for segment {i + 1}, sending as plain text: {error_msg}"
                        )
                        try:
                            await update.message.reply_text(segment)
                        except Exception as e2:
                            logger.error(f"Failed to send segment {i + 1}: {e2}")
            finally:
                # Cancel typing indicator task
                typing_task.cancel()
                try:
                    await typing_task
                except asyncio.CancelledError:
                    pass

        except Exception as e:
            logger.error(f"Error handling message: {e}", exc_info=True)
            await update.message.reply_text(
                "Sorry, an error occurred while processing your message.\n\n"
                f"Details: {self._format_exception_for_user(e)}"
            )

    def _sanitize_filename(self, filename: str) -> str:
        """Sanitize filename for safe local storage."""
        sanitized = re.sub(r'[\\/:*?"<>|\r\n\t]+', "_", filename).strip(" .")
        return sanitized or "file"

    def _guess_extension(
        self, original_name: Optional[str], mime_type: Optional[str], file_type: str
    ) -> str:
        """Guess a suitable file extension."""
        if original_name:
            suffix = Path(original_name).suffix
            if suffix:
                return suffix

        if mime_type:
            guessed = mimetypes.guess_extension(mime_type)
            if guessed:
                return guessed

        fallback_extensions = {
            "photo": ".jpg",
            "video": ".mp4",
            "audio": ".mp3",
            "voice": ".ogg",
            "document": "",
        }
        return fallback_extensions.get(file_type, "")

    def _build_media_file_path(
        self,
        original_name: Optional[str],
        file_unique_id: str,
        mime_type: Optional[str],
        file_type: str,
    ) -> Path:
        """Build a unique path for a Telegram attachment."""
        base_name = self._sanitize_filename(original_name or file_type)
        base_stem = Path(base_name).stem or file_type
        extension = self._guess_extension(original_name, mime_type, file_type)
        timestamp = asyncio.get_running_loop().time()
        unique_part = f"{int(timestamp * 1000)}_{file_unique_id}"
        filename = f"{base_stem}_{unique_part}{extension}"
        return self.config.MEDIA_DIR / filename

    def _extract_file_info_from_update(
        self, update: Update
    ) -> Optional[Dict[str, Any]]:
        """Extract normalized file information from a Telegram update."""
        if not update.message:
            return None

        message = update.message
        caption = getattr(message, "caption", None)

        if message.document:
            doc = message.document
            return {
                "file_id": doc.file_id,
                "file_unique_id": doc.file_unique_id,
                "file_type": "document",
                "original_name": doc.file_name,
                "mime_type": doc.mime_type,
                "file_size": doc.file_size,
                "caption": caption,
            }

        if message.photo:
            photo = message.photo[-1]
            return {
                "file_id": photo.file_id,
                "file_unique_id": photo.file_unique_id,
                "file_type": "photo",
                "original_name": None,
                "mime_type": "image/jpeg",
                "file_size": photo.file_size,
                "caption": caption,
            }

        if message.video:
            video = message.video
            return {
                "file_id": video.file_id,
                "file_unique_id": video.file_unique_id,
                "file_type": "video",
                "original_name": video.file_name,
                "mime_type": video.mime_type,
                "file_size": video.file_size,
                "caption": caption,
            }

        if message.audio:
            audio = message.audio
            return {
                "file_id": audio.file_id,
                "file_unique_id": audio.file_unique_id,
                "file_type": "audio",
                "original_name": audio.file_name,
                "mime_type": audio.mime_type,
                "file_size": audio.file_size,
                "caption": caption,
            }

        if message.voice:
            voice = message.voice
            return {
                "file_id": voice.file_id,
                "file_unique_id": voice.file_unique_id,
                "file_type": "voice",
                "original_name": None,
                "mime_type": voice.mime_type,
                "file_size": voice.file_size,
                "caption": caption,
            }

        return None

    async def _download_telegram_file(
        self, context: ContextTypes.DEFAULT_TYPE, file_id: str, destination: Path
    ) -> Path:
        """Download a Telegram file to the configured media directory."""
        telegram_file = await context.bot.get_file(file_id)
        destination.parent.mkdir(parents=True, exist_ok=True)
        await telegram_file.download_to_drive(custom_path=str(destination))
        return destination

    def _format_saved_media_path(self, saved_path: Path) -> str:
        """Format saved path for user-facing/system-facing messages."""
        return str(saved_path.resolve())

    def _resolve_telegram_file_path(self, file_path: str) -> Path:
        """Resolve a tool-provided file path against the workspace."""
        candidate = Path(file_path)
        if not candidate.is_absolute():
            candidate = self.config.WORKSPACE_DIR / candidate
        return candidate.resolve()

    def _is_allowed_telegram_file_path(self, resolved_path: Path) -> bool:
        """Check that the path is inside the allowed directories."""
        allowed_dirs = [
            self.config.WORKSPACE_DIR.resolve(),
            self.config.MEDIA_DIR.resolve(),
        ]

        for allowed_dir in allowed_dirs:
            try:
                resolved_path.relative_to(allowed_dir)
                return True
            except ValueError:
                continue

        return False

    def _detect_telegram_delivery_method(
        self, resolved_path: Path, file_type: str = "auto"
    ) -> str:
        """Detect which Telegram API should be used for the file."""
        if file_type != "auto":
            return file_type

        suffix = resolved_path.suffix.lower()
        mime_type, _ = mimetypes.guess_type(str(resolved_path))

        if mime_type:
            if mime_type.startswith("image/"):
                return "photo"
            if mime_type.startswith("video/"):
                return "video"
            if mime_type.startswith("audio/"):
                if suffix in {".ogg", ".oga", ".opus"}:
                    return "voice"
                return "audio"

        if suffix in {".png", ".jpg", ".jpeg", ".webp", ".bmp"}:
            return "photo"
        if suffix in {".mp4", ".mov", ".mkv", ".webm", ".avi"}:
            return "video"
        if suffix in {".mp3", ".wav", ".m4a", ".flac", ".aac"}:
            return "audio"
        if suffix in {".ogg", ".oga", ".opus"}:
            return "voice"

        return "document"

    def _build_sent_file_event_message(
        self, sent_path: Path, delivery_method: str, caption: Optional[str] = None
    ) -> str:
        """Build assistant-role system-tone event text for sent files."""
        message_lines = [
            "[System Event] Assistant has sent a file via Telegram.",
            f"Delivery method: {delivery_method}",
            f"Filename: {sent_path.name}",
            f"Path: {self._format_saved_media_path(sent_path)}",
        ]

        mime_type, _ = mimetypes.guess_type(str(sent_path))
        if mime_type:
            message_lines.append(f"MIME type: {mime_type}")

        if caption:
            message_lines.append(f"Caption: {caption}")

        return "\n".join(message_lines)

    async def _send_telegram_file_to_user(
        self,
        file_path: str,
        caption: Optional[str] = None,
        file_type: str = "auto",
    ) -> Dict[str, Any]:
        """Send a local file to the Telegram user and record the event in memory."""
        if self.telegram_bot is None:
            raise RuntimeError(
                "Telegram bot is not available for proactive file sending"
            )

        resolved_path = self._resolve_telegram_file_path(file_path)
        if not resolved_path.exists():
            raise FileNotFoundError(f"File not found: {resolved_path}")
        if not resolved_path.is_file():
            raise ValueError(f"Path is not a file: {resolved_path}")
        if not self._is_allowed_telegram_file_path(resolved_path):
            raise ValueError(
                "File path is outside allowed directories (workspace/media)"
            )

        delivery_method = self._detect_telegram_delivery_method(
            resolved_path, file_type=file_type
        )

        send_kwargs: Dict[str, Any] = {"chat_id": self.config.TELEGRAM_USER_ID}
        if caption:
            send_kwargs["caption"] = caption

        with open(resolved_path, "rb") as file_obj:
            if delivery_method == "photo":
                await self.telegram_bot.send_photo(photo=file_obj, **send_kwargs)
            elif delivery_method == "video":
                await self.telegram_bot.send_video(video=file_obj, **send_kwargs)
            elif delivery_method == "audio":
                await self.telegram_bot.send_audio(audio=file_obj, **send_kwargs)
            elif delivery_method == "voice":
                await self.telegram_bot.send_voice(voice=file_obj, **send_kwargs)
            else:
                await self.telegram_bot.send_document(document=file_obj, **send_kwargs)

        event_text = self._build_sent_file_event_message(
            resolved_path, delivery_method, caption
        )
        await self.memory.add_assistant_message_async(event_text)

        logger.info(
            f"Sent file to Telegram user via {delivery_method}: {resolved_path.name}"
        )
        return {
            "status": "sent",
            "delivery_method": delivery_method,
            "resolved_path": self._format_saved_media_path(resolved_path),
            "caption": caption,
        }

    def _build_file_event_message(
        self, file_info: Dict[str, Any], saved_path: Path
    ) -> str:
        """Build the synthetic user message describing the uploaded file."""
        original_name = file_info.get("original_name") or saved_path.name
        message_lines = [
            "[System Event] The user has sent a file.",
            f"File type: {file_info['file_type']}",
            f"Original filename: {original_name}",
            f"Saved to: {self._format_saved_media_path(saved_path)}",
        ]

        mime_type = file_info.get("mime_type")
        if mime_type:
            message_lines.append(f"MIME type: {mime_type}")

        file_size = file_info.get("file_size")
        if file_size is not None:
            message_lines.append(f"File size: {file_size} bytes")

        caption = file_info.get("caption")
        if caption:
            message_lines.append(f"Caption: {caption}")

        return "\n".join(message_lines)

    async def handle_file(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle incoming Telegram attachments by saving them and notifying the LLM."""
        if not update.effective_user or not update.message:
            return

        user_id = update.effective_user.id

        if user_id != self.config.TELEGRAM_USER_ID:
            await update.message.reply_text("Unauthorized access.")
            logger.warning(f"Unauthorized file from user {user_id}")
            return

        file_info = self._extract_file_info_from_update(update)
        if not file_info:
            logger.warning("Received file handler update without supported attachment")
            await update.message.reply_text("Unsupported file type.")
            return

        logger.info(
            f"Received {file_info['file_type']} from user {user_id}: {file_info.get('original_name') or file_info['file_unique_id']}"
        )

        async def _keep_typing_indicator():
            """Background task to keep typing indicator active."""
            while True:
                try:
                    await context.bot.send_chat_action(
                        chat_id=update.effective_chat.id, action="typing"
                    )
                    await asyncio.sleep(3)
                except Exception as e:
                    logger.warning(f"Typing indicator failed during file handling: {e}")
                    await asyncio.sleep(3)

        try:
            typing_task = asyncio.create_task(_keep_typing_indicator())

            try:
                destination = self._build_media_file_path(
                    original_name=file_info.get("original_name"),
                    file_unique_id=file_info["file_unique_id"],
                    mime_type=file_info.get("mime_type"),
                    file_type=file_info["file_type"],
                )
                saved_path = await self._download_telegram_file(
                    context, file_info["file_id"], destination
                )

                user_message = self._build_file_event_message(file_info, saved_path)
                logger.info(
                    "Built synthetic file event message for LLM: "
                    f"{self._preview_text(user_message)}"
                )
                response = await self._process_message(user_message)
                logger.info(
                    "Prepared final text for Telegram file reply: "
                    f"{self._preview_text(response)}"
                )

                formatted_response = self._format_response_for_telegram(response)
                segments = self._split_message_into_segments(formatted_response)

                logger.debug(f"File response split into {len(segments)} segments")
                logger.info(
                    f"Sending {len(segments)} Telegram segment(s) for file message"
                )

                for i, segment in enumerate(segments):
                    try:
                        logger.debug(
                            f"Sending Telegram file segment {i + 1}/{len(segments)}: "
                            f"{self._preview_text(segment)}"
                        )
                        await update.message.reply_text(segment, parse_mode="HTML")
                        if i < len(segments) - 1:
                            delay = random.uniform(1.0, 2.0)
                            await asyncio.sleep(delay)
                    except Exception as e:
                        logger.warning(
                            f"HTML parsing failed for file segment {i + 1}, sending as plain text: {e}"
                        )
                        await update.message.reply_text(segment)
            finally:
                typing_task.cancel()
                try:
                    await typing_task
                except asyncio.CancelledError:
                    pass

        except Exception as e:
            logger.error(f"Error handling file: {e}", exc_info=True)
            await update.message.reply_text(
                "Sorry, an error occurred while processing your file.\n\n"
                f"Details: {self._format_exception_for_user(e)}"
            )

    async def handle_new_session(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle /new command - archive current session and start new

        Args:
            update: Telegram update object
            context: Telegram context
        """
        if not update.effective_user or not update.message:
            return

        user_id = update.effective_user.id

        if user_id != self.config.TELEGRAM_USER_ID:
            await update.message.reply_text("Unauthorized access.")
            return

        try:
            logger.info("Creating new session")

            # Create new session (automatically closes old one and summarizes remaining conversations)
            new_session_id = await self.memory.new_session_async()
            logger.info(f"Created new session {new_session_id}")

            # Update memory_search_tool session_id
            if hasattr(self, "memory_search_tool") and self.memory_search_tool:
                self.memory_search_tool.session_id = int(new_session_id)
                logger.info(
                    f"Updated memory_search_tool session_id to {new_session_id}"
                )

            self.tool_trace_store.prune_to_max_records()

            await update.message.reply_text(
                "✓ New session created! Previous conversations have been summarized and archived.\n\n"
                "I still remember our history and can recall it when relevant."
            )

        except Exception as e:
            logger.error(f"Error creating new session: {e}", exc_info=True)
            await update.message.reply_text("Error creating new session.")

    async def handle_reset_session(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle /reset command - delete current session

        Args:
            update: Telegram update object
            context: Telegram context
        """
        if not update.effective_user or not update.message:
            return

        user_id = update.effective_user.id

        if user_id != self.config.TELEGRAM_USER_ID:
            await update.message.reply_text("Unauthorized access.")
            return

        try:
            logger.info("Resetting session")

            # Reset session (delete current and create new)
            self.memory.reset_session()

            if hasattr(self, "memory_search_tool") and self.memory_search_tool:
                self.memory_search_tool.session_id = int(
                    self.memory.get_current_session_id()
                )

            self.tool_trace_store.prune_to_max_records()

            await update.message.reply_text(
                "✓ Session reset! Current conversation has been deleted.\n\n"
                "Starting fresh, but I still have memories from previous sessions."
            )

        except Exception as e:
            logger.error(f"Error resetting session: {e}", exc_info=True)
            await update.message.reply_text("Error resetting session.")

    async def _process_message(self, user_message: str) -> str:
        """Process user message through memory and LLM

        Args:
            user_message: User's message text

        Returns:
            Bot's response
        """
        try:
            # Step 1: Add user message to memory (and get embedding for reuse)
            logger.debug("Step 1: Adding user message to memory")
            conversation_id, user_embedding = await self.memory.add_user_message_async(
                user_message
            )

            # Step 2: Get current context (recent conversations + summaries)
            logger.debug("Step 2: Getting current context")
            current_context = self.memory.get_context_messages()

            # Step 3: Retrieve relevant memories from history
            logger.debug("Step 3: Retrieving relevant memories")
            # Get last bot message for dual-query retrieval
            last_bot_message = None
            if current_context:
                for msg in reversed(current_context):
                    if msg.get("role") == "assistant":
                        last_bot_message = msg.get("content", "")
                        break

            # Retrieve memories (reuse embedding from Step 1 to avoid re-vectorization)
            (
                retrieved_summaries,
                retrieved_conversations,
            ) = await self.memory.process_user_input_async(
                user_input=user_message,
                last_bot_message=last_bot_message,
                user_input_embedding=user_embedding,
            )

            logger.debug(
                f"Retrieved {len(retrieved_summaries)} summaries and {len(retrieved_conversations)} conversations"
            )

            # Step 4: Get recent summaries from context window
            logger.debug("Step 4: Getting recent summaries")
            recent_summaries = self.memory.get_recent_summaries()
            logger.debug(f"Got {len(recent_summaries)} recent summaries")

            # Step 5: Enable memory search tool for LLM to use
            logger.debug("Step 5: Enabling memory search tool")
            self.memory_search_tool.enable()

            # Step 5.5: Ensure MCP is connected so tools are available to LLM
            if self.mcp_client:
                logger.debug("Step 5.5: Ensuring MCP is connected")
                await self._ensure_mcp_connected()

            # Step 6: Call LLM with full context and tools
            logger.debug("Step 6: Calling LLM")

            # Define intermediate message callback for Telegram streaming
            async def send_intermediate(text: str):
                if not text.strip():
                    return
                # Formatting and splitting logic similar to handle_message
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
                        # Fallback to plain text if HTML parsing fails
                        try:
                            if hasattr(self, "telegram_bot") and self.telegram_bot:
                                await self.telegram_bot.send_message(
                                    chat_id=self.config.TELEGRAM_USER_ID,
                                    text=segment,
                                )
                        except Exception as e2:
                            logger.error(f"Failed to send intermediate segment: {e2}")

            llm_result = await self.llm_client.chat_async_detailed(
                current_context=current_context,
                retrieved_summaries=retrieved_summaries,
                retrieved_conversations=retrieved_conversations,
                recent_summaries=recent_summaries,
                intermediate_callback=send_intermediate,
            )

            assistant_messages = llm_result.get("assistant_messages", [])
            # Return only the final text to be sent by handle_message, avoiding duplicates
            response = llm_result.get("final_text", "")

            logger.info(
                "LLM detailed result for current message: "
                f"assistant_messages={len(assistant_messages)}, "
                f"final_text={self._preview_text(llm_result.get('final_text', ''))}"
            )
            for idx, assistant_message in enumerate(assistant_messages, start=1):
                logger.debug(
                    f"Assistant message {idx}/{len(assistant_messages)} to persist: "
                    f"{self._preview_text(assistant_message)}"
                )

            # Step 7: Disable memory search tool during response generation
            logger.debug("Step 7: Disabling memory search tool")
            self.memory_search_tool.disable()

            # Step 8: Add assistant responses to memory
            logger.debug("Step 8: Adding assistant responses to memory")
            for assistant_message in assistant_messages:
                conversation_id, summary_id = (
                    await self.memory.add_assistant_message_async(assistant_message)
                )

                if summary_id:
                    logger.info(
                        f"Created new summary (ID: {summary_id}) during message processing"
                    )

            # Step 9: Return response
            logger.info(
                "Message processing complete, returning combined response: "
                f"{self._preview_text(response)}"
            )
            return response

        except Exception as e:
            logger.error(f"Error in _process_message: {e}", exc_info=True)
            raise

    async def _process_scheduled_task(
        self, task_message: str, task_name: str = "Scheduled Task"
    ) -> str:
        """Process scheduled task message through LLM

        Similar to _process_message but:
        - Does NOT save the task message to database
        - Does NOT count toward unsummarized messages
        - Task message is transient and only exists for this LLM call
        - LLM response IS saved to database as part of session

        Args:
            task_message: Raw task message from scheduler

        Returns:
            Bot's response to the scheduled task
        """
        try:
            # Get current timestamp for task
            from utils.time import get_current_timestamp, timestamp_to_str

            trigger_time = get_current_timestamp()
            trigger_time_str = timestamp_to_str(trigger_time)

            # Wrap task message with [SYSTEM_SCHEDULED_TASK] marker
            wrapped_message = (
                f"[SYSTEM_SCHEDULED_TASK]\n"
                f"Task Name: {task_name}\n"
                f"Trigger Time: {trigger_time_str}\n"
                f"Task: {task_message}\n\n"
                f"Please respond proactively based on this scheduled task."
            )

            logger.debug(f"Wrapped scheduled task message: {wrapped_message[:100]}...")

            # Step 1: Get current context (recent conversations + summaries)
            # Note: We do NOT add the task message to memory/context_window
            logger.debug("Step 1: Getting current context for scheduled task")
            current_context = self.memory.get_context_messages()

            # Step 2: Retrieve relevant memories based on task content
            logger.debug("Step 2: Retrieving relevant memories for scheduled task")
            # Use task content for retrieval (not the wrapped version with marker)
            task_embedding = await self.embedding_client.get_embedding_async(
                task_message
            )

            # Get last bot message for dual-query retrieval
            last_bot_message = None
            if current_context:
                for msg in reversed(current_context):
                    if msg.get("role") == "assistant":
                        last_bot_message = msg.get("content", "")
                        break

            # Retrieve memories using task content and embedding
            (
                retrieved_summaries,
                retrieved_conversations,
            ) = await self.memory.process_user_input_async(
                user_input=task_message,
                last_bot_message=last_bot_message,
                user_input_embedding=task_embedding,
            )

            logger.debug(
                f"Retrieved {len(retrieved_summaries)} summaries and "
                f"{len(retrieved_conversations)} conversations for scheduled task"
            )

            # Step 3: Get recent summaries from context window
            logger.debug("Step 3: Getting recent summaries")
            recent_summaries = self.memory.get_recent_summaries()
            logger.debug(f"Got {len(recent_summaries)} recent summaries")

            # Step 4: Enable memory search tool for LLM to use
            logger.debug("Step 4: Enabling memory search tool")
            if self.memory_search_tool:
                self.memory_search_tool.enable()

            # Step 4.5: Ensure MCP is connected so tools are available to LLM
            if self.mcp_client:
                logger.debug("Step 4.5: Ensuring MCP is connected")
                await self._ensure_mcp_connected()

            # Step 5 & 6: Call LLM with custom user message (task message not in current_context)
            # Use chat_with_custom_message_async to handle message building and LLM calling
            logger.debug("Step 5-6: Calling LLM with custom task message")

            # Define intermediate message callback for Telegram streaming
            async def send_intermediate(text: str):
                if not text.strip():
                    return
                # Formatting and splitting logic similar to handle_message
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
                        # Fallback to plain text if HTML parsing fails
                        try:
                            if hasattr(self, "telegram_bot") and self.telegram_bot:
                                await self.telegram_bot.send_message(
                                    chat_id=self.config.TELEGRAM_USER_ID,
                                    text=segment,
                                )
                        except Exception as e2:
                            logger.error(f"Failed to send intermediate segment: {e2}")

            llm_result = await self.llm_client.chat_with_custom_message_async_detailed(
                current_context=current_context,
                retrieved_summaries=retrieved_summaries,
                retrieved_conversations=retrieved_conversations,
                recent_summaries=recent_summaries,
                custom_user_message=wrapped_message,
                intermediate_callback=send_intermediate,
            )

            assistant_messages = llm_result.get("assistant_messages", [])
            # Return only the final text to be sent by handle_message, avoiding duplicates
            response_text = llm_result.get("final_text", "")

            logger.info(
                "LLM detailed result for scheduled task: "
                f"assistant_messages={len(assistant_messages)}, "
                f"final_text={self._preview_text(llm_result.get('final_text', ''))}"
            )
            for idx, assistant_message in enumerate(assistant_messages, start=1):
                logger.debug(
                    f"Scheduled task assistant message {idx}/{len(assistant_messages)} to persist: "
                    f"{self._preview_text(assistant_message)}"
                )

            # Step 7: Disable memory search tool
            logger.debug("Step 7: Disabling memory search tool")
            if self.memory_search_tool:
                self.memory_search_tool.disable()

            # Step 8: Add assistant responses to memory (THESE ARE SAVED!)
            logger.debug(
                "Step 8: Adding assistant responses to memory (scheduled task)"
            )
            for assistant_message in assistant_messages:
                conversation_id, summary_id = (
                    await self.memory.add_assistant_message_async(assistant_message)
                )

                if summary_id:
                    logger.info(
                        f"Created new summary (ID: {summary_id}) during scheduled task processing"
                    )

            # Step 9: Return response
            logger.info(
                "Scheduled task processing complete, returning combined response: "
                f"{self._preview_text(response_text)}"
            )
            return response_text

        except Exception as e:
            logger.error(f"Error in _process_scheduled_task: {e}", exc_info=True)
            # Return a friendly error message that will be sent to user
            return f"[Scheduled Task] {task_message}\n\n(Error occurred while processing, please check logs)"
