import pytest
from unittest.mock import Mock, AsyncMock, patch
from core.memory import MemoryManager
from llm.embedding import EmbeddingClient
from core.database import DatabaseManager
from core.retriever import MemoryRetriever


@pytest.fixture
def mock_db():
    db = Mock(spec=DatabaseManager)
    db.get_active_session.return_value = {"session_id": 1}
    db.get_summaries_by_session.return_value = []
    db.get_unsummarized_conversations.return_value = []
    db.insert_conversation.return_value = 1
    db.search_summaries.return_value = []
    return db


@pytest.fixture
def mock_reranker():
    return Mock()


@pytest.mark.asyncio
async def test_embedding_client_cache():
    """Test that EmbeddingClient indeed caches results."""
    client = EmbeddingClient(api_key="test", base_url="https://api.test", model="test")
    client._client = AsyncMock()

    mock_embedding = [0.1] * 1536
    client._client.embeddings.create.return_value = Mock(
        data=[Mock(embedding=mock_embedding)]
    )

    # First call - should call API
    emb1 = await client.get_embedding_async("hello")
    assert emb1 == mock_embedding
    assert client._client.embeddings.create.call_count == 1

    # Second call - should hit cache
    emb2 = await client.get_embedding_async("hello")
    assert emb2 == mock_embedding
    assert client._client.embeddings.create.call_count == 1

    # Different text - should call API
    await client.get_embedding_async("world")
    assert client._client.embeddings.create.call_count == 2


@pytest.mark.asyncio
async def test_memory_manager_embedding_reuse(mock_db, mock_reranker):
    """Test that MemoryManager reuses embeddings from context window."""
    embedding_client = EmbeddingClient(
        api_key="test", base_url="https://api.test", model="test"
    )
    embedding_client._client = AsyncMock()

    mock_embedding = [0.1] * 1536
    embedding_client._client.embeddings.create.return_value = Mock(
        data=[Mock(embedding=mock_embedding)]
    )

    mm = MemoryManager(mock_db, embedding_client, mock_reranker)

    # 1. Add user message
    user_text = "Hello bot"
    await mm.add_user_message_async(user_text)

    # API should have been called once for user message
    assert embedding_client._client.embeddings.create.call_count == 1

    # 2. Process user input
    # This should reuse the embedding from the context window for user_input
    # and should NOT call API for last_bot_message if none exists
    with patch.object(
        mm.retriever,
        "retrieve_related_memories_async",
        AsyncMock(return_value=([], [])),
    ) as mock_retrieve:
        await mm.process_user_input_async(user_text)

        # Check if retrieve was called with the pre-computed embedding
        args, kwargs = mock_retrieve.call_args
        assert kwargs["query_embedding"] == mock_embedding

    # API call count should still be 1 (because of caching and context reuse)
    assert embedding_client._client.embeddings.create.call_count == 1


@pytest.mark.asyncio
async def test_dual_query_embedding_reuse(mock_db, mock_reranker):
    """Test that dual-query retrieval reuses assistant message embedding."""
    embedding_client = EmbeddingClient(
        api_key="test", base_url="https://api.test", model="test"
    )
    embedding_client._client = AsyncMock()

    user_emb = [0.1] * 1536
    bot_emb = [0.2] * 1536

    # Mock responses for two different texts
    async def side_effect(model, input):
        if input == "User query":
            return Mock(data=[Mock(embedding=user_emb)])
        else:
            return Mock(data=[Mock(embedding=bot_emb)])

    embedding_client._client.embeddings.create.side_effect = side_effect

    mm = MemoryManager(mock_db, embedding_client, mock_reranker)

    # Step 1: Add assistant message (this computes and stores bot_emb)
    await mm.add_assistant_message_async("I am a bot")
    assert embedding_client._client.embeddings.create.call_count == 1

    # Step 2: Add user message (this computes and stores user_emb)
    # We pass it explicitly to simulate the flow in handlers.py
    _, user_embedding = await mm.add_user_message_async("User query")
    assert embedding_client._client.embeddings.create.call_count == 2

    # Step 3: Process user input
    # It should reuse bot_emb from context window
    with patch.object(
        mm.retriever,
        "retrieve_related_memories_async",
        AsyncMock(return_value=([], [])),
    ) as mock_retrieve:
        await mm.process_user_input_async(
            "User query",
            last_bot_message="I am a bot",
            user_input_embedding=user_embedding,
        )

        # Verify both embeddings were reused
        kwargs = mock_retrieve.call_args[1]
        assert kwargs["query_embedding"] == user_emb
        assert kwargs["last_bot_embedding"] == bot_emb

    # Total API calls should still be 2
    assert embedding_client._client.embeddings.create.call_count == 2
