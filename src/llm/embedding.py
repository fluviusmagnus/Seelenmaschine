import asyncio
from typing import List, Optional, Dict, cast
from openai import AsyncOpenAI

from config import Config
from utils.logger import get_logger

logger = get_logger()


class EmbeddingClient:
    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
    ):
        self.api_key = api_key or Config.EMBEDDING_API_KEY
        self.base_url = base_url or Config.EMBEDDING_API_BASE
        self.model = model or Config.EMBEDDING_MODEL
        self.dimension = Config.EMBEDDING_DIMENSION

        self._client: Optional[AsyncOpenAI] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._cache: Dict[str, List[float]] = {}

    def _get_event_loop(self) -> asyncio.AbstractEventLoop:
        if self._loop is None or self._loop.is_closed():
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
        return self._loop

    def _ensure_client_initialized(self) -> None:
        if self._client is None:
            self._client = AsyncOpenAI(api_key=self.api_key, base_url=self.base_url)
            logger.info(f"Initialized EmbeddingClient: {self.model}")

    async def _async_get_embedding(self, text: str) -> List[float]:
        if text in self._cache:
            logger.debug(f"Embedding cache hit for text length: {len(text)}")
            return self._cache[text]

        self._ensure_client_initialized()

        try:
            response = await self._client.embeddings.create(
                model=self.model, input=text
            )
            embedding = response.data[0].embedding

            if len(embedding) != self.dimension:
                logger.warning(
                    f"Embedding dimension mismatch: expected {self.dimension}, got {len(embedding)}"
                )

            self._cache[text] = embedding
            return embedding
        except Exception as e:
            logger.error(f"Failed to get embedding: {e}")
            raise

    def get_embedding(self, text: str) -> List[float]:
        """Synchronous wrapper for get_embedding. Use get_embedding_async in async contexts."""
        try:
            # Check if we're in an event loop
            loop = asyncio.get_running_loop()
            # If we get here, we're in an async context - this shouldn't be called
            raise RuntimeError(
                "get_embedding() called from async context. Use await get_embedding_async() instead."
            )
        except RuntimeError as e:
            if "no running event loop" in str(e).lower():
                # We're in sync context, safe to use run_until_complete
                loop = self._get_event_loop()
                return loop.run_until_complete(self._async_get_embedding(text))
            else:
                raise

    async def get_embedding_async(self, text: str) -> List[float]:
        """Async method for getting embeddings. Use this in async contexts."""
        return await self._async_get_embedding(text)

    async def _async_get_embeddings_batch(self, texts: List[str]) -> List[List[float]]:
        if not texts:
            return []

        results = [None] * len(texts)
        missing_indices = []
        missing_texts = []

        for i, text in enumerate(texts):
            if text in self._cache:
                results[i] = self._cache[text]
            else:
                missing_indices.append(i)
                missing_texts.append(text)

        if not missing_texts:
            logger.debug(f"Full embedding batch cache hit for {len(texts)} texts")
            return cast(List[List[float]], results)

        self._ensure_client_initialized()

        try:
            response = await self._client.embeddings.create(
                model=self.model, input=missing_texts
            )

            new_embeddings = [item.embedding for item in response.data]

            for i, idx in enumerate(missing_indices):
                embedding = new_embeddings[i]
                if len(embedding) != self.dimension:
                    logger.warning(
                        f"Embedding {idx} dimension mismatch: expected {self.dimension}, got {len(embedding)}"
                    )
                self._cache[missing_texts[i]] = embedding
                results[idx] = embedding

            logger.debug(
                f"Embedding batch partial hit: {len(texts) - len(missing_texts)} hits, {len(missing_texts)} misses"
            )
            return cast(List[List[float]], results)
        except Exception as e:
            logger.error(f"Failed to get embeddings batch: {e}")
            raise

    def get_embeddings_batch(self, texts: List[str]) -> List[List[float]]:
        """Synchronous wrapper for get_embeddings_batch. Use get_embeddings_batch_async in async contexts."""
        try:
            # Check if we're in an event loop
            loop = asyncio.get_running_loop()
            # If we get here, we're in an async context - this shouldn't be called
            raise RuntimeError(
                "get_embeddings_batch() called from async context. Use await get_embeddings_batch_async() instead."
            )
        except RuntimeError as e:
            if "no running event loop" in str(e).lower():
                # We're in sync context, safe to use run_until_complete
                loop = self._get_event_loop()
                return loop.run_until_complete(self._async_get_embeddings_batch(texts))
            else:
                raise

    async def get_embeddings_batch_async(self, texts: List[str]) -> List[List[float]]:
        """Async method for getting embeddings batch. Use this in async contexts."""
        return await self._async_get_embeddings_batch(texts)

    async def _async_close(self) -> None:
        if self._client is not None:
            await self._client.close()
            self._client = None

    def close(self) -> None:
        loop = self._get_event_loop()
        if not loop.is_closed():
            loop.run_until_complete(self._async_close())
