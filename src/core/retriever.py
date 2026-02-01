from typing import List, Tuple, Optional
from dataclasses import dataclass

from core.database import DatabaseManager
from llm.embedding import EmbeddingClient
from llm.reranker import RerankerClient
from utils.time import timestamp_to_str
from utils.logger import get_logger

logger = get_logger()


@dataclass
class RetrievedSummary:
    summary_id: int
    summary: str
    first_timestamp: int
    last_timestamp: int
    score: float


@dataclass
class RetrievedConversation:
    conversation_id: int
    timestamp: int
    role: str
    text: str
    score: float


class MemoryRetriever:
    def __init__(
        self,
        db: DatabaseManager,
        embedding_client: EmbeddingClient,
        reranker_client: RerankerClient,
    ):
        self.db = db
        self.embedding_client = embedding_client
        self.reranker_client = reranker_client

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
        from config import Config

        summaries_result = []
        conversations_result = []

        if query_embedding is None:
            query_embedding = self.embedding_client.get_embedding(query)
        else:
            logger.debug("Reusing provided query_embedding")

        query_results = self.db.search_summaries(
            query_embedding,
            limit=Config.RECALL_SUMMARY_PER_QUERY,
            exclude_ids=exclude_summary_ids,
        )

        if last_bot_embedding is None and last_bot_message:
            last_bot_embedding = self.embedding_client.get_embedding(last_bot_message)

        if last_bot_embedding:
            bot_results = self.db.search_summaries(
                last_bot_embedding,
                limit=Config.RECALL_SUMMARY_PER_QUERY,
                exclude_ids=exclude_summary_ids,
            )

            summary_id_to_result = {r[0]: r for r in query_results}
            for r in bot_results:
                if r[0] not in summary_id_to_result:
                    query_results.append(r)

        summaries = []
        for r in query_results:
            summary_id, summary, first_ts, last_ts, distance = r
            summaries.append(
                RetrievedSummary(
                    summary_id=summary_id,
                    summary=summary,
                    first_timestamp=first_ts,
                    last_timestamp=last_ts,
                    score=distance,
                )
            )

        if summaries:
            for summary in summaries:
                # Search conversations within the summary's time range
                conv_results = self.db.get_conversations_by_time_range(
                    start_timestamp=summary.first_timestamp,
                    end_timestamp=summary.last_timestamp,
                    limit=Config.RECALL_CONV_PER_SUMMARY,
                )

                for r in conv_results:
                    conversation_id, timestamp, role, text = r
                    conversations_result.append(
                        RetrievedConversation(
                            conversation_id=conversation_id,
                            timestamp=timestamp,
                            role=role,
                            text=text,
                            score=0.0,  # No distance score for time-range search
                        )
                    )

        if self.reranker_client.is_enabled() and summaries:
            summary_docs = [
                {
                    "text": s.summary,
                    "summary_id": s.summary_id,
                    "first_timestamp": s.first_timestamp,
                    "last_timestamp": s.last_timestamp,
                }
                for s in summaries
            ]
            reranked_summaries = self.reranker_client.rerank(
                query=query, documents=summary_docs, top_n=Config.RERANK_TOP_SUMMARIES
            )
            summaries_result = [
                RetrievedSummary(
                    summary_id=doc["summary_id"],
                    summary=doc["text"],
                    first_timestamp=doc["first_timestamp"],
                    last_timestamp=doc["last_timestamp"],
                    score=0.0,
                )
                for doc in reranked_summaries
            ]
        else:
            summaries_result = summaries[: Config.RERANK_TOP_SUMMARIES]

        if self.reranker_client.is_enabled() and conversations_result:
            conv_docs = [
                {
                    "text": c.text,
                    "conversation_id": c.conversation_id,
                    "timestamp": c.timestamp,
                    "role": c.role,
                }
                for c in conversations_result
            ]
            reranked_convs = self.reranker_client.rerank(
                query=query, documents=conv_docs, top_n=Config.RERANK_TOP_CONVS
            )
            conversations_result = [
                RetrievedConversation(
                    conversation_id=doc["conversation_id"],
                    timestamp=doc["timestamp"],
                    role=doc["role"],
                    text=doc["text"],
                    score=0.0,
                )
                for doc in reranked_convs
            ]
        else:
            conversations_result = conversations_result[: Config.RERANK_TOP_CONVS]

        logger.debug(
            f"Retrieved {len(summaries_result)} summaries and "
            f"{len(conversations_result)} conversations for query"
        )

        return summaries_result, conversations_result

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
        from config import Config

        summaries_result = []
        conversations_result = []

        if query_embedding is None:
            query_embedding = await self.embedding_client.get_embedding_async(query)
        else:
            logger.debug("Reusing provided query_embedding")

        query_results = self.db.search_summaries(
            query_embedding,
            limit=Config.RECALL_SUMMARY_PER_QUERY,
            exclude_ids=exclude_summary_ids,
        )

        if last_bot_embedding is None and last_bot_message:
            last_bot_embedding = await self.embedding_client.get_embedding_async(
                last_bot_message
            )

        if last_bot_embedding:
            bot_results = self.db.search_summaries(
                last_bot_embedding,
                limit=Config.RECALL_SUMMARY_PER_QUERY,
                exclude_ids=exclude_summary_ids,
            )

            summary_id_to_result = {r[0]: r for r in query_results}
            for r in bot_results:
                if r[0] not in summary_id_to_result:
                    query_results.append(r)

        summaries = []
        for r in query_results:
            summary_id, summary, first_ts, last_ts, distance = r
            summaries.append(
                RetrievedSummary(
                    summary_id=summary_id,
                    summary=summary,
                    first_timestamp=first_ts,
                    last_timestamp=last_ts,
                    score=distance,
                )
            )

        if summaries:
            for summary in summaries:
                # Search conversations within the summary's time range
                conv_results = self.db.get_conversations_by_time_range(
                    start_timestamp=summary.first_timestamp,
                    end_timestamp=summary.last_timestamp,
                    limit=Config.RECALL_CONV_PER_SUMMARY,
                )

                for r in conv_results:
                    conversation_id, timestamp, role, text = r
                    conversations_result.append(
                        RetrievedConversation(
                            conversation_id=conversation_id,
                            timestamp=timestamp,
                            role=role,
                            text=text,
                            score=0.0,  # No distance score for time-range search
                        )
                    )

        if self.reranker_client.is_enabled() and summaries:
            summary_docs = [
                {
                    "text": s.summary,
                    "summary_id": s.summary_id,
                    "first_timestamp": s.first_timestamp,
                    "last_timestamp": s.last_timestamp,
                }
                for s in summaries
            ]
            reranked_summaries = await self.reranker_client.rerank_async(
                query=query, documents=summary_docs, top_n=Config.RERANK_TOP_SUMMARIES
            )
            summaries_result = [
                RetrievedSummary(
                    summary_id=doc["summary_id"],
                    summary=doc["text"],
                    first_timestamp=doc["first_timestamp"],
                    last_timestamp=doc["last_timestamp"],
                    score=0.0,
                )
                for doc in reranked_summaries
            ]
        else:
            summaries_result = summaries[: Config.RERANK_TOP_SUMMARIES]

        if self.reranker_client.is_enabled() and conversations_result:
            conv_docs = [
                {
                    "text": c.text,
                    "conversation_id": c.conversation_id,
                    "timestamp": c.timestamp,
                    "role": c.role,
                }
                for c in conversations_result
            ]
            reranked_convs = await self.reranker_client.rerank_async(
                query=query, documents=conv_docs, top_n=Config.RERANK_TOP_CONVS
            )
            conversations_result = [
                RetrievedConversation(
                    conversation_id=doc["conversation_id"],
                    timestamp=doc["timestamp"],
                    role=doc["role"],
                    text=doc["text"],
                    score=0.0,
                )
                for doc in reranked_convs
            ]
        else:
            conversations_result = conversations_result[: Config.RERANK_TOP_CONVS]

        logger.debug(
            f"Retrieved {len(summaries_result)} summaries and "
            f"{len(conversations_result)} conversations for query"
        )

        return summaries_result, conversations_result

    def format_summaries_for_prompt(
        self, summaries: List[RetrievedSummary]
    ) -> List[str]:
        formatted = []

        from config import Config

        for summary in summaries:
            start_time_str = timestamp_to_str(
                summary.first_timestamp, tz=Config.TIMEZONE
            )
            end_time_str = timestamp_to_str(summary.last_timestamp, tz=Config.TIMEZONE)
            if start_time_str == end_time_str:
                formatted.append(f"[{start_time_str}] {summary.summary}")
            else:
                formatted.append(
                    f"[{start_time_str} ~ {end_time_str}] {summary.summary}"
                )

        return formatted

    def format_conversations_for_prompt(
        self, conversations: List[RetrievedConversation]
    ) -> List[str]:
        formatted = []

        from config import Config

        for conv in conversations:
            time_str = timestamp_to_str(conv.timestamp, tz=Config.TIMEZONE)
            role_display = "User" if conv.role == "user" else "Assistant"
            formatted.append(f"[{time_str}] {role_display}: {conv.text}")

        return formatted
