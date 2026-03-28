"""Core application bot assembly."""

from typing import Any, Callable, Optional

from core.config import Config
from core.conversation import ConversationService
from core.database import DatabaseManager
from core.scheduler import TaskScheduler
from core.session_service import SessionService
from core.tools import (
    ToolExecutor,
    ToolRuntime,
    ToolRuntimeState,
    ToolSafetyPolicy,
    ToolTraceService,
)
from llm.chat_client import LLMClient
from llm.embedding import EmbeddingClient
from llm.reranker import RerankerClient
from memory.manager import MemoryManager


class CoreToolHost:
    """Own tool runtime wiring in core, while adapters inject edge callbacks."""

    def __init__(self, owner: Any, *, get_tool_bridge: Callable[[], Any]):
        self.owner = owner
        self.get_tool_bridge = get_tool_bridge

    @staticmethod
    def _get_or_create_component(
        owner: Any,
        attr_name: str,
        expected_type: Any,
        factory: Callable[[], Any],
    ) -> Any:
        """Return a cached helper component or create and cache a replacement."""
        component = getattr(owner, attr_name, None)
        if isinstance(component, expected_type):
            return component

        component = factory()
        try:
            setattr(owner, attr_name, component)
        except Exception:
            pass
        return component

    def register_scheduled_task_tool(self) -> None:
        """Register the scheduled task tool with the scheduler instance."""
        self.get_tool_runtime().register_scheduled_task_tool()

    def register_send_telegram_file_tool(self) -> None:
        """Register the Telegram file sending tool."""
        self.get_tool_runtime().register_send_telegram_file_tool()

    def register_builtin_tools(self) -> None:
        """Register builtin file and shell tools."""
        self.get_tool_runtime().register_builtin_tools()

    def setup_tools(self) -> None:
        """Setup the tool system for the LLM."""
        self.get_tool_runtime().setup_tools()

    async def ensure_mcp_connected(self) -> None:
        """Ensure the MCP client is connected."""
        await self.get_tool_runtime().ensure_mcp_connected()

    def get_tool_runtime(self) -> ToolRuntime:
        """Lazily resolve the tool runtime helper."""
        return self._get_or_create_component(
            self.owner,
            "_tool_runtime",
            ToolRuntime,
            lambda: ToolRuntime(handler=self.owner),
        )

    def get_tool_trace_service(self) -> ToolTraceService:
        """Lazily resolve the tool trace helper."""
        tool_runtime_state = getattr(
            getattr(self.owner, "core_bot", None), "tool_runtime_state", None
        )
        return self._get_or_create_component(
            self.owner,
            "_tool_trace_service",
            ToolTraceService,
            lambda: ToolTraceService(
                store=getattr(tool_runtime_state, "tool_trace_store", None)
                or getattr(self.owner, "tool_trace_store", None),
                get_current_session_id=(
                    getattr(
                        getattr(self.owner, "memory", None),
                        "get_current_session_id",
                        None,
                    )
                    or (lambda: None)
                ),
            ),
        )

    def get_tool_executor_service(self) -> ToolExecutor:
        """Lazily resolve the tool executor."""

        def _build_executor() -> ToolExecutor:
            registry_service = ToolRuntime.get_registry(self.owner)
            tool_bridge = self.get_tool_bridge()
            tool_trace_service = self.get_tool_trace_service()
            tool_runtime_state = getattr(
                getattr(self.owner, "core_bot", None), "tool_runtime_state", None
            )
            config = getattr(self.owner, "config", None) or getattr(
                getattr(self.owner, "core_bot", None), "config", None
            )
            return ToolExecutor(
                config=config,
                tool_registry=registry_service,
                mcp_client=(
                    getattr(tool_runtime_state, "mcp_client", None)
                    if tool_runtime_state is not None
                    else getattr(self.owner, "mcp_client", None)
                ),
                ensure_mcp_connected=getattr(self.owner, "_ensure_mcp_connected", None),
                is_mcp_connected=lambda: (
                    bool(getattr(tool_runtime_state, "mcp_connected", False))
                    if tool_runtime_state is not None
                    else bool(getattr(self.owner, "_mcp_connected", False))
                ),
                is_dangerous_action=getattr(
                    getattr(tool_runtime_state, "safety_policy", None),
                    "is_dangerous_action",
                    getattr(
                        getattr(self.owner, "_tool_safety_policy", None),
                        "is_dangerous_action",
                        ToolSafetyPolicy(config).is_dangerous_action,
                    ),
                ),
                request_approval=tool_bridge.request_approval,
                record_tool_trace=tool_trace_service.record_trace,
                infer_tool_trace_status=tool_trace_service.infer_status,
                notify_approved_action_finished=tool_bridge.notify_approved_action_finished,
                notify_approved_action_failed=tool_bridge.notify_approved_action_failed,
                preview_text=self.owner._preview_text,
                telegram_bot=getattr(self.owner, "telegram_bot", None),
            )

        return self._get_or_create_component(
            self.owner,
            "_tool_executor_service",
            ToolExecutor,
            _build_executor,
        )

    async def execute_tool(self, tool_name: str, arguments_json: str) -> str:
        """Execute a tool call from the LLM."""
        ToolRuntime.get_registry(self.owner)

        executor = self.get_tool_executor_service()
        tool_runtime_state = getattr(
            getattr(self.owner, "core_bot", None), "tool_runtime_state", None
        )
        executor.mcp_client = (
            getattr(tool_runtime_state, "mcp_client", None)
            if tool_runtime_state is not None
            else getattr(self.owner, "mcp_client", None)
        )
        executor.telegram_bot = getattr(self.owner, "telegram_bot", None)
        return await executor.execute_tool(tool_name, arguments_json)


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
        self.session_service: Optional[SessionService] = None
        self.tool_host: Optional[CoreToolHost] = None
        self.tool_runtime_state: Optional[ToolRuntimeState] = None

    def create_conversation_service(
        self,
        *,
        memory_search_tool: Any,
        mcp_client: Any,
        ensure_mcp_connected: Any = None,
        preview_text: Any = None,
    ) -> ConversationService:
        """Build and cache the core conversation pipeline service."""
        self.conversation_service = ConversationService(
            config=self.config,
            memory=self.memory,
            embedding_client=self.embedding_client,
            llm_client=self.llm_client,
            memory_search_tool=memory_search_tool,
            mcp_client=mcp_client,
            ensure_mcp_connected=ensure_mcp_connected,
            preview_text=preview_text,
        )
        return self.conversation_service

    def create_session_service(
        self,
        *,
        tool_trace_store: Any,
        memory_search_tool: Any,
    ) -> SessionService:
        """Build and cache the core session lifecycle service."""
        self.session_service = SessionService(
            memory=self.memory,
            tool_trace_store=tool_trace_store,
            memory_search_tool=memory_search_tool,
        )
        return self.session_service

    def create_tool_host(
        self,
        owner: Any,
        *,
        get_tool_bridge: Callable[[], Any],
    ) -> CoreToolHost:
        """Build and cache the core tool host used by adapters."""
        self.tool_host = CoreToolHost(owner, get_tool_bridge=get_tool_bridge)
        return self.tool_host

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

    def get_conversation_service(self) -> ConversationService:
        """Return the initialized conversation service."""
        if self.conversation_service is None:
            raise RuntimeError("Conversation service has not been initialized")
        return self.conversation_service

    def get_session_service(self) -> SessionService:
        """Return the initialized session lifecycle service."""
        if self.session_service is None:
            raise RuntimeError("Session service has not been initialized")
        return self.session_service

    def get_tool_host(self) -> CoreToolHost:
        """Return the initialized tool host."""
        if self.tool_host is None:
            raise RuntimeError("Tool host has not been initialized")
        return self.tool_host

    async def process_message(
        self,
        user_message: str,
        *,
        intermediate_callback: Optional[Callable[[str], Any]] = None,
    ) -> str:
        """Process a normal user message via the core conversation pipeline."""
        return await self.get_conversation_service().process_message(
            user_message,
            intermediate_callback=intermediate_callback,
        )

    async def process_scheduled_task(
        self,
        task_message: str,
        task_name: str = "Scheduled Task",
        *,
        intermediate_callback: Optional[Callable[[str], Any]] = None,
    ) -> str:
        """Process a scheduled task through the core conversation pipeline."""
        return await self.get_conversation_service().process_scheduled_task(
            task_message,
            task_name,
            intermediate_callback=intermediate_callback,
        )

    async def create_new_session(self) -> int:
        """Archive the current session and start a new one."""
        return await self.get_session_service().create_new_session()

    def reset_session(self) -> int:
        """Reset the current session and return the fresh active session id."""
        return self.get_session_service().reset_session()

    async def ensure_mcp_connected(self) -> None:
        """Ensure MCP is connected through the core-owned tool host."""
        await self.get_tool_host().ensure_mcp_connected()

    async def execute_tool(self, tool_name: str, arguments_json: str) -> str:
        """Execute an LLM tool call through the core-owned tool host."""
        return await self.get_tool_host().execute_tool(tool_name, arguments_json)
