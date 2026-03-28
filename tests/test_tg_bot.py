"""Tests for Telegram adapter.

This module contains tests for the Telegram adapter implementation.
Uses pytest-asyncio for async testing and unittest.mock for mocking.
"""

import sys
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import pytest
from telegram import BotCommand, Message, Update, User
from telegram.ext import Application, ContextTypes

# Add project root to path for absolute imports
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


class TestTelegramAdapterInitialization:
    """Test TelegramAdapter initialization."""

    @pytest.fixture
    def mock_config(self):
        """Create a mock Config."""
        config = Mock()
        config.TELEGRAM_BOT_TOKEN = "test_token"
        config.TELEGRAM_USER_ID = 123456789
        config.TELEGRAM_USE_MARKDOWN = True
        return config

    @pytest.fixture
    def mock_message_handler(self):
        """Create a mock MessageHandler."""
        handler = Mock()
        handler.core_bot = Mock()
        handler.core_bot.scheduler = Mock()
        handler.core_bot.scheduler.set_message_callback = Mock()
        handler.core_bot.scheduler.load_default_tasks = Mock()
        handler.core_bot.scheduler.run_forever = AsyncMock()
        handler.core_bot.scheduler.stop = Mock()
        handler._commands = Mock()
        return handler

    @pytest.mark.asyncio
    async def test_adapter_initialization(self, mock_config, mock_message_handler):
        """Test adapter initialization with dependencies."""
        from adapter.telegram.adapter import TelegramAdapter

        with patch("adapter.telegram.adapter.Config", return_value=mock_config):
            adapter = TelegramAdapter(message_handler=mock_message_handler)

            assert adapter.config == mock_config
            assert adapter.message_handler == mock_message_handler
            assert adapter.scheduler == mock_message_handler.core_bot.scheduler
            assert adapter._application is None

    @pytest.mark.asyncio
    async def test_scheduler_callback_registration(
        self, mock_config, mock_message_handler
    ):
        """Test that scheduler message callback is registered."""
        from adapter.telegram.adapter import TelegramAdapter

        with patch("adapter.telegram.adapter.Config", return_value=mock_config):
            adapter = TelegramAdapter(message_handler=mock_message_handler)

            mock_message_handler.core_bot.scheduler.set_message_callback.assert_called_once()
            assert (
                mock_message_handler.core_bot.scheduler.set_message_callback.call_args[
                    0
                ][0]
                == adapter._send_scheduled_message
            )


class TestTelegramAdapterApplication:
    """Test TelegramAdapter application setup."""

    @pytest.fixture
    def mock_config(self):
        """Create a mock Config."""
        config = Mock()
        config.TELEGRAM_BOT_TOKEN = "test_token"
        config.TELEGRAM_USER_ID = 123456789
        config.TELEGRAM_USE_MARKDOWN = True
        return config

    @pytest.fixture
    def mock_message_handler(self):
        """Create a mock MessageHandler."""
        handler = Mock()
        handler.core_bot = Mock()
        handler.core_bot.scheduler = Mock()
        handler.core_bot.scheduler.set_message_callback = Mock()
        handler.core_bot.scheduler.load_default_tasks = Mock()
        handler.core_bot.scheduler.run_forever = AsyncMock()
        handler.core_bot.scheduler.stop = Mock()
        handler.handle_approve = AsyncMock()
        handler.handle_message = AsyncMock()
        handler.handle_file = AsyncMock()
        commands = Mock()
        commands.handle_start = AsyncMock()
        commands.handle_help = AsyncMock()
        commands.handle_new_session = AsyncMock()
        commands.handle_reset_session = AsyncMock()
        handler._commands = commands
        return handler

    @pytest.fixture
    def mock_application(self):
        """Create a mock Application."""
        app = Mock(spec=Application)
        app.bot = Mock()
        app.add_handler = Mock()
        app.post_init = None
        app.post_shutdown = None
        app.run_polling = Mock()
        app.stop = Mock()
        app.running = False
        return app

    def test_create_application(
        self, mock_config, mock_message_handler, mock_application
    ):
        """Test application creation and handler registration."""
        from adapter.telegram.adapter import TelegramAdapter

        with patch("adapter.telegram.adapter.Config", return_value=mock_config):
            with patch("adapter.telegram.adapter.Application.builder") as mock_builder:
                mock_builder_instance = mock_builder.return_value
                mock_builder_instance.token.return_value = mock_builder_instance
                mock_builder_instance.concurrent_updates.return_value = (
                    mock_builder_instance
                )
                mock_builder_instance.build.return_value = mock_application

                adapter = TelegramAdapter(message_handler=mock_message_handler)
                adapter.create_application()

                assert adapter._application == mock_application
                mock_message_handler.set_telegram_bot.assert_called_once_with(
                    mock_application.bot
                )
                mock_builder_instance.token.assert_called_once_with("test_token")
                mock_builder_instance.concurrent_updates.assert_called_once_with(True)
                assert mock_application.add_handler.call_count == 7

    def test_create_application_enables_concurrent_updates(
        self, mock_config, mock_message_handler, mock_application
    ):
        """Adapter should enable concurrent update handling so /approve isn't blocked."""
        from adapter.telegram.adapter import TelegramAdapter

        with patch("adapter.telegram.adapter.Config", return_value=mock_config):
            with patch("adapter.telegram.adapter.Application.builder") as mock_builder:
                mock_builder_instance = mock_builder.return_value
                mock_builder_instance.token.return_value = mock_builder_instance
                mock_builder_instance.concurrent_updates.return_value = (
                    mock_builder_instance
                )
                mock_builder_instance.build.return_value = mock_application

                adapter = TelegramAdapter(message_handler=mock_message_handler)
                adapter.create_application()

                mock_builder_instance.concurrent_updates.assert_called_once_with(True)

    def test_run_uses_valid_allowed_updates(
        self, mock_config, mock_message_handler, mock_application
    ):
        """run_polling should receive Telegram's serializable update types list."""
        from adapter.telegram.adapter import TelegramAdapter

        with patch("adapter.telegram.adapter.Config", return_value=mock_config):
            adapter = TelegramAdapter(message_handler=mock_message_handler)
            adapter._application = mock_application

            adapter.run()

            mock_application.run_polling.assert_called_once_with(
                allowed_updates=Update.ALL_TYPES
            )

    @pytest.mark.asyncio
    async def test_post_init_hook(
        self, mock_config, mock_message_handler, mock_application
    ):
        """Test post_init hook starts scheduler and registers commands."""
        from adapter.telegram.adapter import TelegramAdapter

        with patch("adapter.telegram.adapter.Config", return_value=mock_config):
            with patch("adapter.telegram.adapter.Application.builder") as mock_builder:
                mock_builder_instance = mock_builder.return_value
                mock_builder_instance.token.return_value = mock_builder_instance
                mock_builder_instance.concurrent_updates.return_value = (
                    mock_builder_instance
                )
                mock_builder_instance.build.return_value = mock_application

                adapter = TelegramAdapter(message_handler=mock_message_handler)
                adapter.create_application()

                post_init = mock_application.post_init
                assert post_init is not None

                mock_app = Mock()
                mock_app.bot = Mock()
                mock_app.bot.set_my_commands = AsyncMock()

                await post_init(mock_app)

                mock_app.bot.set_my_commands.assert_called_once()
                commands = mock_app.bot.set_my_commands.call_args[0][0]
                assert len(commands) == 5
                assert all(isinstance(cmd, BotCommand) for cmd in commands)


class TestTelegramAdapterCommands:
    """Test TelegramAdapter command handlers."""

    @pytest.fixture
    def mock_config(self):
        """Create a mock Config."""
        config = Mock()
        config.TELEGRAM_BOT_TOKEN = "test_token"
        config.TELEGRAM_USER_ID = 123456789
        return config

    @pytest.fixture
    def mock_update(self):
        """Create a mock Update."""
        update = Mock(spec=Update)
        update.effective_user = Mock(spec=User)
        update.effective_user.id = 123456789
        update.message = Mock(spec=Message)
        update.message.reply_text = AsyncMock()
        return update

    @pytest.fixture
    def mock_context(self):
        """Create a mock Context."""
        return Mock(spec=ContextTypes.DEFAULT_TYPE)

    @pytest.mark.asyncio
    async def test_cmd_start_authorized(self, mock_config, mock_update, mock_context):
        """Test /start command for authorized user."""
        from adapter.telegram.adapter import TelegramAdapter
        from adapter.telegram.commands import TelegramCommands

        with patch("adapter.telegram.adapter.Config", return_value=mock_config):
            message_handler = Mock()
            message_handler.core_bot = Mock()
            message_handler.core_bot.config = mock_config
            message_handler.core_bot.scheduler = Mock()
            message_handler.core_bot.scheduler.set_message_callback = Mock()
            message_handler._commands = TelegramCommands(message_handler)
            adapter = TelegramAdapter(message_handler=message_handler)
            await adapter._cmd_start(mock_update, mock_context)

            mock_update.message.reply_text.assert_called_once()
            welcome_text = mock_update.message.reply_text.call_args[0][0]
            assert "Welcome to Seelenmaschine" in welcome_text

    @pytest.mark.asyncio
    async def test_cmd_start_unauthorized(self, mock_config, mock_update, mock_context):
        """Test /start command for unauthorized user."""
        from adapter.telegram.adapter import TelegramAdapter
        from adapter.telegram.commands import TelegramCommands

        mock_update.effective_user.id = 999999999

        with patch("adapter.telegram.adapter.Config", return_value=mock_config):
            message_handler = Mock()
            message_handler.core_bot = Mock()
            message_handler.core_bot.config = mock_config
            message_handler.core_bot.scheduler = Mock()
            message_handler.core_bot.scheduler.set_message_callback = Mock()
            message_handler._commands = TelegramCommands(message_handler)
            adapter = TelegramAdapter(message_handler=message_handler)
            await adapter._cmd_start(mock_update, mock_context)

            mock_update.message.reply_text.assert_called_once()
            assert "Unauthorized" in mock_update.message.reply_text.call_args[0][0]

    @pytest.mark.asyncio
    async def test_cmd_help(self, mock_config, mock_update, mock_context):
        """Test /help command."""
        from adapter.telegram.adapter import TelegramAdapter
        from adapter.telegram.commands import TelegramCommands

        with patch("adapter.telegram.adapter.Config", return_value=mock_config):
            message_handler = Mock()
            message_handler.core_bot = Mock()
            message_handler.core_bot.config = mock_config
            message_handler.core_bot.scheduler = Mock()
            message_handler.core_bot.scheduler.set_message_callback = Mock()
            message_handler._commands = TelegramCommands(message_handler)
            adapter = TelegramAdapter(message_handler=message_handler)
            await adapter._cmd_help(mock_update, mock_context)

            mock_update.message.reply_text.assert_called_once()
            help_text = mock_update.message.reply_text.call_args[0][0]
            assert "Available commands" in help_text
            assert "/new" in help_text
            assert "/reset" in help_text


class TestTelegramAdapterScheduledMessages:
    """Test scheduled message sending."""

    @pytest.fixture
    def mock_config(self):
        """Create a mock Config."""
        config = Mock()
        config.TELEGRAM_BOT_TOKEN = "test_token"
        config.TELEGRAM_USER_ID = 123456789
        config.TELEGRAM_USE_MARKDOWN = True
        return config

    @pytest.fixture
    def mock_message_handler(self):
        """Create a mock MessageHandler with formatting and splitting methods."""
        handler = Mock()
        handler.core_bot = Mock()
        handler.core_bot.scheduler = Mock()
        handler.core_bot.scheduler.set_message_callback = Mock()
        handler._format_response_for_telegram = Mock(return_value="Formatted message")
        handler._split_message_into_segments = Mock(return_value=["Segment 1"])
        handler._handle_scheduled_message = AsyncMock(return_value="LLM response")
        handler._commands = Mock()
        return handler

    @pytest.mark.asyncio
    async def test_send_scheduled_message_success(
        self, mock_config, mock_message_handler
    ):
        """Test successful scheduled message sending with segments."""
        from adapter.telegram.adapter import TelegramAdapter

        with patch("adapter.telegram.adapter.Config", return_value=mock_config):
            adapter = TelegramAdapter(message_handler=mock_message_handler)

            mock_app = Mock()
            mock_app.bot = Mock()
            mock_app.bot.send_message = AsyncMock()
            mock_app.bot.send_chat_action = AsyncMock()
            adapter._application = mock_app

            with patch("asyncio.sleep"):
                await adapter._send_scheduled_message("Test scheduled message")

                mock_message_handler._handle_scheduled_message.assert_called_once()
                mock_message_handler._format_response_for_telegram.assert_called_once()
                mock_message_handler._split_message_into_segments.assert_called_once()
                mock_app.bot.send_message.assert_called_once()
                call_args = mock_app.bot.send_message.call_args
                assert call_args.kwargs["chat_id"] == 123456789
                assert call_args.kwargs["parse_mode"] == "HTML"

    @pytest.mark.asyncio
    async def test_send_scheduled_message_multiple_segments(
        self, mock_config, mock_message_handler
    ):
        """Test scheduled message sending with multiple segments."""
        from adapter.telegram.adapter import TelegramAdapter

        mock_message_handler._split_message_into_segments = Mock(
            return_value=["Segment 1", "Segment 2", "Segment 3"]
        )

        with patch("adapter.telegram.adapter.Config", return_value=mock_config):
            adapter = TelegramAdapter(message_handler=mock_message_handler)

            mock_app = Mock()
            mock_app.bot = Mock()
            mock_app.bot.send_message = AsyncMock()
            mock_app.bot.send_chat_action = AsyncMock()
            adapter._application = mock_app

            with patch("asyncio.sleep"):
                await adapter._send_scheduled_message("Test scheduled message")

                assert mock_app.bot.send_message.call_count == 3

    @pytest.mark.asyncio
    async def test_send_scheduled_message_no_application(self, mock_config):
        """Test scheduled message when application is not initialized."""
        from adapter.telegram.adapter import TelegramAdapter

        with patch("adapter.telegram.adapter.Config", return_value=mock_config):
            message_handler = Mock()
            message_handler.core_bot = Mock()
            message_handler.core_bot.scheduler = Mock()
            message_handler.core_bot.scheduler.set_message_callback = Mock()
            message_handler._commands = Mock()
            adapter = TelegramAdapter(message_handler=message_handler)
            await adapter._send_scheduled_message("Test message")

    @pytest.mark.asyncio
    async def test_send_scheduled_message_typing_indicator(
        self, mock_config, mock_message_handler
    ):
        """Test that typing indicator is sent during scheduled message."""
        from adapter.telegram.adapter import TelegramAdapter

        with patch("adapter.telegram.adapter.Config", return_value=mock_config):
            adapter = TelegramAdapter(message_handler=mock_message_handler)

            mock_app = Mock()
            mock_app.bot = Mock()
            mock_app.bot.send_message = AsyncMock()
            mock_app.bot.send_chat_action = AsyncMock()
            adapter._application = mock_app

            with patch("random.uniform", return_value=0):
                await adapter._send_scheduled_message("Test scheduled message")
                mock_app.bot.send_message.assert_called()

    @pytest.mark.asyncio
    async def test_send_scheduled_message_html_fallback(
        self, mock_config, mock_message_handler
    ):
        """Test fallback to plain text when HTML parsing fails."""
        from adapter.telegram.adapter import TelegramAdapter

        mock_message_handler._split_message_into_segments = Mock(
            return_value=["Segment with <b>HTML</b>"]
        )

        with patch("adapter.telegram.adapter.Config", return_value=mock_config):
            adapter = TelegramAdapter(message_handler=mock_message_handler)

            mock_app = Mock()
            mock_app.bot = Mock()
            mock_app.bot.send_chat_action = AsyncMock()

            call_count = 0

            async def side_effect(*args, **kwargs):
                nonlocal call_count
                call_count += 1
                if call_count == 1 and kwargs.get("parse_mode") == "HTML":
                    raise Exception("Can't parse HTML entities")
                return Mock()

            mock_app.bot.send_message = AsyncMock(side_effect=side_effect)
            adapter._application = mock_app

            with patch("asyncio.sleep"):
                await adapter._send_scheduled_message("Test message")
                assert mock_app.bot.send_message.call_count == 2


class TestTelegramAdapterMessageSegmentation:
    """Test message segmentation with typing indicator."""

    @pytest.fixture
    def mock_config(self):
        """Create a mock Config."""
        config = Mock()
        config.TELEGRAM_BOT_TOKEN = "test_token"
        config.TELEGRAM_USER_ID = 123456789
        return config

    @pytest.fixture
    def mock_message_handler_with_segments(self):
        """Create a mock MessageHandler that returns multiple segments."""
        handler = Mock()
        handler.core_bot = Mock()
        handler.core_bot.scheduler = Mock()
        handler.core_bot.scheduler.set_message_callback = Mock()
        handler._format_response_for_telegram = Mock(return_value="Formatted message")
        handler._split_message_into_segments = Mock(
            return_value=["Segment 1 content", "Segment 2 content", "Segment 3 content"]
        )
        handler._handle_scheduled_message = AsyncMock(return_value="LLM response")
        handler._commands = Mock()
        return handler

    @pytest.mark.asyncio
    async def test_delay_between_segments(
        self, mock_config, mock_message_handler_with_segments
    ):
        """Test that there is a delay between message segments."""
        from adapter.telegram.adapter import TelegramAdapter

        with patch("adapter.telegram.adapter.Config", return_value=mock_config):
            adapter = TelegramAdapter(
                message_handler=mock_message_handler_with_segments
            )

            mock_app = Mock()
            mock_app.bot = Mock()
            mock_app.bot.send_message = AsyncMock()
            mock_app.bot.send_chat_action = AsyncMock()
            adapter._application = mock_app

            sleep_calls = []

            async def mock_sleep(delay):
                sleep_calls.append(delay)

            with patch("asyncio.sleep", side_effect=mock_sleep):
                await adapter._send_scheduled_message("Test message")
                assert len(sleep_calls) >= 2
                for delay in sleep_calls:
                    assert 1.0 <= delay <= 2.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
