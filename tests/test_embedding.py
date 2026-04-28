import pytest
from unittest.mock import Mock, patch, AsyncMock

from llm.embedding import EmbeddingClient


@pytest.fixture
def mock_config():
    """Mock Config for tests."""
    with patch("llm.embedding.Config") as mock:
        mock.EMBEDDING_API_KEY = "test-api-key"
        mock.EMBEDDING_API_BASE = "https://test.api.com/v1"
        mock.EMBEDDING_MODEL = "test-embedding-model"
        mock.EMBEDDING_DIMENSION = 768
        mock.EMBEDDING_CACHE_MAX_ENTRIES = 2048
        yield mock


@pytest.fixture
def embedding_client(mock_config):
    """Create EmbeddingClient with mocked config."""
    return EmbeddingClient()


class TestEmbeddingClient:
    """Test EmbeddingClient functionality."""

    def test_initialization_defaults(self, mock_config):
        """Test initialization with default config values."""
        client = EmbeddingClient()
        assert client.api_key == "test-api-key"
        assert client.base_url == "https://test.api.com/v1"
        assert client.model == "test-embedding-model"
        assert client.dimension == 768
        assert client.cache_max_entries == 2048
        assert client._client is None

    def test_initialization_custom_values(self, mock_config):
        """Test initialization with custom values."""
        client = EmbeddingClient(
            api_key="custom-key",
            base_url="https://custom.api.com/v1",
            model="custom-model",
        )
        assert client.api_key == "custom-key"
        assert client.base_url == "https://custom.api.com/v1"
        assert client.model == "custom-model"

    def test_ensure_client_initialized(self, embedding_client):
        """Test _ensure_client_initialized creates client."""
        with patch("llm.embedding.AsyncOpenAI") as mock_openai:
            mock_client = Mock()
            mock_openai.return_value = mock_client

            embedding_client._ensure_client_initialized()

            assert embedding_client._client is not None
            mock_openai.assert_called_once_with(
                api_key="test-api-key", base_url="https://test.api.com/v1"
            )

    def test_ensure_client_initialized_idempotent(self, embedding_client):
        """Test _ensure_client_initialized doesn't recreate client."""
        with patch("llm.embedding.AsyncOpenAI") as mock_openai:
            mock_client = Mock()
            mock_openai.return_value = mock_client

            embedding_client._ensure_client_initialized()
            call_count_1 = mock_openai.call_count

            embedding_client._ensure_client_initialized()
            call_count_2 = mock_openai.call_count

            assert call_count_1 == call_count_2

    @pytest.mark.asyncio
    async def test_get_embedding_error_handling(self, embedding_client):
        """Test get_embedding_async raises on API error."""
        with patch.object(embedding_client, "_ensure_client_initialized"):
            embedding_client._client = AsyncMock()
            embedding_client._client.embeddings.create = AsyncMock(
                side_effect=Exception("API Error")
            )

            with pytest.raises(Exception, match="API Error"):
                await embedding_client.get_embedding_async("test text")

    @pytest.mark.asyncio
    async def test_get_embedding_async(self, embedding_client):
        """Test asynchronous get_embedding_async."""
        mock_response = Mock()
        mock_response.data = [Mock()]
        mock_response.data[0].embedding = [0.1] * 768

        with patch.object(embedding_client, "_ensure_client_initialized"):
            embedding_client._client = AsyncMock()
            embedding_client._client.embeddings.create = AsyncMock(
                return_value=mock_response
            )

            embedding = await embedding_client.get_embedding_async("test text")

            assert len(embedding) == 768
            embedding_client._client.embeddings.create.assert_awaited_once_with(
                model="test-embedding-model", input="test text"
            )

    @pytest.mark.asyncio
    async def test_get_embedding_async_dimension_mismatch(self, embedding_client):
        """Test get_embedding_async handles dimension mismatch."""
        mock_response = Mock()
        mock_response.data = [Mock()]
        mock_response.data[0].embedding = [0.1] * 512

        with patch.object(embedding_client, "_ensure_client_initialized"):
            embedding_client._client = AsyncMock()
            embedding_client._client.embeddings.create = AsyncMock(
                return_value=mock_response
            )

            embedding = await embedding_client.get_embedding_async("test text")

            assert len(embedding) == 512

    @pytest.mark.asyncio
    async def test_get_embeddings_batch_async_multiple(self, embedding_client):
        """Test get_embeddings_batch_async with multiple inputs."""
        mock_response = Mock()
        mock_response.data = [
            Mock(embedding=[0.1] * 768),
            Mock(embedding=[0.2] * 768),
            Mock(embedding=[0.3] * 768),
        ]

        with patch.object(embedding_client, "_ensure_client_initialized"):
            embedding_client._client = AsyncMock()
            embedding_client._client.embeddings.create = AsyncMock(
                return_value=mock_response
            )

            embeddings = await embedding_client.get_embeddings_batch_async(
                ["text1", "text2", "text3"]
            )

            assert len(embeddings) == 3
            assert all(len(emb) == 768 for emb in embeddings)

    @pytest.mark.asyncio
    async def test_get_embeddings_batch_async_empty(self, embedding_client):
        """Test get_embeddings_batch_async with empty list."""
        embeddings = await embedding_client.get_embeddings_batch_async([])
        assert embeddings == []

    @pytest.mark.asyncio
    async def test_get_embeddings_batch_async_dimension_mismatch(
        self, embedding_client
    ):
        """Test get_embeddings_batch_async handles dimension mismatch."""
        mock_response = Mock()
        mock_response.data = [
            Mock(embedding=[0.1] * 768),
            Mock(embedding=[0.2] * 512),
            Mock(embedding=[0.3] * 768),
        ]

        with patch.object(embedding_client, "_ensure_client_initialized"):
            embedding_client._client = AsyncMock()
            embedding_client._client.embeddings.create = AsyncMock(
                return_value=mock_response
            )

            embeddings = await embedding_client.get_embeddings_batch_async(
                ["text1", "text2", "text3"]
            )

            assert len(embeddings) == 3
            assert len(embeddings[1]) == 512

    @pytest.mark.asyncio
    async def test_get_embeddings_batch_async(self, embedding_client):
        """Test asynchronous get_embeddings_batch_async."""
        mock_response = Mock()
        mock_response.data = [Mock(embedding=[0.1] * 768), Mock(embedding=[0.2] * 768)]

        with patch.object(embedding_client, "_ensure_client_initialized"):
            embedding_client._client = AsyncMock()
            embedding_client._client.embeddings.create = AsyncMock(
                return_value=mock_response
            )

            embeddings = await embedding_client.get_embeddings_batch_async(
                ["text1", "text2"]
            )

            assert len(embeddings) == 2
            embedding_client._client.embeddings.create.assert_awaited_once_with(
                model="test-embedding-model", input=["text1", "text2"]
            )

    @pytest.mark.asyncio
    async def test_embedding_cache_evicts_oldest_entry(self, mock_config):
        """Embedding cache should be bounded to avoid unbounded process growth."""
        mock_config.EMBEDDING_CACHE_MAX_ENTRIES = 2
        client = EmbeddingClient()
        responses = [
            Mock(data=[Mock(embedding=[0.1] * 768)]),
            Mock(data=[Mock(embedding=[0.2] * 768)]),
            Mock(data=[Mock(embedding=[0.3] * 768)]),
        ]

        with patch.object(client, "_ensure_client_initialized"):
            client._client = AsyncMock()
            client._client.embeddings.create = AsyncMock(side_effect=responses)

            await client.get_embedding_async("text1")
            await client.get_embedding_async("text2")
            await client.get_embedding_async("text3")

        assert list(client._cache.keys()) == ["text2", "text3"]

    @pytest.mark.asyncio
    async def test_embedding_cache_hit_refreshes_lru_order(self, mock_config):
        """Recently used entries should survive later insertions."""
        mock_config.EMBEDDING_CACHE_MAX_ENTRIES = 2
        client = EmbeddingClient()
        responses = [
            Mock(data=[Mock(embedding=[0.1] * 768)]),
            Mock(data=[Mock(embedding=[0.2] * 768)]),
            Mock(data=[Mock(embedding=[0.3] * 768)]),
        ]

        with patch.object(client, "_ensure_client_initialized"):
            client._client = AsyncMock()
            client._client.embeddings.create = AsyncMock(side_effect=responses)

            await client.get_embedding_async("text1")
            await client.get_embedding_async("text2")
            await client.get_embedding_async("text1")
            await client.get_embedding_async("text3")

        assert list(client._cache.keys()) == ["text1", "text3"]
        assert client._client.embeddings.create.await_count == 3

    @pytest.mark.asyncio
    async def test_embedding_cache_can_be_disabled(self, mock_config):
        """A zero cache size should keep behavior correct while storing nothing."""
        mock_config.EMBEDDING_CACHE_MAX_ENTRIES = 0
        client = EmbeddingClient()
        mock_response = Mock(data=[Mock(embedding=[0.1] * 768)])

        with patch.object(client, "_ensure_client_initialized"):
            client._client = AsyncMock()
            client._client.embeddings.create = AsyncMock(return_value=mock_response)

            await client.get_embedding_async("text1")
            await client.get_embedding_async("text1")

        assert client._cache == {}
        assert client._client.embeddings.create.await_count == 2

    @pytest.mark.asyncio
    async def test_close_async(self, embedding_client):
        """Async close should close the underlying client."""
        mock_client = Mock()
        mock_client.close = AsyncMock()
        embedding_client._client = mock_client

        await embedding_client.close_async()

        mock_client.close.assert_awaited_once()
        assert embedding_client._client is None
