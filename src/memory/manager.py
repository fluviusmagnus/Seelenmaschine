import json
from typing import List, Dict, Optional, Tuple, Any

from memory.context import ContextWindow, Message
from core.database import DatabaseManager
from memory.vector_retriever import VectorRetriever
from llm.embedding import EmbeddingClient
from llm.reranker import RerankerClient
from memory.recall import MemoryRecall
from memory.seele import Seele
from memory.sessions import SessionMemory
from memory.summaries import SummaryGenerator
from utils.logger import get_logger

logger = get_logger()


class MemoryManager:
    def __init__(
        self,
        db: DatabaseManager,
        embedding_client: EmbeddingClient,
        reranker_client: RerankerClient,
    ):
        self.db = db
        self.embedding_client = embedding_client
        self.reranker_client = reranker_client

        self.context_window = ContextWindow()
        self.retriever = VectorRetriever(db, embedding_client, reranker_client)
        self.seele = Seele(db)
        self.sessions = SessionMemory(
            db=db,
            embedding_client=embedding_client,
            context_window=self.context_window,
        )
        self.summary_generator = SummaryGenerator()
        self.recall = MemoryRecall(
            context_window=self.context_window,
            retriever=self.retriever,
        )

        self._ensure_active_session()

    def _ensure_active_session(self) -> None:
        """Ensure there's an active session, create one if not."""
        self.sessions.ensure_active_session(
            restore_context_from_session=self._restore_context_from_session
        )

    def _restore_context_from_session(self, session_id: int) -> None:
        """Restore context window from session's recent conversations."""
        self.sessions.restore_context_from_session(session_id)

    def get_current_session_id(self) -> int:
        """Get current active session ID."""
        active_session = self.db.get_active_session()
        if active_session:
            return active_session["session_id"]
        raise RuntimeError("No active session found")

    def new_session(self) -> int:
        """Create a new session and close the old one if exists.

        Before closing the old session, summarizes all remaining conversations
        in the context window and updates long-term memory.
        """
        return self.sessions.new_session(
            generate_summary=self._generate_summary,
            update_long_term_memory=self._update_long_term_memory,
        )

    async def new_session_async(self) -> int:
        """Async version of new_session. Use this in async contexts.

        Create a new session and close the old one if exists.
        Before closing the old session, summarizes all remaining conversations
        in the context window and updates long-term memory.
        """
        return await self.sessions.new_session_async(
            generate_summary_async=self._generate_summary_async,
            update_long_term_memory_async=self._update_long_term_memory_async,
        )

    def reset_session(self) -> None:
        """Delete current session and create a new one."""
        self.sessions.reset_session()

    def process_user_input(
        self, user_input: str, last_bot_message: Optional[str] = None
    ) -> Tuple[List[str], List[str]]:
        """Process user input and retrieve related memories.

        Excludes recent summaries already in context window from vector search.
        """
        return self.recall.process_user_input(
            user_input=user_input,
            last_bot_message=last_bot_message,
        )

    async def process_user_input_async(
        self,
        user_input: str,
        last_bot_message: Optional[str] = None,
        user_input_embedding: Optional[List[float]] = None,
    ) -> Tuple[List[str], List[str]]:
        """Async version of process_user_input.

        Excludes recent summaries already in context window from vector search.

        Args:
            user_input: User input text
            last_bot_message: Optional last bot message for dual-query
            user_input_embedding: Optional pre-computed embedding
        """
        return await self.recall.process_user_input_async(
            user_input=user_input,
            last_bot_message=last_bot_message,
            user_input_embedding=user_input_embedding,
        )

    def add_user_message(
        self, text: str, embedding: Optional[List[float]] = None
    ) -> Tuple[int, List[float]]:
        session_id = self.get_current_session_id()
        return self.sessions.add_user_message(
            session_id=session_id,
            text=text,
            embedding=embedding,
        )

    async def add_user_message_async(
        self, text: str, embedding: Optional[List[float]] = None
    ) -> Tuple[int, List[float]]:
        """Async version of add_user_message. Use this in async contexts.

        Returns:
            Tuple of (conversation_id, embedding) - embedding is returned for reuse
        """
        session_id = self.get_current_session_id()
        return await self.sessions.add_user_message_async(
            session_id=session_id,
            text=text,
            embedding=embedding,
        )

    def add_assistant_message(
        self, text: str, embedding: Optional[List[float]] = None
    ) -> Tuple[int, Optional[int]]:
        session_id = self.get_current_session_id()
        return self.sessions.add_assistant_message(
            session_id=session_id,
            text=text,
            check_and_create_summary=self._check_and_create_summary,
            update_long_term_memory=self._update_long_term_memory,
            embedding=embedding,
        )

    async def add_assistant_message_async(
        self, text: str, embedding: Optional[List[float]] = None
    ) -> Tuple[int, Optional[int]]:
        """Async version of add_assistant_message. Use this in async contexts."""
        session_id = self.get_current_session_id()
        return await self.sessions.add_assistant_message_async(
            session_id=session_id,
            text=text,
            check_and_create_summary_async=self._check_and_create_summary_async,
            update_long_term_memory_async=self._update_long_term_memory_async,
            embedding=embedding,
        )

    def _check_and_create_summary(
        self,
    ) -> Tuple[Optional[int], Optional[List[Message]]]:
        """Check if summary should be created and create it.

        Returns:
            Tuple of (summary_id, messages_used_for_summary)
        """
        return self.sessions.check_and_create_summary(
            get_current_session_id=self.get_current_session_id,
            generate_summary=self._generate_summary,
        )

    async def _check_and_create_summary_async(
        self,
    ) -> Tuple[Optional[int], Optional[List[Message]]]:
        """Async version of _check_and_create_summary.

        Returns:
            Tuple of (summary_id, messages_used_for_summary)
        """
        return await self.sessions.check_and_create_summary_async(
            get_current_session_id=self.get_current_session_id,
            generate_summary_async=self._generate_summary_async,
        )

    def _generate_summary(self, messages: List[Message]) -> str:
        """Generate an independent summary for the given messages.

        Each summary is independent and only covers the specific messages provided.
        Summaries are later retrieved via vector search based on relevance, not
        by sequential order.
        """
        return self.summary_generator.generate_summary(messages)

    async def _generate_summary_async(self, messages: List[Message]) -> str:
        """Async version of _generate_summary. Use this in async contexts."""
        return await self.summary_generator.generate_summary_async(messages)

    def _generate_memory_update(self, messages: List[Message], summary_id: int) -> str:
        """Generate memory update JSON patch from messages. Use _generate_memory_update_async in async contexts."""
        from llm.chat_client import LLMClient

        client = LLMClient()
        messages_dict = [msg.to_dict() for msg in messages]

        summary_row = self.db.get_summary_by_id(summary_id)
        first_timestamp = summary_row["first_timestamp"] if summary_row else None
        last_timestamp = summary_row["last_timestamp"] if summary_row else None

        current_seele = self.get_long_term_memory()
        current_seele_json = json.dumps(current_seele, ensure_ascii=False, indent=2)

        json_patch = client.generate_memory_update(
            messages_dict, current_seele_json, first_timestamp, last_timestamp
        )
        client.close()
        return json_patch

    def _generate_complete_memory_json(
        self, messages: List[Message], error_message: str, summary_id: int
    ) -> str:
        """Generate complete seele.json when JSON Patch fails. Use _generate_complete_memory_json_async in async contexts."""
        from llm.chat_client import LLMClient

        client = LLMClient()
        messages_dict = [msg.to_dict() for msg in messages]
        current_seele = self.get_long_term_memory()
        current_seele_json = json.dumps(current_seele, ensure_ascii=False, indent=2)

        summary_row = self.db.get_summary_by_id(summary_id)
        first_timestamp = summary_row["first_timestamp"] if summary_row else None
        last_timestamp = summary_row["last_timestamp"] if summary_row else None

        complete_json = client.generate_complete_memory_json(
            messages_dict,
            current_seele_json,
            error_message,
            first_timestamp,
            last_timestamp,
        )
        client.close()
        return complete_json

    async def _generate_memory_update_async(
        self, messages: List[Message], summary_id: int
    ) -> str:
        """Async version of _generate_memory_update. Use this in async contexts."""
        from llm.chat_client import LLMClient

        client = LLMClient()
        messages_dict = [msg.to_dict() for msg in messages]

        summary_row = self.db.get_summary_by_id(summary_id)
        first_timestamp = summary_row["first_timestamp"] if summary_row else None
        last_timestamp = summary_row["last_timestamp"] if summary_row else None

        current_seele = self.get_long_term_memory()
        current_seele_json = json.dumps(current_seele, ensure_ascii=False, indent=2)

        json_patch = await client.generate_memory_update_async(
            messages_dict, current_seele_json, first_timestamp, last_timestamp
        )
        await client.close_async()
        return json_patch

    async def _generate_complete_memory_json_async(
        self, messages: List[Message], error_message: str, summary_id: int
    ) -> str:
        """Async version of _generate_complete_memory_json. Use this in async contexts."""
        from llm.chat_client import LLMClient

        client = LLMClient()
        messages_dict = [msg.to_dict() for msg in messages]
        current_seele = self.get_long_term_memory()
        current_seele_json = json.dumps(current_seele, ensure_ascii=False, indent=2)

        summary_row = self.db.get_summary_by_id(summary_id)
        first_timestamp = summary_row["first_timestamp"] if summary_row else None
        last_timestamp = summary_row["last_timestamp"] if summary_row else None

        complete_json = await client.generate_complete_memory_json_async(
            messages_dict,
            current_seele_json,
            error_message,
            first_timestamp,
            last_timestamp,
        )
        await client.close_async()
        return complete_json

    def _update_long_term_memory(
        self, summary_id: int, messages: List[Message]
    ) -> bool:
        """Update long-term memory using the messages that were just summarized.

        Args:
            summary_id: The ID of the summary that was just created
            messages: The messages that were used to generate the summary

        Returns:
            True if update was successful, False otherwise
        """
        try:
            if not messages:
                return False

            json_patch = self._generate_memory_update(messages, summary_id)
            if not json_patch:
                return False

            return self.update_long_term_memory(summary_id, json_patch, messages)
        except Exception as e:
            logger.error(f"Failed to update long-term memory: {e}")
            return False

    async def _update_long_term_memory_async(
        self, summary_id: int, messages: List[Message]
    ) -> bool:
        """Async version of _update_long_term_memory.

        Args:
            summary_id: The ID of the summary that was just created
            messages: The messages that were used to generate the summary

        Returns:
            True if update was successful, False otherwise
        """
        try:
            if not messages:
                return False

            json_patch = await self._generate_memory_update_async(messages, summary_id)
            if not json_patch:
                return False

            return await self.update_long_term_memory_async(
                summary_id, json_patch, messages
            )
        except Exception as e:
            logger.error(f"Failed to update long-term memory: {e}")
            return False

    def update_long_term_memory(
        self, summary_id: int, json_patch: str, messages: Optional[List[Message]] = None
    ) -> bool:
        """Update long-term memory (seele.json) with a JSON Patch.

        If JSON Patch fails, falls back to generating complete seele.json.

        Args:
            summary_id: ID of the summary triggering the update
            json_patch: JSON string - should be a JSON Patch array (RFC 6902)
                       Also accepts dict format for backward compatibility
            messages: Optional messages used for fallback if patch fails

        Returns:
            True if successful, False otherwise
        """
        try:
            patch_data = json.loads(json_patch.strip())

            from prompts import update_seele_json

            success = update_seele_json(patch_data)
            if success:
                patch_type = "array" if isinstance(patch_data, list) else "dict"
                logger.info(
                    f"Updated seele.json with {patch_type} patch from summary {summary_id}"
                )
                return True

            if messages:
                logger.warning(
                    f"JSON Patch failed for summary {summary_id}, attempting fallback to complete JSON generation"
                )
                return self._fallback_to_complete_json(
                    summary_id, messages, "JSON Patch application failed"
                )

            logger.warning(
                f"Failed to apply patch from summary {summary_id}, no fallback available"
            )
            return False
        except json.JSONDecodeError as e:
            error_msg = f"Invalid JSON in patch from summary {summary_id}: {e}"
            logger.error(error_msg)
            if messages:
                logger.warning("Attempting fallback to complete JSON generation")
                return self._fallback_to_complete_json(summary_id, messages, error_msg)
            return False
        except Exception as e:
            error_msg = f"Failed to update long-term memory: {e}"
            logger.error(error_msg)
            if messages:
                logger.warning("Attempting fallback to complete JSON generation")
                return self._fallback_to_complete_json(summary_id, messages, error_msg)
            return False

    def _fallback_to_complete_json(
        self, summary_id: int, messages: List[Message], error_message: str
    ) -> bool:
        """Fallback method: generate and apply complete seele.json when patch fails.

        Args:
            summary_id: ID of the summary triggering the update
            messages: Messages to analyze
            error_message: The error message from the failed patch attempt

        Returns:
            True if successful, False otherwise
        """
        max_retries = 2

        for attempt in range(max_retries):
            try:
                logger.info(
                    f"Generating complete seele.json as fallback for summary {summary_id} (attempt {attempt + 1}/{max_retries})"
                )
                complete_json_str = self._generate_complete_memory_json(
                    messages, error_message, summary_id
                )
                if not complete_json_str:
                    logger.error("Failed to generate complete JSON - empty response")
                    continue

                complete_json_str = self._clean_json_response(complete_json_str)
                logger.debug(f"Generated JSON length: {len(complete_json_str)} chars")
                logger.debug(f"First 200 chars: {complete_json_str[:200]}")
                logger.debug(f"Last 200 chars: {complete_json_str[-200:]}")

                complete_data = json.loads(complete_json_str)
                if not self._validate_seele_structure(complete_data):
                    logger.warning("Generated JSON has invalid structure, retrying...")
                    error_message = (
                        "Previous attempt produced invalid structure. Ensure all required "
                        "fields are present: bot, user, memorable_events, commands_and_agreements"
                    )
                    continue

                self.seele._write_complete_seele_json(complete_data)
                logger.info(
                    f"Successfully updated seele.json with complete JSON (fallback) for summary {summary_id}"
                )
                return True
            except json.JSONDecodeError as e:
                logger.error(
                    f"JSON parsing failed (attempt {attempt + 1}/{max_retries}): {e}"
                )
                logger.error(
                    f"Error at line {e.lineno}, column {e.colno}, position {e.pos}"
                )
                if attempt < max_retries - 1:
                    error_message = (
                        f"Previous JSON generation failed with parse error at line {e.lineno}: {str(e)}. "
                        "Please ensure proper JSON syntax: all strings must be properly quoted and escaped, "
                        "no trailing commas, proper brace/bracket matching."
                    )
                else:
                    logger.error("Max retries reached for complete JSON generation")
                    return False
            except Exception as e:
                logger.error(
                    f"Fallback to complete JSON failed (attempt {attempt + 1}/{max_retries}): {e}"
                )
                if attempt >= max_retries - 1:
                    return False

        return False

    def _clean_json_response(self, response: str) -> str:
        """Clean LLM response to extract valid JSON.

        Args:
            response: Raw response from LLM

        Returns:
            Cleaned JSON string
        """
        return self.seele.clean_json_response(response)

    def _validate_seele_structure(self, data: dict) -> bool:
        """Validate that the seele.json structure has all required fields.

        Args:
            data: Parsed JSON data

        Returns:
            True if valid, False otherwise
        """
        return self.seele.validate_seele_structure(data)

    async def update_long_term_memory_async(
        self, summary_id: int, json_patch: str, messages: Optional[List[Message]] = None
    ) -> bool:
        """Async version of update_long_term_memory. Use this in async contexts.

        If JSON Patch fails, falls back to generating complete seele.json.
        """
        try:
            patch_data = json.loads(json_patch.strip())

            from prompts import update_seele_json

            success = update_seele_json(patch_data)
            if success:
                patch_type = "array" if isinstance(patch_data, list) else "dict"
                logger.info(
                    f"Updated seele.json with {patch_type} patch from summary {summary_id}"
                )
                return True

            if messages:
                logger.warning(
                    f"JSON Patch failed for summary {summary_id}, attempting fallback to complete JSON generation"
                )
                return await self._fallback_to_complete_json_async(
                    summary_id, messages, "JSON Patch application failed"
                )

            logger.warning(
                f"Failed to apply patch from summary {summary_id}, no fallback available"
            )
            return False
        except json.JSONDecodeError as e:
            error_msg = f"Invalid JSON in patch from summary {summary_id}: {e}"
            logger.error(error_msg)
            if messages:
                logger.warning("Attempting fallback to complete JSON generation")
                return await self._fallback_to_complete_json_async(
                    summary_id, messages, error_msg
                )
            return False
        except Exception as e:
            error_msg = f"Failed to update long-term memory: {e}"
            logger.error(error_msg)
            if messages:
                logger.warning("Attempting fallback to complete JSON generation")
                return await self._fallback_to_complete_json_async(
                    summary_id, messages, error_msg
                )
            return False

    async def _fallback_to_complete_json_async(
        self, summary_id: int, messages: List[Message], error_message: str
    ) -> bool:
        """Async version of _fallback_to_complete_json. Use this in async contexts."""
        max_retries = 2

        for attempt in range(max_retries):
            try:
                logger.info(
                    f"Generating complete seele.json as fallback for summary {summary_id} (attempt {attempt + 1}/{max_retries})"
                )
                complete_json_str = await self._generate_complete_memory_json_async(
                    messages, error_message, summary_id
                )
                if not complete_json_str:
                    logger.error("Failed to generate complete JSON - empty response")
                    continue

                complete_json_str = self._clean_json_response(complete_json_str)
                logger.debug(f"Generated JSON length: {len(complete_json_str)} chars")
                logger.debug(f"First 200 chars: {complete_json_str[:200]}")
                logger.debug(f"Last 200 chars: {complete_json_str[-200:]}")

                complete_data = json.loads(complete_json_str)
                if not self._validate_seele_structure(complete_data):
                    logger.warning("Generated JSON has invalid structure, retrying...")
                    error_message = (
                        "Previous attempt produced invalid structure. Ensure all required "
                        "fields are present: bot, user, memorable_events, commands_and_agreements"
                    )
                    continue

                self.seele._write_complete_seele_json(complete_data)
                logger.info(
                    f"Successfully updated seele.json with complete JSON (fallback) for summary {summary_id}"
                )
                return True
            except json.JSONDecodeError as e:
                logger.error(
                    f"JSON parsing failed (attempt {attempt + 1}/{max_retries}): {e}"
                )
                logger.error(
                    f"Error at line {e.lineno}, column {e.colno}, position {e.pos}"
                )
                if attempt < max_retries - 1:
                    error_message = (
                        f"Previous JSON generation failed with parse error at line {e.lineno}: {str(e)}. "
                        "Please ensure proper JSON syntax: all strings must be properly quoted and escaped, "
                        "no trailing commas, proper brace/bracket matching."
                    )
                else:
                    logger.error("Max retries reached for complete JSON generation")
                    return False
            except Exception as e:
                logger.error(
                    f"Fallback to complete JSON failed (attempt {attempt + 1}/{max_retries}): {e}"
                )
                if attempt >= max_retries - 1:
                    return False

        return False

    def get_long_term_memory(self) -> Dict[str, Any]:
        return self.seele.get_long_term_memory()

    def get_context_messages(self) -> List[Dict[str, str]]:
        return self.recall.get_context_messages()

    def get_recent_summaries(self) -> List[str]:
        return self.recall.get_recent_summaries()


