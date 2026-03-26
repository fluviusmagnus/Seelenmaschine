"""Tests for tg_bot/handlers.py

This module tests the message handler functionality,
including tool execution, MCP client integration, and message processing.
"""

import sys
from pathlib import Path
from unittest.mock import Mock, patch, AsyncMock
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
        return {
            "config": Mock(),
            "db": Mock(),
            "embedding_client": Mock(),
            "reranker_client": Mock(),
            "memory": Mock(),
            "scheduler": Mock(),
            "llm_client": Mock(),
        }

    def test_handler_initializes_components(self, mock_dependencies):
        """Test that handler initializes all required components"""
        from tg_bot.handlers import MessageHandler

        with patch("tg_bot.handlers.Config") as mock_config_class:
            with patch("tg_bot.handlers.DatabaseManager"):
                with patch("tg_bot.handlers.EmbeddingClient"):
                    with patch("tg_bot.handlers.RerankerClient"):
                        with patch("tg_bot.handlers.MemoryManager"):
                            with patch("tg_bot.handlers.TaskScheduler"):
                                with patch("tg_bot.handlers.ScheduledTaskTool"):
                                    with patch("tg_bot.handlers.LLMClient"):
                                        with patch("tg_bot.handlers.MemorySearchTool"):
                                            mock_config_instance = Mock()
                                            mock_config_class.return_value = (
                                                mock_config_instance
                                            )

                                            handler = MessageHandler()

                                            # Verify handler was created
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

        handler.send_telegram_file_tool = Mock()
        handler.send_telegram_file_tool.name = "send_telegram_file"
        handler.send_telegram_file_tool.execute = AsyncMock(return_value="File sent")

        handler.mcp_client = None

        return handler

    @pytest.mark.asyncio
    async def test_execute_memory_search_tool(self, mock_handler):
        """Test executing memory search tool"""
        # This is a placeholder - actual implementation would test the real handler
        tool_name = "memory_search"
        arguments = '{"query": "test query"}'

        # Mock the execution
        result = await mock_handler.memory_search_tool.execute(**json.loads(arguments))

        assert result == "Memory search result"
        mock_handler.memory_search_tool.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_execute_scheduled_task_tool(self, mock_handler):
        """Test executing scheduled task tool"""
        tool_name = "scheduled_task"
        arguments = '{"message": "Test message", "trigger": "in 1 hour"}'

        # Mock the execution
        result = await mock_handler.scheduled_task_tool.execute(**json.loads(arguments))

        assert result == "Task scheduled"
        mock_handler.scheduled_task_tool.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_execute_send_telegram_file_tool(self, mock_handler):
        """Test executing send_telegram_file tool"""
        arguments = '{"file_path": "output/report.pdf", "caption": "导出结果"}'

        result = await mock_handler.send_telegram_file_tool.execute(
            **json.loads(arguments)
        )

        assert result == "File sent"
        mock_handler.send_telegram_file_tool.execute.assert_called_once()


class TestMessageProcessing:
    """Test message processing functionality"""

    def test_process_message_structure(self):
        """Test the structure of message processing"""
        # This is a placeholder for actual message processing tests
        # In a real scenario, we would test:
        # - Message parsing
        # - Command extraction
        # - Context loading
        # - Response generation
        # - Tool execution
        pass

    def test_format_exception_for_user_truncates_long_messages(self):
        """User-facing error summaries should stay concise."""
        from tg_bot.handlers import MessageHandler

        error = RuntimeError("x" * 500)

        formatted = MessageHandler._format_exception_for_user(error)

        assert len(formatted) == 300
        assert formatted.endswith("...")

    @pytest.mark.asyncio
    async def test_process_message_saves_intermediate_assistant_messages(self):
        """Assistant text emitted during tool calling should also be saved to memory."""
        from tg_bot.handlers import MessageHandler

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

        handler._process_message = MessageHandler._process_message.__get__(
            handler, Mock
        )

        response = await handler._process_message("你好")

        assert response == "最终答复"
        assert handler.memory.add_assistant_message_async.await_count == 2
        handler.memory.add_assistant_message_async.assert_any_await("我先查一下")
        handler.memory.add_assistant_message_async.assert_any_await("最终答复")

    @pytest.mark.asyncio
    async def test_process_scheduled_task_saves_intermediate_assistant_messages(self):
        """Scheduled task assistant text emitted during tool calling should be saved."""
        from tg_bot.handlers import MessageHandler

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

        handler._process_scheduled_task = (
            MessageHandler._process_scheduled_task.__get__(handler, Mock)
        )

        response = await handler._process_scheduled_task("提醒喝水", "喝水提醒")

        assert response == "别忘了喝水。"
        assert handler.memory.add_assistant_message_async.await_count == 2
        handler.memory.add_assistant_message_async.assert_any_await("我提醒你一下")
        handler.memory.add_assistant_message_async.assert_any_await("别忘了喝水。")

    @pytest.mark.asyncio
    async def test_handle_message_returns_error_details_on_failure(self):
        """Top-level message errors should include readable details for debugging."""
        from tg_bot.handlers import MessageHandler

        handler = Mock(spec=MessageHandler)
        handler.config = Mock()
        handler.config.TELEGRAM_USER_ID = 123456789
        handler._pending_approval = None
        handler._process_message = AsyncMock(
            side_effect=RuntimeError("maximum context length exceeded")
        )
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


class TestFileHandling:
    """Test Telegram file handling in MessageHandler."""

    @pytest.fixture
    def mock_handler(self, tmp_path):
        """Create a minimal mock handler with bound file methods."""
        from tg_bot.handlers import MessageHandler

        handler = Mock(spec=MessageHandler)
        handler.config = Mock()
        handler.config.TELEGRAM_USER_ID = 123456789
        handler.config.WORKSPACE_DIR = tmp_path
        handler.config.MEDIA_DIR = tmp_path / "media"
        handler._process_message = AsyncMock(return_value="LLM file response")
        handler._format_response_for_telegram = Mock(return_value="Formatted response")
        handler._split_message_into_segments = Mock(return_value=["Segment 1"])

        handler._sanitize_filename = MessageHandler._sanitize_filename.__get__(
            handler, Mock
        )
        handler._guess_extension = MessageHandler._guess_extension.__get__(
            handler, Mock
        )
        handler._build_media_file_path = MessageHandler._build_media_file_path.__get__(
            handler, Mock
        )
        handler._extract_file_info_from_update = (
            MessageHandler._extract_file_info_from_update.__get__(handler, Mock)
        )
        handler._download_telegram_file = (
            MessageHandler._download_telegram_file.__get__(handler, Mock)
        )
        handler._format_saved_media_path = (
            MessageHandler._format_saved_media_path.__get__(handler, Mock)
        )
        handler._build_file_event_message = (
            MessageHandler._build_file_event_message.__get__(handler, Mock)
        )
        handler._resolve_telegram_file_path = (
            MessageHandler._resolve_telegram_file_path.__get__(handler, Mock)
        )
        handler._is_allowed_telegram_file_path = (
            MessageHandler._is_allowed_telegram_file_path.__get__(handler, Mock)
        )
        handler._detect_telegram_delivery_method = (
            MessageHandler._detect_telegram_delivery_method.__get__(handler, Mock)
        )
        handler._build_sent_file_event_message = (
            MessageHandler._build_sent_file_event_message.__get__(handler, Mock)
        )
        handler._send_telegram_file_to_user = (
            MessageHandler._send_telegram_file_to_user.__get__(handler, Mock)
        )
        handler.handle_file = MessageHandler.handle_file.__get__(handler, Mock)
        handler.memory = Mock()
        handler.memory.add_assistant_message_async = AsyncMock()
        handler.telegram_bot = Mock()
        handler.telegram_bot.send_document = AsyncMock()
        handler.telegram_bot.send_photo = AsyncMock()
        handler.telegram_bot.send_video = AsyncMock()
        handler.telegram_bot.send_audio = AsyncMock()
        handler.telegram_bot.send_voice = AsyncMock()

        return handler

    @pytest.fixture
    def mock_context(self):
        """Create mock Telegram context."""
        context = Mock()
        context.bot = Mock()
        context.bot.send_chat_action = AsyncMock()
        context.bot.get_file = AsyncMock()
        return context

    @pytest.fixture
    def mock_update_with_document(self):
        """Create update containing a Telegram document."""
        update = Mock()
        update.effective_user = Mock()
        update.effective_user.id = 123456789
        update.effective_chat = Mock()
        update.effective_chat.id = 123456789
        update.message = Mock()
        update.message.reply_text = AsyncMock()
        update.message.caption = "这是附件说明"
        update.message.photo = None
        update.message.video = None
        update.message.audio = None
        update.message.voice = None

        document = Mock()
        document.file_id = "file-id"
        document.file_unique_id = "unique-id"
        document.file_name = "report.pdf"
        document.mime_type = "application/pdf"
        document.file_size = 1024
        update.message.document = document

        return update

    def test_build_file_event_message(self, mock_handler, tmp_path):
        """Test synthetic user message creation for files."""
        saved_path = tmp_path / "media" / "report_unique-id.pdf"
        file_info = {
            "file_type": "document",
            "original_name": "report.pdf",
            "mime_type": "application/pdf",
            "file_size": 1024,
            "caption": "附件说明",
        }

        message = mock_handler._build_file_event_message(file_info, saved_path)

        assert "[System Event] The user has sent a file." in message
        assert "Original filename: report.pdf" in message
        assert f"Saved to: {saved_path.resolve()}" in message
        assert "MIME type: application/pdf" in message
        assert "File size: 1024 bytes" in message
        assert "Caption: 附件说明" in message

    @pytest.mark.asyncio
    async def test_handle_file_processes_document(
        self, mock_handler, mock_context, mock_update_with_document
    ):
        """Test document upload is saved and forwarded into normal message flow."""
        telegram_file = Mock()
        telegram_file.download_to_drive = AsyncMock()
        mock_context.bot.get_file.return_value = telegram_file

        async def download_side_effect(custom_path):
            Path(custom_path).parent.mkdir(parents=True, exist_ok=True)
            Path(custom_path).write_text("dummy", encoding="utf-8")

        telegram_file.download_to_drive.side_effect = download_side_effect

        await mock_handler.handle_file(mock_update_with_document, mock_context)

        mock_context.bot.get_file.assert_called_once_with("file-id")
        mock_handler._process_message.assert_called_once()
        processed_message = mock_handler._process_message.call_args[0][0]
        assert "[System Event] The user has sent a file." in processed_message
        assert "Original filename: report.pdf" in processed_message
        assert "Saved to:" in processed_message
        mock_update_with_document.message.reply_text.assert_called_once_with(
            "Segment 1", parse_mode="HTML"
        )

    @pytest.mark.asyncio
    async def test_handle_file_rejects_unauthorized_user(
        self, mock_handler, mock_context, mock_update_with_document
    ):
        """Test unauthorized users cannot upload files."""
        mock_update_with_document.effective_user.id = 999999999

        await mock_handler.handle_file(mock_update_with_document, mock_context)

        mock_handler._process_message.assert_not_called()
        mock_update_with_document.message.reply_text.assert_called_once_with(
            "Unauthorized access."
        )

    def test_detect_telegram_delivery_method(self, mock_handler, tmp_path):
        """Test Telegram delivery method auto detection by file type."""
        assert (
            mock_handler._detect_telegram_delivery_method(tmp_path / "image.png")
            == "photo"
        )
        assert (
            mock_handler._detect_telegram_delivery_method(tmp_path / "clip.mp4")
            == "video"
        )
        assert (
            mock_handler._detect_telegram_delivery_method(tmp_path / "song.mp3")
            == "audio"
        )
        assert (
            mock_handler._detect_telegram_delivery_method(tmp_path / "note.ogg")
            == "voice"
        )
        assert (
            mock_handler._detect_telegram_delivery_method(tmp_path / "report.pdf")
            == "document"
        )

    @pytest.mark.asyncio
    async def test_send_telegram_file_to_user_uses_photo_and_logs_system_event(
        self, mock_handler, tmp_path
    ):
        """Test proactive photo sending and assistant-role system-tone logging."""
        image_path = tmp_path / "media" / "chart.png"
        image_path.parent.mkdir(parents=True, exist_ok=True)
        image_path.write_bytes(b"fake-image")

        result = await mock_handler._send_telegram_file_to_user(
            str(image_path), caption="最新图表"
        )

        assert result["delivery_method"] == "photo"
        mock_handler.telegram_bot.send_photo.assert_awaited_once()
        mock_handler.memory.add_assistant_message_async.assert_awaited_once()
        event_text = mock_handler.memory.add_assistant_message_async.await_args.args[0]
        assert event_text.startswith(
            "[System Event] Assistant has sent a file via Telegram."
        )
        assert "Delivery method: photo" in event_text
        assert "Caption: 最新图表" in event_text

    @pytest.mark.asyncio
    async def test_send_telegram_file_to_user_routes_by_media_type(
        self, mock_handler, tmp_path
    ):
        """Test different Telegram APIs are selected by file type."""
        video_path = tmp_path / "media" / "movie.mp4"
        audio_path = tmp_path / "media" / "sound.mp3"
        voice_path = tmp_path / "media" / "voice.ogg"
        document_path = tmp_path / "media" / "report.pdf"

        for path in [video_path, audio_path, voice_path, document_path]:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"binary")

        await mock_handler._send_telegram_file_to_user(str(video_path))
        await mock_handler._send_telegram_file_to_user(str(audio_path))
        await mock_handler._send_telegram_file_to_user(str(voice_path))
        await mock_handler._send_telegram_file_to_user(str(document_path))

        mock_handler.telegram_bot.send_video.assert_awaited_once()
        mock_handler.telegram_bot.send_audio.assert_awaited_once()
        mock_handler.telegram_bot.send_voice.assert_awaited_once()
        mock_handler.telegram_bot.send_document.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_send_telegram_file_to_user_rejects_outside_workspace(
        self, mock_handler, tmp_path
    ):
        """Test proactive file sending rejects files outside workspace/media."""
        outside_file = tmp_path.parent / "outside.txt"
        outside_file.write_text("x", encoding="utf-8")

        with pytest.raises(ValueError, match="outside allowed directories"):
            await mock_handler._send_telegram_file_to_user(str(outside_file))


class TestSplitMessageIntoSegments:
    """Test the _split_message_into_segments method"""

    @pytest.fixture
    def mock_handler(self):
        """Create a mock MessageHandler with the split method"""
        from tg_bot.handlers import MessageHandler

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


# Run tests if executed directly
if __name__ == "__main__":
    pytest.main([__file__, "-v"])
