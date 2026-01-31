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
        
        with patch('tg_bot.bot.Config', return_value=mock_config):
            bot = TelegramBot(message_handler=mock_message_handler)
            
            assert bot.config == mock_config
            assert bot.message_handler == mock_message_handler
            assert bot.scheduler == mock_message_handler.scheduler
            assert bot._application is None
    
    @pytest.mark.asyncio
    async def test_scheduler_callback_registration(self, mock_config, mock_message_handler):
        """Test that scheduler message callback is registered"""
        from tg_bot.bot import TelegramBot
        
        with patch('tg_bot.bot.Config', return_value=mock_config):
            bot = TelegramBot(message_handler=mock_message_handler)
            
            # Verify callback was registered
            mock_message_handler.scheduler.set_message_callback.assert_called_once()
            # Verify it's the bot's method
            assert mock_message_handler.scheduler.set_message_callback.call_args[0][0] == bot._send_scheduled_message


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
    
    def test_create_application(self, mock_config, mock_message_handler, mock_application):
        """Test application creation and handler registration"""
        from tg_bot.bot import TelegramBot
        
        with patch('tg_bot.bot.Config', return_value=mock_config):
            with patch('tg_bot.bot.Application.builder') as mock_builder:
                mock_builder.return_value.token.return_value.build.return_value = mock_application
                
                bot = TelegramBot(message_handler=mock_message_handler)
                bot.create_application()
                
                # Verify application was created
                assert bot._application == mock_application
                
                # Verify token was set
                mock_builder.return_value.token.assert_called_once_with("test_token")
                
                # Verify handlers were added (should be 5 handlers: start, help, new, reset, message)
                assert mock_application.add_handler.call_count == 5
    
    @pytest.mark.asyncio
    async def test_post_init_hook(self, mock_config, mock_message_handler, mock_application):
        """Test post_init hook starts scheduler and registers commands"""
        from tg_bot.bot import TelegramBot
        
        with patch('tg_bot.bot.Config', return_value=mock_config):
            with patch('tg_bot.bot.Application.builder') as mock_builder:
                mock_builder.return_value.token.return_value.build.return_value = mock_application
                
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
        
        with patch('tg_bot.bot.Config', return_value=mock_config):
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
        
        with patch('tg_bot.bot.Config', return_value=mock_config):
            bot = TelegramBot(message_handler=Mock())
            await bot._cmd_start(mock_update, mock_context)
            
            # Verify unauthorized message was sent
            mock_update.message.reply_text.assert_called_once()
            assert "Unauthorized" in mock_update.message.reply_text.call_args[0][0]
    
    @pytest.mark.asyncio
    async def test_cmd_help(self, mock_config, mock_update, mock_context):
        """Test /help command"""
        from tg_bot.bot import TelegramBot
        
        with patch('tg_bot.bot.Config', return_value=mock_config):
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
    
    @pytest.mark.asyncio
    async def test_send_scheduled_message_success(self, mock_config):
        """Test successful scheduled message sending"""
        from tg_bot.bot import TelegramBot
        
        with patch('tg_bot.bot.Config', return_value=mock_config):
            bot = TelegramBot(message_handler=Mock())
            
            # Mock the application and bot
            mock_app = Mock()
            mock_app.bot = Mock()
            mock_app.bot.send_message = AsyncMock()
            bot._application = mock_app
            
            # Send a scheduled message
            await bot._send_scheduled_message("Test scheduled message")
            
            # Verify message was sent
            mock_app.bot.send_message.assert_called_once()
            call_args = mock_app.bot.send_message.call_args
            assert call_args.kwargs['chat_id'] == 123456789
            assert "Test scheduled message" in call_args.kwargs['text']
    
    @pytest.mark.asyncio
    async def test_send_scheduled_message_no_application(self, mock_config):
        """Test scheduled message when application is not initialized"""
        from tg_bot.bot import TelegramBot
        
        with patch('tg_bot.bot.Config', return_value=mock_config):
            bot = TelegramBot(message_handler=Mock())
            # Don't set _application
            
            # Should not raise exception, just log error
            await bot._send_scheduled_message("Test message")
            # Test passes if no exception is raised
    
    @pytest.mark.asyncio
    async def test_send_scheduled_message_markdown_fallback(self, mock_config):
        """Test fallback to plain text when MarkdownV2 fails"""
        from tg_bot.bot import TelegramBot
        
        with patch('tg_bot.bot.Config', return_value=mock_config):
            bot = TelegramBot(message_handler=Mock())
            
            # Mock the application and bot
            mock_app = Mock()
            mock_app.bot = Mock()
            
            # First call raises markdown error, second succeeds
            async def side_effect(*args, **kwargs):
                if 'parse_mode' in kwargs and kwargs['parse_mode'] == 'MarkdownV2':
                    raise Exception("Can't parse entities")
                return Mock()
            
            mock_app.bot.send_message = AsyncMock(side_effect=side_effect)
            bot._application = mock_app
            
            # Send message with markdown
            await bot._send_scheduled_message("Test with *bold* text")
            
            # Verify both calls were made
            assert mock_app.bot.send_message.call_count == 2


# Run tests if executed directly
if __name__ == "__main__":
    pytest.main([__file__, "-v"])
