"""Tests for platform-neutral adapter runtime contracts."""

from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest


@pytest.mark.asyncio
async def test_core_runtime_initializes_with_fake_adapter_capabilities():
    """Core runtime should initialize without any Telegram-specific object."""
    from core.adapter_contracts import AdapterRuntimeCapabilities
    from core.bot import CoreBot

    config = Mock()
    config.ENABLE_MCP = False
    config.DATA_DIR = Path("data/test")
    config.WORKSPACE_DIR = Path("data/test/workspace")
    config.MEDIA_DIR = Path("data/test/workspace/media")

    memory = Mock()
    memory.get_current_session_id.return_value = 1

    llm_client = Mock()
    llm_client.set_tools = Mock()
    llm_client.set_tool_executor = Mock()

    core_bot = CoreBot(
        config=config,
        db=Mock(),
        embedding_client=Mock(),
        reranker_client=Mock(),
        memory=memory,
        scheduler=Mock(),
        llm_client=llm_client,
    )

    approval_delegate = Mock()
    approval_delegate.request_approval = AsyncMock(return_value=True)
    approval_delegate.notify_approved_action_finished = AsyncMock()
    approval_delegate.notify_approved_action_failed = AsyncMock()

    send_file_to_user = AsyncMock(return_value={"result": "sent"})
    send_status_message = AsyncMock()
    capabilities = AdapterRuntimeCapabilities(
        preview_text=lambda text, max_length=120: str(text)[:max_length],
        send_file_to_user=send_file_to_user,
        send_status_message=send_status_message,
    )

    core_bot.initialize_adapter_runtime(
        approval_delegate=approval_delegate,
        capabilities=capabilities,
    )

    assert core_bot.get_tool_runtime() is not None
    assert core_bot.get_tool_executor_service() is not None
    llm_client.set_tools.assert_called()
    llm_client.set_tool_executor.assert_called_once_with(core_bot.execute_tool)