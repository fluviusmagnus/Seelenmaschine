import pytest
from unittest.mock import Mock, patch, AsyncMock

from llm.reranker import RerankerClient


@pytest.fixture
def mock_config():
    """Mock Config for tests."""
    with patch("llm.reranker.Config") as mock:
        mock.RERANK_API_KEY = "test-rerank-key"
        mock.RERANK_API_BASE = "https://test-rerank.api.com/v1"
        mock.RERANK_MODEL = "test-reranker-model"
        yield mock


@pytest.fixture
def reranker_client(mock_config):
    """Create RerankerClient with mocked config."""
    return RerankerClient()


@pytest.fixture
def disabled_reranker():
    """Create disabled RerankerClient."""
    with patch("llm.reranker.Config") as mock:
        mock.RERANK_API_KEY = ""
        mock.RERANK_API_BASE = ""
        mock.RERANK_MODEL = ""
        client = RerankerClient()
        yield client


class TestRerankerClient:
    """Test RerankerClient functionality."""

    def test_initialization_enabled(self, mock_config):
        """Test initialization with all required config."""
        client = RerankerClient()
        assert client.api_key == "test-rerank-key"
        assert client.base_url == "https://test-rerank.api.com/v1"
        assert client.model == "test-reranker-model"
        assert client._enabled is True
        assert client._client is None
        assert client._loop is None

    def test_initialization_custom_values(self, mock_config):
        """Test initialization with custom values."""
        client = RerankerClient(
            api_key="custom-key",
            base_url="https://custom.api.com/v1",
            model="custom-model",
        )
        assert client.api_key == "custom-key"
        assert client.base_url == "https://custom.api.com/v1"
        assert client.model == "custom-model"
        assert client._enabled is True

    def test_initialization_disabled(self, disabled_reranker):
        """Test initialization when disabled (missing config)."""
        assert disabled_reranker.api_key == ""
        assert disabled_reranker.base_url == ""
        assert disabled_reranker.model == ""
        assert disabled_reranker._enabled is False

    def test_is_enabled(self, reranker_client, disabled_reranker):
        """Test is_enabled method."""
        assert reranker_client.is_enabled() is True
        assert disabled_reranker.is_enabled() is False

    def test_get_event_loop_creates_new_loop(self, reranker_client):
        """Test _get_event_loop creates new loop if needed."""
        loop = reranker_client._get_event_loop()
        assert loop is not None
        assert not loop.is_closed()

    def test_get_event_loop_reuses_existing_loop(self, reranker_client):
        """Test _get_event_loop reuses existing loop."""
        loop1 = reranker_client._get_event_loop()
        loop2 = reranker_client._get_event_loop()
        assert loop1 is loop2

    def test_ensure_client_initialized(self, reranker_client):
        """Test _ensure_client_initialized creates httpx client."""
        with patch("llm.reranker.httpx.AsyncClient") as mock_client:
            mock_instance = Mock()
            mock_client.return_value = mock_instance

            reranker_client._ensure_client_initialized()

            assert reranker_client._client is not None
            mock_client.assert_called_once_with(
                headers={
                    "Authorization": "Bearer test-rerank-key",
                    "Content-Type": "application/json",
                },
                timeout=30.0,
            )

    def test_ensure_client_initialized_idempotent(self, reranker_client):
        """Test _ensure_client_initialized doesn't recreate client."""
        with patch("llm.reranker.httpx.AsyncClient") as mock_client:
            mock_instance = Mock()
            mock_client.return_value = mock_instance

            reranker_client._ensure_client_initialized()
            call_count_1 = mock_client.call_count

            reranker_client._ensure_client_initialized()
            call_count_2 = mock_client.call_count

            assert call_count_1 == call_count_2

    def test_ensure_client_initialized_when_disabled(self, disabled_reranker):
        """Test _ensure_client_initialized raises when disabled."""
        with pytest.raises(ValueError, match="Reranker is not enabled"):
            disabled_reranker._ensure_client_initialized()

    @pytest.mark.asyncio
    async def test_async_rerank_success(self, reranker_client):
        """Test successful async rerank."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "results": [
                {"index": 2, "relevance_score": 0.95},
                {"index": 0, "relevance_score": 0.80},
                {"index": 1, "relevance_score": 0.60},
            ]
        }

        documents = [
            {"text": "Doc 1", "id": 1},
            {"text": "Doc 2", "id": 2},
            {"text": "Doc 3", "id": 3},
        ]

        with patch.object(reranker_client, "_ensure_client_initialized"):
            reranker_client._client = AsyncMock()
            reranker_client._client.post = AsyncMock(return_value=mock_response)

            result = await reranker_client._async_rerank("query", documents, top_n=2)

            assert len(result) == 2
            assert result[0]["text"] == "Doc 3"
            assert result[1]["text"] == "Doc 1"

    @pytest.mark.asyncio
    async def test_async_rerank_empty_documents(self, reranker_client):
        """Test async rerank with empty documents."""
        result = await reranker_client._async_rerank("query", [], top_n=5)
        assert result == []

    @pytest.mark.asyncio
    async def test_async_rerank_disabled(self, disabled_reranker):
        """Test async rerank when disabled returns original."""
        documents = [{"text": "Doc 1"}, {"text": "Doc 2"}]
        result = await disabled_reranker._async_rerank("query", documents, top_n=1)
        assert result == [{"text": "Doc 1"}]

    @pytest.mark.asyncio
    async def test_async_rerank_api_error(self, reranker_client):
        """Test async rerank with API error."""
        mock_response = Mock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"

        documents = [{"text": "Doc 1"}, {"text": "Doc 2"}]

        with patch.object(reranker_client, "_ensure_client_initialized"):
            reranker_client._client = AsyncMock()
            reranker_client._client.post = AsyncMock(return_value=mock_response)

            result = await reranker_client._async_rerank("query", documents)

            assert result == documents

    @pytest.mark.asyncio
    async def test_async_rerank_unexpected_response_format(self, reranker_client):
        """Test async rerank with unexpected response format."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"unexpected": "format"}

        documents = [{"text": "Doc 1"}, {"text": "Doc 2"}]

        with patch.object(reranker_client, "_ensure_client_initialized"):
            reranker_client._client = AsyncMock()
            reranker_client._client.post = AsyncMock(return_value=mock_response)

            result = await reranker_client._async_rerank("query", documents)

            assert result == documents

    @pytest.mark.asyncio
    async def test_async_rerank_exception(self, reranker_client):
        """Test async rerank with exception."""
        documents = [{"text": "Doc 1"}, {"text": "Doc 2"}]

        with patch.object(reranker_client, "_ensure_client_initialized"):
            reranker_client._client = AsyncMock()
            reranker_client._client.post = AsyncMock(
                side_effect=Exception("Network error")
            )

            result = await reranker_client._async_rerank("query", documents)

            assert result == documents

    def test_rerank_sync(self, reranker_client):
        """Test synchronous rerank."""
        documents = [{"text": "Doc 1"}, {"text": "Doc 2"}]

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "results": [
                {"index": 1, "relevance_score": 0.90},
                {"index": 0, "relevance_score": 0.70},
            ]
        }

        with patch.object(reranker_client, "_ensure_client_initialized"):
            reranker_client._client = AsyncMock()
            reranker_client._client.post = AsyncMock(return_value=mock_response)

            result = reranker_client.rerank("query", documents)

            assert len(result) == 2
            assert result[0]["text"] == "Doc 2"
            assert result[1]["text"] == "Doc 1"

    def test_rerank_sync_disabled(self, disabled_reranker):
        """Test sync rerank when disabled."""
        documents = [{"text": "Doc 1"}, {"text": "Doc 2"}]
        result = disabled_reranker.rerank("query", documents, top_n=1)
        assert result == [{"text": "Doc 1"}]

    def test_rerank_sync_no_top_n(self, reranker_client):
        """Test sync rerank without top_n parameter."""
        documents = [{"text": "Doc 1"}, {"text": "Doc 2"}, {"text": "Doc 3"}]

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "results": [
                {"index": 2, "relevance_score": 0.95},
                {"index": 1, "relevance_score": 0.80},
                {"index": 0, "relevance_score": 0.60},
            ]
        }

        with patch.object(reranker_client, "_ensure_client_initialized"):
            reranker_client._client = AsyncMock()
            reranker_client._client.post = AsyncMock(return_value=mock_response)

            result = reranker_client.rerank("query", documents)

            assert len(result) == 3

    @pytest.mark.asyncio
    async def test_rerank_async(self, reranker_client):
        """Test asynchronous rerank."""
        documents = [{"text": "Doc 1"}, {"text": "Doc 2"}]

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "results": [
                {"index": 0, "relevance_score": 0.90},
                {"index": 1, "relevance_score": 0.70},
            ]
        }

        with patch.object(reranker_client, "_ensure_client_initialized"):
            reranker_client._client = AsyncMock()
            reranker_client._client.post = AsyncMock(return_value=mock_response)

            result = await reranker_client.rerank_async("query", documents)

            assert len(result) == 2
            assert result[0]["text"] == "Doc 1"
            assert result[1]["text"] == "Doc 2"

    def test_close(self, reranker_client):
        """Test closing client."""
        import asyncio

        mock_client = Mock()
        mock_client.aclose = AsyncMock()
        reranker_client._client = mock_client
        reranker_client._loop = asyncio.new_event_loop()

        reranker_client.close()

        # Verify the client was set to None after close
        assert reranker_client._client is None

        if not reranker_client._loop.is_closed():
            reranker_client._loop.close()

    def test_close_when_no_client(self, reranker_client):
        """Test close when no client exists."""
        reranker_client._client = None
        reranker_client.close()

    def test_rerank_in_async_context_raises(self, reranker_client):
        """Test rerank raises RuntimeError in async context."""

        async def async_func():
            with pytest.raises(
                RuntimeError, match="rerank\\(\\) called from async context"
            ):
                reranker_client.rerank("query", [])

        import asyncio

        asyncio.run(async_func())
