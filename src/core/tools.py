"""Tool runtime, registry, and execution orchestration."""

import html
import json
import time
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional

from core.config import Config
from tools.file_io import (
    AppendFileTool,
    ReadFileTool,
    ReplaceFileContentTool,
    WriteFileTool,
)
from tools.file_search import GlobSearchTool, GrepSearchTool
from tools.memory_search import MemorySearchTool
from tools.mcp_client import MCPClient
from tools.scheduled_tasks import ScheduledTaskTool
from tools.send_file import SendFileTool
from tools.shell import is_dangerous_command
from tools.shell import ShellCommandTool
from tools.tool_trace import ToolTraceQueryTool, ToolTraceStore
from utils.logger import get_logger

logger = get_logger()


class ToolSafetyPolicy:
    """Evaluate whether a tool action requires explicit user approval."""

    _PATH_GUARDED_TOOLS = {
        "write_file": "file_path",
        "replace_file_content": "file_path",
        "append_file": "file_path",
        "read_file": "file_path",
        "grep_search": "path",
        "glob_search": "path",
    }

    def __init__(self, config: Any):
        self.config = config

    def is_path_outside_allowed_dirs(self, target_path: str) -> bool:
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
        except Exception as error:
            logger.error(f"Error checking path bounds: {error}")
            return True

    def is_dangerous_action(
        self, tool_name: str, arguments: Dict[str, Any]
    ) -> tuple[bool, str]:
        """Determine whether a tool call requires user approval."""
        if tool_name == "execute_shell_command":
            cmd = arguments.get("command", "")
            dangerous, category = is_dangerous_command(cmd)
            if dangerous:
                return True, f"shell_threat:{category}"

            cwd = arguments.get("cwd", "")
            if cwd and self.is_path_outside_allowed_dirs(cwd):
                return True, "file_outside_workspace"

        path_argument = self._PATH_GUARDED_TOOLS.get(tool_name)
        if path_argument:
            if self.is_path_outside_allowed_dirs(arguments.get(path_argument, "")):
                return True, "file_outside_workspace"

        return False, ""


class ToolRegistry:
    """Store tool instances and expose OpenAI-style tool definitions."""

    def __init__(self) -> None:
        self._tools: Dict[str, Any] = {}

    def register_named(self, tool_name: str, tool: Any) -> None:
        """Register a tool instance under an explicit name."""
        self._tools[tool_name] = tool

    def get(self, tool_name: str) -> Optional[Any]:
        """Get a registered tool by name."""
        return self._tools.get(tool_name)

    def collect_tool_defs(self) -> List[Dict[str, Any]]:
        """Collect OpenAI-format definitions for all registered tools."""
        return [
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.parameters,
                },
            }
            for tool in self._tools.values()
        ]


class ToolTraceService:
    """Persist tool execution traces and classify their outcome."""

    def __init__(
        self,
        *,
        store: Any,
        get_current_session_id: Callable[[], Any],
    ) -> None:
        self.store = store
        self.get_current_session_id = get_current_session_id

    @staticmethod
    def infer_status(result: Any) -> str:
        """Classify a tool result into success/error for logging."""
        result_text = str(result)
        if result_text.startswith("Error:") or result_text.startswith("Command failed"):
            return "error"
        return "success"

    async def record_trace(
        self,
        *,
        trace_id: Optional[int] = None,
        tool_name: str,
        arguments: Dict[str, Any],
        result: Any,
        status: str,
        duration_ms: int,
        approval_required: bool,
        approved_by_user: bool,
    ) -> Optional[int]:
        """Persist a tool execution trace unless the trace-query tool triggered it."""
        if tool_name == "query_tool_history":
            return None
        if self.store is None:
            return None

        try:
            session_id = self.get_current_session_id()
            return self.store.append_trace(
                trace_id=trace_id,
                session_id=session_id,
                tool_name=tool_name,
                arguments=arguments,
                result=result,
                status=status,
                duration_ms=duration_ms,
                approval_required=approval_required,
                approved_by_user=approved_by_user,
            )
        except Exception as error:
            logger.warning(f"Failed to persist tool trace for {tool_name}: {error}")
            return None


class ToolRuntimeState:
    """Own the mutable bookkeeping state used by the tool runtime."""

    def __init__(
        self,
        *,
        config: Any,
        get_current_session_id: Callable[[], Any],
    ) -> None:
        self.tool_trace_store = ToolTraceStore(config.DATA_DIR)
        self.tool_trace_query_tool = ToolTraceQueryTool(
            self.tool_trace_store, get_current_session_id
        )
        self.tool_trace_service = ToolTraceService(
            store=self.tool_trace_store,
            get_current_session_id=get_current_session_id,
        )
        self.registry_service = ToolRegistry()
        self.safety_policy = ToolSafetyPolicy(config)
        self.memory_search_tool: Any = None
        self.scheduled_task_tool: Any = None
        self.send_file_tool: Any = None
        self.mcp_client: Any = None
        self.mcp_connected = False


class ToolRuntime:
    """Configure the LLM tool runtime and optional MCP integration."""

    def __init__(
        self,
        handler: Any,
    ):
        self.handler = handler

    def _get_core_bot(self) -> Any:
        """Return the core bot dependency owner attached to the adapter."""
        core_bot = getattr(self.handler, "core_bot", None)
        if core_bot is None:
            raise RuntimeError("CoreBot has not been attached to the handler")
        return core_bot

    def _get_runtime_state(self) -> ToolRuntimeState:
        """Return the core-owned mutable tool runtime state."""
        state = self._get_core_bot().tool_runtime_state
        if not isinstance(state, ToolRuntimeState):
            raise RuntimeError("Tool runtime state has not been initialized on CoreBot")
        return state

    def _register_stateful_tool(
        self, *, state_attr: str, factory: Callable[[], Any], label: str
    ) -> None:
        """Create and register a core-owned tool instance."""
        state = self._get_runtime_state()
        try:
            tool = factory()
            setattr(state, state_attr, tool)
            state.registry_service.register_named(tool.name, tool)
            logger.info(f"Registered {label} tool")
        except Exception as error:
            logger.error(f"Failed to register {label} tool: {error}")
            setattr(state, state_attr, None)

    def _ensure_memory_search_tool(self) -> Any:
        """Create the memory search tool lazily when the handler has not built it yet."""
        state = self._get_runtime_state()
        core_bot = self._get_core_bot()
        if state.memory_search_tool is None:
            session_id = core_bot.memory.get_current_session_id()
            state.memory_search_tool = MemorySearchTool(
                session_id=str(session_id),
                db=core_bot.db,
                embedding_client=core_bot.embedding_client,
                reranker_client=core_bot.reranker_client,
            )
        return state.memory_search_tool

    def _register_local_runtime_tools(self) -> None:
        """Ensure every local runtime tool is present in the registry."""
        state = self._get_runtime_state()
        registry = state.registry_service
        if state.tool_trace_query_tool:
            registry.register_named(
                state.tool_trace_query_tool.name, state.tool_trace_query_tool
            )
            logger.info("Added query_tool_history tool")

        memory_search_tool = self._ensure_memory_search_tool()
        if memory_search_tool:
            registry.register_named(memory_search_tool.name, memory_search_tool)
            logger.info("Added memory_search tool")

        if state.scheduled_task_tool:
            registry.register_named(
                state.scheduled_task_tool.name, state.scheduled_task_tool
            )
            logger.info("Added scheduled_task tool")

        if state.send_file_tool:
            registry.register_named(state.send_file_tool.name, state.send_file_tool)
            logger.info("Added send_file tool")

    def register_core_tools(self) -> None:
        """Register stateful core-owned tools needed by the runtime."""
        core_bot = self._get_core_bot()
        self._register_stateful_tool(
            state_attr="scheduled_task_tool",
            factory=lambda: ScheduledTaskTool(core_bot.scheduler),
            label="scheduled_task",
        )
        self._register_stateful_tool(
            state_attr="send_file_tool",
            factory=lambda: SendFileTool(
                lambda **kwargs: self.handler.core_bot.file_delivery_service.send_file_to_user(
                    telegram_bot=getattr(self.handler, "telegram_bot", None),
                    **kwargs,
                )
            ),
            label="send_file",
        )

    def register_builtin_tools(self) -> None:
        """Register builtin file and shell tools on the handler."""
        try:
            builtin_tools = [
                ReadFileTool(),
                WriteFileTool(),
                ReplaceFileContentTool(),
                AppendFileTool(),
                GrepSearchTool(),
                GlobSearchTool(),
                ShellCommandTool(),
            ]
            registry = self._get_runtime_state().registry_service
            for tool in builtin_tools:
                registry.register_named(tool.name, tool)
            logger.info("Registered builtin file and shell tools")
        except Exception as error:
            logger.error(f"Failed to register builtin tools: {error}")

    def setup_tools(self) -> None:
        """Initialize MCP state and register basic tools with the LLM client."""
        state = self._get_runtime_state()
        core_bot = self._get_core_bot()
        if core_bot.config.ENABLE_MCP:
            state.mcp_client = MCPClient()
            state.mcp_connected = False
        else:
            state.mcp_client = None
            state.mcp_connected = False

        self._publish_tools()

    def _publish_tools(self, extra_tools: Optional[List[Dict[str, Any]]] = None) -> None:
        """Publish local tools plus optional remote tools to the LLM client."""
        core_bot = self._get_core_bot()
        self._register_local_runtime_tools()
        tools = self._get_runtime_state().registry_service.collect_tool_defs()
        if extra_tools:
            tools.extend(extra_tools)

        core_bot.llm_client.set_tools(tools)
        core_bot.llm_client.set_tool_executor(core_bot.execute_tool)

        logger.info(f"Tools registered: {len(tools)}")

    async def ensure_mcp_connected(self) -> None:
        """Connect MCP lazily and merge remote tools into the LLM tool list."""
        state = self._get_runtime_state()
        core_bot = self._get_core_bot()
        if state.mcp_client and not state.mcp_connected:
            try:
                await state.mcp_client.__aenter__()
                state.mcp_connected = True

                mcp_tools = await state.mcp_client.list_tools()
                logger.info(f"Connected MCP client with {len(mcp_tools)} tools")
                for tool in mcp_tools:
                    tool_func = tool.get("function", {})
                    name = tool_func.get("name", "Unknown")
                    desc = tool_func.get("description", "No description")
                    logger.debug(f"  - [MCP Tool] {name}: {desc}")

                self._publish_tools(mcp_tools)
                logger.info(
                    f"Updated tools: local + {len(mcp_tools)} MCP tools"
                )
            except Exception as error:
                logger.error(f"Failed to connect MCP client: {error}")
                state.mcp_connected = False
                self._publish_tools()


class ToolExecutor:
    """Execute registered tools with approval, tracing, and MCP fallback."""

    _TOOL_CONTEXT_ARGUMENTS_PREVIEW_MAX = Config.TOOL_TRACE_ARGUMENTS_PREVIEW_MAX
    _TOOL_CONTEXT_RESULT_PREVIEW_MAX = Config.TOOL_TRACE_RESULT_PREVIEW_MAX

    def __init__(
        self,
        *,
        config: Any,
        tool_registry: Any,
        mcp_client: Any,
        ensure_mcp_connected: Optional[Callable[[], Awaitable[None]]],
        is_mcp_connected: Callable[[], bool],
        is_dangerous_action: Callable[[str, Dict[str, Any]], tuple[bool, str]],
        request_approval: Callable[[str, Dict[str, Any], str], Awaitable[bool]],
        record_tool_trace: Callable[..., Awaitable[None]],
        infer_tool_trace_status: Callable[[Any], str],
        notify_approved_action_finished: Callable[[str, str], Awaitable[None]],
        notify_approved_action_failed: Callable[[str, Exception], Awaitable[None]],
        preview_text: Callable[[Optional[str], int], str],
        telegram_bot: Any = None,
    ) -> None:
        self.config = config
        self.tool_registry = tool_registry
        self.mcp_client = mcp_client
        self.ensure_mcp_connected = ensure_mcp_connected
        self.is_mcp_connected = is_mcp_connected
        self.is_dangerous_action = is_dangerous_action
        self.request_approval = request_approval
        self.record_tool_trace = record_tool_trace
        self.infer_tool_trace_status = infer_tool_trace_status
        self.notify_approved_action_finished = notify_approved_action_finished
        self.notify_approved_action_failed = notify_approved_action_failed
        self.preview_text = preview_text
        self.telegram_bot = telegram_bot

    @staticmethod
    def _to_json_text(value: Any) -> str:
        try:
            return json.dumps(value, ensure_ascii=False)
        except Exception:
            return str(value)

    @staticmethod
    def _truncate_preview_text(text: str, max_length: int) -> str:
        if len(text) <= max_length:
            return text
        omitted = len(text) - max_length
        return f"{text[:max_length]}...[truncated {omitted} chars]"

    def _build_arguments_preview(self, arguments: Dict[str, Any]) -> str:
        return self._truncate_preview_text(
            self._to_json_text(arguments),
            self._TOOL_CONTEXT_ARGUMENTS_PREVIEW_MAX,
        )

    def _build_result_preview(self, result: Any) -> str:
        if self.record_tool_trace.__self__.store is not None:
            store = self.record_tool_trace.__self__.store
            return store._sanitize_and_truncate_result(  # type: ignore[attr-defined]
                str(result),
                self._TOOL_CONTEXT_RESULT_PREVIEW_MAX,
            )
        return self._truncate_preview_text(
            str(result),
            self._TOOL_CONTEXT_RESULT_PREVIEW_MAX,
        )

    def _build_tool_context_message(
        self,
        *,
        trace_id: int,
        status: str,
        tool_name: str,
        arguments: Dict[str, Any],
        result: Any,
    ) -> str:
        return (
            "[Tool Call]\n"
            f"trace_id: {trace_id}\n"
            f'status: "{status}"\n'
            f'tool_name: "{tool_name}"\n'
            f"arguments_preview: {self._build_arguments_preview(arguments)}\n"
            f'result_preview: "{self._build_result_preview(result)}"'
        )

    @staticmethod
    def _elapsed_ms(start_time: float) -> int:
        """Convert a perf_counter start time into milliseconds."""
        return int((time.perf_counter() - start_time) * 1000)

    async def _record_tool_result(
        self,
        *,
        trace_id: int,
        tool_name: str,
        arguments: Dict[str, Any],
        result: str,
        start_time: float,
        dangerous: bool,
        approval_granted: bool,
    ) -> Optional[int]:
        """Persist a successful or handled tool result to the trace log."""
        return await self.record_tool_trace(
            trace_id=trace_id,
            tool_name=tool_name,
            arguments=arguments,
            result=result,
            status=self.infer_tool_trace_status(result),
            duration_ms=self._elapsed_ms(start_time),
            approval_required=dangerous,
            approved_by_user=approval_granted,
        )

    async def _finalize_success(
        self,
        *,
        trace_id: int,
        tool_name: str,
        arguments: Dict[str, Any],
        result: str,
        start_time: float,
        dangerous: bool,
        approval_granted: bool,
        source_label: str,
    ) -> Dict[str, Any]:
        """Log, trace, and notify for a successful tool execution path."""
        logger.info(
            f"{source_label} tool execution finished: {tool_name}, "
            f"preview={self.preview_text(result)}"
        )
        stored_trace_id = await self._record_tool_result(
            trace_id=trace_id,
            tool_name=tool_name,
            arguments=arguments,
            result=result,
            start_time=start_time,
            dangerous=dangerous,
            approval_granted=approval_granted,
        )
        if approval_granted:
            await self.notify_approved_action_finished(tool_name, result)
        effective_trace_id = stored_trace_id or trace_id
        status = self.infer_tool_trace_status(result)
        return {
            "result": result,
            "trace_id": effective_trace_id,
            "context_message": self._build_tool_context_message(
                trace_id=effective_trace_id,
                status=status,
                tool_name=tool_name,
                arguments=arguments,
                result=result,
            ),
        }

    async def _try_execute_registered_tool(
        self,
        *,
        trace_id: int,
        tool_name: str,
        arguments: Dict[str, Any],
        start_time: float,
        dangerous: bool,
        approval_granted: bool,
    ) -> Optional[Dict[str, Any]]:
        """Execute a locally registered tool when available."""
        tool_instance = self.tool_registry.get(tool_name)
        if tool_instance is None:
            return None

        result = await tool_instance.execute(**arguments)
        return await self._finalize_success(
            trace_id=trace_id,
            tool_name=tool_name,
            arguments=arguments,
            result=result,
            start_time=start_time,
            dangerous=dangerous,
            approval_granted=approval_granted,
            source_label="Local",
        )

    async def _try_execute_mcp_tool(
        self,
        *,
        trace_id: int,
        tool_name: str,
        arguments: Dict[str, Any],
        start_time: float,
        dangerous: bool,
        approval_granted: bool,
    ) -> Optional[Dict[str, Any]]:
        """Execute an MCP tool when the remote registry contains it."""
        if not self.mcp_client:
            return None

        if self.ensure_mcp_connected is not None:
            await self.ensure_mcp_connected()

        if not self.is_mcp_connected():
            return None

        mcp_tools = self.mcp_client.get_tools_sync()
        if not any(t["function"]["name"] == tool_name for t in mcp_tools):
            return None

        result = await self.mcp_client.call_tool(tool_name, arguments)
        return await self._finalize_success(
            trace_id=trace_id,
            tool_name=tool_name,
            arguments=arguments,
            result=result,
            start_time=start_time,
            dangerous=dangerous,
            approval_granted=approval_granted,
            source_label="MCP",
        )

    async def execute_tool(self, tool_name: str, arguments_json: str) -> Dict[str, Any]:
        """Execute a tool call from the LLM."""
        start_time = time.perf_counter()
        trace_id = time.time_ns()
        try:
            arguments = json.loads(arguments_json)
        except json.JSONDecodeError as error:
            logger.error(f"Failed to parse tool arguments: {error}")
            result = f"Error: Invalid JSON arguments: {error}"
            return {
                "result": result,
                "trace_id": trace_id,
                "context_message": self._build_tool_context_message(
                    trace_id=trace_id,
                    status="error",
                    tool_name=tool_name,
                    arguments={},
                    result=result,
                ),
            }

        logger.info(f"Executing tool: {tool_name} with args: {arguments}")

        dangerous, reason = self.is_dangerous_action(tool_name, arguments)
        approval_granted = False

        if not dangerous and self.telegram_bot and self.config is not None:
            try:
                msg = f"🔧 <b>Tool execution:</b> <code>{tool_name}</code>\n"
                args_str = html.escape(
                    json.dumps(arguments, ensure_ascii=False)[
                        : Config.TOOL_EXECUTION_NOTIFICATION_ARGUMENTS_MAX
                    ]
                )
                msg += f"<b>Arguments:</b> <pre>{args_str}</pre>"
                self._fire_and_forget_status(msg)
            except Exception as error:
                logger.warning(f"Failed to send tool execute notification: {error}")

        if dangerous:
            logger.warning(f"Dangerous action detected: {tool_name} reason={reason}")
            approved = await self.request_approval(tool_name, arguments, reason)
            if not approved:
                logger.info(f"User rejected dangerous action: {tool_name}")
                result = (
                    f"Error: Action was rejected by the user (reason: {reason}). "
                    "Do NOT retry this action."
                )
                await self.record_tool_trace(
                    trace_id=trace_id,
                    tool_name=tool_name,
                    arguments=arguments,
                    result=result,
                    status="rejected",
                    duration_ms=self._elapsed_ms(start_time),
                    approval_required=True,
                    approved_by_user=False,
                )
                return {
                    "result": result,
                    "trace_id": trace_id,
                    "context_message": self._build_tool_context_message(
                        trace_id=trace_id,
                        status="rejected",
                        tool_name=tool_name,
                        arguments=arguments,
                        result=result,
                    ),
                }
            logger.info(f"User approved dangerous action: {tool_name}")
            approval_granted = True

        try:
            result = await self._try_execute_registered_tool(
                trace_id=trace_id,
                tool_name=tool_name,
                arguments=arguments,
                start_time=start_time,
                dangerous=dangerous,
                approval_granted=approval_granted,
            )
            if result is not None:
                return result

            result = await self._try_execute_mcp_tool(
                trace_id=trace_id,
                tool_name=tool_name,
                arguments=arguments,
                start_time=start_time,
                dangerous=dangerous,
                approval_granted=approval_granted,
            )
            if result is not None:
                return result

            result = f"Error: Tool not found: {tool_name}"
            await self.record_tool_trace(
                trace_id=trace_id,
                tool_name=tool_name,
                arguments=arguments,
                result=result,
                status="error",
                duration_ms=self._elapsed_ms(start_time),
                approval_required=dangerous,
                approved_by_user=approval_granted,
            )
            if approval_granted:
                await self.notify_approved_action_finished(tool_name, result)
            return {
                "result": result,
                "trace_id": trace_id,
                "context_message": self._build_tool_context_message(
                    trace_id=trace_id,
                    status="error",
                    tool_name=tool_name,
                    arguments=arguments,
                    result=result,
                ),
            }
        except Exception as error:
            logger.error(
                f"Tool execution raised exception after approval state="
                f"{approval_granted}: {tool_name} - {error}",
                exc_info=True,
            )
            await self.record_tool_trace(
                trace_id=trace_id,
                tool_name=tool_name,
                arguments=arguments,
                result=f"{type(error).__name__}: {error}",
                status="error",
                duration_ms=self._elapsed_ms(start_time),
                approval_required=dangerous,
                approved_by_user=approval_granted,
            )
            if approval_granted:
                await self.notify_approved_action_failed(tool_name, error)
            raise

    def _fire_and_forget_status(self, text: str) -> None:
        """Send a non-blocking Telegram status message when available."""
        if not self.telegram_bot or self.config is None:
            return

        import asyncio

        asyncio.create_task(
            self.telegram_bot.send_message(
                chat_id=self.config.TELEGRAM_USER_ID,
                text=text,
                parse_mode="HTML",
            )
        )
