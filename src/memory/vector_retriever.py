import asyncio
from typing import Any, Callable, List, Tuple, Optional
from dataclasses import dataclass

from core.database import DatabaseManager
from llm.embedding import EmbeddingClient
from llm.reranker import RerankerClient
from utils.async_utils import ensure_not_in_async_context, run_sync
from utils.time import timestamp_to_str
from utils.logger import get_logger

logger = get_logger()


@dataclass
class RetrievedSummary:
    summary_id: int
    session_id: int
    summary: str
    first_timestamp: int
    last_timestamp: int
    score: float


@dataclass
class RetrievedConversation:
    conversation_id: int
    session_id: int
    timestamp: int
    role: str
    text: str
    score: float


class VectorRetriever:
    def __init__(
        self,
        db: DatabaseManager,
        embedding_client: EmbeddingClient,
        reranker_client: RerankerClient,
    ):
        self.db = db
        self.embedding_client = embedding_client
        self.reranker_client = reranker_client
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    def _get_event_loop(self) -> asyncio.AbstractEventLoop:
        if self._loop is None or self._loop.is_closed():
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
        return self._loop

    @staticmethod
    def _merge_query_results(
        query_results: list[tuple], bot_results: list[tuple]
    ) -> list[tuple]:
        """Merge summary rows without introducing duplicates."""
        summary_id_to_result = {r[0]: r for r in query_results}
        for row in bot_results:
            if row[0] not in summary_id_to_result:
                query_results.append(row)
        return query_results

    @staticmethod
    def _rows_to_summaries(rows: list[tuple]) -> List[RetrievedSummary]:
        """Convert DB rows into RetrievedSummary models."""
        return [
            RetrievedSummary(
                summary_id=summary_id,
                session_id=session_id,
                summary=summary,
                first_timestamp=first_ts,
                last_timestamp=last_ts,
                score=distance,
            )
            for summary_id, session_id, summary, first_ts, last_ts, distance in rows
        ]

    def _collect_conversations_for_summaries(
        self, summaries: List[RetrievedSummary], limit: int
    ) -> List[RetrievedConversation]:
        """Collect conversations referenced by retrieved summaries."""
        ranges = [(summary.first_timestamp, summary.last_timestamp) for summary in summaries]
        conv_results = self.db.get_conversations_by_time_ranges(
            ranges=ranges,
            limit_per_range=limit,
        )
        conversations: List[RetrievedConversation] = []
        seen_conversation_ids: set[int] = set()

        for conversation_id, session_id, timestamp, role, text in conv_results:
            if conversation_id in seen_conversation_ids:
                continue
            seen_conversation_ids.add(conversation_id)
            conversations.append(
                RetrievedConversation(
                    conversation_id=conversation_id,
                    session_id=session_id,
                    timestamp=timestamp,
                    role=role,
                    text=text,
                    score=0.0,
                )
            )
        return conversations

    @staticmethod
    def _summary_docs(summaries: List[RetrievedSummary]) -> List[dict]:
        return [
            {
                "text": s.summary,
                "summary_id": s.summary_id,
                "session_id": s.session_id,
                "first_timestamp": s.first_timestamp,
                "last_timestamp": s.last_timestamp,
            }
            for s in summaries
        ]

    @staticmethod
    def _conversation_docs(conversations: List[RetrievedConversation]) -> List[dict]:
        return [
            {
                "text": c.text,
                "conversation_id": c.conversation_id,
                "session_id": c.session_id,
                "timestamp": c.timestamp,
                "role": c.role,
            }
            for c in conversations
        ]

    @staticmethod
    def _reranked_summary_models(reranked_docs: List[dict]) -> List[RetrievedSummary]:
        return [
            RetrievedSummary(
                summary_id=doc["summary_id"],
                session_id=doc["session_id"],
                summary=doc["text"],
                first_timestamp=doc["first_timestamp"],
                last_timestamp=doc["last_timestamp"],
                score=0.0,
            )
            for doc in reranked_docs
        ]

    @staticmethod
    def _reranked_conversation_models(
        reranked_docs: List[dict],
    ) -> List[RetrievedConversation]:
        return [
            RetrievedConversation(
                conversation_id=doc["conversation_id"],
                session_id=doc["session_id"],
                timestamp=doc["timestamp"],
                role=doc["role"],
                text=doc["text"],
                score=0.0,
            )
            for doc in reranked_docs
        ]

    async def _retrieve_related_memories_impl(
        self,
        *,
        query: str,
        last_bot_message: Optional[str],
        query_embedding: Optional[List[float]],
        last_bot_embedding: Optional[List[float]],
        exclude_summary_ids: Optional[List[int]],
        embedding_fetcher: Callable[[str], Any],
        rerank_fetcher: Callable[[str, List[dict], int], Any],
    ) -> Tuple[List[RetrievedSummary], List[RetrievedConversation]]:
        """Shared implementation for sync/async memory retrieval."""
        from core.config import Config

        if query_embedding is None:
            query_embedding = await embedding_fetcher(query)
        else:
            logger.debug("Reusing provided query_embedding")

        query_results = self.db.search_summaries(
            query_embedding,
            limit=Config.RECALL_SUMMARY_PER_QUERY,
            exclude_ids=exclude_summary_ids,
        )

        if last_bot_embedding is None and last_bot_message:
            last_bot_embedding = await embedding_fetcher(last_bot_message)

        if last_bot_embedding:
            bot_results = self.db.search_summaries(
                last_bot_embedding,
                limit=Config.RECALL_SUMMARY_PER_QUERY,
                exclude_ids=exclude_summary_ids,
            )
            query_results = self._merge_query_results(query_results, bot_results)

        summaries = self._rows_to_summaries(query_results)
        conversations_result = self._collect_conversations_for_summaries(
            summaries,
            Config.RECALL_CONV_PER_SUMMARY,
        )

        if self.reranker_client.is_enabled() and summaries:
            reranked_summaries = await rerank_fetcher(
                query,
                self._summary_docs(summaries),
                Config.RERANK_TOP_SUMMARIES,
            )
            summaries_result = self._reranked_summary_models(reranked_summaries)
        else:
            summaries_result = summaries[: Config.RERANK_TOP_SUMMARIES]

        if self.reranker_client.is_enabled() and conversations_result:
            reranked_convs = await rerank_fetcher(
                query,
                self._conversation_docs(conversations_result),
                Config.RERANK_TOP_CONVS,
            )
            conversations_result = self._reranked_conversation_models(reranked_convs)
        else:
            conversations_result = conversations_result[: Config.RERANK_TOP_CONVS]

        logger.debug(
            f"Retrieved {len(summaries_result)} summaries and "
            f"{len(conversations_result)} conversations for query"
        )
        return summaries_result, conversations_result

    def retrieve_related_memories(
        self,
        query: str,
        last_bot_message: Optional[str] = None,
        query_embedding: Optional[List[float]] = None,
        last_bot_embedding: Optional[List[float]] = None,
        exclude_summary_ids: Optional[List[int]] = None,
    ) -> Tuple[List[RetrievedSummary], List[RetrievedConversation]]:
        """Retrieve related memories via vector search.

        Args:
            query: Query text (only used if query_embedding not provided)
            last_bot_message: Optional last bot message for dual-query
            query_embedding: Optional pre-computed query embedding
            last_bot_embedding: Optional pre-computed bot embedding
            exclude_summary_ids: Optional list of summary_ids to exclude
        """
        ensure_not_in_async_context(
            "retrieve_related_memories() called from async context. "
            "Use await retrieve_related_memories_async() instead."
        )

        async def _embedding_fetcher(text: str) -> List[float]:
            return await self.embedding_client.get_embedding_async(text)

        async def _rerank_fetcher(
            current_query: str, documents: List[dict], top_n: int
        ) -> List[dict]:
            return await self.reranker_client.rerank_async(
                query=current_query,
                documents=documents,
                top_n=top_n,
            )

        return run_sync(
            lambda: self._retrieve_related_memories_impl(
                query=query,
                last_bot_message=last_bot_message,
                query_embedding=query_embedding,
                last_bot_embedding=last_bot_embedding,
                exclude_summary_ids=exclude_summary_ids,
                embedding_fetcher=_embedding_fetcher,
                rerank_fetcher=_rerank_fetcher,
            ),
            self._get_event_loop,
        )

    async def retrieve_related_memories_async(
        self,
        query: str,
        last_bot_message: Optional[str] = None,
        query_embedding: Optional[List[float]] = None,
        last_bot_embedding: Optional[List[float]] = None,
        exclude_summary_ids: Optional[List[int]] = None,
    ) -> Tuple[List[RetrievedSummary], List[RetrievedConversation]]:
        """Async version of retrieve_related_memories.

        Args:
            query: Query text (only used if query_embedding not provided)
            last_bot_message: Optional last bot message for dual-query
            query_embedding: Optional pre-computed query embedding
            last_bot_embedding: Optional pre-computed bot embedding
            exclude_summary_ids: Optional list of summary_ids to exclude
        """
        return await self._retrieve_related_memories_impl(
            query=query,
            last_bot_message=last_bot_message,
            query_embedding=query_embedding,
            last_bot_embedding=last_bot_embedding,
            exclude_summary_ids=exclude_summary_ids,
            embedding_fetcher=self.embedding_client.get_embedding_async,
            rerank_fetcher=lambda current_query, documents, top_n: self.reranker_client.rerank_async(
                query=current_query,
                documents=documents,
                top_n=top_n,
            ),
        )

    def format_summaries_for_prompt(
        self, summaries: List[RetrievedSummary]
    ) -> List[str]:
        formatted = []

        from core.config import Config

        for summary in summaries:
            start_time_str = timestamp_to_str(
                summary.first_timestamp, tz=Config.TIMEZONE
            )
            end_time_str = timestamp_to_str(summary.last_timestamp, tz=Config.TIMEZONE)
            if start_time_str == end_time_str:
                formatted.append(
                    f"[{start_time_str}][session_id={summary.session_id}] {summary.summary}"
                )
            else:
                formatted.append(
                    f"[{start_time_str} ~ {end_time_str}][session_id={summary.session_id}] {summary.summary}"
                )

        return formatted

    def format_conversations_for_prompt(
        self, conversations: List[RetrievedConversation]
    ) -> List[str]:
        formatted = []

        from core.config import Config
        from prompts import load_seele_json

        seele_data = load_seele_json()
        bot_name = (
            seele_data.get("bot", {}).get("name", "AI Assistant") or "AI Assistant"
        )
        user_name = seele_data.get("user", {}).get("name", "User") or "User"

        role_to_name = {
            "user": user_name,
            "assistant": bot_name,
        }

        for conv in conversations:
            time_str = timestamp_to_str(conv.timestamp, tz=Config.TIMEZONE)
            role_display = role_to_name.get(conv.role, conv.role)
            formatted.append(
                f"[{time_str}][session_id={conv.session_id}] {role_display}: {conv.text}"
            )

        return formatted
