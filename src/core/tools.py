"""Tool runtime, registry, and execution orchestration."""

import asyncio
import html
import json
import time
from typing import Any, Awaitable, Callable, Dict, List, Optional

from core.config import Config
from core.hitl import ApprovalDecision, ApprovalTimeoutError
from utils.logger import get_logger
from utils.tool_safety import is_dangerous_command, is_path_outside_allowed_dirs

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

    _GENERIC_PATH_FIELD_NAMES = {
        "path",
        "file_path",
        "directory",
        "dir",
        "cwd",
        "root",
        "target_path",
        "output_path",
        "input_path",
    }

    def __init__(self, config: Any):
        self.config = config

    def is_path_outside_allowed_dirs(self, target_path: str) -> bool:
        """Check whether a path resolves outside workspace/media allowed dirs."""
        try:
            return is_path_outside_allowed_dirs(target_path)
        except Exception as error:
            logger.error(f"Error checking path bounds: {error}")
            return True

    def _find_outside_path_in_value(self, field_name: str, value: Any) -> Optional[str]:
        """Recursively inspect tool arguments for suspicious path-like values."""
        normalized_name = field_name.lower()

        if isinstance(value, str):
            if normalized_name not in self._GENERIC_PATH_FIELD_NAMES:
                return None
            return value if self.is_path_outside_allowed_dirs(value) else None

        if isinstance(value, dict):
            for nested_key, nested_value in value.items():
                hit = self._find_outside_path_in_value(str(nested_key), nested_value)
                if hit:
                    return hit
            return None

        if isinstance(value, (list, tuple)) and normalized_name in self._GENERIC_PATH_FIELD_NAMES:
            for item in value:
                if isinstance(item, str) and self.is_path_outside_allowed_dirs(item):
                    return item

        return None

    def _find_outside_path_in_arguments(self, arguments: Dict[str, Any]) -> Optional[str]:
        """Return the first dangerous path found in arbitrary tool arguments."""
        for key, value in arguments.items():
            hit = self._find_outside_path_in_value(str(key), value)
            if hit:
                return hit
        return None

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

        outside_path = self._find_outside_path_in_arguments(arguments)
        if outside_path:
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

    def sanitize_result_preview(self, result: Any, *, max_length: int) -> str:
        """Sanitize tool output previews without leaking store internals."""
        result_text = "" if result is None else str(result)
        if self.store is None:
            if len(result_text) <= max_length:
                return result_text
            omitted = len(result_text) - max_length
            return f"{result_text[:max_length]}...[truncated {omitted} chars]"
        return self.store.sanitize_and_truncate_result(result_text, max_length)


class ToolExecutor:
    """Execute registered tools with approval, tracing, and MCP fallback."""

    _TOOL_CONTEXT_ARGUMENTS_PREVIEW_MAX = Config.TOOL_TRACE_ARGUMENTS_PREVIEW_MAX
    _TOOL_CONTEXT_RESULT_PREVIEW_MAX = Config.TOOL_TRACE_RESULT_PREVIEW_MAX

    def __init__(
        self,
        *,
        config: Any,
        tool_registry: Any,
        get_mcp_client: Callable[[], Any],
        ensure_mcp_connected: Optional[Callable[[], Awaitable[None]]],
        is_mcp_connected: Callable[[], bool],
        is_dangerous_action: Callable[[str, Dict[str, Any]], tuple[bool, str]],
        request_approval: Callable[[str, Dict[str, Any], str], Awaitable[bool]],
        record_tool_trace: Callable[..., Awaitable[None]],
        infer_tool_trace_status: Callable[[Any], str],
        sanitize_result_preview: Callable[[Any, int], str],
        notify_approved_action_finished: Callable[[str, str], Awaitable[None]],
        notify_approved_action_failed: Callable[[str, Exception], Awaitable[None]],
        file_artifact_service: Any,
        preview_text: Callable[[Optional[str], int], str],
        get_send_status_message: Callable[[], Optional[Callable[[str], Awaitable[None]]]],
    ) -> None:
        self.config = config
        self.tool_registry = tool_registry
        self.get_mcp_client = get_mcp_client
        self.ensure_mcp_connected = ensure_mcp_connected
        self.is_mcp_connected = is_mcp_connected
        self.is_dangerous_action = is_dangerous_action
        self.request_approval = request_approval
        self.record_tool_trace = record_tool_trace
        self.infer_tool_trace_status = infer_tool_trace_status
        self.sanitize_result_preview = sanitize_result_preview
        self.notify_approved_action_finished = notify_approved_action_finished
        self.notify_approved_action_failed = notify_approved_action_failed
        self.file_artifact_service = file_artifact_service
        self.preview_text = preview_text
        self.get_send_status_message = get_send_status_message

    def _normalize_result_for_llm(self, result: Any, *, source_label: str) -> str:
        result_text = str(result)
        if not result_text or self.file_artifact_service is None:
            return result_text

        persisted = self.file_artifact_service.maybe_persist_text_base64(
            result_text,
            source=source_label.lower(),
            prefix=f"{source_label.lower()}_tool_output",
        )
        return persisted or result_text

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
        return self.sanitize_result_preview(
            result,
            self._TOOL_CONTEXT_RESULT_PREVIEW_MAX,
        )

    async def _execute_with_timeout(
        self, operation: Awaitable[Any], *, tool_name: str
    ) -> Any:
        """Run a tool operation with the configured default timeout."""
        raw_timeout = getattr(self.config, "TOOL_EXECUTION_TIMEOUT_SECONDS", 90.0)
        try:
            timeout_seconds = float(raw_timeout)
        except (TypeError, ValueError):
            timeout_seconds = 90.0
        try:
            return await asyncio.wait_for(operation, timeout=timeout_seconds)
        except asyncio.TimeoutError as error:
            raise TimeoutError(
                f"Tool execution timed out after {timeout_seconds:g} seconds: {tool_name}"
            ) from error

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
    def _format_rejection_result(decision: ApprovalDecision) -> str:
        """Build a rejection result string that preserves optional user feedback."""
        base_reason = decision.abort_reason or "User declined this action."
        result = f"Error: {base_reason}"
        if decision.user_message:
            result += f" User feedback: {decision.user_message}"
        return result

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
        event_message = None
        if isinstance(result, dict):
            event_message = result.get("event_message")
            result = result.get("result", "")

        result = self._normalize_result_for_llm(result, source_label=source_label)
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
            "event_message": event_message,
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

        if tool_name == "execute_shell_command":
            result = await tool_instance.execute(**arguments)
        else:
            result = await self._execute_with_timeout(
                tool_instance.execute(**arguments),
                tool_name=tool_name,
            )
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
        mcp_client = self.get_mcp_client()
        if not mcp_client:
            return None

        if self.ensure_mcp_connected is not None:
            await self.ensure_mcp_connected()

        if not self.is_mcp_connected():
            return None

        mcp_tools = await mcp_client.list_tools()
        if not any(t["function"]["name"] == tool_name for t in mcp_tools):
            return None

        result = await self._execute_with_timeout(
            mcp_client.call_tool(tool_name, arguments),
            tool_name=tool_name,
        )
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

        logger.info(
            f"Executing tool: {tool_name} "
            f"args_preview={self._build_arguments_preview(arguments)}"
        )

        dangerous, reason = self.is_dangerous_action(tool_name, arguments)
        approval_granted = False
        send_status_message = self.get_send_status_message()

        if not dangerous and send_status_message and self.config is not None:
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
            try:
                decision = await self.request_approval(tool_name, arguments, reason)
            except ApprovalTimeoutError as error:
                result = str(error)
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
            if not decision.approved:
                logger.info(f"User rejected dangerous action: {tool_name}")
                result = self._format_rejection_result(decision)
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
        """Send a non-blocking platform status message when available."""
        send_status_message = self.get_send_status_message()
        if not send_status_message or self.config is None:
            return

        import asyncio

        asyncio.create_task(send_status_message(text))
