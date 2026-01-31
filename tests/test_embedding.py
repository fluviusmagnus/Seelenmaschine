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
        assert client._client is None
        assert client._loop is None

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

    def test_get_event_loop_creates_new_loop(self, embedding_client):
        """Test _get_event_loop creates new loop if needed."""
        loop = embedding_client._get_event_loop()
        assert loop is not None
        assert not loop.is_closed()

    def test_get_event_loop_reuses_existing_loop(self, embedding_client):
        """Test _get_event_loop reuses existing loop."""
        loop1 = embedding_client._get_event_loop()
        loop2 = embedding_client._get_event_loop()
        assert loop1 is loop2

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

    def test_get_embedding_sync(self, embedding_client):
        """Test synchronous get_embedding."""
        mock_response = Mock()
        mock_response.data = [Mock()]
        mock_response.data[0].embedding = [0.1] * 768

        with patch.object(embedding_client, "_ensure_client_initialized"):
            embedding_client._client = AsyncMock()
            embedding_client._client.embeddings.create = AsyncMock(
                return_value=mock_response
            )

            embedding = embedding_client.get_embedding("test text")

            assert len(embedding) == 768
            assert all(isinstance(x, float) for x in embedding)

    def test_get_embedding_dimension_mismatch(self, embedding_client, caplog):
        """Test get_embedding logs warning on dimension mismatch."""
        mock_response = Mock()
        mock_response.data = [Mock()]
        mock_response.data[0].embedding = [0.1] * 512

        with patch.object(embedding_client, "_ensure_client_initialized"):
            embedding_client._client = AsyncMock()
            embedding_client._client.embeddings.create = AsyncMock(
                return_value=mock_response
            )

            embedding = embedding_client.get_embedding("test text")

            assert len(embedding) == 512

    def test_get_embedding_error_handling(self, embedding_client):
        """Test get_embedding raises on API error."""
        with patch.object(embedding_client, "_ensure_client_initialized"):
            embedding_client._client = AsyncMock()
            embedding_client._client.embeddings.create = AsyncMock(
                side_effect=Exception("API Error")
            )

            with pytest.raises(Exception, match="API Error"):
                embedding_client.get_embedding("test text")

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

    def test_get_embeddings_batch_sync(self, embedding_client):
        """Test synchronous get_embeddings_batch."""
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

            embeddings = embedding_client.get_embeddings_batch(
                ["text1", "text2", "text3"]
            )

            assert len(embeddings) == 3
            assert all(len(emb) == 768 for emb in embeddings)

    def test_get_embeddings_batch_empty(self, embedding_client):
        """Test get_embeddings_batch with empty list."""
        embeddings = embedding_client.get_embeddings_batch([])
        assert embeddings == []

    def test_get_embeddings_batch_dimension_mismatch(self, embedding_client):
        """Test get_embeddings_batch handles dimension mismatch."""
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

            embeddings = embedding_client.get_embeddings_batch(
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
    async def test_get_embeddings_batch_async_empty(self, embedding_client):
        """Test get_embeddings_batch_async with empty list."""
        embeddings = await embedding_client.get_embeddings_batch_async([])
        assert embeddings == []

    def test_close(self, embedding_client):
        """Test closing client."""
        import asyncio

        mock_client = Mock()
        mock_client.close = AsyncMock()
        embedding_client._client = mock_client
        embedding_client._loop = asyncio.new_event_loop()

        embedding_client.close()

        # Verify the client was set to None after close
        assert embedding_client._client is None

        if not embedding_client._loop.is_closed():
            embedding_client._loop.close()

    def test_close_when_no_client(self, embedding_client):
        """Test close when no client exists."""
        embedding_client._client = None
        embedding_client.close()

    def test_get_embedding_in_async_context_raises(self, embedding_client):
        """Test get_embedding raises RuntimeError in async context."""

        async def async_func():
            with pytest.raises(
                RuntimeError, match="get_embedding\\(\\) called from async context"
            ):
                embedding_client.get_embedding("test")

        import asyncio

        asyncio.run(async_func())

    def test_get_embeddings_batch_in_async_context_raises(self, embedding_client):
        """Test get_embeddings_batch raises RuntimeError in async context."""

        async def async_func():
            with pytest.raises(
                RuntimeError,
                match="get_embeddings_batch\\(\\) called from async context",
            ):
                embedding_client.get_embeddings_batch(["test"])

        import asyncio

        asyncio.run(async_func())
