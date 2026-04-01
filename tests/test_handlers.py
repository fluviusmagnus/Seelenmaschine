"""Tests for tg_bot/handlers.py

This module tests the message handler functionality,
including tool execution, MCP client integration, and message processing.
"""

import asyncio
import sys
from pathlib import Path
from unittest.mock import Mock, AsyncMock
import json
import pytest

# Add paths for imports
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


class TestMessageHandlerInitialization:
    """Test MessageHandler initialization"""

    @pytest.fixture
    def mock_dependencies(self):
        """Create mock dependencies"""
        config = Mock()
        config.ENABLE_MCP = False
        config.DATA_DIR = Path("data/test")
        config.WORKSPACE_DIR = Path("data/test/workspace")
        config.MEDIA_DIR = Path("data/test/workspace/media")
        config.DEBUG_MODE = False
        memory = Mock()
        memory.get_current_session_id.return_value = 1
        return {
            "config": config,
            "db": Mock(),
            "embedding_client": Mock(),
            "reranker_client": Mock(),
            "memory": memory,
            "scheduler": Mock(),
            "llm_client": Mock(),
        }

    def test_handler_initializes_components(self, mock_dependencies):
        """Test that handler initializes all required components"""
        from adapter.telegram.controller import TelegramController
        from core.bot import CoreBot

        core_bot = CoreBot(**mock_dependencies)
        handler = TelegramController(core_bot=core_bot)

        assert handler is not None


class TestToolExecution:
    """Test tool execution functionality"""

    @pytest.fixture
    def mock_handler(self):
        """Create a mock handler with tool execution capability"""
        handler = Mock()
        handler.memory_search_tool = Mock()
        handler.memory_search_tool.name = "memory_search"
        handler.memory_search_tool.execute = AsyncMock(
            return_value="Memory search result"
        )

        handler.scheduled_task_tool = Mock()
        handler.scheduled_task_tool.name = "scheduled_task"
        handler.scheduled_task_tool.execute = AsyncMock(return_value="Task scheduled")

        handler.send_file_tool = Mock()
        handler.send_file_tool.name = "send_file"
        handler.send_file_tool.execute = AsyncMock(return_value="File sent")

        handler.mcp_client = None

        return handler

    @pytest.mark.asyncio
    async def test_execute_memory_search_tool(self, mock_handler):
        """Test executing memory search tool"""
        # This is a placeholder - actual implementation would test the real handler
        arguments = '{"query": "test query"}'

        # Mock the execution
        result = await mock_handler.memory_search_tool.execute(**json.loads(arguments))

        assert result == "Memory search result"
        mock_handler.memory_search_tool.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_execute_scheduled_task_tool(self, mock_handler):
        """Test executing scheduled task tool"""
        arguments = '{"message": "Test message", "trigger": "in 1 hour"}'

        # Mock the execution
        result = await mock_handler.scheduled_task_tool.execute(**json.loads(arguments))

        assert result == "Task scheduled"
        mock_handler.scheduled_task_tool.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_execute_send_file_tool(self, mock_handler):
        """Test executing send_file tool"""
        arguments = '{"file_path": "output/report.pdf", "caption": "导出结果"}'

        result = await mock_handler.send_file_tool.execute(**json.loads(arguments))

        assert result == "File sent"
        mock_handler.send_file_tool.execute.assert_called_once()


class TestMessageProcessing:
    """Test message processing functionality"""

    @staticmethod
    def _build_core_bot_for_conversation(handler, *, scheduled: bool = False):
        from core.bot import CoreBot
        from core.conversation import ConversationService

        config = Mock()
        config.ENABLE_MCP = False
        config.DATA_DIR = Path("data/test")
        config.WORKSPACE_DIR = Path("data/test/workspace")
        config.MEDIA_DIR = Path("data/test/workspace/media")

        core_bot = CoreBot(
            config=config,
            db=Mock(),
            embedding_client=getattr(handler, "embedding_client", Mock()),
            reranker_client=Mock(),
            memory=handler.memory,
            scheduler=Mock(),
            llm_client=handler.llm_client,
        )
        core_bot.conversation_service = ConversationService(
            config=core_bot.config,
            memory=core_bot.memory,
            embedding_client=core_bot.embedding_client,
            llm_client=core_bot.llm_client,
            memory_search_tool=handler.memory_search_tool,
            mcp_client=handler.mcp_client,
            ensure_mcp_connected=handler._ensure_mcp_connected,
            preview_text=handler._preview_text,
        )
        return core_bot

    @pytest.mark.asyncio
    async def test_process_message_returns_final_text_without_assistant_history(self):
        """Message processing should return the final LLM text and persist it once."""
        from adapter.telegram.controller import TelegramController

        handler = Mock(spec=TelegramController)
        handler.memory = Mock()
        handler.memory.add_user_message_async = AsyncMock(return_value=(1, [0.1, 0.2]))
        handler.memory.get_context_messages = Mock(return_value=[])
        handler.memory.process_user_input_async = AsyncMock(return_value=([], []))
        handler.memory.get_recent_summaries = Mock(return_value=[])
        handler.memory.add_assistant_message_async = AsyncMock(return_value=(2, None))
        handler.memory.add_tool_message_async = AsyncMock(return_value=3)

        handler.memory_search_tool = Mock()
        handler.memory_search_tool.enable = Mock()
        handler.memory_search_tool.disable = Mock()

        handler.mcp_client = None
        handler._ensure_mcp_connected = AsyncMock()

        handler.llm_client = Mock()
        handler.llm_client.chat_async_detailed = AsyncMock(
            return_value={
                "final_text": "这是最后答复",
                "assistant_messages": ["这是最后答复"],
                "tool_context_messages": [],
                "conversation_events": [
                    {"role": "assistant", "content": "这是最后答复"}
                ],
            }
        )

        core_bot = self._build_core_bot_for_conversation(handler)
        response = await core_bot.process_message("帮我总结一下")

        assert response == "这是最后答复"
        handler.memory.add_user_message_async.assert_awaited_once_with("帮我总结一下")
        handler.memory.process_user_input_async.assert_awaited_once_with(
            user_input="帮我总结一下",
            last_bot_message=None,
            user_input_embedding=[0.1, 0.2],
        )
        handler.memory_search_tool.enable.assert_called_once()
        handler.memory_search_tool.disable.assert_called_once()
        handler.memory.add_assistant_message_async.assert_awaited_once_with(
            "这是最后答复"
        )

    def test_format_exception_for_user_truncates_long_messages(self):
        """User-facing error summaries should stay concise."""
        from adapter.telegram.controller import TelegramController

        error = RuntimeError("x" * 500)

        formatted = TelegramController._format_exception_for_user(error)

        assert len(formatted) == 300
        assert formatted.endswith("...")

    @pytest.mark.asyncio
    async def test_process_message_saves_intermediate_assistant_messages(self):
        """Assistant text emitted during tool calling should also be saved to memory."""
        from adapter.telegram.controller import TelegramController

        handler = Mock(spec=TelegramController)
        handler.memory = Mock()
        handler.memory.add_user_message_async = AsyncMock(return_value=(1, [0.1, 0.2]))
        handler.memory.get_context_messages = Mock(
            return_value=[{"role": "user", "content": "你好"}]
        )
        handler.memory.process_user_input_async = AsyncMock(return_value=([], []))
        handler.memory.get_recent_summaries = Mock(return_value=[])
        handler.memory.add_assistant_message_async = AsyncMock(
            side_effect=[(2, None), (3, None)]
        )
        handler.memory.add_scheduled_task_message_async = AsyncMock(return_value=4)
        handler.memory.add_tool_message_async = AsyncMock(return_value=4)

        handler.memory_search_tool = Mock()
        handler.memory_search_tool.enable = Mock()
        handler.memory_search_tool.disable = Mock()

        handler.mcp_client = None
        handler._ensure_mcp_connected = AsyncMock()

        handler.llm_client = Mock()
        handler.llm_client.chat_async_detailed = AsyncMock(
            return_value={
                "final_text": "最终答复",
                "assistant_messages": ["我先查一下", "最终答复"],
                "tool_context_messages": [
                    '[Tool Call]\ntrace_id: 1\nstatus: "success"\ntool_name: "search_memories"\narguments_preview: {"query": "test"}\nresult_preview: "ok"'
                ],
                "conversation_events": [
                    {"role": "assistant", "content": "我先查一下"},
                    {
                        "role": "system",
                        "content": '[Tool Call]\ntrace_id: 1\nstatus: "success"\ntool_name: "search_memories"\narguments_preview: {"query": "test"}\nresult_preview: "ok"',
                    },
                    {"role": "assistant", "content": "最终答复"},
                ],
            }
        )

        core_bot = self._build_core_bot_for_conversation(handler)
        response = await core_bot.process_message("你好")

        assert response == "最终答复"
        handler.memory.add_tool_message_async.assert_awaited_once()
        assert handler.memory.add_assistant_message_async.await_count == 2
        handler.memory.add_assistant_message_async.assert_any_await("我先查一下")
        handler.memory.add_assistant_message_async.assert_any_await("最终答复")
        assert handler.memory.add_assistant_message_async.await_args_list[0].args == (
            "我先查一下",
        )
        assert handler.memory.add_tool_message_async.await_args_list[0].args == (
            '[Tool Call]\ntrace_id: 1\nstatus: "success"\ntool_name: "search_memories"\narguments_preview: {"query": "test"}\nresult_preview: "ok"',
        )
        assert handler.memory.add_assistant_message_async.await_args_list[1].args == (
            "最终答复",
        )

    @pytest.mark.asyncio
    async def test_process_scheduled_task_saves_intermediate_assistant_messages(self):
        """Scheduled task assistant text emitted during tool calling should be saved."""
        from adapter.telegram.controller import TelegramController

        handler = Mock(spec=TelegramController)
        handler.memory = Mock()
        handler.memory.get_context_messages = Mock(return_value=[])
        handler.memory.process_user_input_async = AsyncMock(return_value=([], []))
        handler.memory.get_recent_summaries = Mock(return_value=[])
        handler.memory.add_assistant_message_async = AsyncMock(
            side_effect=[(2, None), (3, None)]
        )
        handler.memory.add_scheduled_task_message_async = AsyncMock(return_value=4)
        handler.memory.add_tool_message_async = AsyncMock(return_value=4)

        handler.embedding_client = Mock()
        handler.embedding_client.get_embedding_async = AsyncMock(
            return_value=[0.1, 0.2]
        )

        handler.memory_search_tool = Mock()
        handler.memory_search_tool.enable = Mock()
        handler.memory_search_tool.disable = Mock()

        handler.mcp_client = None
        handler._ensure_mcp_connected = AsyncMock()

        handler.llm_client = Mock()
        handler.llm_client.chat_with_custom_message_async_detailed = AsyncMock(
            return_value={
                "final_text": "别忘了喝水。",
                "assistant_messages": ["我提醒你一下", "别忘了喝水。"],
                "tool_context_messages": [
                    '[Tool Call]\ntrace_id: 2\nstatus: "success"\ntool_name: "scheduled_task"\narguments_preview: {"message": "提醒喝水"}\nresult_preview: "ok"'
                ],
                "conversation_events": [
                    {"role": "assistant", "content": "我提醒你一下"},
                    {
                        "role": "system",
                        "content": '[Tool Call]\ntrace_id: 2\nstatus: "success"\ntool_name: "scheduled_task"\narguments_preview: {"message": "提醒喝水"}\nresult_preview: "ok"',
                    },
                    {"role": "assistant", "content": "别忘了喝水。"},
                ],
            }
        )

        core_bot = self._build_core_bot_for_conversation(handler, scheduled=True)
        response = await core_bot.process_scheduled_task(
            "提醒喝水",
            "喝水提醒",
            "task-123",
        )

        assert response == "别忘了喝水。"
        handler.memory.add_scheduled_task_message_async.assert_awaited_once()
        scheduled_trigger_message = (
            handler.memory.add_scheduled_task_message_async.await_args.args[0]
        )
        assert "[Scheduled Task]" in scheduled_trigger_message
        assert "task_id: task-123" in scheduled_trigger_message
        assert "name: 喝水提醒" in scheduled_trigger_message
        assert "message: 提醒喝水" in scheduled_trigger_message
        assert (
            "This is a trigger message. Now execute the task described above and then continue the current conversation."
            in scheduled_trigger_message
        )
        handler.llm_client.chat_with_custom_message_async_detailed.assert_awaited_once()
        assert (
            handler.llm_client.chat_with_custom_message_async_detailed.await_args.kwargs[
                "custom_message_role"
            ]
            == "system"
        )
        assert handler.memory.add_assistant_message_async.await_count == 2
        handler.memory.add_assistant_message_async.assert_any_await("我提醒你一下")
        handler.memory.add_assistant_message_async.assert_any_await("别忘了喝水。")
        assert handler.memory.add_assistant_message_async.await_args_list[0].args == (
            "我提醒你一下",
        )
        assert handler.memory.add_tool_message_async.await_args_list[0].args == (
            '[Tool Call]\ntrace_id: 2\nstatus: "success"\ntool_name: "scheduled_task"\narguments_preview: {"message": "提醒喝水"}\nresult_preview: "ok"',
        )
        assert handler.memory.add_assistant_message_async.await_args_list[1].args == (
            "别忘了喝水。",
        )

    @pytest.mark.asyncio
    async def test_handle_message_returns_error_details_on_failure(self):
        """Top-level message errors should include readable details for debugging."""
        from adapter.telegram.controller import TelegramController
        from adapter.telegram.messages import TelegramMessages

        handler = Mock(spec=TelegramController)
        handler.config = Mock()
        handler.config.TELEGRAM_USER_ID = 123456789
        handler.core_bot = Mock()
        handler.core_bot.config = handler.config
        handler.core_bot.process_message = AsyncMock(
            side_effect=RuntimeError("maximum context length exceeded")
        )
        handler._send_intermediate_response = AsyncMock()
        handler._format_exception_for_user = (
            TelegramController._format_exception_for_user
        )
        handler.messages = TelegramMessages(
            core_bot=handler.core_bot,
            access_guard=Mock(
                reject_unauthorized=AsyncMock(return_value=False),
            ),
            approval_service=None,
            files=Mock(),
            response_sender=Mock(),
            preview_text=TelegramController._preview_text,
            format_exception_for_user=TelegramController._format_exception_for_user,
            intermediate_callback=handler._send_intermediate_response,
        )
        handler.handle_message = TelegramController.handle_message.__get__(
            handler, Mock
        )

        update = Mock()
        update.effective_user = Mock()
        update.effective_user.id = 123456789
        update.effective_chat = Mock()
        update.effective_chat.id = 123456789
        update.message = Mock()
        update.message.text = "你好"
        update.message.reply_text = AsyncMock()

        context = Mock()
        context.bot = Mock()
        context.bot.send_chat_action = AsyncMock()

        await handler.handle_message(update, context)

        sent_text = update.message.reply_text.await_args.args[0]
        assert "Sorry, an error occurred while processing your message." in sent_text
        assert "maximum context length exceeded" in sent_text

    @pytest.mark.asyncio
    async def test_handle_message_does_not_reraise_when_error_reply_fails(self):
        """If Telegram is unreachable during error reporting, the handler should only log."""
        from adapter.telegram.controller import TelegramController
        from adapter.telegram.messages import TelegramMessages

        handler = Mock(spec=TelegramController)
        handler.config = Mock()
        handler.config.TELEGRAM_USER_ID = 123456789
        handler.core_bot = Mock()
        handler.core_bot.config = handler.config
        handler.core_bot.process_message = AsyncMock(
            side_effect=RuntimeError("Request timed out.")
        )
        handler._send_intermediate_response = AsyncMock()
        handler.messages = TelegramMessages(
            core_bot=handler.core_bot,
            access_guard=Mock(
                reject_unauthorized=AsyncMock(return_value=False),
            ),
            approval_service=None,
            files=Mock(),
            response_sender=Mock(),
            preview_text=TelegramController._preview_text,
            format_exception_for_user=TelegramController._format_exception_for_user,
            intermediate_callback=handler._send_intermediate_response,
        )
        handler.handle_message = TelegramController.handle_message.__get__(
            handler, Mock
        )

        update = Mock()
        update.effective_user = Mock()
        update.effective_user.id = 123456789
        update.effective_chat = Mock()
        update.effective_chat.id = 123456789
        update.message = Mock()
        update.message.text = "你好"
        update.message.reply_text = AsyncMock(
            side_effect=RuntimeError("telegram send failed")
        )

        context = Mock()
        context.bot = Mock()
        context.bot.send_chat_action = AsyncMock()

        await handler.handle_message(update, context)

        update.message.reply_text.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_execute_tool_resumes_dangerous_shell_after_approve(self):
        """Dangerous shell actions should continue executing after /approve."""
        from adapter.telegram.commands import TelegramCommands
        from core.approval import ApprovalService
        from core.bot import CoreBot
        from core.tools import ToolSafetyPolicy

        config = Mock()
        config.TELEGRAM_USER_ID = 123456789
        config.ENABLE_MCP = False
        config.DATA_DIR = Path("data/test")
        config.WORKSPACE_DIR = Path("data/test/workspace")
        config.MEDIA_DIR = Path("data/test/workspace/media")

        memory = Mock()
        memory.get_current_session_id.return_value = 1

        core_bot = CoreBot(
            config=config,
            db=Mock(),
            embedding_client=Mock(),
            reranker_client=Mock(),
            memory=memory,
            scheduler=Mock(),
            llm_client=Mock(),
        )

        owner = Mock()
        owner.core_bot = core_bot
        owner.telegram_bot = Mock()
        owner.telegram_bot.send_message = AsyncMock()
        owner.file_service = Mock()
        owner._preview_text = lambda text, max_length=120: str(text)[:max_length]

        shell_tool = Mock()
        shell_tool.execute = AsyncMock(return_value="dangerous command completed")
        approval_service = ApprovalService()
        pending_holder = {"request": None}
        approval_service.set_state_listener(
            lambda request: pending_holder.__setitem__("request", request)
        )

        commands = TelegramCommands(
            core_bot=core_bot,
            access_guard=Mock(reject_unauthorized=AsyncMock(return_value=False)),
            approval_service=approval_service,
            get_telegram_bot=lambda: owner.telegram_bot,
            preview_text=owner._preview_text,
            format_exception_for_user=str,
        )
        core_bot.initialize_telegram_runtime(
            owner,
            approval_delegate=commands,
            preview_text=owner._preview_text,
        )
        core_bot.tool_runtime_state.safety_policy = ToolSafetyPolicy(config)
        core_bot.tool_runtime_state.registry_service.register_named(
            "execute_shell_command", shell_tool
        )

        execution_task = asyncio.create_task(
            core_bot.execute_tool(
                "execute_shell_command", json.dumps({"command": "rm /etc/passwd"})
            )
        )

        await asyncio.sleep(0)

        assert pending_holder["request"] is not None
        assert pending_holder["request"].tool_name == "execute_shell_command"
        shell_tool.execute.assert_not_awaited()

        update = Mock()
        update.effective_user = Mock()
        update.effective_user.id = 123456789
        update.message = Mock()
        update.message.reply_text = AsyncMock()
        context = Mock()

        await commands.handle_approve(update, context)
        result = await execution_task
        await asyncio.sleep(0)

        assert result["result"] == "dangerous command completed"
        shell_tool.execute.assert_awaited_once_with(command="rm /etc/passwd")
        update.message.reply_text.assert_not_awaited()
        assert pending_holder["request"] is None

        sent_texts = [
            call.kwargs["text"]
            for call in owner.telegram_bot.send_message.await_args_list
        ]
        assert any("DANGEROUS ACTION DETECTED" in text for text in sent_texts)
        assert any("Approved action finished" in text for text in sent_texts)
        assert not any(
            "Approved action is now executing" in text for text in sent_texts
        )

    @pytest.mark.asyncio
    async def test_handle_message_aborts_pending_approval_on_regular_message(self):
        """A non-/approve message should abort the pending dangerous action."""
        from adapter.telegram.controller import TelegramController
        from adapter.telegram.messages import TelegramMessages
        from core.approval import ApprovalService, PendingApprovalRequest

        handler = Mock(spec=TelegramController)
        handler.config = Mock()
        handler.config.TELEGRAM_USER_ID = 123456789
        handler.core_bot = Mock()
        handler.core_bot.config = handler.config
        handler.core_bot.process_message = AsyncMock()
        approval_service = ApprovalService()
        handler.messages = TelegramMessages(
            core_bot=handler.core_bot,
            access_guard=Mock(
                reject_unauthorized=AsyncMock(return_value=False),
            ),
            approval_service=approval_service,
            files=Mock(),
            response_sender=Mock(),
            preview_text=TelegramController._preview_text,
            format_exception_for_user=TelegramController._format_exception_for_user,
            intermediate_callback=AsyncMock(),
        )
        handler.handle_message = TelegramController.handle_message.__get__(
            handler, Mock
        )

        loop = asyncio.get_running_loop()
        pending_request = PendingApprovalRequest(
            tool_name="execute_shell_command",
            arguments={"command": "rm /etc/passwd"},
            reason="shell_threat:data_loss",
            future=loop.create_future(),
            created_at=loop.time(),
        )
        approval_service._update_pending_request(pending_request)

        update = Mock()
        update.effective_user = Mock()
        update.effective_user.id = 123456789
        update.effective_chat = Mock()
        update.effective_chat.id = 123456789
        update.message = Mock()
        update.message.text = "继续"
        update.message.reply_text = AsyncMock()

        context = Mock()
        context.bot = Mock()
        context.bot.send_chat_action = AsyncMock()

        await handler.handle_message(update, context)

        assert pending_request.future.done() is True
        assert pending_request.future.result() is False
        handler.core_bot.process_message.assert_not_called()
        update.message.reply_text.assert_awaited_once_with("❌ Pending action aborted.")


class TestPathSafetyApproval:
    """Test unified path safety approval for builtin tools."""

    @pytest.fixture
    def safety_policy(self, tmp_path):
        """Create the shared tool safety policy."""
        from core.tools import ToolSafetyPolicy

        config = Mock()
        config.WORKSPACE_DIR = tmp_path
        config.MEDIA_DIR = tmp_path / "media"
        return ToolSafetyPolicy(config)

    def test_grep_search_path_with_dotdot_inside_workspace_is_allowed(
        self, safety_policy
    ):
        """Normalized .. paths staying in workspace should not require approval."""
        dangerous, reason = safety_policy.is_dangerous_action(
            "grep_search",
            {"pattern": "todo", "path": "src/../src"},
        )

        assert not dangerous
        assert reason == ""

    def test_grep_search_parent_traversal_outside_workspace_requires_approval(
        self, safety_policy
    ):
        """Relative traversal escaping workspace should require approval."""
        dangerous, reason = safety_policy.is_dangerous_action(
            "grep_search",
            {"pattern": "todo", "path": "../outside"},
        )

        assert dangerous
        assert reason == "file_outside_workspace"

    def test_glob_search_home_expansion_requires_approval(self, safety_policy):
        """Home-expanded paths should be checked against the same boundary rules."""
        dangerous, reason = safety_policy.is_dangerous_action(
            "glob_search",
            {"pattern": "*.py", "path": "~"},
        )

        assert dangerous
        assert reason == "file_outside_workspace"

    def test_glob_search_without_explicit_path_stays_allowed(self, safety_policy):
        """Omitted search root should default to workspace and stay non-dangerous."""
        dangerous, reason = safety_policy.is_dangerous_action(
            "glob_search",
            {"pattern": "*.py"},
        )

        assert not dangerous
        assert reason == ""

    def test_shell_command_parent_traversal_requires_approval(self, safety_policy):
        """Shell commands referencing explicit outside-workspace paths should require approval."""
        dangerous, reason = safety_policy.is_dangerous_action(
            "execute_shell_command",
            {"command": "cat ../secret.txt"},
        )

        assert dangerous
        assert reason == "shell_threat:outside_workspace_path"

    def test_shell_command_workspace_relative_path_stays_allowed(self, safety_policy):
        """Shell commands using in-workspace relative paths should remain allowed."""
        dangerous, reason = safety_policy.is_dangerous_action(
            "execute_shell_command",
            {"command": "cat src/file.txt"},
        )

        assert not dangerous
        assert reason == ""

    def test_shell_command_outside_cwd_requires_approval(self, safety_policy):
        """Shell cwd outside allowed directories should also require approval."""
        dangerous, reason = safety_policy.is_dangerous_action(
            "execute_shell_command",
            {"command": "echo hi", "cwd": "../outside"},
        )

        assert dangerous
        assert reason == "file_outside_workspace"


class TestSplitMessageIntoSegments:
    """Test Telegram formatter message segmentation."""

    @pytest.fixture
    def formatter(self):
        """Create a formatter for Telegram message splitting tests."""
        from adapter.telegram.formatter import TelegramResponseFormatter

        return TelegramResponseFormatter()

    def test_short_message_no_split(self, formatter):
        """Test that short messages are not split"""
        text = "This is a short message"
        segments = formatter.split_message_into_segments(text)

        assert len(segments) == 1
        assert segments[0] == text

    def test_multiple_paragraphs_split_even_when_short(self, formatter):
        """Test that multi-paragraph messages are split even if short"""
        text = "Paragraph 1.\n\nParagraph 2.\n\nParagraph 3."

        segments = formatter.split_message_into_segments(text)

        assert segments == ["Paragraph 1.", "Paragraph 2.", "Paragraph 3."]

    def test_single_newlines_split_even_when_short(self, formatter):
        """Single line breaks should also create separate Telegram segments."""
        text = "Line 1\nLine 2\nLine 3"

        segments = formatter.split_message_into_segments(text)

        assert segments == ["Line 1", "Line 2", "Line 3"]

    def test_consecutive_list_items_stay_grouped(self, formatter):
        """List items should stay together instead of being split per line."""
        text = "Intro\n- first item\n- second item\nAfter"

        segments = formatter.split_message_into_segments(text)

        assert segments == ["Intro", "- first item\n- second item", "After"]

    def test_message_split_at_paragraphs(self, formatter):
        """Test that messages are split at paragraph boundaries"""
        # Create a message with multiple paragraphs
        paragraphs = [f"Paragraph {i} with some content." for i in range(5)]
        text = "\n\n".join(paragraphs)

        segments = formatter.split_message_into_segments(text, max_length=100)

        # Should be split into multiple segments
        assert len(segments) > 1
        # Each segment should not exceed max_length
        for segment in segments:
            assert len(segment) <= 100

    def test_code_blocks_not_split(self, formatter):
        """Test that code blocks (<pre>) are never split"""
        text = "Some text\n\n<pre>\ncode line 1\ncode line 2\ncode line 3\n</pre>\n\nMore text"

        segments = formatter.split_message_into_segments(text, max_length=50)

        # Code block should remain intact in one segment
        for segment in segments:
            if "<pre>" in segment:
                assert "</pre>" in segment
                # Should contain all lines
                assert "code line 1" in segment
                assert "code line 2" in segment
                assert "code line 3" in segment

    def test_text_around_code_blocks_still_splits_normally(self, formatter):
        """Text around code blocks should still be segmented, while code stays intact."""
        text = "Intro paragraph.\n\n<pre>print('hi')</pre>\n\nOutro paragraph."

        segments = formatter.split_message_into_segments(text, max_length=100)

        assert segments == [
            "Intro paragraph.",
            "<pre>print('hi')</pre>",
            "Outro paragraph.",
        ]

    def test_multiple_code_blocks_with_text_between_keep_original_batching(
        self, formatter
    ):
        """Each code block should remain atomic while surrounding text stays independently segmented."""
        text = (
            "First paragraph.\n\n"
            "<pre>first()</pre>\n\n"
            "Middle paragraph.\n\n"
            "<pre>second()</pre>\n\n"
            "Last paragraph."
        )

        segments = formatter.split_message_into_segments(text, max_length=100)

        assert segments == [
            "First paragraph.",
            "<pre>first()</pre>",
            "Middle paragraph.",
            "<pre>second()</pre>",
            "Last paragraph.",
        ]

    def test_blockquote_not_split(self, formatter):
        """Test that blockquotes are never split"""
        text = "Introduction\n\n<blockquote>Citation content here</blockquote>\n\nConclusion"

        segments = formatter.split_message_into_segments(text, max_length=30)

        # Blockquote should remain intact
        for segment in segments:
            if "<blockquote>" in segment:
                assert "</blockquote>" in segment
                assert "Citation content here" in segment

    def test_multiple_code_blocks(self, formatter):
        """Test handling multiple code blocks - verify both blocks remain intact"""
        text = (
            "Text before\n\n"
            "<pre>First code block</pre>\n\n"
            "Middle text\n\n"
            "<pre>Second code block</pre>\n\n"
            "Text after"
        )

        # Use a larger max_length to ensure everything fits in fewer segments
        segments = formatter.split_message_into_segments(text, max_length=500)

        # Combine all segments to check overall content
        all_content = "\n".join(segments)

        # Both code blocks should be intact (complete with opening and closing tags)
        assert "<pre>First code block</pre>" in all_content
        assert "<pre>Second code block</pre>" in all_content

        # Verify the blocks are not split across segments improperly
        for seg in segments:
            # If a segment contains <pre>, it should also contain </pre>
            if "<pre>" in seg:
                assert (
                    "</pre>" in seg
                ), f"Code block split incorrectly in segment: {seg}"

    def test_empty_segments_filtered(self, formatter):
        """Test that empty segments are filtered out"""
        text = "Paragraph 1\n\n\n\nParagraph 2"  # Multiple newlines

        segments = formatter.split_message_into_segments(text)

        # No empty segments
        for segment in segments:
            assert segment.strip()

    def test_no_empty_lines_in_segments(self, formatter):
        """Test that segments don't contain empty lines at start/end"""
        text = "Paragraph 1\n\n\n\nParagraph 2"

        segments = formatter.split_message_into_segments(text)

        # All segments should be non-empty
        assert len(segments) > 0
        for segment in segments:
            assert len(segment) > 0  # Not empty
            assert segment.strip()  # Not just whitespace
            # No leading/trailing empty paragraphs (double newlines at boundaries)
            assert not segment.startswith("\n\n")
            assert not segment.endswith("\n\n")

    def test_only_whitespace_filtered(self, formatter):
        """Test that whitespace-only content is filtered"""
        text = "   \n\n   \n\nActual content\n\n   "

        segments = formatter.split_message_into_segments(text)

        # Should only contain the actual content
        assert len(segments) >= 1
        assert any("Actual content" in seg for seg in segments)
        # No segment should be only whitespace
        for segment in segments:
            assert not segment.isspace() or len(segment) == 0
            if len(segment) > 0:
                assert segment.strip()

    def test_long_html_segment_keeps_tags_balanced(self, formatter):
        """Long formatted text should be split without breaking HTML tags."""
        text = "<b>" + ("word " * 30).strip() + "</b>"

        segments = formatter.split_message_into_segments(text, max_length=40)

        assert len(segments) > 1
        for segment in segments:
            assert len(segment) <= 40
            assert segment.startswith("<b>")
            assert segment.endswith("</b>")


# Run tests if executed directly
if __name__ == "__main__":
    pytest.main([__file__, "-v"])
