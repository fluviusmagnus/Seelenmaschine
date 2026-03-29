from typing import List, Optional, Tuple

from memory.context import ContextWindow
from memory.vector_retriever import VectorRetriever


class MemoryRecall:
    """Coordinate retrieval against the current context window."""

    def __init__(self, context_window: ContextWindow, retriever: VectorRetriever):
        self.context_window = context_window
        self.retriever = retriever

    def process_user_input(
        self, user_input: str, last_bot_message: Optional[str] = None
    ) -> Tuple[List[str], List[str]]:
        """Retrieve and format related memories for the current user input."""
        exclude_summary_ids = self.context_window.get_recent_summary_ids()
        summaries, conversations = self.retriever.retrieve_related_memories(
            query=user_input,
            last_bot_message=last_bot_message,
            exclude_summary_ids=exclude_summary_ids,
        )
        return (
            self.retriever.format_summaries_for_prompt(summaries),
            self.retriever.format_conversations_for_prompt(conversations),
        )

    async def process_user_input_async(
        self,
        user_input: str,
        last_bot_message: Optional[str] = None,
        user_input_embedding: Optional[List[float]] = None,
    ) -> Tuple[List[str], List[str]]:
        """Async version of process_user_input."""
        exclude_summary_ids = self.context_window.get_recent_summary_ids()
        messages = self.context_window.get_messages()
        last_bot_embedding = None

        for msg in reversed(messages):
            if msg.role == "assistant" and msg.embedding:
                last_bot_embedding = msg.embedding
                break

        if user_input_embedding is None and messages:
            last_msg = messages[-1]
            if last_msg.role == "user" and last_msg.text == user_input:
                user_input_embedding = last_msg.embedding

        summaries, conversations = await self.retriever.retrieve_related_memories_async(
            query=user_input,
            last_bot_message=last_bot_message,
            query_embedding=user_input_embedding,
            last_bot_embedding=last_bot_embedding,
            exclude_summary_ids=exclude_summary_ids,
        )
        return (
            self.retriever.format_summaries_for_prompt(summaries),
            self.retriever.format_conversations_for_prompt(conversations),
        )

    def get_context_messages(self) -> List[dict]:
        """Expose the current context window as chat messages."""
        return self.context_window.get_context_as_messages()

    def get_recent_summaries(self) -> List[str]:
        """Expose recent summaries as plain text."""
        return self.context_window.get_recent_summaries_as_text()

