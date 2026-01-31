import pytest
from unittest.mock import Mock, patch
from core.memory import MemoryManager
from config import Config


@pytest.fixture
def mock_deps():
    db = Mock()
    db.get_active_session.return_value = {"session_id": 1}
    db.get_summaries_by_session.return_value = []
    db.get_unsummarized_conversations.return_value = []

    embedding_client = Mock()
    embedding_client.get_embedding.return_value = [0.1] * 1536

    # Use AsyncMock for async methods
    embedding_client.get_embedding_async = Mock()
    embedding_client.get_embedding_async.return_value = [0.1] * 1536

    reranker_client = Mock()
    return db, embedding_client, reranker_client


def test_add_assistant_message_strips_blockquote_when_debug_off(mock_deps, monkeypatch):
    db, embedding_client, reranker_client = mock_deps
    monkeypatch.setattr(Config, "DEBUG_MODE", False)

    # Mock Config trigger to avoid summarization logic cluttering the test
    monkeypatch.setattr(Config, "CONTEXT_WINDOW_TRIGGER_SUMMARY", 100)

    memory = MemoryManager(db, embedding_client, reranker_client)

    text = "Reply <blockquote>thought</blockquote> here"
    memory.add_assistant_message(text)

    # Check what was saved to DB
    insert_call = db.insert_conversation.call_args
    saved_text = insert_call[1]["text"]
    assert "<blockquote>" not in saved_text
    assert "thought" not in saved_text
    assert saved_text == "Reply  here"

    # Check what was passed to embedding (should always be stripped)
    embedding_call = embedding_client.get_embedding.call_args
    embedded_text = embedding_call[0][0]
    assert embedded_text == "Reply  here"


def test_add_assistant_message_keeps_blockquote_when_debug_on(mock_deps, monkeypatch):
    db, embedding_client, reranker_client = mock_deps
    monkeypatch.setattr(Config, "DEBUG_MODE", True)
    monkeypatch.setattr(Config, "CONTEXT_WINDOW_TRIGGER_SUMMARY", 100)

    memory = MemoryManager(db, embedding_client, reranker_client)

    text = "Reply <blockquote>thought</blockquote> here"
    memory.add_assistant_message(text)

    # Check what was saved to DB (should keep blockquote)
    insert_call = db.insert_conversation.call_args
    saved_text = insert_call[1]["text"]
    assert "<blockquote>thought</blockquote>" in saved_text

    # Check what was passed to embedding (should ALWAYS be stripped)
    embedding_call = embedding_client.get_embedding.call_args
    embedded_text = embedding_call[0][0]
    assert "<blockquote>" not in embedded_text
    assert embedded_text == "Reply  here"


def test_add_user_message_always_strips_for_embedding(mock_deps, monkeypatch):
    db, embedding_client, reranker_client = mock_deps
    memory = MemoryManager(db, embedding_client, reranker_client)

    text = "User message <blockquote>not possible but test</blockquote>"
    memory.add_user_message(text)

    # User message storage should NOT be stripped (though it usually doesn't have blockquotes)
    insert_call = db.insert_conversation.call_args
    saved_text = insert_call[1]["text"]
    assert "<blockquote>" in saved_text

    # But embedding should be stripped
    embedding_call = embedding_client.get_embedding.call_args
    embedded_text = embedding_call[0][0]
    assert "<blockquote>" not in embedded_text
    assert embedded_text == "User message"
