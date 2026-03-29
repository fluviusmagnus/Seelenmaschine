from typing import List

from memory.context import Message


class SummaryGenerator:
    """Generate conversation summaries through the LLM client."""

    def generate_summary(self, messages: List[Message]) -> str:
        """Generate an independent summary for the provided messages."""
        from llm.chat_client import LLMClient

        client = LLMClient()
        messages_dict = [msg.to_dict() for msg in messages]
        summary = client.generate_summary(None, messages_dict)
        client.close()
        return summary

    async def generate_summary_async(self, messages: List[Message]) -> str:
        """Async version of generate_summary."""
        from llm.chat_client import LLMClient

        client = LLMClient()
        messages_dict = [msg.to_dict() for msg in messages]
        summary = await client.generate_summary_async(None, messages_dict)
        await client.close_async()
        return summary


