"""Tests for platform-neutral adapter runtime contracts."""

from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest


@pytest.mark.asyncio
async def test_core_bot_create_async_runs_memory_bootstrap_once():
    """Async factory should own startup bootstrap without work in __init__."""
    from core.bot import CoreBot

    memory = Mock()
    memory.ensure_long_term_memory_schema_async = AsyncMock(return_value=True)
    memory.ensure_session_snapshot_current = Mock()

    core_bot = await CoreBot.create_async(
        config=Mock(),
        db=Mock(),
        embedding_client=Mock(),
        reranker_client=Mock(),
        memory=memory,
        scheduler=Mock(),
        llm_client=Mock(),
    )
    await core_bot.initialize_async()

    memory.ensure_long_term_memory_schema_async.assert_awaited_once_with()
    memory.ensure_session_snapshot_current.assert_called_once_with()


@pytest.mark.asyncio
async def test_core_runtime_initializes_with_fake_adapter_capabilities():
    """Core runtime should initialize without any Telegram-specific object."""
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

    core_bot.initialize_adapter_runtime(
        approval_delegate=approval_delegate,
        preview_text=lambda text, max_length=120: str(text)[:max_length],
        send_file_to_user=send_file_to_user,
        send_status_message=send_status_message,
    )

    assert core_bot._tool_runtime_initialized is True
    llm_client.set_tools.assert_called()
    llm_client.set_tool_executor.assert_called_once_with(core_bot.execute_tool)


@pytest.mark.asyncio
async def test_core_execute_tool_uses_live_runtime_providers_without_executor_resync():
    """CoreBot.execute_tool should use current runtime providers without mutating executor fields."""
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
    first_status_message = AsyncMock()

    core_bot.initialize_adapter_runtime(
        approval_delegate=approval_delegate,
        preview_text=lambda text, max_length=120: str(text)[:max_length],
        send_file_to_user=send_file_to_user,
        send_status_message=first_status_message,
    )

    read_tool = Mock()
    read_tool.execute = AsyncMock(return_value="content")
    core_bot.registry_service.register_named("read_file", read_tool)

    second_status_message = AsyncMock()
    core_bot._send_status_message = second_status_message

    await core_bot.execute_tool("read_file", '{"file_path": "notes.txt"}')
    await __import__("asyncio").sleep(0)

    second_status_message.assert_awaited()
