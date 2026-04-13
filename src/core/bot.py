"""Core application bot assembly."""

import asyncio
from typing import Any, Callable, Optional

from core.adapter_contracts import AdapterApprovalDelegate, AdapterRuntimeCapabilities
from core.config import Config
from core.conversation import ConversationService
from core.database import DatabaseManager
from core.file_service import FileArtifactService, FileDeliveryService
from core.hitl import ApprovalService, StopController
from core.scheduler import TaskScheduler
from core.session_service import SessionService
from core.tools import (
    ToolExecutor,
    ToolRuntime,
    ToolRuntimeState,
)
from llm.chat_client import LLMClient
from llm.embedding import EmbeddingClient
from llm.reranker import RerankerClient
from memory.manager import MemoryManager


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
        self.memory.ensure_long_term_memory_schema()
        self.scheduler = scheduler or TaskScheduler(self.db)
        self.llm_client = llm_client or LLMClient()
        self.conversation_service: Optional[ConversationService] = None
        self.session_service: Optional[SessionService] = None
        self.tool_runtime_state: Optional[ToolRuntimeState] = None
        self.approval_service = ApprovalService()
        self.file_artifact_service = FileArtifactService(config=self.config)
        self.file_delivery_service: Optional[FileDeliveryService] = None
        self._approval_delegate: Optional[Any] = None
        self._tool_runtime: Optional[ToolRuntime] = None
        self._tool_executor_service: Optional[ToolExecutor] = None
        self._send_file_to_user: Optional[Callable[..., Any]] = None
        self._preview_text: Optional[Callable[[Optional[str], int], str]] = None
        self._send_status_message: Optional[Callable[[str], Any]] = None
        self._stop_controller = StopController()

    def create_tool_runtime_state(
        self,
        *,
        get_current_session_id: Callable[[], Any],
    ) -> ToolRuntimeState:
        """Build and cache the shared tool runtime state."""
        self.tool_runtime_state = ToolRuntimeState(
            config=self.config,
            get_current_session_id=get_current_session_id,
        )
        return self.tool_runtime_state

    def get_tool_runtime(self) -> ToolRuntime:
        """Lazily resolve the tool runtime helper."""
        if self._send_file_to_user is None:
            raise RuntimeError("Tool runtime send_file capability has not been attached")
        if self._tool_runtime is None:
            self._tool_runtime = ToolRuntime(
                core_bot=self,
                send_file_to_user=self._send_file_to_user,
            )
        return self._tool_runtime

    def get_tool_executor_service(self) -> ToolExecutor:
        """Lazily resolve the tool executor."""
        if self._approval_delegate is None:
            raise RuntimeError("Tool runtime approval delegate has not been attached")
        if self._preview_text is None:
            raise RuntimeError("Tool runtime capabilities have not been attached")

        if self.tool_runtime_state is None:
            raise RuntimeError("Tool runtime state has not been initialized")

        if self._tool_executor_service is None:
            registry_service = self.tool_runtime_state.registry_service
            if registry_service is None:
                raise RuntimeError("Tool registry has not been initialized on CoreBot")
            self._tool_executor_service = ToolExecutor(
                config=self.config,
                tool_registry=registry_service,
                get_mcp_client=lambda: self.tool_runtime_state.mcp_client,
                ensure_mcp_connected=self.ensure_mcp_connected,
                is_mcp_connected=lambda: bool(self.tool_runtime_state.mcp_connected),
                is_dangerous_action=self.tool_runtime_state.safety_policy.is_dangerous_action,
                request_approval=self._approval_delegate.request_approval,
                record_tool_trace=self.tool_runtime_state.tool_trace_service.record_trace,
                infer_tool_trace_status=self.tool_runtime_state.tool_trace_service.infer_status,
                sanitize_result_preview=lambda result, max_length: self.tool_runtime_state.tool_trace_service.sanitize_result_preview(
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

    def initialize_adapter_runtime(
        self,
        *,
        approval_delegate: AdapterApprovalDelegate,
        capabilities: AdapterRuntimeCapabilities,
    ) -> ToolExecutor:
        """Initialize the core services needed by an adapter runtime."""
        if self.tool_runtime_state is None:
            self.create_tool_runtime_state(
                get_current_session_id=self.memory.get_current_session_id,
            )

        self._approval_delegate = approval_delegate
        self._tool_runtime = None
        self._tool_executor_service = None
        self._send_file_to_user = capabilities.send_file_to_user
        self._preview_text = capabilities.preview_text
        self._send_status_message = capabilities.send_status_message

        tool_runtime = self.get_tool_runtime()
        tool_runtime.register_core_tools()
        tool_runtime.register_builtin_tools()
        tool_runtime.setup_tools()

        if self.tool_runtime_state is None:
            raise RuntimeError("Tool runtime state has not been initialized")

        self.conversation_service = ConversationService(
            config=self.config,
            memory=self.memory,
            embedding_client=self.embedding_client,
            llm_client=self.llm_client,
            memory_search_tool=self.tool_runtime_state.memory_search_tool,
            mcp_client=self.tool_runtime_state.mcp_client,
            ensure_mcp_connected=self.ensure_mcp_connected,
            preview_text=capabilities.preview_text,
            begin_run=self.begin_tool_loop_run,
            end_run=self.end_tool_loop_run,
            check_stop_requested=self.check_stop_requested,
        )
        self.session_service = SessionService(
            memory=self.memory,
            tool_trace_store=self.tool_runtime_state.tool_trace_store,
            memory_search_tool=self.tool_runtime_state.memory_search_tool,
        )
        return self.get_tool_executor_service()

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
        if self.session_service is None:
            raise RuntimeError("Session service has not been initialized")
        return await self.session_service.create_new_session()

    def reset_session(self) -> int:
        """Reset the current session and return the fresh active session id."""
        if self.session_service is None:
            raise RuntimeError("Session service has not been initialized")
        return self.session_service.reset_session()

    async def ensure_mcp_connected(self) -> None:
        """Ensure MCP is connected through the core-owned tool runtime."""
        await self.get_tool_runtime().ensure_mcp_connected()

    async def warmup_tool_runtime(self) -> None:
        """Warm up tool runtime integrations during application startup."""
        await self.get_tool_runtime().warmup()

    async def execute_tool(self, tool_name: str, arguments_json: str) -> Any:
        """Execute an LLM tool call through the core-owned tool executor."""
        if self.tool_runtime_state is None:
            raise RuntimeError("Tool runtime state has not been initialized")

        if self.tool_runtime_state.registry_service is None:
            raise RuntimeError("Tool registry has not been initialized on CoreBot")
        return await self.get_tool_executor_service().execute_tool(tool_name, arguments_json)
