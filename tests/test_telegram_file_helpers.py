import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from adapter.telegram.files import TelegramFiles
from adapter.telegram.formatter import TelegramResponseFormatter
from adapter.telegram.delivery import TelegramAccessGuard, TelegramResponseSender
from adapter.telegram.controller import TelegramController
from core.file_service import FileDeliveryService


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
def controller(config, memory):
    handler = Mock(spec=TelegramController)
    handler.core_bot = Mock()
    handler.core_bot.config = config
    handler.core_bot.memory = memory
    handler.core_bot.process_message = AsyncMock(return_value="LLM file response")
    handler.core_bot.process_scheduled_task = AsyncMock(return_value="LLM scheduled")
    handler.core_bot.get_processing_lock = Mock(return_value=asyncio.Lock())
    handler.core_bot.run_post_response_summary_check = AsyncMock(return_value=None)
    handler.files = TelegramFiles(config=config)
    handler.response_sender = TelegramResponseSender(
        config=config,
        formatter=TelegramResponseFormatter(),
    )
    handler.access_guard = TelegramAccessGuard(config)
    handler.approval_service = None
    handler._send_intermediate_response = AsyncMock()
    handler._preview_text = Mock(
        side_effect=lambda text, max_length=120: text[:max_length]
    )
    handler._format_exception_for_user = Mock(side_effect=str)
    handler._format_user_error_text = TelegramController._format_user_error_text.__get__(
        handler, Mock
    )
    handler.process_message = TelegramController.process_message.__get__(handler, Mock)
    handler.handle_file = TelegramController.handle_file.__get__(handler, Mock)
    return handler


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


class TestTelegramControllerFiles:
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
        self, controller, mock_context, mock_update_with_document
    ):
        telegram_file = Mock()
        telegram_file.download_to_drive = AsyncMock()
        mock_context.bot.get_file.return_value = telegram_file

        async def download_side_effect(custom_path):
            Path(custom_path).parent.mkdir(parents=True, exist_ok=True)
            Path(custom_path).write_text("dummy", encoding="utf-8")

        telegram_file.download_to_drive.side_effect = download_side_effect

        await controller.handle_file(mock_update_with_document, mock_context)

        mock_context.bot.get_file.assert_called_once_with("file-id")
        controller.core_bot.process_message.assert_awaited_once()
        processed_message = controller.core_bot.process_message.await_args.args[0]
        process_kwargs = controller.core_bot.process_message.await_args.kwargs
        assert "[File Event]" in processed_message
        assert "The user has sent a file." in processed_message
        assert "Original filename: report.pdf" in processed_message
        assert "Saved to:" in processed_message
        assert process_kwargs["message_for_embedding"] == "这是附件说明"
        mock_update_with_document.message.reply_text.assert_called_once_with(
            "LLM file response", parse_mode="HTML"
        )
        controller.core_bot.run_post_response_summary_check.assert_awaited_once_with(
            context_label="file reply delivery"
        )

    @pytest.mark.asyncio
    async def test_handle_file_summary_phase_does_not_keep_typing(
        self, controller, mock_context, mock_update_with_document
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

        controller.core_bot.run_post_response_summary_check = AsyncMock(
            side_effect=_summary_check
        )

        task = asyncio.create_task(
            controller.handle_file(mock_update_with_document, mock_context)
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
    async def test_handle_file_shows_typing_while_waiting_for_processing_lock(
        self, controller, mock_context, mock_update_with_document
    ):
        telegram_file = Mock()
        telegram_file.download_to_drive = AsyncMock()
        mock_context.bot.get_file.return_value = telegram_file

        async def download_side_effect(custom_path):
            Path(custom_path).parent.mkdir(parents=True, exist_ok=True)
            Path(custom_path).write_text("dummy", encoding="utf-8")

        telegram_file.download_to_drive.side_effect = download_side_effect

        shared_lock = asyncio.Lock()
        await shared_lock.acquire()
        controller.core_bot.get_processing_lock = Mock(return_value=shared_lock)

        task = asyncio.create_task(
            controller.handle_file(mock_update_with_document, mock_context)
        )
        await asyncio.sleep(0.05)

        controller.core_bot.process_message.assert_not_awaited()
        assert mock_context.bot.send_chat_action.await_count > 0

        shared_lock.release()
        await task

        controller.core_bot.process_message.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_process_message_uses_core_bot_entrypoint(
        self, controller
    ):
        controller.core_bot.process_message = AsyncMock(return_value="reply")
        controller._send_intermediate_response = AsyncMock()

        response = await controller.process_message("hello")

        assert response == "reply"
        controller.core_bot.process_message.assert_awaited_once_with(
            "hello",
            message_for_embedding=None,
            intermediate_callback=controller._send_intermediate_response,
        )

    @pytest.mark.asyncio
    async def test_process_message_passes_embedding_override(
        self, controller
    ):
        controller.core_bot.process_message = AsyncMock(return_value="reply")

        response = await controller.process_message(
            "hello",
            message_for_embedding="caption text",
        )

        assert response == "reply"
        controller.core_bot.process_message.assert_awaited_once_with(
            "hello",
            message_for_embedding="caption text",
            intermediate_callback=controller._send_intermediate_response,
        )

    @pytest.mark.asyncio
    async def test_handle_file_uses_unified_user_error_text(
        self, controller, mock_context, mock_update_with_document
    ):
        telegram_file = Mock()
        telegram_file.download_to_drive = AsyncMock(side_effect=KeyError("error"))
        mock_context.bot.get_file.return_value = telegram_file

        await controller.handle_file(mock_update_with_document, mock_context)

        sent_text = mock_update_with_document.message.reply_text.await_args.args[0]
        assert sent_text == (
            "Sorry, an error occurred while processing your file.\n\n"
            "Details: error"
        ) or "Sorry, an error occurred while processing your file." in sent_text

    @pytest.mark.asyncio
    async def test_handle_file_rejects_unauthorized_user(
        self, controller, mock_context, mock_update_with_document
    ):
        mock_update_with_document.effective_user.id = 999999999

        await controller.handle_file(mock_update_with_document, mock_context)

        controller.core_bot.process_message.assert_not_called()
        mock_update_with_document.message.reply_text.assert_called_once_with(
            "Unauthorized access."
        )


class TestTelegramFiles:
    @pytest.mark.asyncio
    async def test_handle_file_accepts_explicit_lock_and_summary_hooks(
        self, files_helper, mock_context, mock_update_with_document
    ):
        telegram_file = Mock()
        telegram_file.download_to_drive = AsyncMock()
        mock_context.bot.get_file.return_value = telegram_file

        async def download_side_effect(custom_path):
            Path(custom_path).parent.mkdir(parents=True, exist_ok=True)
            Path(custom_path).write_text("dummy", encoding="utf-8")

        telegram_file.download_to_drive.side_effect = download_side_effect

        process_message = AsyncMock(return_value="LLM file response")
        response_sender = Mock()
        response_sender.send_reply_text = AsyncMock()
        get_processing_lock = Mock(return_value=asyncio.Lock())
        run_summary_check = AsyncMock(return_value=None)

        await files_helper.handle_file(
            update=mock_update_with_document,
            context=mock_context,
            process_message=process_message,
            get_processing_lock=get_processing_lock,
            run_post_response_summary_check=run_summary_check,
            response_sender=response_sender,
            preview_text=lambda text, max_length=120: text[:max_length],
            format_exception_for_user=str,
        )

        get_processing_lock.assert_called_once_with()
        process_message.assert_awaited_once()
        run_summary_check.assert_awaited_once_with(context_label="file reply delivery")
        response_sender.send_reply_text.assert_awaited_once()

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

        service = FileDeliveryService(config=config)

        prepared = service.prepare_file_delivery(
            file_path=str(image_path),
            caption="最新图表",
        )
        result = await files_helper.send_local_file(
            telegram_bot=telegram_bot,
            resolved_path=Path(prepared["resolved_path"]),
            caption="最新图表",
        )
        event_text = service.build_sent_file_event_message(
            Path(prepared["resolved_path"]),
            result,
            "最新图表",
            platform_label="telegram",
        )

        assert result == "photo"
        telegram_bot.send_photo.assert_awaited_once()
        memory.add_assistant_message_async.assert_not_awaited()
        assert event_text.startswith(
            "[System Event] Assistant has sent a file via telegram."
        )
        assert "Delivery method: photo" in event_text
        assert "Caption: 最新图表" in event_text

    @pytest.mark.asyncio
    async def test_send_file_to_user_routes_by_media_type(self, files_helper, config):
        service = FileDeliveryService(config=config)
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

        await files_helper.send_local_file(
            telegram_bot=telegram_bot,
            resolved_path=Path(service.prepare_file_delivery(file_path=str(video_path))["resolved_path"]),
        )
        await files_helper.send_local_file(
            telegram_bot=telegram_bot,
            resolved_path=Path(service.prepare_file_delivery(file_path=str(audio_path))["resolved_path"]),
        )
        await files_helper.send_local_file(
            telegram_bot=telegram_bot,
            resolved_path=Path(service.prepare_file_delivery(file_path=str(voice_path))["resolved_path"]),
        )
        await files_helper.send_local_file(
            telegram_bot=telegram_bot,
            resolved_path=Path(service.prepare_file_delivery(file_path=str(document_path))["resolved_path"]),
        )

        telegram_bot.send_video.assert_awaited_once()
        telegram_bot.send_audio.assert_awaited_once()
        telegram_bot.send_voice.assert_awaited_once()
        telegram_bot.send_document.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_send_file_to_user_rejects_outside_workspace(
        self, files_helper, config
    ):
        service = FileDeliveryService(config=config)
        outside_file = config.WORKSPACE_DIR.parent / "outside.txt"
        outside_file.write_text("x", encoding="utf-8")

        with pytest.raises(ValueError, match="outside allowed directories"):
            service.prepare_file_delivery(
                file_path=str(outside_file),
            )
