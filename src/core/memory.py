import json
from typing import List, Dict, Optional, Tuple, Any

from core.context import ContextWindow, Message
from core.retriever import MemoryRetriever
from core.database import DatabaseManager
from llm.embedding import EmbeddingClient
from llm.reranker import RerankerClient
from utils.time import get_current_timestamp
from utils.logger import get_logger

logger = get_logger()


class MemoryManager:
    def __init__(
        self,
        db: DatabaseManager,
        embedding_client: EmbeddingClient,
        reranker_client: RerankerClient
    ):
        self.db = db
        self.embedding_client = embedding_client
        self.reranker_client = reranker_client
        
        self.context_window = ContextWindow()
        self.retriever = MemoryRetriever(db, embedding_client, reranker_client)
        
        self._ensure_active_session()

    def _ensure_active_session(self) -> None:
        """Ensure there's an active session, create one if not."""
        active_session = self.db.get_active_session()
        if active_session is None:
            from utils.time import get_current_timestamp
            session_id = self.db.create_session(get_current_timestamp())
            logger.info(f"Created new active session: {session_id}")
        else:
            # Restore context from existing session
            session_id = active_session["session_id"]
            self._restore_context_from_session(session_id)
            logger.info(f"Restored context from active session: {session_id}")
    
    def _restore_context_from_session(self, session_id: int) -> None:
        """Restore context window from session's recent conversations.
        
        First restores existing summaries to context window (up to RECENT_SUMMARIES_MAX).
        Then processes unsummarized conversations - if there are more than the trigger 
        threshold, creates summaries for older messages to maintain context window size.
        
        Args:
            session_id: The session ID to restore from
        """
        from config import Config
        
        trigger_count = Config.CONTEXT_WINDOW_TRIGGER_SUMMARY
        keep_count = Config.CONTEXT_WINDOW_KEEP_MIN
        max_recent_summaries = Config.RECENT_SUMMARIES_MAX
        
        # Step 1: Restore existing summaries to context window (most recent first)
        existing_summaries = self.db.get_summaries_by_session(session_id)
        if existing_summaries:
            # Take only the most recent summaries (up to max_recent_summaries)
            recent_summaries = existing_summaries[:max_recent_summaries]
            # Reverse to add oldest first (to maintain chronological order in context window)
            for summary_row in reversed(recent_summaries):
                self.context_window.add_summary(
                    summary=summary_row["summary"],
                    summary_id=summary_row["summary_id"]
                )
            logger.info(f"Restored {len(recent_summaries)} existing summaries to context window")
        
        # Step 2: Get only unsummarized conversations
        unsummarized_conversations = self.db.get_unsummarized_conversations(session_id)
        total_count = len(unsummarized_conversations)
        
        if total_count == 0:
            logger.info("No unsummarized conversations to restore")
            return
        
        if total_count <= keep_count:
            # Simple case: fewer unsummarized messages than keep threshold
            # Just restore all to context window
            for conv in unsummarized_conversations:
                self.context_window.add_message(
                    role=conv["role"],
                    text=conv["text"]
                )
            logger.info(f"Restored {total_count} unsummarized messages to context window")
            return
        
        # Complex case: more unsummarized messages than keep threshold
        # Need to handle old messages through summarization
        
        if total_count >= trigger_count:
            # We have enough messages to trigger summary
            # Calculate how many messages to summarize
            messages_to_summarize_count = total_count - keep_count
            
            logger.info(f"Session has {total_count} unsummarized messages, creating summaries for oldest {messages_to_summarize_count}")
            
            # Process messages in batches if needed
            summarized_so_far = 0
            while summarized_so_far < messages_to_summarize_count:
                batch_size = min(keep_count, messages_to_summarize_count - summarized_so_far)
                batch_conversations = unsummarized_conversations[summarized_so_far:summarized_so_far + batch_size]
                
                # Convert to Message objects
                batch_messages = [
                    Message(role=conv["role"], text=conv["text"])
                    for conv in batch_conversations
                ]
                
                # Generate summary
                summary_text = self._generate_summary(batch_messages)
                
                # Get timestamps from conversations
                first_timestamp = batch_conversations[0]["timestamp"]
                last_timestamp = batch_conversations[-1]["timestamp"]
                
                # Store summary with embedding
                embedding = self.embedding_client.get_embedding(summary_text)
                summary_id = self.db.insert_summary(
                    session_id=session_id,
                    summary=summary_text,
                    first_timestamp=first_timestamp,
                    last_timestamp=last_timestamp,
                    embedding=embedding
                )
                
                # Add to recent summaries
                self.context_window.add_summary(summary=summary_text, summary_id=summary_id)
                
                # Update long-term memory
                self._update_long_term_memory(summary_id, batch_messages)
                
                logger.info(f"Created summary {summary_id} for {len(batch_messages)} messages during restoration")
                summarized_so_far += batch_size
        
        # Now restore only the most recent unsummarized messages to context window
        recent_conversations = unsummarized_conversations[-keep_count:]
        for conv in recent_conversations:
            self.context_window.add_message(
                role=conv["role"],
                text=conv["text"]
            )
        
        logger.info(f"Restored {len(recent_conversations)} recent unsummarized messages to context window")

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
        old_session = self.db.get_active_session()
        if old_session:
            # Summarize all remaining messages in context window before closing
            remaining_messages = self.context_window.context_window
            if remaining_messages:
                logger.info(f"Summarizing {len(remaining_messages)} remaining messages before closing session")
                
                # Generate summary for all remaining messages
                summary_text = self._generate_summary(remaining_messages)
                
                # Get timestamps
                from utils.time import get_current_timestamp
                first_timestamp = int(get_current_timestamp() - len(remaining_messages) * 60)
                last_timestamp = get_current_timestamp()
                
                # Store summary with embedding
                embedding = self.embedding_client.get_embedding(summary_text)
                summary_id = self.db.insert_summary(
                    session_id=old_session["session_id"],
                    summary=summary_text,
                    first_timestamp=first_timestamp,
                    last_timestamp=last_timestamp,
                    embedding=embedding
                )
                
                logger.info(f"Created final summary for session {old_session['session_id']}: summary_id={summary_id}")
                
                # Update long-term memory with these messages
                self._update_long_term_memory(summary_id, remaining_messages)
            
            # Close the old session
            from utils.time import get_current_timestamp
            self.db.close_session(old_session["session_id"], get_current_timestamp())
            logger.info(f"Closed session: {old_session['session_id']}")
        
        # Create new session
        from utils.time import get_current_timestamp
        new_session_id = self.db.create_session(get_current_timestamp())
        
        # Clear context window for new session
        self.context_window.clear()
        logger.info(f"Created new session: {new_session_id}")
        return new_session_id

    async def new_session_async(self) -> int:
        """Async version of new_session. Use this in async contexts.
        
        Create a new session and close the old one if exists.
        Before closing the old session, summarizes all remaining conversations
        in the context window and updates long-term memory.
        """
        old_session = self.db.get_active_session()
        if old_session:
            # Summarize all remaining messages in context window before closing
            remaining_messages = self.context_window.context_window
            if remaining_messages:
                logger.info(f"Summarizing {len(remaining_messages)} remaining messages before closing session")
                
                # Generate summary for all remaining messages (async)
                summary_text = await self._generate_summary_async(remaining_messages)
                
                # Get timestamps
                from utils.time import get_current_timestamp
                first_timestamp = int(get_current_timestamp() - len(remaining_messages) * 60)
                last_timestamp = get_current_timestamp()
                
                # Store summary with embedding (async)
                embedding = await self.embedding_client.get_embedding_async(summary_text)
                summary_id = self.db.insert_summary(
                    session_id=old_session["session_id"],
                    summary=summary_text,
                    first_timestamp=first_timestamp,
                    last_timestamp=last_timestamp,
                    embedding=embedding
                )
                
                logger.info(f"Created final summary for session {old_session['session_id']}: summary_id={summary_id}")
                
                # Update long-term memory with these messages (async)
                await self._update_long_term_memory_async(summary_id, remaining_messages)
            
            # Close the old session
            from utils.time import get_current_timestamp
            self.db.close_session(old_session["session_id"], get_current_timestamp())
            logger.info(f"Closed session: {old_session['session_id']}")
        
        # Create new session
        from utils.time import get_current_timestamp
        new_session_id = self.db.create_session(get_current_timestamp())
        
        # Clear context window for new session
        self.context_window.clear()
        logger.info(f"Created new session: {new_session_id}")
        return new_session_id

    def reset_session(self) -> None:
        """Delete current session and create a new one."""
        old_session = self.db.get_active_session()
        if old_session:
            session_id = old_session["session_id"]
            self.db.delete_session(session_id)
            logger.info(f"Deleted session: {session_id}")
        
        from utils.time import get_current_timestamp
        new_session_id = self.db.create_session(get_current_timestamp())
        
        self.context_window.clear()
        logger.info(f"Created new session after reset: {new_session_id}")

    def process_user_input(
        self,
        user_input: str,
        last_bot_message: Optional[str] = None
    ) -> Tuple[List[str], List[str]]:
        """Process user input and retrieve related memories.
        
        Excludes recent summaries already in context window from vector search.
        """
        # Get IDs of recent summaries to exclude from search
        exclude_summary_ids = self.context_window.get_recent_summary_ids()
        
        summaries, conversations = self.retriever.retrieve_related_memories(
            query=user_input,
            last_bot_message=last_bot_message,
            exclude_summary_ids=exclude_summary_ids
        )
        
        formatted_summaries = self.retriever.format_summaries_for_prompt(summaries)
        formatted_conversations = self.retriever.format_conversations_for_prompt(conversations)
        
        return formatted_summaries, formatted_conversations
    
    async def process_user_input_async(
        self,
        user_input: str,
        last_bot_message: Optional[str] = None,
        user_input_embedding: Optional[List[float]] = None
    ) -> Tuple[List[str], List[str]]:
        """Async version of process_user_input.
        
        Excludes recent summaries already in context window from vector search.
        
        Args:
            user_input: User input text (only used if user_input_embedding not provided)
            last_bot_message: Optional last bot message for dual-query
            user_input_embedding: Optional pre-computed embedding to avoid re-vectorization
        """
        # Get IDs of recent summaries to exclude from search
        exclude_summary_ids = self.context_window.get_recent_summary_ids()
        
        summaries, conversations = await self.retriever.retrieve_related_memories_async(
            query=user_input,
            last_bot_message=last_bot_message,
            query_embedding=user_input_embedding,
            exclude_summary_ids=exclude_summary_ids
        )
        
        formatted_summaries = self.retriever.format_summaries_for_prompt(summaries)
        formatted_conversations = self.retriever.format_conversations_for_prompt(conversations)
        
        return formatted_summaries, formatted_conversations

    def add_user_message(self, text: str, embedding: Optional[List[float]] = None) -> int:
        timestamp = get_current_timestamp()
        session_id = self.get_current_session_id()
        
        if embedding is None:
            embedding = self.embedding_client.get_embedding(text)
        
        conversation_id = self.db.insert_conversation(
            session_id=session_id,
            timestamp=timestamp,
            role="user",
            text=text,
            embedding=embedding
        )
        
        self.context_window.add_message(role="user", text=text)
        
        logger.debug(f"Added user message: conversation_id={conversation_id}")
        return conversation_id
    
    async def add_user_message_async(self, text: str, embedding: Optional[List[float]] = None) -> Tuple[int, List[float]]:
        """Async version of add_user_message. Use this in async contexts.
        
        Returns:
            Tuple of (conversation_id, embedding) - embedding is returned for reuse
        """
        timestamp = get_current_timestamp()
        session_id = self.get_current_session_id()
        
        if embedding is None:
            embedding = await self.embedding_client.get_embedding_async(text)
        
        conversation_id = self.db.insert_conversation(
            session_id=session_id,
            timestamp=timestamp,
            role="user",
            text=text,
            embedding=embedding
        )
        
        self.context_window.add_message(role="user", text=text)
        
        logger.debug(f"Added user message: conversation_id={conversation_id}")
        return conversation_id, embedding

    def add_assistant_message(
        self,
        text: str,
        embedding: Optional[List[float]] = None
    ) -> Tuple[int, Optional[int]]:
        
        timestamp = get_current_timestamp()
        session_id = self.get_current_session_id()
        
        if embedding is None:
            embedding = self.embedding_client.get_embedding(text)
        
        conversation_id = self.db.insert_conversation(
            session_id=session_id,
            timestamp=timestamp,
            role="assistant",
            text=text,
            embedding=embedding
        )
        
        self.context_window.add_message(role="assistant", text=text)
        
        summary_id, summarized_messages = self._check_and_create_summary()
        
        if summary_id is not None and summarized_messages is not None:
            self._update_long_term_memory(summary_id, summarized_messages)
        
        logger.debug(f"Added assistant message: conversation_id={conversation_id}")
        return conversation_id, summary_id
    
    async def add_assistant_message_async(
        self,
        text: str,
        embedding: Optional[List[float]] = None
    ) -> Tuple[int, Optional[int]]:
        """Async version of add_assistant_message. Use this in async contexts."""
        timestamp = get_current_timestamp()
        session_id = self.get_current_session_id()
        
        if embedding is None:
            embedding = await self.embedding_client.get_embedding_async(text)
        
        conversation_id = self.db.insert_conversation(
            session_id=session_id,
            timestamp=timestamp,
            role="assistant",
            text=text,
            embedding=embedding
        )
        
        self.context_window.add_message(role="assistant", text=text)
        
        summary_id, summarized_messages = await self._check_and_create_summary_async()
        
        if summary_id is not None and summarized_messages is not None:
            await self._update_long_term_memory_async(summary_id, summarized_messages)
        
        logger.debug(f"Added assistant message: conversation_id={conversation_id}")
        return conversation_id, summary_id

    def _check_and_create_summary(self) -> Tuple[Optional[int], Optional[List[Message]]]:
        """Check if summary should be created and create it.
        
        Returns:
            Tuple of (summary_id, messages_used_for_summary)
        """
        from config import Config
        
        trigger_count = Config.CONTEXT_WINDOW_TRIGGER_SUMMARY
        keep_count = Config.CONTEXT_WINDOW_KEEP_MIN
        
        if self.context_window.get_total_message_count() < trigger_count:
            return None, None
        
        messages_to_summarize = self.context_window.get_messages_for_summary(
            keep_count
        )
        
        if not messages_to_summarize:
            return None, None
        
        summary_text = self._generate_summary(messages_to_summarize)
        
        first_timestamp = int(get_current_timestamp() - len(messages_to_summarize) * 60)
        last_timestamp = get_current_timestamp()
        
        embedding = self.embedding_client.get_embedding(summary_text)
        session_id = self.get_current_session_id()
        
        summary_id = self.db.insert_summary(
            session_id=session_id,
            summary=summary_text,
            first_timestamp=first_timestamp,
            last_timestamp=last_timestamp,
            embedding=embedding
        )
        
        self.context_window.add_summary(summary=summary_text, summary_id=summary_id)
        self.context_window.remove_earliest_messages(keep_count)
        
        logger.info(f"Created summary: summary_id={summary_id}, length={len(summary_text)}")
        return summary_id, messages_to_summarize
    
    async def _check_and_create_summary_async(self) -> Tuple[Optional[int], Optional[List[Message]]]:
        """Async version of _check_and_create_summary.
        
        Returns:
            Tuple of (summary_id, messages_used_for_summary)
        """
        from config import Config
        
        trigger_count = Config.CONTEXT_WINDOW_TRIGGER_SUMMARY
        keep_count = Config.CONTEXT_WINDOW_KEEP_MIN
        
        if self.context_window.get_total_message_count() < trigger_count:
            return None, None
        
        messages_to_summarize = self.context_window.get_messages_for_summary(
            keep_count
        )
        
        if not messages_to_summarize:
            return None, None
        
        summary_text = await self._generate_summary_async(messages_to_summarize)
        
        first_timestamp = int(get_current_timestamp() - len(messages_to_summarize) * 60)
        last_timestamp = get_current_timestamp()
        
        embedding = await self.embedding_client.get_embedding_async(summary_text)
        session_id = self.get_current_session_id()
        
        summary_id = self.db.insert_summary(
            session_id=session_id,
            summary=summary_text,
            first_timestamp=first_timestamp,
            last_timestamp=last_timestamp,
            embedding=embedding
        )
        
        self.context_window.add_summary(summary=summary_text, summary_id=summary_id)
        self.context_window.remove_earliest_messages(keep_count)
        
        logger.info(f"Created summary: summary_id={summary_id}, length={len(summary_text)}")
        return summary_id, messages_to_summarize

    def _generate_summary(self, messages: List[Message]) -> str:
        """Generate an independent summary for the given messages.
        
        Each summary is independent and only covers the specific messages provided.
        Summaries are later retrieved via vector search based on relevance, not
        by sequential order.
        """
        from llm.client import LLMClient
        
        client = LLMClient()
        
        messages_dict = [msg.to_dict() for msg in messages]
        # Always pass None for existing_summary - each summary is independent
        summary = client.generate_summary(None, messages_dict)
        
        client.close()
        return summary
    
    async def _generate_summary_async(self, messages: List[Message]) -> str:
        """Async version of _generate_summary. Use this in async contexts."""
        from llm.client import LLMClient
        
        client = LLMClient()
        
        messages_dict = [msg.to_dict() for msg in messages]
        # Always pass None for existing_summary - each summary is independent
        summary = await client.generate_summary_async(None, messages_dict)
        
        await client.close_async()
        return summary

    def _generate_memory_update(self, messages: List[Message], summary_id: int) -> str:
        """Generate memory update JSON patch from messages. Use _generate_memory_update_async in async contexts."""
        from llm.client import LLMClient
        
        client = LLMClient()
        
        messages_dict = [msg.to_dict() for msg in messages]
        
        # Get time information from summary
        summary_row = self.db.get_summary_by_id(summary_id)
        first_timestamp = summary_row["first_timestamp"] if summary_row else None
        last_timestamp = summary_row["last_timestamp"] if summary_row else None
        
        json_patch = client.generate_memory_update(messages_dict, first_timestamp, last_timestamp)
        
        client.close()
        return json_patch
    
    def _generate_complete_memory_json(self, messages: List[Message], error_message: str, summary_id: int) -> str:
        """Generate complete seele.json when JSON Patch fails. Use _generate_complete_memory_json_async in async contexts."""
        from llm.client import LLMClient
        import json
        
        client = LLMClient()
        
        messages_dict = [msg.to_dict() for msg in messages]
        
        # Get current seele.json as string
        current_seele = self.get_long_term_memory()
        current_seele_json = json.dumps(current_seele, ensure_ascii=False, indent=2)
        
        # Get time information from summary
        summary_row = self.db.get_summary_by_id(summary_id)
        first_timestamp = summary_row["first_timestamp"] if summary_row else None
        last_timestamp = summary_row["last_timestamp"] if summary_row else None
        
        complete_json = client.generate_complete_memory_json(messages_dict, current_seele_json, error_message, first_timestamp, last_timestamp)
        
        client.close()
        return complete_json
    
    async def _generate_memory_update_async(self, messages: List[Message], summary_id: int) -> str:
        """Async version of _generate_memory_update. Use this in async contexts."""
        from llm.client import LLMClient
        
        client = LLMClient()
        
        messages_dict = [msg.to_dict() for msg in messages]
        
        # Get time information from summary
        summary_row = self.db.get_summary_by_id(summary_id)
        first_timestamp = summary_row["first_timestamp"] if summary_row else None
        last_timestamp = summary_row["last_timestamp"] if summary_row else None
        
        json_patch = await client.generate_memory_update_async(messages_dict, first_timestamp, last_timestamp)
        
        await client.close_async()
        return json_patch
    
    async def _generate_complete_memory_json_async(self, messages: List[Message], error_message: str, summary_id: int) -> str:
        """Async version of _generate_complete_memory_json. Use this in async contexts."""
        from llm.client import LLMClient
        import json
        
        client = LLMClient()
        
        messages_dict = [msg.to_dict() for msg in messages]
        
        # Get current seele.json as string
        current_seele = self.get_long_term_memory()
        current_seele_json = json.dumps(current_seele, ensure_ascii=False, indent=2)
        
        # Get time information from summary
        summary_row = self.db.get_summary_by_id(summary_id)
        first_timestamp = summary_row["first_timestamp"] if summary_row else None
        last_timestamp = summary_row["last_timestamp"] if summary_row else None
        
        complete_json = await client.generate_complete_memory_json_async(messages_dict, current_seele_json, error_message, first_timestamp, last_timestamp)
        
        await client.close_async()
        return complete_json

    def _update_long_term_memory(self, summary_id: int, messages: List[Message]) -> bool:
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
            
            # Try JSON Patch first
            json_patch = self._generate_memory_update(messages, summary_id)
            
            if not json_patch:
                return False
            
            success = self.update_long_term_memory(summary_id, json_patch, messages)
            return success
            
        except Exception as e:
            logger.error(f"Failed to update long-term memory: {e}")
            return False
    
    async def _update_long_term_memory_async(self, summary_id: int, messages: List[Message]) -> bool:
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
            
            # Try JSON Patch first
            json_patch = await self._generate_memory_update_async(messages, summary_id)
            
            if not json_patch:
                return False
            
            success = await self.update_long_term_memory_async(summary_id, json_patch, messages)
            return success
            
        except Exception as e:
            logger.error(f"Failed to update long-term memory: {e}")
            return False

    def update_long_term_memory(self, summary_id: int, json_patch: str, messages: Optional[List[Message]] = None) -> bool:
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
            # Parse the JSON patch
            patch_data = json.loads(json_patch.strip())
            
            from prompts.system import update_seele_json
            success = update_seele_json(patch_data)
            
            if success:
                patch_type = "array" if isinstance(patch_data, list) else "dict"
                logger.info(f"Updated seele.json with {patch_type} patch from summary {summary_id}")
                return True
            else:
                # JSON Patch failed, try fallback if messages provided
                if messages:
                    logger.warning(f"JSON Patch failed for summary {summary_id}, attempting fallback to complete JSON generation")
                    return self._fallback_to_complete_json(summary_id, messages, "JSON Patch application failed")
                else:
                    logger.warning(f"Failed to apply patch from summary {summary_id}, no fallback available")
                    return False
            
        except json.JSONDecodeError as e:
            error_msg = f"Invalid JSON in patch from summary {summary_id}: {e}"
            logger.error(error_msg)
            # Try fallback if messages provided
            if messages:
                logger.warning("Attempting fallback to complete JSON generation")
                return self._fallback_to_complete_json(summary_id, messages, error_msg)
            return False
        except Exception as e:
            error_msg = f"Failed to update long-term memory: {e}"
            logger.error(error_msg)
            # Try fallback if messages provided
            if messages:
                logger.warning("Attempting fallback to complete JSON generation")
                return self._fallback_to_complete_json(summary_id, messages, error_msg)
            return False
    
    def _fallback_to_complete_json(self, summary_id: int, messages: List[Message], error_message: str) -> bool:
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
                logger.info(f"Generating complete seele.json as fallback for summary {summary_id} (attempt {attempt + 1}/{max_retries})")
                
                # Generate complete JSON
                complete_json_str = self._generate_complete_memory_json(messages, error_message, summary_id)
                
                if not complete_json_str:
                    logger.error("Failed to generate complete JSON - empty response")
                    continue
                
                # Clean the response
                complete_json_str = self._clean_json_response(complete_json_str)
                
                # Log the response for debugging
                logger.debug(f"Generated JSON length: {len(complete_json_str)} chars")
                logger.debug(f"First 200 chars: {complete_json_str[:200]}")
                logger.debug(f"Last 200 chars: {complete_json_str[-200:]}")
                
                # Parse and validate
                complete_data = json.loads(complete_json_str)
                
                # Validate structure
                if not self._validate_seele_structure(complete_data):
                    logger.warning("Generated JSON has invalid structure, retrying...")
                    error_message = "Previous attempt produced invalid structure. Ensure all required fields are present: bot, user, memorable_events, commands_and_agreements"
                    continue
                
                # Write directly to seele.json
                from config import Config
                import json as json_module
                
                config = Config()
                seele_path = config.SEELE_JSON_PATH
                
                seele_path.parent.mkdir(parents=True, exist_ok=True)
                with open(seele_path, "w", encoding="utf-8") as f:
                    json_module.dump(complete_data, f, indent=2, ensure_ascii=False)
                
                # Clear cache to force reload
                import prompts.system
                prompts.system._seele_json_cache = None
                
                logger.info(f"Successfully updated seele.json with complete JSON (fallback) for summary {summary_id}")
                return True
                
            except json.JSONDecodeError as e:
                logger.error(f"JSON parsing failed (attempt {attempt + 1}/{max_retries}): {e}")
                logger.error(f"Error at line {e.lineno}, column {e.colno}, position {e.pos}")
                if attempt < max_retries - 1:
                    # Update error message for next retry
                    error_message = f"Previous JSON generation failed with parse error at line {e.lineno}: {str(e)}. Please ensure proper JSON syntax: all strings must be properly quoted and escaped, no trailing commas, proper brace/bracket matching."
                else:
                    logger.error("Max retries reached for complete JSON generation")
                    return False
                    
            except Exception as e:
                logger.error(f"Fallback to complete JSON failed (attempt {attempt + 1}/{max_retries}): {e}")
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
        # Remove markdown code blocks if present
        if "```json" in response:
            response = response.split("```json")[1].split("```")[0]
        elif "```" in response:
            response = response.split("```")[1].split("```")[0]
        
        # Strip whitespace
        response = response.strip()
        
        # Find the actual JSON object
        start = response.find('{')
        end = response.rfind('}')
        
        if start != -1 and end != -1 and end > start:
            response = response[start:end + 1]
        
        return response
    
    def _validate_seele_structure(self, data: dict) -> bool:
        """Validate that the seele.json structure has all required fields.
        
        Args:
            data: Parsed JSON data
            
        Returns:
            True if valid, False otherwise
        """
        required_fields = ["bot", "user", "memorable_events", "commands_and_agreements"]
        
        for field in required_fields:
            if field not in data:
                logger.warning(f"Missing required field: {field}")
                return False
        
        # Validate memorable_events is array and not too long
        if not isinstance(data["memorable_events"], list):
            logger.warning("memorable_events is not an array")
            return False
        
        if len(data["memorable_events"]) > 20:
            logger.warning(f"memorable_events has {len(data['memorable_events'])} events (max 20), truncating...")
            data["memorable_events"] = data["memorable_events"][-20:]
        
        return True
    
    async def update_long_term_memory_async(self, summary_id: int, json_patch: str, messages: Optional[List[Message]] = None) -> bool:
        """Async version of update_long_term_memory. Use this in async contexts.
        
        If JSON Patch fails, falls back to generating complete seele.json.
        """
        try:
            # Parse the JSON patch
            patch_data = json.loads(json_patch.strip())
            
            from prompts.system import update_seele_json
            success = update_seele_json(patch_data)
            
            if success:
                patch_type = "array" if isinstance(patch_data, list) else "dict"
                logger.info(f"Updated seele.json with {patch_type} patch from summary {summary_id}")
                return True
            else:
                # JSON Patch failed, try fallback if messages provided
                if messages:
                    logger.warning(f"JSON Patch failed for summary {summary_id}, attempting fallback to complete JSON generation")
                    return await self._fallback_to_complete_json_async(summary_id, messages, "JSON Patch application failed")
                else:
                    logger.warning(f"Failed to apply patch from summary {summary_id}, no fallback available")
                    return False
            
        except json.JSONDecodeError as e:
            error_msg = f"Invalid JSON in patch from summary {summary_id}: {e}"
            logger.error(error_msg)
            # Try fallback if messages provided
            if messages:
                logger.warning("Attempting fallback to complete JSON generation")
                return await self._fallback_to_complete_json_async(summary_id, messages, error_msg)
            return False
        except Exception as e:
            error_msg = f"Failed to update long-term memory: {e}"
            logger.error(error_msg)
            # Try fallback if messages provided
            if messages:
                logger.warning("Attempting fallback to complete JSON generation")
                return await self._fallback_to_complete_json_async(summary_id, messages, error_msg)
            return False
    
    async def _fallback_to_complete_json_async(self, summary_id: int, messages: List[Message], error_message: str) -> bool:
        """Async version of _fallback_to_complete_json. Use this in async contexts."""
        max_retries = 2
        
        for attempt in range(max_retries):
            try:
                logger.info(f"Generating complete seele.json as fallback for summary {summary_id} (attempt {attempt + 1}/{max_retries})")
                
                # Generate complete JSON
                complete_json_str = await self._generate_complete_memory_json_async(messages, error_message, summary_id)
                
                if not complete_json_str:
                    logger.error("Failed to generate complete JSON - empty response")
                    continue
                
                # Clean the response
                complete_json_str = self._clean_json_response(complete_json_str)
                
                # Log the response for debugging
                logger.debug(f"Generated JSON length: {len(complete_json_str)} chars")
                logger.debug(f"First 200 chars: {complete_json_str[:200]}")
                logger.debug(f"Last 200 chars: {complete_json_str[-200:]}")
                
                # Parse and validate
                complete_data = json.loads(complete_json_str)
                
                # Validate structure
                if not self._validate_seele_structure(complete_data):
                    logger.warning("Generated JSON has invalid structure, retrying...")
                    error_message = "Previous attempt produced invalid structure. Ensure all required fields are present: bot, user, memorable_events, commands_and_agreements"
                    continue
                
                # Write directly to seele.json
                from config import Config
                import json as json_module
                
                config = Config()
                seele_path = config.SEELE_JSON_PATH
                
                seele_path.parent.mkdir(parents=True, exist_ok=True)
                with open(seele_path, "w", encoding="utf-8") as f:
                    json_module.dump(complete_data, f, indent=2, ensure_ascii=False)
                
                # Clear cache to force reload
                import prompts.system
                prompts.system._seele_json_cache = None
                
                logger.info(f"Successfully updated seele.json with complete JSON (fallback) for summary {summary_id}")
                return True
                
            except json.JSONDecodeError as e:
                logger.error(f"JSON parsing failed (attempt {attempt + 1}/{max_retries}): {e}")
                logger.error(f"Error at line {e.lineno}, column {e.colno}, position {e.pos}")
                if attempt < max_retries - 1:
                    # Update error message for next retry
                    error_message = f"Previous JSON generation failed with parse error at line {e.lineno}: {str(e)}. Please ensure proper JSON syntax: all strings must be properly quoted and escaped, no trailing commas, proper brace/bracket matching."
                else:
                    logger.error("Max retries reached for complete JSON generation")
                    return False
                    
            except Exception as e:
                logger.error(f"Fallback to complete JSON failed (attempt {attempt + 1}/{max_retries}): {e}")
                if attempt >= max_retries - 1:
                    return False
        
        return False

    def get_long_term_memory(self) -> Dict[str, Any]:
        from prompts.system import load_seele_json
        return load_seele_json()

    def get_context_messages(self) -> List[Dict[str, str]]:
        return self.context_window.get_context_as_messages()

    def get_recent_summaries(self) -> List[str]:
        return self.context_window.get_recent_summaries_as_text()
