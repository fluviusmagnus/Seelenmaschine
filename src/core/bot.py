"""Core application bot assembly."""

import asyncio
from typing import Any, Callable, Optional

from core.adapter_contracts import AdapterApprovalDelegate
from core.config import Config
from core.conversation import ConversationService
from core.database import DatabaseManager
from core.file_service import FileArtifactService, FileDeliveryService
from core.hitl import ApprovalService, StopController
from core.scheduler import TaskScheduler
from core.tools import (
    ToolExecutor,
    ToolRegistry,
    ToolSafetyPolicy,
    ToolTraceService,
)
from llm.chat_client import LLMClient
from llm.embedding import EmbeddingClient
from llm.reranker import RerankerClient
from memory.manager import MemoryManager
from tools.file_io import (
    AppendFileTool,
    ReadFileTool,
    ReplaceFileContentTool,
    WriteFileTool,
)
from tools.file_search import GlobSearchTool, GrepSearchTool
from tools.mcp_client import MCPClient
from tools.memory_search import MemorySearchTool
from tools.scheduled_tasks import ScheduledTaskTool
from tools.send_file import SendFileTool
from tools.shell import ShellCommandTool
from tools.tool_trace import ToolTraceQueryTool, ToolTraceStore
from utils.logger import get_logger

logger = get_logger()


class CoreBot:
    """Own the core runtime dependencies independently of any adapter."""

    def __init__(
        self,
        *,
        config: Optional[Any] = None,
        db: Optional[Any] = None,
        embedding_client: Optional[Any] = None,
        reranker_client: Optional[Any] = None,
        memory: Optional[Any] = None,
        scheduler: Optional[Any] = None,
        llm_client: Optional[Any] = None,
    ) -> None:
        self.config = config or Config()
        self.db = db or DatabaseManager()
        self.embedding_client = embedding_client or EmbeddingClient()
        self.reranker_client = reranker_client or RerankerClient()
        self.memory = memory or MemoryManager(
            db=self.db,
            embedding_client=self.embedding_client,
            reranker_client=self.reranker_client,
        )
        self.scheduler = scheduler or TaskScheduler(self.db)
        self.llm_client = llm_client or LLMClient()
        self.conversation_service: Optional[ConversationService] = None
        self._tool_runtime_initialized = False
        self.tool_trace_store: Optional[Any] = None
        self.tool_trace_query_tool: Optional[Any] = None
        self.tool_trace_service: Optional[Any] = None
        self.registry_service: Optional[ToolRegistry] = None
        self.safety_policy: Optional[ToolSafetyPolicy] = None
        self.memory_search_tool: Optional[Any] = None
        self.scheduled_task_tool: Optional[Any] = None
        self.send_file_tool: Optional[Any] = None
        self.mcp_client: Optional[Any] = None
        self.mcp_connected = False
        self.approval_service = ApprovalService()
        self.file_artifact_service = FileArtifactService(config=self.config)
        self.file_delivery_service: Optional[FileDeliveryService] = None
        self._approval_delegate: Optional[Any] = None
        self._tool_executor_service: Optional[ToolExecutor] = None
        self._send_file_to_user: Optional[Callable[..., Any]] = None
        self._preview_text: Optional[Callable[[Optional[str], int], str]] = None
        self._send_status_message: Optional[Callable[[str], Any]] = None
        self._stop_controller = StopController()
        self._bootstrap_initialized = False

    @classmethod
    async def create_async(cls, **kwargs: Any) -> "CoreBot":
        """Construct and initialize the core runtime."""
        bot = cls(**kwargs)
        await bot.initialize_async()
        return bot

    async def initialize_async(self) -> None:
        """Run async startup bootstrap tasks once."""
        if self._bootstrap_initialized:
            return

        await self.memory.ensure_long_term_memory_schema_async()
        self.memory.ensure_session_snapshot_current()
        self._bootstrap_initialized = True

    def _initialize_tool_runtime_state(self) -> None:
        """Initialize core-owned tool runtime fields."""
        self.tool_trace_store = ToolTraceStore(self.config.DATA_DIR)
        self.tool_trace_query_tool = ToolTraceQueryTool(
            self.tool_trace_store,
            self.memory.get_current_session_id,
        )
        self.tool_trace_service = ToolTraceService(
            store=self.tool_trace_store,
            get_current_session_id=self.memory.get_current_session_id,
        )
        self.registry_service = ToolRegistry()
        self.safety_policy = ToolSafetyPolicy(self.config)
        self._tool_runtime_initialized = True

    def _require_tool_runtime(self) -> None:
        """Ensure the tool runtime fields are initialized."""
        if not self._tool_runtime_initialized:
            raise RuntimeError("Tool runtime state has not been initialized on CoreBot")

    def _get_tool_executor(self) -> ToolExecutor:
        """Lazily resolve the tool executor."""
        if self._approval_delegate is None:
            raise RuntimeError("Tool runtime approval delegate has not been attached")
        if self._preview_text is None:
            raise RuntimeError("Tool runtime capabilities have not been attached")

        self._require_tool_runtime()
        if self.registry_service is None or self.safety_policy is None or self.tool_trace_service is None:
            raise RuntimeError("Tool runtime services have not been initialized on CoreBot")

        if self._tool_executor_service is None:
            self._tool_executor_service = ToolExecutor(
                config=self.config,
                tool_registry=self.registry_service,
                get_mcp_client=lambda: self.mcp_client,
                ensure_mcp_connected=self.ensure_mcp_connected,
                is_mcp_connected=lambda: bool(self.mcp_connected),
                is_dangerous_action=self.safety_policy.is_dangerous_action,
                request_approval=self._approval_delegate.request_approval,
                record_tool_trace=self.tool_trace_service.record_trace,
                infer_tool_trace_status=self.tool_trace_service.infer_status,
                sanitize_result_preview=lambda result, max_length: self.tool_trace_service.sanitize_result_preview(
                    result,
                    max_length=max_length,
                ),
                notify_approved_action_finished=self._approval_delegate.notify_approved_action_finished,
                notify_approved_action_failed=self._approval_delegate.notify_approved_action_failed,
                file_artifact_service=self.file_artifact_service,
                preview_text=self._preview_text,
                get_send_status_message=lambda: self._send_status_message,
            )
        return self._tool_executor_service

    def _register_stateful_tool(
        self, *, state_attr: str, factory: Callable[[], Any], label: str
    ) -> None:
        """Create and register a core-owned tool instance."""
        self._require_tool_runtime()
        if self.registry_service is None:
            raise RuntimeError("Tool registry has not been initialized on CoreBot")
        try:
            tool = factory()
            setattr(self, state_attr, tool)
            self.registry_service.register_named(tool.name, tool)
            logger.info(f"Registered {label} tool")
        except Exception as error:
            logger.error(f"Failed to register {label} tool: {error}")
            setattr(self, state_attr, None)

    def _ensure_memory_search_tool(self) -> Any:
        """Create the memory search tool lazily."""
        self._require_tool_runtime()
        if self.memory_search_tool is None:
            session_id = self.memory.get_current_session_id()
            self.memory_search_tool = MemorySearchTool(
                session_id=str(session_id),
                db=self.db,
                embedding_client=self.embedding_client,
                reranker_client=self.reranker_client,
            )
        return self.memory_search_tool

    def _register_local_runtime_tools(self) -> None:
        """Ensure every local runtime tool is present in the registry."""
        self._require_tool_runtime()
        if self.registry_service is None:
            raise RuntimeError("Tool registry has not been initialized on CoreBot")
        registry = self.registry_service
        if self.tool_trace_query_tool:
            registry.register_named(
                self.tool_trace_query_tool.name, self.tool_trace_query_tool
            )
            logger.info("Added query_tool_history tool")

        memory_search_tool = self._ensure_memory_search_tool()
        if memory_search_tool:
            registry.register_named(memory_search_tool.name, memory_search_tool)
            logger.info("Added memory_search tool")

        if self.scheduled_task_tool:
            registry.register_named(
                self.scheduled_task_tool.name, self.scheduled_task_tool
            )
            logger.info("Added scheduled_task tool")

        if self.send_file_tool:
            registry.register_named(self.send_file_tool.name, self.send_file_tool)
            logger.info("Added send_file tool")

    def _register_core_tools(self) -> None:
        """Register stateful core-owned tools needed by the runtime."""
        if self._send_file_to_user is None:
            raise RuntimeError("Tool runtime send_file capability has not been attached")

        self._register_stateful_tool(
            state_attr="scheduled_task_tool",
            factory=lambda: ScheduledTaskTool(self.scheduler),
            label="scheduled_task",
        )
        self._register_stateful_tool(
            state_attr="send_file_tool",
            factory=lambda: SendFileTool(
                lambda **kwargs: self._send_file_to_user(**kwargs)
            ),
            label="send_file",
        )

    def _register_builtin_tools(self) -> None:
        """Register builtin file and shell tools."""
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
            self._require_tool_runtime()
            if self.registry_service is None:
                raise RuntimeError("Tool registry has not been initialized on CoreBot")
            registry = self.registry_service
            for tool in builtin_tools:
                registry.register_named(tool.name, tool)
            logger.info("Registered builtin file and shell tools")
        except Exception as error:
            logger.error(f"Failed to register builtin tools: {error}")

    def _publish_tools(self, extra_tools: Optional[list[dict[str, Any]]] = None) -> None:
        """Publish local tools plus optional remote tools to the LLM client."""
        self._register_local_runtime_tools()
        if self.registry_service is None:
            raise RuntimeError("Tool registry has not been initialized on CoreBot")
        tools = self.registry_service.collect_tool_defs()
        if extra_tools:
            tools.extend(extra_tools)

        self.llm_client.set_tools(tools)
        self.llm_client.set_tool_executor(self.execute_tool)
        logger.info(f"Tools registered: {len(tools)}")

    def _setup_tools(self) -> None:
        """Initialize MCP state and register tools with the LLM client."""
        self._require_tool_runtime()
        if self.config.ENABLE_MCP:
            self.mcp_client = MCPClient(file_artifact_service=self.file_artifact_service)
            self.mcp_connected = False
        else:
            self.mcp_client = None
            self.mcp_connected = False

        self._publish_tools()

    def initialize_adapter_runtime(
        self,
        *,
        approval_delegate: AdapterApprovalDelegate,
        preview_text: Callable[[Optional[str], int], str],
        send_file_to_user: Callable[..., Any],
        send_status_message: Optional[Callable[[str], Any]] = None,
    ) -> ToolExecutor:
        """Initialize the core services needed by an adapter runtime."""
        if not self._tool_runtime_initialized:
            self._initialize_tool_runtime_state()

        self._approval_delegate = approval_delegate
        self._tool_executor_service = None
        self._send_file_to_user = send_file_to_user
        self._preview_text = preview_text
        self._send_status_message = send_status_message

        self._register_core_tools()
        self._register_builtin_tools()
        self._setup_tools()

        self._require_tool_runtime()

        self.conversation_service = ConversationService(
            config=self.config,
            memory=self.memory,
            embedding_client=self.embedding_client,
            llm_client=self.llm_client,
            memory_search_tool=self.memory_search_tool,
            mcp_client=self.mcp_client,
            ensure_mcp_connected=self.ensure_mcp_connected,
            preview_text=preview_text,
            begin_run=self.begin_tool_loop_run,
            end_run=self.end_tool_loop_run,
            check_stop_requested=self.check_stop_requested,
        )
        return self._get_tool_executor()

    async def process_message(
        self,
        user_message: str,
        *,
        message_for_embedding: Optional[str] = None,
        intermediate_callback: Optional[Callable[[str], Any]] = None,
    ) -> str:
        """Process a normal user message via the core conversation pipeline."""
        if self.conversation_service is None:
            raise RuntimeError("Conversation service has not been initialized")
        return await self.conversation_service.process_message(
            user_message,
            message_for_embedding=message_for_embedding,
            intermediate_callback=intermediate_callback,
        )

    async def process_scheduled_task(
        self,
        task_message: str,
        task_name: str = "Scheduled Task",
        task_id: Optional[str] = None,
        *,
        intermediate_callback: Optional[Callable[[str], Any]] = None,
    ) -> str:
        """Process a scheduled task through the core conversation pipeline."""
        if self.conversation_service is None:
            raise RuntimeError("Conversation service has not been initialized")
        return await self.conversation_service.process_scheduled_task(
            task_message,
            task_name,
            task_id,
            intermediate_callback=intermediate_callback,
        )

    def get_processing_lock(self) -> asyncio.Lock:
        """Expose the shared conversation sequencing lock."""
        if self.conversation_service is None:
            raise RuntimeError("Conversation service has not been initialized")
        return self.conversation_service.processing_lock

    def begin_tool_loop_run(self) -> None:
        """Mark the start of a conversation/tool loop run."""
        self._stop_controller.begin_run()

    def end_tool_loop_run(self) -> None:
        """Mark the end of a conversation/tool loop run and clear stop state."""
        self._stop_controller.end_run()

    def request_stop_current_run(self, reason: str = "User requested stop.") -> bool:
        """Request a cooperative stop for the currently active conversation/tool loop."""
        return self._stop_controller.request_stop(reason)

    def check_stop_requested(self) -> None:
        """Raise if the active run has been asked to stop."""
        self._stop_controller.check_stop_requested()

    def has_running_conversation(self) -> bool:
        """Return whether a conversation/tool loop is currently running."""
        return self._stop_controller.has_running_run()

    def is_stop_requested(self) -> bool:
        """Return whether the current active run has a pending stop request."""
        return self._stop_controller.is_stop_requested()

    async def run_post_response_summary_check(self, *, context_label: str) -> Optional[int]:
        """Run the explicit post-reply summary check."""
        if self.conversation_service is None:
            raise RuntimeError("Conversation service has not been initialized")
        return await self.conversation_service.run_post_response_summary_check(
            context_label=context_label
        )

    async def create_new_session(self) -> int:
        """Archive the current session and start a new one."""
        self._require_tool_runtime()
        if self.tool_trace_store is None:
            raise RuntimeError("Tool trace store has not been initialized on CoreBot")
        logger.info("Creating new session")
        new_session_id = await self.memory.new_session_async()
        logger.info(f"Created new session {new_session_id}")
        self._sync_memory_search_session(int(new_session_id))
        self.tool_trace_store.prune_to_max_records()
        return int(new_session_id)

    def reset_session(self) -> int:
        """Reset the current session and return the fresh active session id."""
        self._require_tool_runtime()
        if self.tool_trace_store is None:
            raise RuntimeError("Tool trace store has not been initialized on CoreBot")
        logger.info("Resetting session")
        self.memory.reset_session()
        session_id = int(self.memory.get_current_session_id())
        self._sync_memory_search_session(session_id)
        self.tool_trace_store.prune_to_max_records()
        return session_id

    def _sync_memory_search_session(self, session_id: int) -> None:
        """Keep the memory search tool aligned with the active session."""
        self._require_tool_runtime()
        if self.memory_search_tool is None:
            return
        self.memory_search_tool.session_id = int(session_id)
        logger.info(f"Updated memory_search_tool session_id to {session_id}")

    async def ensure_mcp_connected(self) -> None:
        """Ensure MCP is connected through the core-owned tool runtime."""
        self._require_tool_runtime()
        if self.mcp_client and not self.mcp_connected:
            try:
                await self.mcp_client.__aenter__()
                self.mcp_connected = True

                mcp_tools = await self.mcp_client.list_tools()
                logger.info(f"Connected MCP client with {len(mcp_tools)} tools")
                tool_names = [
                    tool.get("function", {}).get("name", "Unknown")
                    for tool in mcp_tools
                ]
                logger.debug(f"MCP tool names: {tool_names}")

                self._publish_tools(mcp_tools)
                logger.info(f"Updated tools: local + {len(mcp_tools)} MCP tools")
            except Exception as error:
                logger.error(f"Failed to connect MCP client: {error}")
                self.mcp_connected = False
                self._publish_tools()

    async def warmup_tool_runtime(self) -> None:
        """Warm up tool runtime integrations during application startup."""
        self._require_tool_runtime()
        if not self.mcp_client:
            logger.debug("Skipping tool runtime warmup because MCP is disabled")
            return

        logger.info("Warming up core MCP integration")
        await self.ensure_mcp_connected()

    async def execute_tool(self, tool_name: str, arguments_json: str) -> Any:
        """Execute an LLM tool call through the core-owned tool executor."""
        if not self._tool_runtime_initialized:
            raise RuntimeError("Tool runtime state has not been initialized")

        if self.registry_service is None:
            raise RuntimeError("Tool registry has not been initialized on CoreBot")
        return await self._get_tool_executor().execute_tool(tool_name, arguments_json)
