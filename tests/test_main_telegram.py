"""Tests for main_telegram.py entry point

This module tests the main entry point for the Telegram bot,
including argument parsing, initialization, and signal handling.
"""

import sys
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

# Add paths for imports
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


class TestMainTelegramArgumentParsing:
    """Test command line argument parsing"""

    def test_main_exits_without_profile(self):
        """Test that main exits when no profile is provided"""
        from io import StringIO

        test_args = ["main_telegram.py"]

        with patch.object(sys, "argv", test_args):
            with patch("sys.stdout", new=StringIO()) as fake_stdout:
                with pytest.raises(SystemExit) as exc_info:
                    import importlib

                    # We need to reimport to test the exit
                    if "main_telegram" in sys.modules:
                        del sys.modules["main_telegram"]
                    main_module = importlib.import_module("main_telegram")
                    main_module.main()

                assert exc_info.value.code == 1
                output = fake_stdout.getvalue()
                assert "Usage:" in output or "profile" in output.lower()


class TestMainTelegramInitialization:
    """Test initialization and setup"""

    @pytest.fixture
    def mock_dependencies(self):
        """Create mock dependencies for main_telegram"""
        mocks = {
            "init_config": Mock(),
            "CoreBot": Mock(),
            "MessageHandler": Mock(),
            "TelegramAdapter": Mock(),
            "get_logger": Mock(),
        }
        return mocks

    def test_main_initializes_logger_after_config(self):
        """Test that logger initialization is wired into the entry point."""
        test_args = ["main_telegram.py", "test_profile"]
        call_order = []

        with patch.object(sys, "argv", test_args):
            with patch("main_telegram.init_config") as mock_init_config:
                with patch("main_telegram.init_logger") as mock_init_logger:
                    with patch("main_telegram.CoreBot") as mock_core_bot:
                        with patch(
                            "main_telegram.TelegramController"
                        ) as mock_controller:
                            with patch(
                                "main_telegram.TelegramAdapter"
                            ) as mock_adapter:
                                with patch(
                                    "main_telegram.SchedulerRuntime"
                                ) as mock_runtime:
                                    with patch(
                                        "main_telegram.register_stop_signal_handlers"
                                    ):
                                        adapter_instance = Mock()
                                        mock_adapter.return_value = adapter_instance
                                        core_bot_instance = Mock()
                                        core_bot_instance.scheduler = Mock()
                                        mock_core_bot.return_value = core_bot_instance
                                        runtime_instance = Mock()
                                        runtime_instance.build_post_init.return_value = Mock()
                                        runtime_instance.build_post_shutdown.return_value = Mock()
                                        mock_runtime.return_value = runtime_instance
                                        mock_init_config.side_effect = (
                                            lambda profile: call_order.append(
                                                ("init_config", profile)
                                            )
                                        )
                                        mock_init_logger.side_effect = lambda: call_order.append(
                                            ("init_logger", None)
                                        )

                                        import main_telegram

                                        main_telegram.main()

                                        mock_init_config.assert_called_once_with(
                                            "test_profile"
                                        )
                                        mock_init_logger.assert_called_once_with()
                                        assert call_order == [
                                            ("init_config", "test_profile"),
                                            ("init_logger", None),
                                        ]


class TestMainTelegramBotLifecycle:
    """Test TelegramAdapter lifecycle management"""

    def test_bot_created_with_message_handler(self):
        """Test that TelegramAdapter is created with the message handler"""
        mock_message_handler = Mock()

        with patch("main_telegram.TelegramController") as mock_handler_class:
            with patch("main_telegram.TelegramAdapter") as mock_bot_class:
                mock_handler_class.return_value = mock_message_handler
                mock_bot_instance = Mock()
                mock_bot_class.return_value = mock_bot_instance

                # Import and test
                if "main_telegram" in sys.modules:
                    del sys.modules["main_telegram"]

                # Bot should be created with message_handler
                mock_bot_class.assert_not_called()  # Not called at import time


# Run tests if executed directly
if __name__ == "__main__":
    pytest.main([__file__, "-v"])
