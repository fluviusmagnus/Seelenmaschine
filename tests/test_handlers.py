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
        from adapter.telegram.handlers import MessageHandler
        from core.bot import CoreBot

        core_bot = CoreBot(**mock_dependencies)
        handler = MessageHandler(core_bot=core_bot)

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
        core_bot.create_conversation_service(
            memory_search_tool=handler.memory_search_tool,
            mcp_client=handler.mcp_client,
            ensure_mcp_connected=handler._ensure_mcp_connected,
            preview_text=handler._preview_text,
        )
        return core_bot

    @pytest.mark.asyncio
    async def test_process_message_returns_final_text_without_assistant_history(self):
        """Message processing should return the final LLM text and persist it once."""
        from adapter.telegram.handlers import MessageHandler

        handler = Mock(spec=MessageHandler)
        handler.memory = Mock()
        handler.memory.add_user_message_async = AsyncMock(return_value=(1, [0.1, 0.2]))
        handler.memory.get_context_messages = Mock(return_value=[])
        handler.memory.process_user_input_async = AsyncMock(return_value=([], []))
        handler.memory.get_recent_summaries = Mock(return_value=[])
        handler.memory.add_assistant_message_async = AsyncMock(return_value=(2, None))

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
        from adapter.telegram.handlers import MessageHandler

        error = RuntimeError("x" * 500)

        formatted = MessageHandler._format_exception_for_user(error)

        assert len(formatted) == 300
        assert formatted.endswith("...")

    @pytest.mark.asyncio
    async def test_process_message_saves_intermediate_assistant_messages(self):
        """Assistant text emitted during tool calling should also be saved to memory."""
        from adapter.telegram.handlers import MessageHandler

        handler = Mock(spec=MessageHandler)
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
            }
        )

        core_bot = self._build_core_bot_for_conversation(handler)
        response = await core_bot.process_message("你好")

        assert response == "最终答复"
        assert handler.memory.add_assistant_message_async.await_count == 2
        handler.memory.add_assistant_message_async.assert_any_await("我先查一下")
        handler.memory.add_assistant_message_async.assert_any_await("最终答复")

    @pytest.mark.asyncio
    async def test_process_scheduled_task_saves_intermediate_assistant_messages(self):
        """Scheduled task assistant text emitted during tool calling should be saved."""
        from adapter.telegram.handlers import MessageHandler

        handler = Mock(spec=MessageHandler)
        handler.memory = Mock()
        handler.memory.get_context_messages = Mock(return_value=[])
        handler.memory.process_user_input_async = AsyncMock(return_value=([], []))
        handler.memory.get_recent_summaries = Mock(return_value=[])
        handler.memory.add_assistant_message_async = AsyncMock(
            side_effect=[(2, None), (3, None)]
        )

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
            }
        )

        core_bot = self._build_core_bot_for_conversation(handler, scheduled=True)
        response = await core_bot.process_scheduled_task("提醒喝水", "喝水提醒")

        assert response == "别忘了喝水。"
        assert handler.memory.add_assistant_message_async.await_count == 2
        handler.memory.add_assistant_message_async.assert_any_await("我提醒你一下")
        handler.memory.add_assistant_message_async.assert_any_await("别忘了喝水。")

    @pytest.mark.asyncio
    async def test_handle_message_returns_error_details_on_failure(self):
        """Top-level message errors should include readable details for debugging."""
        from adapter.telegram.handlers import MessageHandler

        handler = Mock(spec=MessageHandler)
        handler.config = Mock()
        handler.config.TELEGRAM_USER_ID = 123456789
        handler._pending_approval = None
        handler.core_bot = Mock()
        handler.core_bot.config = handler.config
        handler.core_bot.process_message = AsyncMock(
            side_effect=RuntimeError("maximum context length exceeded")
        )
        handler._send_intermediate_response = AsyncMock()
        handler._format_exception_for_user = MessageHandler._format_exception_for_user
        handler.handle_message = MessageHandler.handle_message.__get__(handler, Mock)

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
    async def test_execute_tool_resumes_dangerous_shell_after_approve(self):
        """Dangerous shell actions should continue executing after /approve."""
        from adapter.telegram.handlers import MessageHandler
        from adapter.telegram.tool_bridge import TelegramToolBridge
        from core.bot import CoreToolHost
        from core.approval import ApprovalService

        handler = Mock(spec=MessageHandler)
        handler.config = Mock()
        handler.config.TELEGRAM_USER_ID = 123456789
        handler.telegram_bot = Mock()
        handler.telegram_bot.send_message = AsyncMock()
        handler._approval_lock = asyncio.Lock()
        handler._pending_approval = None
        handler.mcp_client = None
        handler._mcp_connected = False
        handler._tool_registry = {}

        shell_tool = Mock()
        shell_tool.execute = AsyncMock(return_value="dangerous command completed")
        handler._tool_registry["execute_shell_command"] = shell_tool

        from core.tools import ToolSafetyPolicy

        handler._preview_text = MessageHandler._preview_text
        handler._format_exception_for_user = MessageHandler._format_exception_for_user
        handler._tool_safety_policy = ToolSafetyPolicy(handler.config)
        handler._approval_service = ApprovalService()
        handler._approval_service.set_state_listener(
            lambda request: setattr(handler, "_pending_approval", request)
        )
        handler._tool_bridge = TelegramToolBridge(handler)
        handler._tool_host = CoreToolHost(
            handler,
            get_tool_bridge=lambda: handler._tool_bridge,
        )
        handler.core_bot = Mock()
        handler.core_bot.config = handler.config
        handler.core_bot.tool_runtime_state = None
        handler.core_bot.execute_tool = handler._tool_host.execute_tool
        handler.handle_approve = MessageHandler.handle_approve.__get__(handler, Mock)
        handler._execute_tool = MessageHandler._execute_tool.__get__(handler, Mock)

        execution_task = asyncio.create_task(
            handler._execute_tool(
                "execute_shell_command", json.dumps({"command": "rm /etc/passwd"})
            )
        )

        await asyncio.sleep(0)

        assert handler._pending_approval is not None
        assert handler._pending_approval.tool_name == "execute_shell_command"
        shell_tool.execute.assert_not_awaited()

        update = Mock()
        update.effective_user = Mock()
        update.effective_user.id = 123456789
        update.message = Mock()
        update.message.reply_text = AsyncMock()
        context = Mock()

        await handler.handle_approve(update, context)
        result = await execution_task
        await asyncio.sleep(0)

        assert result == "dangerous command completed"
        shell_tool.execute.assert_awaited_once_with(command="rm /etc/passwd")
        update.message.reply_text.assert_not_awaited()
        assert handler._pending_approval is None

        sent_texts = [
            call.kwargs["text"]
            for call in handler.telegram_bot.send_message.await_args_list
        ]
        assert any("DANGEROUS ACTION DETECTED" in text for text in sent_texts)
        assert any("Approved action finished" in text for text in sent_texts)
        assert not any(
            "Approved action is now executing" in text for text in sent_texts
        )

    @pytest.mark.asyncio
    async def test_handle_message_aborts_pending_approval_on_regular_message(self):
        """A non-/approve message should abort the pending dangerous action."""
        from adapter.telegram.handlers import MessageHandler, PendingApprovalRequest

        handler = Mock(spec=MessageHandler)
        handler.config = Mock()
        handler.config.TELEGRAM_USER_ID = 123456789
        handler.core_bot = Mock()
        handler.core_bot.config = handler.config
        handler.core_bot.process_message = AsyncMock()
        handler.handle_message = MessageHandler.handle_message.__get__(handler, Mock)

        loop = asyncio.get_running_loop()
        handler._pending_approval = PendingApprovalRequest(
            tool_name="execute_shell_command",
            arguments={"command": "rm /etc/passwd"},
            reason="shell_threat:data_loss",
            future=loop.create_future(),
            created_at=loop.time(),
        )

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

        assert handler._pending_approval.future.done() is True
        assert handler._pending_approval.future.result() is False
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
    """Test the _split_message_into_segments method"""

    @pytest.fixture
    def mock_handler(self):
        """Create a mock MessageHandler with the split method"""
        from adapter.telegram.handlers import MessageHandler

        # Create a minimal mock handler
        handler = Mock(spec=MessageHandler)

        # Bind the actual method to the mock
        handler._split_message_into_segments = (
            MessageHandler._split_message_into_segments.__get__(handler, Mock)
        )

        return handler

    def test_short_message_no_split(self, mock_handler):
        """Test that short messages are not split"""
        text = "This is a short message"
        segments = mock_handler._split_message_into_segments(text)

        assert len(segments) == 1
        assert segments[0] == text

    def test_multiple_paragraphs_split_even_when_short(self, mock_handler):
        """Test that multi-paragraph messages are split even if short"""
        text = "Paragraph 1.\n\nParagraph 2.\n\nParagraph 3."

        segments = mock_handler._split_message_into_segments(text)

        assert segments == ["Paragraph 1.", "Paragraph 2.", "Paragraph 3."]

    def test_single_newlines_split_even_when_short(self, mock_handler):
        """Single line breaks should also create separate Telegram segments."""
        text = "Line 1\nLine 2\nLine 3"

        segments = mock_handler._split_message_into_segments(text)

        assert segments == ["Line 1", "Line 2", "Line 3"]

    def test_consecutive_list_items_stay_grouped(self, mock_handler):
        """List items should stay together instead of being split per line."""
        text = "Intro\n- first item\n- second item\nAfter"

        segments = mock_handler._split_message_into_segments(text)

        assert segments == ["Intro", "- first item\n- second item", "After"]

    def test_message_split_at_paragraphs(self, mock_handler):
        """Test that messages are split at paragraph boundaries"""
        # Create a message with multiple paragraphs
        paragraphs = [f"Paragraph {i} with some content." for i in range(5)]
        text = "\n\n".join(paragraphs)

        segments = mock_handler._split_message_into_segments(text, max_length=100)

        # Should be split into multiple segments
        assert len(segments) > 1
        # Each segment should not exceed max_length
        for segment in segments:
            assert len(segment) <= 100

    def test_code_blocks_not_split(self, mock_handler):
        """Test that code blocks (<pre>) are never split"""
        text = "Some text\n\n<pre>\ncode line 1\ncode line 2\ncode line 3\n</pre>\n\nMore text"

        segments = mock_handler._split_message_into_segments(text, max_length=50)

        # Code block should remain intact in one segment
        for segment in segments:
            if "<pre>" in segment:
                assert "</pre>" in segment
                # Should contain all lines
                assert "code line 1" in segment
                assert "code line 2" in segment
                assert "code line 3" in segment

    def test_text_around_code_blocks_still_splits_normally(self, mock_handler):
        """Text around code blocks should still be segmented, while code stays intact."""
        text = "Intro paragraph.\n\n<pre>print('hi')</pre>\n\nOutro paragraph."

        segments = mock_handler._split_message_into_segments(text, max_length=100)

        assert segments == [
            "Intro paragraph.",
            "<pre>print('hi')</pre>",
            "Outro paragraph.",
        ]

    def test_multiple_code_blocks_with_text_between_keep_original_batching(
        self, mock_handler
    ):
        """Each code block should remain atomic while surrounding text stays independently segmented."""
        text = (
            "First paragraph.\n\n"
            "<pre>first()</pre>\n\n"
            "Middle paragraph.\n\n"
            "<pre>second()</pre>\n\n"
            "Last paragraph."
        )

        segments = mock_handler._split_message_into_segments(text, max_length=100)

        assert segments == [
            "First paragraph.",
            "<pre>first()</pre>",
            "Middle paragraph.",
            "<pre>second()</pre>",
            "Last paragraph.",
        ]

    def test_blockquote_not_split(self, mock_handler):
        """Test that blockquotes are never split"""
        text = "Introduction\n\n<blockquote>Citation content here</blockquote>\n\nConclusion"

        segments = mock_handler._split_message_into_segments(text, max_length=30)

        # Blockquote should remain intact
        for segment in segments:
            if "<blockquote>" in segment:
                assert "</blockquote>" in segment
                assert "Citation content here" in segment

    def test_multiple_code_blocks(self, mock_handler):
        """Test handling multiple code blocks - verify both blocks remain intact"""
        text = (
            "Text before\n\n"
            "<pre>First code block</pre>\n\n"
            "Middle text\n\n"
            "<pre>Second code block</pre>\n\n"
            "Text after"
        )

        # Use a larger max_length to ensure everything fits in fewer segments
        segments = mock_handler._split_message_into_segments(text, max_length=500)

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

    def test_empty_segments_filtered(self, mock_handler):
        """Test that empty segments are filtered out"""
        text = "Paragraph 1\n\n\n\nParagraph 2"  # Multiple newlines

        segments = mock_handler._split_message_into_segments(text)

        # No empty segments
        for segment in segments:
            assert segment.strip()

    def test_no_empty_lines_in_segments(self, mock_handler):
        """Test that segments don't contain empty lines at start/end"""
        text = "Paragraph 1\n\n\n\nParagraph 2"

        segments = mock_handler._split_message_into_segments(text)

        # All segments should be non-empty
        assert len(segments) > 0
        for segment in segments:
            assert len(segment) > 0  # Not empty
            assert segment.strip()  # Not just whitespace
            # No leading/trailing empty paragraphs (double newlines at boundaries)
            assert not segment.startswith("\n\n")
            assert not segment.endswith("\n\n")

    def test_only_whitespace_filtered(self, mock_handler):
        """Test that whitespace-only content is filtered"""
        text = "   \n\n   \n\nActual content\n\n   "

        segments = mock_handler._split_message_into_segments(text)

        # Should only contain the actual content
        assert len(segments) >= 1
        assert any("Actual content" in seg for seg in segments)
        # No segment should be only whitespace
        for segment in segments:
            assert not segment.isspace() or len(segment) == 0
            if len(segment) > 0:
                assert segment.strip()

    def test_long_html_segment_keeps_tags_balanced(self, mock_handler):
        """Long formatted text should be split without breaking HTML tags."""
        text = "<b>" + ("word " * 30).strip() + "</b>"

        segments = mock_handler._split_message_into_segments(text, max_length=40)

        assert len(segments) > 1
        for segment in segments:
            assert len(segment) <= 40
            assert segment.startswith("<b>")
            assert segment.endswith("</b>")


# Run tests if executed directly
if __name__ == "__main__":
    pytest.main([__file__, "-v"])
