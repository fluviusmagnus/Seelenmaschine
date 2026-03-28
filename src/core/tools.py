"""Tool runtime, registry, and execution orchestration."""

import html
import json
import time
from typing import Any, Awaitable, Callable, Dict, List, Optional

from utils.logger import get_logger

logger = get_logger()


class ToolRegistry:
    """Store tool instances and expose OpenAI-style tool definitions."""

    def __init__(self) -> None:
        self._tools: Dict[str, Any] = {}

    def register(self, tool: Any) -> None:
        """Register a tool instance by its declared name."""
        self._tools[tool.name] = tool

    def register_named(self, tool_name: str, tool: Any) -> None:
        """Register a tool instance under an explicit name."""
        self._tools[tool_name] = tool

    def register_many(self, tools: List[Any]) -> None:
        """Register multiple tools."""
        for tool in tools:
            self.register(tool)

    def get(self, tool_name: str) -> Optional[Any]:
        """Get a registered tool by name."""
        return self._tools.get(tool_name)

    def as_dict(self) -> Dict[str, Any]:
        """Return a shallow dict copy of the registered tools."""
        return dict(self._tools)

    @staticmethod
    def make_tool_def(tool: Any) -> Dict[str, Any]:
        """Build an OpenAI-format tool definition from a tool instance."""
        return {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.parameters,
            },
        }

    def collect_tool_defs(self) -> List[Dict[str, Any]]:
        """Collect OpenAI-format definitions for all registered tools."""
        return [self.make_tool_def(tool) for tool in self._tools.values()]


class ToolRuntime:
    """Configure the LLM tool runtime and optional MCP integration."""

    def __init__(
        self,
        handler: Any,
        memory_search_tool_cls: Any,
        mcp_client_cls: Any,
    ):
        self.handler = handler
        self.memory_search_tool_cls = memory_search_tool_cls
        self.mcp_client_cls = mcp_client_cls

    def register_scheduled_task_tool(self) -> None:
        """Register the scheduled task tool on the handler."""
        try:
            self.handler.scheduled_task_tool = self.handler.scheduled_task_tool_cls(
                self.handler.scheduler
            )
            self.handler.scheduled_task_tool_def = self.handler._make_tool_def(
                self.handler.scheduled_task_tool
            )
            logger.info("Registered scheduled_task tool with scheduler")
        except Exception as error:
            logger.error(f"Failed to register scheduled_task tool: {error}")
            self.handler.scheduled_task_tool = None
            self.handler.scheduled_task_tool_def = None

    def register_send_telegram_file_tool(self) -> None:
        """Register the Telegram file sending tool on the handler."""
        try:
            self.handler.send_telegram_file_tool = (
                self.handler.send_telegram_file_tool_cls(
                    self.handler._send_telegram_file_to_user
                )
            )
            self.handler.send_telegram_file_tool_def = self.handler._make_tool_def(
                self.handler.send_telegram_file_tool
            )
            logger.info("Registered send_telegram_file tool")
        except Exception as error:
            logger.error(f"Failed to register send_telegram_file tool: {error}")
            self.handler.send_telegram_file_tool = None
            self.handler.send_telegram_file_tool_def = None

    def register_builtin_tools(self) -> None:
        """Register builtin file and shell tools on the handler."""
        try:
            self.handler.read_file_tool = self.handler.read_file_tool_cls()
            self.handler.write_file_tool = self.handler.write_file_tool_cls()
            self.handler.replace_file_content_tool = (
                self.handler.replace_file_content_tool_cls()
            )
            self.handler.append_file_tool = self.handler.append_file_tool_cls()
            self.handler.grep_search_tool = self.handler.grep_search_tool_cls()
            self.handler.glob_search_tool = self.handler.glob_search_tool_cls()
            self.handler.shell_command_tool = self.handler.shell_command_tool_cls()

            builtin_tools = [
                self.handler.read_file_tool,
                self.handler.write_file_tool,
                self.handler.replace_file_content_tool,
                self.handler.append_file_tool,
                self.handler.grep_search_tool,
                self.handler.glob_search_tool,
                self.handler.shell_command_tool,
            ]
            for tool in builtin_tools:
                self.handler._tool_registry[tool.name] = tool
            self.handler._tool_registry_service.register_many(builtin_tools)
            logger.info("Registered builtin file and shell tools")
        except Exception as error:
            logger.error(f"Failed to register builtin tools: {error}")

    def collect_builtin_tool_defs(self) -> List[Dict[str, Any]]:
        """Collect OpenAI-format tool definitions for builtin tools."""
        return self.handler._tool_registry_service.collect_tool_defs()

    def setup_tools(self) -> None:
        """Initialize MCP state and register basic tools with the LLM client."""
        if self.handler.config.ENABLE_MCP:
            self.handler.mcp_client = self.mcp_client_cls()
            self.handler._mcp_connected = False
        else:
            self.handler.mcp_client = None
            self.handler._mcp_connected = False

        self.setup_basic_tools()

    def setup_basic_tools(self) -> None:
        """Register local tools and the executor in the LLM client."""
        tools: List[Dict[str, Any]] = []

        if self.handler.scheduled_task_tool_def:
            tools.append(self.handler.scheduled_task_tool_def)
            logger.info("Added scheduled_task tool")

        if self.handler.send_telegram_file_tool_def:
            tools.append(self.handler.send_telegram_file_tool_def)
            logger.info("Added send_telegram_file tool")

        if self.handler.tool_trace_query_tool:
            self.handler._tool_registry[self.handler.tool_trace_query_tool.name] = (
                self.handler.tool_trace_query_tool
            )
            self.handler._tool_registry_service.register(
                self.handler.tool_trace_query_tool
            )
            logger.info("Added query_tool_history tool")

        tools.extend(self.collect_builtin_tool_defs())

        session_id = self.handler.memory.get_current_session_id()
        if (
            not hasattr(self.handler, "memory_search_tool")
            or self.handler.memory_search_tool is None
        ):
            self.handler.memory_search_tool = self.memory_search_tool_cls(
                session_id=str(session_id),
                db=self.handler.db,
                embedding_client=self.handler.embedding_client,
                reranker_client=self.handler.reranker_client,
            )

        self.handler._tool_registry[self.handler.memory_search_tool.name] = (
            self.handler.memory_search_tool
        )
        self.handler._tool_registry_service.register(self.handler.memory_search_tool)

        if self.handler.scheduled_task_tool:
            self.handler._tool_registry[self.handler.scheduled_task_tool.name] = (
                self.handler.scheduled_task_tool
            )
            self.handler._tool_registry_service.register(
                self.handler.scheduled_task_tool
            )

        if self.handler.send_telegram_file_tool:
            self.handler._tool_registry[self.handler.send_telegram_file_tool.name] = (
                self.handler.send_telegram_file_tool
            )
            self.handler._tool_registry_service.register(
                self.handler.send_telegram_file_tool
            )

        tools.append(self.handler._make_tool_def(self.handler.memory_search_tool))
        logger.info("Added memory_search tool")

        self.handler.llm_client.set_tools(tools)
        self.handler.llm_client.set_tool_executor(self.handler._execute_tool)

        logger.info(f"Basic tools registered: {len(tools)}")

    async def ensure_mcp_connected(self) -> None:
        """Connect MCP lazily and merge remote tools into the LLM tool list."""
        if self.handler.mcp_client and not self.handler._mcp_connected:
            try:
                await self.handler.mcp_client.__aenter__()
                self.handler._mcp_connected = True

                mcp_tools = await self.handler.mcp_client.list_tools()
                logger.info(f"Connected MCP client with {len(mcp_tools)} tools")
                for tool in mcp_tools:
                    tool_func = tool.get("function", {})
                    name = tool_func.get("name", "Unknown")
                    desc = tool_func.get("description", "No description")
                    logger.debug(f"  - [MCP Tool] {name}: {desc}")

                all_tools: List[Dict[str, Any]] = []
                all_tools.extend(self.collect_builtin_tool_defs())
                all_tools.extend(mcp_tools)

                self.handler.llm_client.set_tools(all_tools)
                logger.info(
                    f"Updated tools: {len(all_tools)} total including {len(mcp_tools)} MCP tools"
                )
            except Exception as error:
                logger.error(f"Failed to connect MCP client: {error}")
                self.handler._mcp_connected = False
                self.setup_basic_tools()


class ToolExecutor:
    """Execute registered tools with approval, tracing, and MCP fallback."""

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
    def _elapsed_ms(start_time: float) -> int:
        """Convert a perf_counter start time into milliseconds."""
        return int((time.perf_counter() - start_time) * 1000)

    async def execute_tool(self, tool_name: str, arguments_json: str) -> str:
        """Execute a tool call from the LLM."""
        start_time = time.perf_counter()
        try:
            arguments = json.loads(arguments_json)
        except json.JSONDecodeError as error:
            logger.error(f"Failed to parse tool arguments: {error}")
            return f"Error: Invalid JSON arguments: {error}"

        logger.info(f"Executing tool: {tool_name} with args: {arguments}")

        dangerous, reason = self.is_dangerous_action(tool_name, arguments)
        approval_granted = False

        if not dangerous and self.telegram_bot and self.config is not None:
            try:
                msg = f"🔧 <b>Tool execution:</b> <code>{tool_name}</code>\n"
                args_str = html.escape(json.dumps(arguments, ensure_ascii=False)[:500])
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
                    tool_name=tool_name,
                    arguments=arguments,
                    result=result,
                    status="rejected",
                    duration_ms=self._elapsed_ms(start_time),
                    approval_required=True,
                    approved_by_user=False,
                )
                return result
            logger.info(f"User approved dangerous action: {tool_name}")
            approval_granted = True

        try:
            tool_instance = self.tool_registry.get(tool_name)
            if tool_instance is not None:
                result = await tool_instance.execute(**arguments)
                logger.info(
                    f"Tool execution finished: {tool_name}, "
                    f"preview={self.preview_text(result)}"
                )
                await self.record_tool_trace(
                    tool_name=tool_name,
                    arguments=arguments,
                    result=result,
                    status=self.infer_tool_trace_status(result),
                    duration_ms=self._elapsed_ms(start_time),
                    approval_required=dangerous,
                    approved_by_user=approval_granted,
                )
                if approval_granted:
                    await self.notify_approved_action_finished(tool_name, result)
                return result

            if self.mcp_client:
                if self.ensure_mcp_connected is not None:
                    await self.ensure_mcp_connected()

                if self.is_mcp_connected():
                    mcp_tools = self.mcp_client.get_tools_sync()
                    if any(t["function"]["name"] == tool_name for t in mcp_tools):
                        result = await self.mcp_client.call_tool(tool_name, arguments)
                        logger.info(
                            f"MCP tool execution finished: {tool_name}, "
                            f"preview={self.preview_text(result)}"
                        )
                        await self.record_tool_trace(
                            tool_name=tool_name,
                            arguments=arguments,
                            result=result,
                            status=self.infer_tool_trace_status(result),
                            duration_ms=self._elapsed_ms(start_time),
                            approval_required=dangerous,
                            approved_by_user=approval_granted,
                        )
                        if approval_granted:
                            await self.notify_approved_action_finished(tool_name, result)
                        return result

            result = f"Error: Tool not found: {tool_name}"
            await self.record_tool_trace(
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
            return result
        except Exception as error:
            logger.error(
                f"Tool execution raised exception after approval state="
                f"{approval_granted}: {tool_name} - {error}",
                exc_info=True,
            )
            await self.record_tool_trace(
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
