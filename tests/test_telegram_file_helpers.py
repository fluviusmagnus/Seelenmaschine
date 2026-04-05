import sys
from pathlib import Path
from types import SimpleNamespace
import asyncio
from unittest.mock import AsyncMock, Mock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from adapter.telegram.files import TelegramFiles
from adapter.telegram.formatter import TelegramResponseFormatter
from adapter.telegram.delivery import TelegramAccessGuard, TelegramResponseSender
from adapter.telegram.messages import TelegramMessages
from core.file_delivery_service import FileDeliveryService


@pytest.fixture
def config(tmp_path):
    return SimpleNamespace(
        TELEGRAM_USER_ID=123456789,
        WORKSPACE_DIR=tmp_path,
        MEDIA_DIR=tmp_path / "media",
        DEBUG_MODE=False,
    )


@pytest.fixture
def memory():
    memory = Mock()
    memory.add_assistant_message_async = AsyncMock()
    return memory


@pytest.fixture
def files_helper(config, memory):
    return TelegramFiles(config=config)


@pytest.fixture
def message_handler(config, memory):
    handler = Mock()
    handler.core_bot = Mock()
    handler.core_bot.config = config
    handler.core_bot.memory = memory
    handler.core_bot.process_message = AsyncMock(return_value="LLM file response")
    handler.core_bot.process_scheduled_task = AsyncMock(return_value="LLM scheduled")
    handler.core_bot.get_processing_lock = Mock(return_value=asyncio.Lock())
    handler.core_bot.run_post_response_summary_check = AsyncMock(return_value=None)
    handler._send_intermediate_response = AsyncMock()
    handler._preview_text = Mock(
        side_effect=lambda text, max_length=120: text[:max_length]
    )
    handler._format_exception_for_user = Mock(side_effect=str)
    return handler


@pytest.fixture
def messages_helper(message_handler):
    return TelegramMessages(
        core_bot=message_handler.core_bot,
        access_guard=TelegramAccessGuard(message_handler.core_bot.config),
        approval_service=None,
        files=TelegramFiles(
            config=message_handler.core_bot.config,
        ),
        response_sender=TelegramResponseSender(
            config=message_handler.core_bot.config,
            formatter=TelegramResponseFormatter(),
        ),
        preview_text=message_handler._preview_text,
        format_exception_for_user=message_handler._format_exception_for_user,
        intermediate_callback=message_handler._send_intermediate_response,
    )


@pytest.fixture
def mock_context():
    context = Mock()
    context.bot = Mock()
    context.bot.send_chat_action = AsyncMock()
    context.bot.get_file = AsyncMock()
    return context


@pytest.fixture
def mock_update_with_document():
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


class TestTelegramMessages:
    def test_build_received_file_event_message(self, files_helper, config):
        saved_path = config.MEDIA_DIR / "report_unique-id.pdf"
        file_info = {
            "file_type": "document",
            "original_name": "report.pdf",
            "mime_type": "application/pdf",
            "file_size": 1024,
            "caption": "附件说明",
        }

        message = files_helper.build_received_file_event_message(file_info, saved_path)

        assert "[File Event]" in message
        assert "The user has sent a file." in message
        assert "Original filename: report.pdf" in message
        assert f"Saved to: {saved_path.resolve()}" in message
        assert "MIME type: application/pdf" in message
        assert "File size: 1024 bytes" in message
        assert "Caption: 附件说明" in message

    @pytest.mark.asyncio
    async def test_handle_file_processes_document(
        self, messages_helper, message_handler, mock_context, mock_update_with_document
    ):
        telegram_file = Mock()
        telegram_file.download_to_drive = AsyncMock()
        mock_context.bot.get_file.return_value = telegram_file

        async def download_side_effect(custom_path):
            Path(custom_path).parent.mkdir(parents=True, exist_ok=True)
            Path(custom_path).write_text("dummy", encoding="utf-8")

        telegram_file.download_to_drive.side_effect = download_side_effect

        await messages_helper.handle_file(mock_update_with_document, mock_context)

        mock_context.bot.get_file.assert_called_once_with("file-id")
        message_handler.core_bot.process_message.assert_awaited_once()
        processed_message = message_handler.core_bot.process_message.await_args.args[0]
        process_kwargs = message_handler.core_bot.process_message.await_args.kwargs
        assert "[File Event]" in processed_message
        assert "The user has sent a file." in processed_message
        assert "Original filename: report.pdf" in processed_message
        assert "Saved to:" in processed_message
        assert process_kwargs["message_for_embedding"] == "这是附件说明"
        mock_update_with_document.message.reply_text.assert_called_once_with(
            "LLM file response", parse_mode="HTML"
        )
        message_handler.core_bot.run_post_response_summary_check.assert_awaited_once_with(
            context_label="file reply delivery"
        )

    @pytest.mark.asyncio
    async def test_handle_file_summary_phase_does_not_keep_typing(
        self, messages_helper, message_handler, mock_context, mock_update_with_document
    ):
        telegram_file = Mock()
        telegram_file.download_to_drive = AsyncMock()
        mock_context.bot.get_file.return_value = telegram_file

        async def download_side_effect(custom_path):
            Path(custom_path).parent.mkdir(parents=True, exist_ok=True)
            Path(custom_path).write_text("dummy", encoding="utf-8")

        telegram_file.download_to_drive.side_effect = download_side_effect

        release_summary = asyncio.Event()

        async def _summary_check(**_: object) -> None:
            await release_summary.wait()

        message_handler.core_bot.run_post_response_summary_check = AsyncMock(
            side_effect=_summary_check
        )

        task = asyncio.create_task(
            messages_helper.handle_file(mock_update_with_document, mock_context)
        )
        await asyncio.sleep(0.05)

        mock_update_with_document.message.reply_text.assert_called_once_with(
            "LLM file response", parse_mode="HTML"
        )
        send_count_after_reply = mock_context.bot.send_chat_action.await_count
        await asyncio.sleep(0.2)
        assert mock_context.bot.send_chat_action.await_count == send_count_after_reply

        release_summary.set()
        await task

    @pytest.mark.asyncio
    async def test_process_message_uses_core_bot_entrypoint(
        self, messages_helper, message_handler
    ):
        message_handler.core_bot.process_message = AsyncMock(return_value="reply")
        message_handler._send_intermediate_response = AsyncMock()

        response = await messages_helper.process_message("hello")

        assert response == "reply"
        message_handler.core_bot.process_message.assert_awaited_once_with(
            "hello",
            message_for_embedding=None,
            intermediate_callback=messages_helper.intermediate_callback,
        )

    @pytest.mark.asyncio
    async def test_process_message_passes_embedding_override(
        self, messages_helper, message_handler
    ):
        message_handler.core_bot.process_message = AsyncMock(return_value="reply")

        response = await messages_helper.process_message(
            "hello",
            message_for_embedding="caption text",
        )

        assert response == "reply"
        message_handler.core_bot.process_message.assert_awaited_once_with(
            "hello",
            message_for_embedding="caption text",
            intermediate_callback=messages_helper.intermediate_callback,
        )

    @pytest.mark.asyncio
    async def test_handle_file_rejects_unauthorized_user(
        self, messages_helper, message_handler, mock_context, mock_update_with_document
    ):
        mock_update_with_document.effective_user.id = 999999999

        await messages_helper.handle_file(mock_update_with_document, mock_context)

        message_handler.core_bot.process_message.assert_not_called()
        mock_update_with_document.message.reply_text.assert_called_once_with(
            "Unauthorized access."
        )


class TestTelegramFiles:
    def test_detect_telegram_delivery_method(self, files_helper, config):
        assert (
            files_helper.detect_telegram_delivery_method(
                config.WORKSPACE_DIR / "image.png"
            )
            == "photo"
        )
        assert (
            files_helper.detect_telegram_delivery_method(
                config.WORKSPACE_DIR / "clip.mp4"
            )
            == "video"
        )
        assert (
            files_helper.detect_telegram_delivery_method(
                config.WORKSPACE_DIR / "song.mp3"
            )
            == "audio"
        )
        assert (
            files_helper.detect_telegram_delivery_method(
                config.WORKSPACE_DIR / "note.ogg"
            )
            == "voice"
        )
        assert (
            files_helper.detect_telegram_delivery_method(
                config.WORKSPACE_DIR / "report.pdf"
            )
            == "document"
        )

    @pytest.mark.asyncio
    async def test_send_file_to_user_uses_photo_and_logs_system_event(
        self, files_helper, memory, config
    ):
        image_path = config.MEDIA_DIR / "chart.png"
        image_path.parent.mkdir(parents=True, exist_ok=True)
        image_path.write_bytes(b"fake-image")

        telegram_bot = Mock()
        telegram_bot.send_photo = AsyncMock()
        telegram_bot.send_document = AsyncMock()
        telegram_bot.send_video = AsyncMock()
        telegram_bot.send_audio = AsyncMock()
        telegram_bot.send_voice = AsyncMock()

        service = FileDeliveryService(
            config=config,
            memory=memory,
            telegram_files=files_helper,
        )

        result = await service.send_file_to_user(
            telegram_bot=telegram_bot,
            file_path=str(image_path),
            caption="最新图表",
        )

        assert result["delivery_method"] == "photo"
        telegram_bot.send_photo.assert_awaited_once()
        memory.add_assistant_message_async.assert_awaited_once()
        event_text = memory.add_assistant_message_async.await_args.args[0]
        assert event_text.startswith(
            "[System Event] Assistant has sent a file via Telegram."
        )
        assert "Delivery method: photo" in event_text
        assert "Caption: 最新图表" in event_text

    @pytest.mark.asyncio
    async def test_send_file_to_user_routes_by_media_type(self, files_helper, config):
        service = FileDeliveryService(
            config=config,
            memory=Mock(add_assistant_message_async=AsyncMock()),
            telegram_files=files_helper,
        )
        telegram_bot = Mock()
        telegram_bot.send_photo = AsyncMock()
        telegram_bot.send_document = AsyncMock()
        telegram_bot.send_video = AsyncMock()
        telegram_bot.send_audio = AsyncMock()
        telegram_bot.send_voice = AsyncMock()

        video_path = config.MEDIA_DIR / "movie.mp4"
        audio_path = config.MEDIA_DIR / "sound.mp3"
        voice_path = config.MEDIA_DIR / "voice.ogg"
        document_path = config.MEDIA_DIR / "report.pdf"

        for path in [video_path, audio_path, voice_path, document_path]:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"binary")

        await service.send_file_to_user(
            telegram_bot=telegram_bot, file_path=str(video_path)
        )
        await service.send_file_to_user(
            telegram_bot=telegram_bot, file_path=str(audio_path)
        )
        await service.send_file_to_user(
            telegram_bot=telegram_bot, file_path=str(voice_path)
        )
        await service.send_file_to_user(
            telegram_bot=telegram_bot, file_path=str(document_path)
        )

        telegram_bot.send_video.assert_awaited_once()
        telegram_bot.send_audio.assert_awaited_once()
        telegram_bot.send_voice.assert_awaited_once()
        telegram_bot.send_document.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_send_file_to_user_rejects_outside_workspace(
        self, files_helper, config
    ):
        service = FileDeliveryService(
            config=config,
            memory=Mock(add_assistant_message_async=AsyncMock()),
            telegram_files=files_helper,
        )
        telegram_bot = Mock()
        outside_file = config.WORKSPACE_DIR.parent / "outside.txt"
        outside_file.write_text("x", encoding="utf-8")

        with pytest.raises(ValueError, match="outside allowed directories"):
            await service.send_file_to_user(
                telegram_bot=telegram_bot,
                file_path=str(outside_file),
            )
