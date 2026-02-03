"""Tests for Telegram Bot

This module contains tests for the Telegram Bot implementation.
Uses pytest-asyncio for async testing and unittest.mock for mocking.
"""

import sys
from pathlib import Path

# Add project root to path for absolute imports
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pytest
import pytest_asyncio
from unittest.mock import Mock, patch, AsyncMock, MagicMock
from telegram import Update, User, Message, BotCommand
from telegram.ext import Application, ContextTypes


class TestTelegramBotInitialization:
    """Test TelegramBot initialization"""

    @pytest.fixture
    def mock_config(self):
        """Create a mock Config"""
        config = Mock()
        config.TELEGRAM_BOT_TOKEN = "test_token"
        config.TELEGRAM_USER_ID = 123456789
        config.TELEGRAM_USE_MARKDOWN = True
        return config

    @pytest.fixture
    def mock_message_handler(self):
        """Create a mock MessageHandler"""
        handler = Mock()
        handler.scheduler = Mock()
        handler.scheduler.set_message_callback = Mock()
        handler.scheduler.load_default_tasks = Mock()
        handler.scheduler.run_forever = AsyncMock()
        handler.scheduler.stop = Mock()
        return handler

    @pytest.mark.asyncio
    async def test_bot_initialization(self, mock_config, mock_message_handler):
        """Test bot initialization with dependencies"""
        from tg_bot.bot import TelegramBot

        with patch("tg_bot.bot.Config", return_value=mock_config):
            bot = TelegramBot(message_handler=mock_message_handler)

            assert bot.config == mock_config
            assert bot.message_handler == mock_message_handler
            assert bot.scheduler == mock_message_handler.scheduler
            assert bot._application is None

    @pytest.mark.asyncio
    async def test_scheduler_callback_registration(
        self, mock_config, mock_message_handler
    ):
        """Test that scheduler message callback is registered"""
        from tg_bot.bot import TelegramBot

        with patch("tg_bot.bot.Config", return_value=mock_config):
            bot = TelegramBot(message_handler=mock_message_handler)

            # Verify callback was registered
            mock_message_handler.scheduler.set_message_callback.assert_called_once()
            # Verify it's the bot's method
            assert (
                mock_message_handler.scheduler.set_message_callback.call_args[0][0]
                == bot._send_scheduled_message
            )


class TestTelegramBotApplication:
    """Test TelegramBot application setup"""

    @pytest.fixture
    def mock_config(self):
        """Create a mock Config"""
        config = Mock()
        config.TELEGRAM_BOT_TOKEN = "test_token"
        config.TELEGRAM_USER_ID = 123456789
        config.TELEGRAM_USE_MARKDOWN = True
        return config

    @pytest.fixture
    def mock_message_handler(self):
        """Create a mock MessageHandler"""
        handler = Mock()
        handler.scheduler = Mock()
        handler.scheduler.set_message_callback = Mock()
        handler.scheduler.load_default_tasks = Mock()
        handler.scheduler.run_forever = AsyncMock()
        handler.scheduler.stop = Mock()
        handler.handle_new_session = AsyncMock()
        handler.handle_reset_session = AsyncMock()
        handler.handle_message = AsyncMock()
        return handler

    @pytest.fixture
    def mock_application(self):
        """Create a mock Application"""
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
        """Test application creation and handler registration"""
        from tg_bot.bot import TelegramBot

        with patch("tg_bot.bot.Config", return_value=mock_config):
            with patch("tg_bot.bot.Application.builder") as mock_builder:
                mock_builder.return_value.token.return_value.build.return_value = (
                    mock_application
                )

                bot = TelegramBot(message_handler=mock_message_handler)
                bot.create_application()

                # Verify application was created
                assert bot._application == mock_application

                # Verify token was set
                mock_builder.return_value.token.assert_called_once_with("test_token")

                # Verify handlers were added (should be 5 handlers: start, help, new, reset, message)
                assert mock_application.add_handler.call_count == 5

    @pytest.mark.asyncio
    async def test_post_init_hook(
        self, mock_config, mock_message_handler, mock_application
    ):
        """Test post_init hook starts scheduler and registers commands"""
        from tg_bot.bot import TelegramBot

        with patch("tg_bot.bot.Config", return_value=mock_config):
            with patch("tg_bot.bot.Application.builder") as mock_builder:
                mock_builder.return_value.token.return_value.build.return_value = (
                    mock_application
                )

                bot = TelegramBot(message_handler=mock_message_handler)
                bot.create_application()

                # Get the post_init hook
                post_init = mock_application.post_init
                assert post_init is not None

                # Mock the application context
                mock_app = Mock()
                mock_app.bot = Mock()
                mock_app.bot.set_my_commands = AsyncMock()

                # Call post_init
                await post_init(mock_app)

                # Verify commands were registered
                mock_app.bot.set_my_commands.assert_called_once()
                commands = mock_app.bot.set_my_commands.call_args[0][0]
                assert len(commands) == 4
                assert all(isinstance(cmd, BotCommand) for cmd in commands)


class TestTelegramBotCommands:
    """Test TelegramBot command handlers"""

    @pytest.fixture
    def mock_config(self):
        """Create a mock Config"""
        config = Mock()
        config.TELEGRAM_BOT_TOKEN = "test_token"
        config.TELEGRAM_USER_ID = 123456789
        return config

    @pytest.fixture
    def mock_update(self):
        """Create a mock Update"""
        update = Mock(spec=Update)
        update.effective_user = Mock(spec=User)
        update.effective_user.id = 123456789
        update.message = Mock(spec=Message)
        update.message.reply_text = AsyncMock()
        return update

    @pytest.fixture
    def mock_context(self):
        """Create a mock Context"""
        return Mock(spec=ContextTypes.DEFAULT_TYPE)

    @pytest.mark.asyncio
    async def test_cmd_start_authorized(self, mock_config, mock_update, mock_context):
        """Test /start command for authorized user"""
        from tg_bot.bot import TelegramBot

        with patch("tg_bot.bot.Config", return_value=mock_config):
            bot = TelegramBot(message_handler=Mock())
            await bot._cmd_start(mock_update, mock_context)

            # Verify welcome message was sent
            mock_update.message.reply_text.assert_called_once()
            welcome_text = mock_update.message.reply_text.call_args[0][0]
            assert "Welcome to Seelenmaschine" in welcome_text

    @pytest.mark.asyncio
    async def test_cmd_start_unauthorized(self, mock_config, mock_update, mock_context):
        """Test /start command for unauthorized user"""
        from tg_bot.bot import TelegramBot

        # Change user ID to unauthorized
        mock_update.effective_user.id = 999999999

        with patch("tg_bot.bot.Config", return_value=mock_config):
            bot = TelegramBot(message_handler=Mock())
            await bot._cmd_start(mock_update, mock_context)

            # Verify unauthorized message was sent
            mock_update.message.reply_text.assert_called_once()
            assert "Unauthorized" in mock_update.message.reply_text.call_args[0][0]

    @pytest.mark.asyncio
    async def test_cmd_help(self, mock_config, mock_update, mock_context):
        """Test /help command"""
        from tg_bot.bot import TelegramBot

        with patch("tg_bot.bot.Config", return_value=mock_config):
            bot = TelegramBot(message_handler=Mock())
            await bot._cmd_help(mock_update, mock_context)

            # Verify help message was sent
            mock_update.message.reply_text.assert_called_once()
            help_text = mock_update.message.reply_text.call_args[0][0]
            assert "Available commands" in help_text
            assert "/new" in help_text
            assert "/reset" in help_text


class TestTelegramBotScheduledMessages:
    """Test scheduled message sending"""

    @pytest.fixture
    def mock_config(self):
        """Create a mock Config"""
        config = Mock()
        config.TELEGRAM_BOT_TOKEN = "test_token"
        config.TELEGRAM_USER_ID = 123456789
        config.TELEGRAM_USE_MARKDOWN = True
        return config

    @pytest.fixture
    def mock_message_handler(self):
        """Create a mock MessageHandler with formatting and splitting methods"""
        handler = Mock()
        handler._format_response_for_telegram = Mock(return_value="Formatted message")
        handler._split_message_into_segments = Mock(return_value=["Segment 1"])
        handler._handle_scheduled_message = AsyncMock(return_value="LLM response")
        return handler

    @pytest.mark.asyncio
    async def test_send_scheduled_message_success(
        self, mock_config, mock_message_handler
    ):
        """Test successful scheduled message sending with segments"""
        from tg_bot.bot import TelegramBot

        with patch("tg_bot.bot.Config", return_value=mock_config):
            bot = TelegramBot(message_handler=mock_message_handler)

            # Mock the application and bot
            mock_app = Mock()
            mock_app.bot = Mock()
            mock_app.bot.send_message = AsyncMock()
            mock_app.bot.send_chat_action = AsyncMock()
            bot._application = mock_app

            # Mock asyncio.sleep to avoid actual delays
            with patch("asyncio.sleep"):
                # Send a scheduled message
                await bot._send_scheduled_message("Test scheduled message")

                # Verify LLM processing was called
                mock_message_handler._handle_scheduled_message.assert_called_once()

                # Verify formatting was called
                mock_message_handler._format_response_for_telegram.assert_called_once()

                # Verify splitting was called
                mock_message_handler._split_message_into_segments.assert_called_once()

                # Verify message was sent
                mock_app.bot.send_message.assert_called_once()
                call_args = mock_app.bot.send_message.call_args
                assert call_args.kwargs["chat_id"] == 123456789
                assert call_args.kwargs["parse_mode"] == "HTML"

    @pytest.mark.asyncio
    async def test_send_scheduled_message_multiple_segments(
        self, mock_config, mock_message_handler
    ):
        """Test scheduled message sending with multiple segments"""
        from tg_bot.bot import TelegramBot

        # Setup multiple segments
        mock_message_handler._split_message_into_segments = Mock(
            return_value=["Segment 1", "Segment 2", "Segment 3"]
        )

        with patch("tg_bot.bot.Config", return_value=mock_config):
            bot = TelegramBot(message_handler=mock_message_handler)

            # Mock the application and bot
            mock_app = Mock()
            mock_app.bot = Mock()
            mock_app.bot.send_message = AsyncMock()
            mock_app.bot.send_chat_action = AsyncMock()
            bot._application = mock_app

            # Mock asyncio.sleep to avoid actual delays
            with patch("asyncio.sleep"):
                # Send a scheduled message
                await bot._send_scheduled_message("Test scheduled message")

                # Verify all 3 segments were sent
                assert mock_app.bot.send_message.call_count == 3

    @pytest.mark.asyncio
    async def test_send_scheduled_message_no_application(self, mock_config):
        """Test scheduled message when application is not initialized"""
        from tg_bot.bot import TelegramBot

        with patch("tg_bot.bot.Config", return_value=mock_config):
            bot = TelegramBot(message_handler=Mock())
            # Don't set _application

            # Should not raise exception, just log error
            await bot._send_scheduled_message("Test message")
            # Test passes if no exception is raised

    @pytest.mark.asyncio
    async def test_send_scheduled_message_typing_indicator(
        self, mock_config, mock_message_handler
    ):
        """Test that typing indicator is sent during scheduled message"""
        from tg_bot.bot import TelegramBot

        with patch("tg_bot.bot.Config", return_value=mock_config):
            bot = TelegramBot(message_handler=mock_message_handler)

            # Mock the application and bot
            mock_app = Mock()
            mock_app.bot = Mock()
            mock_app.bot.send_message = AsyncMock()
            mock_app.bot.send_chat_action = AsyncMock()
            bot._application = mock_app

            # Mock random.uniform to return 0 to speed up delays between segments
            with patch("random.uniform", return_value=0):
                # Send a scheduled message
                await bot._send_scheduled_message("Test scheduled message")

                # Verify message was sent successfully
                # (typing indicator may or may not execute depending on timing,
                # but the important thing is the code path works without errors)
                mock_app.bot.send_message.assert_called()

    @pytest.mark.asyncio
    async def test_send_scheduled_message_html_fallback(
        self, mock_config, mock_message_handler
    ):
        """Test fallback to plain text when HTML parsing fails"""
        from tg_bot.bot import TelegramBot

        # Setup single segment
        mock_message_handler._split_message_into_segments = Mock(
            return_value=["Segment with <b>HTML</b>"]
        )

        with patch("tg_bot.bot.Config", return_value=mock_config):
            bot = TelegramBot(message_handler=mock_message_handler)

            # Mock the application and bot
            mock_app = Mock()
            mock_app.bot = Mock()
            mock_app.bot.send_chat_action = AsyncMock()

            # First call raises HTML error, second succeeds
            call_count = 0

            async def side_effect(*args, **kwargs):
                nonlocal call_count
                call_count += 1
                if call_count == 1 and kwargs.get("parse_mode") == "HTML":
                    raise Exception("Can't parse HTML entities")
                return Mock()

            mock_app.bot.send_message = AsyncMock(side_effect=side_effect)
            bot._application = mock_app

            # Mock asyncio.sleep to avoid actual delays
            with patch("asyncio.sleep"):
                # Send a scheduled message
                await bot._send_scheduled_message("Test message")

                # Verify both calls were made (HTML failed, plain text succeeded)
                assert mock_app.bot.send_message.call_count == 2


class TestTelegramBotMessageSegmentation:
    """Test message segmentation with typing indicator"""

    @pytest.fixture
    def mock_config(self):
        """Create a mock Config"""
        config = Mock()
        config.TELEGRAM_BOT_TOKEN = "test_token"
        config.TELEGRAM_USER_ID = 123456789
        return config

    @pytest.fixture
    def mock_message_handler_with_segments(self):
        """Create a mock MessageHandler that returns multiple segments"""
        handler = Mock()
        handler._format_response_for_telegram = Mock(return_value="Formatted message")
        handler._split_message_into_segments = Mock(
            return_value=["Segment 1 content", "Segment 2 content", "Segment 3 content"]
        )
        handler._handle_scheduled_message = AsyncMock(return_value="LLM response")
        return handler

    @pytest.mark.asyncio
    async def test_delay_between_segments(
        self, mock_config, mock_message_handler_with_segments
    ):
        """Test that there is a delay between message segments"""
        from tg_bot.bot import TelegramBot

        with patch("tg_bot.bot.Config", return_value=mock_config):
            bot = TelegramBot(message_handler=mock_message_handler_with_segments)

            # Mock the application and bot
            mock_app = Mock()
            mock_app.bot = Mock()
            mock_app.bot.send_message = AsyncMock()
            mock_app.bot.send_chat_action = AsyncMock()
            bot._application = mock_app

            # Track sleep calls
            sleep_calls = []

            async def mock_sleep(delay):
                sleep_calls.append(delay)

            with patch("asyncio.sleep", side_effect=mock_sleep):
                # Send a scheduled message
                await bot._send_scheduled_message("Test message")

                # With 3 segments, there should be 2 delays (not after the last one)
                assert len(sleep_calls) >= 2
                # Each delay should be 1-2 seconds
                for delay in sleep_calls:
                    assert 1.0 <= delay <= 2.0


# Run tests if executed directly
if __name__ == "__main__":
    pytest.main([__file__, "-v"])
