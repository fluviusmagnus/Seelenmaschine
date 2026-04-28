from typing import List, Optional, Dict, Any
import httpx

from core.config import Config
from utils.logger import get_logger

logger = get_logger()


class RerankerClient:
    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None
    ):
        self.api_key = api_key or Config.RERANK_API_KEY
        self.base_url = base_url or Config.RERANK_API_BASE
        self.model = model or Config.RERANK_MODEL
        
        self._enabled = bool(self.api_key and self.model and self.base_url)
        self._client: Optional[httpx.AsyncClient] = None
        
        if self._enabled:
            logger.info(f"RerankerClient initialized: {self.model}")
        else:
            logger.info("RerankerClient is disabled (no api_key, model, or base_url)")

    def is_enabled(self) -> bool:
        return self._enabled

    def _ensure_client_initialized(self) -> None:
        if not self._enabled:
            raise ValueError("Reranker is not enabled")
        if self._client is None:
            self._client = httpx.AsyncClient(
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json"
                },
                timeout=30.0
            )

    async def _async_rerank(
        self,
        query: str,
        documents: List[Dict[str, Any]],
        top_n: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        if not self._enabled:
            return documents[:top_n] if top_n else documents
        
        self._ensure_client_initialized()
        
        if not documents:
            return []
        
        try:
            # Extract text from documents
            texts = [doc.get("text", "") for doc in documents]
            
            # Prepare rerank request
            # Try OpenAI-compatible rerank endpoint first
            rerank_url = f"{self.base_url.rstrip('/')}/rerank"
            payload = {
                "model": self.model,
                "query": query,
                "documents": texts,
                "top_n": top_n or len(documents)
            }
            
            response = await self._client.post(rerank_url, json=payload)
            
            if response.status_code == 200:
                result_data = response.json()
                
                # Parse response (format may vary by provider)
                if "results" in result_data:
                    # Standard format: {"results": [{"index": 0, "relevance_score": 0.9}, ...]}
                    ranked_indices = [(item["index"], item.get("relevance_score", 0)) 
                                     for item in result_data["results"]]
                    ranked_indices.sort(key=lambda x: x[1], reverse=True)
                    result = [documents[idx] for idx, _ in ranked_indices[:top_n]]
                else:
                    # Fallback: return original order
                    logger.warning(f"Unexpected rerank response format: {result_data}")
                    result = documents[:top_n] if top_n else documents
                
                logger.debug(f"Reranked {len(documents)} documents, returning top {len(result)}")
                return result
            else:
                error_msg = response.text
                logger.error(f"Rerank API error ({response.status_code}): {error_msg}")
                return documents[:top_n] if top_n else documents
            
        except Exception as e:
            logger.error(f"Rerank failed, returning original documents: {e}")
            return documents[:top_n] if top_n else documents

    async def rerank_async(
        self,
        query: str,
        documents: List[Dict[str, Any]],
        top_n: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """Async method for reranking. Use this in async contexts."""
        return await self._async_rerank(query, documents, top_n)

    async def _async_close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def close_async(self) -> None:
        """Async method for closing the underlying client."""
        await self._async_close()
