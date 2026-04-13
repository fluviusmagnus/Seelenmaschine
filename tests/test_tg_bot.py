"""Tests for Telegram adapter.

This module contains tests for the Telegram adapter implementation.
Uses pytest-asyncio for async testing and unittest.mock for mocking.
"""

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import pytest
from telegram import Update
from telegram.ext import Application

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
        config.TELEGRAM_CONNECT_TIMEOUT = 15.0
        config.TELEGRAM_READ_TIMEOUT = 30.0
        config.TELEGRAM_WRITE_TIMEOUT = 30.0
        config.TELEGRAM_POOL_TIMEOUT = 15.0
        config.TELEGRAM_GET_UPDATES_CONNECT_TIMEOUT = 5.0
        config.TELEGRAM_GET_UPDATES_READ_TIMEOUT = 5.0
        config.TELEGRAM_GET_UPDATES_WRITE_TIMEOUT = 5.0
        config.TELEGRAM_GET_UPDATES_POOL_TIMEOUT = 5.0
        config.TELEGRAM_BOOTSTRAP_RETRIES = 3
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
        config.TELEGRAM_CONNECT_TIMEOUT = 15.0
        config.TELEGRAM_READ_TIMEOUT = 30.0
        config.TELEGRAM_WRITE_TIMEOUT = 30.0
        config.TELEGRAM_POOL_TIMEOUT = 15.0
        config.TELEGRAM_GET_UPDATES_CONNECT_TIMEOUT = 5.0
        config.TELEGRAM_GET_UPDATES_READ_TIMEOUT = 5.0
        config.TELEGRAM_GET_UPDATES_WRITE_TIMEOUT = 5.0
        config.TELEGRAM_GET_UPDATES_POOL_TIMEOUT = 5.0
        config.TELEGRAM_BOOTSTRAP_RETRIES = 3
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
        handler.handle_message = AsyncMock()
        handler.handle_file = AsyncMock()
        commands = Mock()
        commands.handle_start = AsyncMock()
        commands.handle_help = AsyncMock()
        commands.handle_new_session = AsyncMock()
        commands.handle_reset_session = AsyncMock()
        commands.handle_stop = AsyncMock()
        commands.handle_approve = AsyncMock()
        handler.commands = commands
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
                mock_builder_instance.get_updates_connect_timeout.return_value = (
                    mock_builder_instance
                )
                mock_builder_instance.get_updates_read_timeout.return_value = (
                    mock_builder_instance
                )
                mock_builder_instance.get_updates_write_timeout.return_value = (
                    mock_builder_instance
                )
                mock_builder_instance.get_updates_pool_timeout.return_value = (
                    mock_builder_instance
                )
                mock_builder_instance.connect_timeout.return_value = (
                    mock_builder_instance
                )
                mock_builder_instance.read_timeout.return_value = mock_builder_instance
                mock_builder_instance.write_timeout.return_value = (
                    mock_builder_instance
                )
                mock_builder_instance.pool_timeout.return_value = mock_builder_instance
                mock_builder_instance.build.return_value = mock_application

                adapter = TelegramAdapter(message_handler=mock_message_handler)
                adapter.create_application()

                assert adapter._application == mock_application
                mock_message_handler.set_telegram_bot.assert_called_once_with(
                    mock_application.bot
                )
                mock_builder_instance.token.assert_called_once_with("test_token")
                mock_builder_instance.concurrent_updates.assert_called_once_with(True)
                mock_builder_instance.get_updates_connect_timeout.assert_called_once_with(
                    5.0
                )
                mock_builder_instance.get_updates_read_timeout.assert_called_once_with(
                    5.0
                )
                mock_builder_instance.get_updates_write_timeout.assert_called_once_with(
                    5.0
                )
                mock_builder_instance.get_updates_pool_timeout.assert_called_once_with(
                    5.0
                )
                mock_builder_instance.connect_timeout.assert_called_once_with(15.0)
                mock_builder_instance.read_timeout.assert_called_once_with(30.0)
                mock_builder_instance.write_timeout.assert_called_once_with(30.0)
                mock_builder_instance.pool_timeout.assert_called_once_with(15.0)
                assert mock_application.add_handler.call_count == 8
                assert mock_application.post_init is not None
                assert mock_application.post_shutdown is not None

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
                mock_builder_instance.get_updates_connect_timeout.return_value = (
                    mock_builder_instance
                )
                mock_builder_instance.get_updates_read_timeout.return_value = (
                    mock_builder_instance
                )
                mock_builder_instance.get_updates_write_timeout.return_value = (
                    mock_builder_instance
                )
                mock_builder_instance.get_updates_pool_timeout.return_value = (
                    mock_builder_instance
                )
                mock_builder_instance.connect_timeout.return_value = (
                    mock_builder_instance
                )
                mock_builder_instance.read_timeout.return_value = mock_builder_instance
                mock_builder_instance.write_timeout.return_value = (
                    mock_builder_instance
                )
                mock_builder_instance.pool_timeout.return_value = mock_builder_instance
                mock_builder_instance.build.return_value = mock_application

                adapter = TelegramAdapter(message_handler=mock_message_handler)
                adapter.create_application()

                mock_builder_instance.concurrent_updates.assert_called_once_with(True)

    def test_create_application_sets_get_updates_specific_timeouts(
        self, mock_config, mock_message_handler, mock_application
    ):
        """Adapter should use shorter get_updates timeouts to reduce shutdown noise."""
        from adapter.telegram.adapter import TelegramAdapter

        mock_config.TELEGRAM_GET_UPDATES_CONNECT_TIMEOUT = 5.0
        mock_config.TELEGRAM_GET_UPDATES_READ_TIMEOUT = 5.0
        mock_config.TELEGRAM_GET_UPDATES_WRITE_TIMEOUT = 5.0
        mock_config.TELEGRAM_GET_UPDATES_POOL_TIMEOUT = 5.0

        with patch("adapter.telegram.adapter.Config", return_value=mock_config):
            with patch("adapter.telegram.adapter.Application.builder") as mock_builder:
                mock_builder_instance = mock_builder.return_value
                mock_builder_instance.token.return_value = mock_builder_instance
                mock_builder_instance.concurrent_updates.return_value = (
                    mock_builder_instance
                )
                mock_builder_instance.get_updates_connect_timeout.return_value = (
                    mock_builder_instance
                )
                mock_builder_instance.get_updates_read_timeout.return_value = (
                    mock_builder_instance
                )
                mock_builder_instance.get_updates_write_timeout.return_value = (
                    mock_builder_instance
                )
                mock_builder_instance.get_updates_pool_timeout.return_value = (
                    mock_builder_instance
                )
                mock_builder_instance.connect_timeout.return_value = (
                    mock_builder_instance
                )
                mock_builder_instance.read_timeout.return_value = mock_builder_instance
                mock_builder_instance.write_timeout.return_value = (
                    mock_builder_instance
                )
                mock_builder_instance.pool_timeout.return_value = mock_builder_instance
                mock_builder_instance.build.return_value = mock_application

                adapter = TelegramAdapter(message_handler=mock_message_handler)
                adapter.create_application()

                mock_builder_instance.get_updates_connect_timeout.assert_called_once_with(
                    5.0
                )
                mock_builder_instance.get_updates_read_timeout.assert_called_once_with(
                    5.0
                )
                mock_builder_instance.get_updates_write_timeout.assert_called_once_with(
                    5.0
                )
                mock_builder_instance.get_updates_pool_timeout.assert_called_once_with(
                    5.0
                )

    def test_run_uses_valid_allowed_updates(
        self, mock_config, mock_message_handler, mock_application
    ):
        """run_polling should receive Telegram's serializable update types list."""
        from adapter.telegram.adapter import TelegramAdapter

        with patch("adapter.telegram.adapter.Config", return_value=mock_config):
            adapter = TelegramAdapter(message_handler=mock_message_handler)
            adapter._application = mock_application

            with patch.object(adapter, "_ensure_event_loop") as mock_ensure_event_loop:
                adapter.run()

            mock_ensure_event_loop.assert_called_once_with()
            mock_application.run_polling.assert_called_once_with(
                allowed_updates=Update.ALL_TYPES,
                bootstrap_retries=3,
            )

    def test_ensure_event_loop_creates_new_loop_when_missing(
        self, mock_config, mock_message_handler
    ):
        """Adapter should create and register a loop on Python 3.12+ sync startup."""
        from adapter.telegram.adapter import TelegramAdapter

        with patch("adapter.telegram.adapter.Config", return_value=mock_config):
            adapter = TelegramAdapter(message_handler=mock_message_handler)
            fake_loop = Mock(spec=asyncio.AbstractEventLoop)

            with patch(
                "adapter.telegram.adapter.asyncio.get_running_loop",
                side_effect=RuntimeError,
            ):
                with patch(
                    "adapter.telegram.adapter.asyncio.get_event_loop_policy"
                ) as mock_get_event_loop_policy:
                    mock_policy = mock_get_event_loop_policy.return_value
                    mock_policy.get_event_loop.side_effect = RuntimeError

                    with patch(
                        "adapter.telegram.adapter.asyncio.new_event_loop",
                        return_value=fake_loop,
                    ) as mock_new_event_loop:
                        with patch(
                            "adapter.telegram.adapter.asyncio.set_event_loop"
                        ) as mock_set_event_loop:
                            loop = adapter._ensure_event_loop()

            assert loop is fake_loop
            mock_new_event_loop.assert_called_once_with()
            mock_set_event_loop.assert_called_once_with(fake_loop)

    def test_create_application_post_init_warms_runtime_and_starts_scheduler(
        self, mock_config, mock_message_handler, mock_application
    ):
        """Application post_init should warm tool runtime and start the scheduler."""
        from adapter.telegram.adapter import TelegramAdapter

        with patch("adapter.telegram.adapter.Config", return_value=mock_config):
            with patch("adapter.telegram.adapter.Application.builder") as mock_builder:
                mock_builder_instance = mock_builder.return_value
                mock_builder_instance.token.return_value = mock_builder_instance
                mock_builder_instance.concurrent_updates.return_value = (
                    mock_builder_instance
                )
                mock_builder_instance.get_updates_connect_timeout.return_value = (
                    mock_builder_instance
                )
                mock_builder_instance.get_updates_read_timeout.return_value = (
                    mock_builder_instance
                )
                mock_builder_instance.get_updates_write_timeout.return_value = (
                    mock_builder_instance
                )
                mock_builder_instance.get_updates_pool_timeout.return_value = (
                    mock_builder_instance
                )
                mock_builder_instance.connect_timeout.return_value = (
                    mock_builder_instance
                )
                mock_builder_instance.read_timeout.return_value = mock_builder_instance
                mock_builder_instance.write_timeout.return_value = (
                    mock_builder_instance
                )
                mock_builder_instance.pool_timeout.return_value = mock_builder_instance
                mock_builder_instance.build.return_value = mock_application

                adapter = TelegramAdapter(message_handler=mock_message_handler)
                mock_message_handler.core_bot.warmup_tool_runtime = AsyncMock()
                mock_message_handler.core_bot.scheduler.start = Mock()
                adapter._application = adapter._application_setup.create_application(
                    application_builder_factory=mock_builder,
                    command_handler_cls=__import__(
                        "telegram.ext", fromlist=["CommandHandler"]
                    ).CommandHandler,
                    message_handler_cls=__import__(
                        "telegram.ext", fromlist=["MessageHandler"]
                    ).MessageHandler,
                    filters_module=__import__(
                        "telegram.ext", fromlist=["filters"]
                    ).filters,
                )

                assert mock_application.post_init is not None

                mock_runtime_app = Mock()
                mock_runtime_app.bot = Mock()
                mock_runtime_app.bot.set_my_commands = AsyncMock()

                awaitable = mock_application.post_init(mock_runtime_app)
                import asyncio

                asyncio.run(awaitable)

                mock_runtime_app.bot.set_my_commands.assert_awaited_once()
                mock_message_handler.core_bot.warmup_tool_runtime.assert_awaited_once_with()
                mock_message_handler.core_bot.scheduler.start.assert_called_once_with()

    def test_create_application_post_shutdown_stops_scheduler(
        self, mock_config, mock_message_handler, mock_application
    ):
        """Application post_shutdown should stop the scheduler through its own API."""
        from adapter.telegram.adapter import TelegramAdapter

        with patch("adapter.telegram.adapter.Config", return_value=mock_config):
            with patch("adapter.telegram.adapter.Application.builder") as mock_builder:
                mock_builder_instance = mock_builder.return_value
                mock_builder_instance.token.return_value = mock_builder_instance
                mock_builder_instance.concurrent_updates.return_value = (
                    mock_builder_instance
                )
                mock_builder_instance.get_updates_connect_timeout.return_value = (
                    mock_builder_instance
                )
                mock_builder_instance.get_updates_read_timeout.return_value = (
                    mock_builder_instance
                )
                mock_builder_instance.get_updates_write_timeout.return_value = (
                    mock_builder_instance
                )
                mock_builder_instance.get_updates_pool_timeout.return_value = (
                    mock_builder_instance
                )
                mock_builder_instance.connect_timeout.return_value = (
                    mock_builder_instance
                )
                mock_builder_instance.read_timeout.return_value = mock_builder_instance
                mock_builder_instance.write_timeout.return_value = (
                    mock_builder_instance
                )
                mock_builder_instance.pool_timeout.return_value = mock_builder_instance
                mock_builder_instance.build.return_value = mock_application

                adapter = TelegramAdapter(message_handler=mock_message_handler)
                mock_message_handler.core_bot.scheduler.stop = Mock()
                mock_message_handler.core_bot.scheduler.wait_stopped = AsyncMock()
                adapter._application = adapter._application_setup.create_application(
                    application_builder_factory=mock_builder,
                    command_handler_cls=__import__(
                        "telegram.ext", fromlist=["CommandHandler"]
                    ).CommandHandler,
                    message_handler_cls=__import__(
                        "telegram.ext", fromlist=["MessageHandler"]
                    ).MessageHandler,
                    filters_module=__import__(
                        "telegram.ext", fromlist=["filters"]
                    ).filters,
                )

                assert mock_application.post_shutdown is not None
                asyncio.run(mock_application.post_shutdown(Mock()))

                mock_message_handler.core_bot.scheduler.stop.assert_called_once_with()
                mock_message_handler.core_bot.scheduler.wait_stopped.assert_awaited_once_with()


class TestTelegramAdapterCommands:
    """Test TelegramAdapter command handlers."""


class TestTelegramAdapterScheduledMessages:
    """Test scheduled message sending."""

    @pytest.fixture
    def mock_config(self):
        """Create a mock Config."""
        config = Mock()
        config.TELEGRAM_BOT_TOKEN = "test_token"
        config.TELEGRAM_USER_ID = 123456789
        config.TELEGRAM_USE_MARKDOWN = True
        config.TELEGRAM_CONNECT_TIMEOUT = 15.0
        config.TELEGRAM_READ_TIMEOUT = 30.0
        config.TELEGRAM_WRITE_TIMEOUT = 30.0
        config.TELEGRAM_POOL_TIMEOUT = 15.0
        config.TELEGRAM_GET_UPDATES_CONNECT_TIMEOUT = 5.0
        config.TELEGRAM_GET_UPDATES_READ_TIMEOUT = 5.0
        config.TELEGRAM_GET_UPDATES_WRITE_TIMEOUT = 5.0
        config.TELEGRAM_GET_UPDATES_POOL_TIMEOUT = 5.0
        config.TELEGRAM_BOOTSTRAP_RETRIES = 3
        return config

    @pytest.fixture
    def mock_message_handler(self):
        """Create a mock MessageHandler with scheduled message support."""
        handler = Mock()
        handler.core_bot = Mock()
        handler.core_bot.scheduler = Mock()
        handler.core_bot.scheduler.set_message_callback = Mock()
        handler.messages = Mock()
        handler.messages.send_scheduled_message = AsyncMock()
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

            await adapter._send_scheduled_message("Test scheduled message")

            mock_message_handler.messages.send_scheduled_message.assert_awaited_once_with(
                application=mock_app,
                message="Test scheduled message",
                task_name="Scheduled Task",
                task_id=None,
            )

    @pytest.mark.asyncio
    async def test_send_scheduled_message_multiple_segments(
        self, mock_config, mock_message_handler
    ):
        """Test scheduled message sending with multiple segments."""
        from adapter.telegram.adapter import TelegramAdapter

        with patch("adapter.telegram.adapter.Config", return_value=mock_config):
            adapter = TelegramAdapter(message_handler=mock_message_handler)

            mock_app = Mock()
            mock_app.bot = Mock()
            mock_app.bot.send_message = AsyncMock()
            mock_app.bot.send_chat_action = AsyncMock()
            adapter._application = mock_app

            await adapter._send_scheduled_message("Test scheduled message")

            mock_message_handler.messages.send_scheduled_message.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_send_scheduled_message_no_application(self, mock_config):
        """Test scheduled message when application is not initialized."""
        from adapter.telegram.adapter import TelegramAdapter

        with patch("adapter.telegram.adapter.Config", return_value=mock_config):
            message_handler = Mock()
            message_handler.core_bot = Mock()
            message_handler.core_bot.scheduler = Mock()
            message_handler.core_bot.scheduler.set_message_callback = Mock()
            message_handler.messages = Mock()
            message_handler.messages.send_scheduled_message = AsyncMock()
            adapter = TelegramAdapter(message_handler=message_handler)
            await adapter._send_scheduled_message("Test message")

            message_handler.messages.send_scheduled_message.assert_awaited_once()

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

            await adapter._send_scheduled_message("Test scheduled message")
            mock_message_handler.messages.send_scheduled_message.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_send_scheduled_message_html_fallback(
        self, mock_config, mock_message_handler
    ):
        """Test fallback to plain text when HTML parsing fails."""
        from adapter.telegram.adapter import TelegramAdapter

        with patch("adapter.telegram.adapter.Config", return_value=mock_config):
            adapter = TelegramAdapter(message_handler=mock_message_handler)

            mock_app = Mock()
            mock_app.bot = Mock()
            mock_app.bot.send_chat_action = AsyncMock()

            adapter._application = mock_app
            await adapter._send_scheduled_message("Test message")
            mock_message_handler.messages.send_scheduled_message.assert_awaited_once()


class TestTelegramAdapterMessageSegmentation:
    """Test message segmentation with typing indicator."""

    @pytest.fixture
    def mock_config(self):
        """Create a mock Config."""
        config = Mock()
        config.TELEGRAM_BOT_TOKEN = "test_token"
        config.TELEGRAM_USER_ID = 123456789
        config.TELEGRAM_CONNECT_TIMEOUT = 15.0
        config.TELEGRAM_READ_TIMEOUT = 30.0
        config.TELEGRAM_WRITE_TIMEOUT = 30.0
        config.TELEGRAM_POOL_TIMEOUT = 15.0
        config.TELEGRAM_GET_UPDATES_CONNECT_TIMEOUT = 5.0
        config.TELEGRAM_GET_UPDATES_READ_TIMEOUT = 5.0
        config.TELEGRAM_GET_UPDATES_WRITE_TIMEOUT = 5.0
        config.TELEGRAM_GET_UPDATES_POOL_TIMEOUT = 5.0
        config.TELEGRAM_BOOTSTRAP_RETRIES = 3
        return config

    @pytest.fixture
    def mock_message_handler_with_segments(self):
        """Create a mock MessageHandler for scheduled message delegation."""
        handler = Mock()
        handler.core_bot = Mock()
        handler.core_bot.scheduler = Mock()
        handler.core_bot.scheduler.set_message_callback = Mock()
        handler.messages = Mock()
        handler.messages.send_scheduled_message = AsyncMock()
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

            await adapter._send_scheduled_message("Test message")
            mock_message_handler_with_segments.messages.send_scheduled_message.assert_awaited_once()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
