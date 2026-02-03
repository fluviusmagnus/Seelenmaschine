"""Message handlers for Telegram bot"""

import asyncio
import html
import json
import random
import re
from typing import List

from telegram import Update
from telegram.ext import ContextTypes

from config import Config
from core.database import DatabaseManager
from core.memory import MemoryManager
from core.scheduler import TaskScheduler
from llm.embedding import EmbeddingClient
from llm.reranker import RerankerClient
from tools.memory_search import MemorySearchTool
from tools.mcp_client import MCPClient
from tools.scheduled_task_tool import ScheduledTaskTool
from llm.client import LLMClient
from utils.logger import get_logger

logger = get_logger()


class MessageHandler:
    """Handles incoming messages and commands"""

    def __init__(self):
        """Initialize message handler"""
        self.config = Config()
        self.db = DatabaseManager()

        # Initialize embedding and reranker clients
        self.embedding_client = EmbeddingClient()
        self.reranker_client = RerankerClient()

        # Initialize memory manager with proper dependencies
        self.memory = MemoryManager(
            db=self.db,
            embedding_client=self.embedding_client,
            reranker_client=self.reranker_client,
        )

        # Initialize scheduler
        self.scheduler = TaskScheduler(self.db)

        # Initialize scheduled task tool with scheduler
        self.scheduled_task_tool = None
        self.scheduled_task_tool_def = None
        self._register_scheduled_task_tool()

        # Initialize LLM client
        self.llm_client = LLMClient()

        # Initialize attributes
        self.memory_search_tool = None
        self.mcp_client = None
        self._mcp_connected = False

        # Setup tools for LLM
        self._setup_tools()

        # Setup scheduler callback (will be started as Application job in bot.py)
        self.scheduler.set_message_callback(self._handle_scheduled_message)
        logger.info("Task scheduler callback registered")

        logger.info("MessageHandler initialized")

    def _register_scheduled_task_tool(self):
        """Register the scheduled task tool with scheduler instance"""
        try:
            self.scheduled_task_tool = ScheduledTaskTool(self.scheduler)
            self.scheduled_task_tool_def = {
                "type": "function",
                "function": {
                    "name": self.scheduled_task_tool.name,
                    "description": self.scheduled_task_tool.description,
                    "parameters": self.scheduled_task_tool.parameters,
                },
            }
            logger.info("Registered scheduled_task tool with scheduler")
        except Exception as e:
            logger.error(f"Failed to register scheduled_task tool: {e}")
            self.scheduled_task_tool = None
            self.scheduled_task_tool_def = None

    async def _handle_scheduled_message(
        self, message: str, task_name: str = "Scheduled Task"
    ) -> str:
        """Handle messages from scheduled tasks - trigger LLM conversation

        This method is called when a scheduled task triggers. It:
        1. Wraps the task message with [SYSTEM_SCHEDULED_TASK] marker
        2. Does NOT save the task message to database (transient)
        3. Calls LLM to generate a response
        4. Saves the LLM response to database (part of session)
        5. Returns the LLM response for sending to user

        Args:
            message: Raw task message from scheduler
            task_name: Name of the scheduled task for context

        Returns:
            LLM generated response to send to user
        """
        logger.info(f"Processing scheduled task '{task_name}': {message[:50]}...")
        return await self._process_scheduled_task(message, task_name)

    def _format_response_for_telegram(self, text: str) -> str:
        """Format response text for Telegram HTML"""
        # We are switching to HTML parse mode as it is more robust for our needs
        # We need to escape special HTML characters in the text, but PRESERVE our blockquote tags
        # and other formatting if we want to support it.

        # However, the LLM outputs markdown-like text (e.g. **bold**) and our specific blockquotes.
        # So we need a comprehensive formatter:
        # 1. Escape HTML special chars in the whole text (except our tags? No, that's hard).
        # Better approach:
        # 1. Split text by our known tags (blockquote).
        # 2. For the non-tag parts, escape HTML (<, >, &).
        # 3. For the tag parts, keep them as is (Telegram supports <blockquote> in HTML mode).
        # 4. Also handle markdown bold/italic if possible, OR just strip them/convert them.

        # Simplified approach consistent with user request:
        # User wants blockquotes to be CODE BLOCKS to avoid issues.
        # So we will convert <blockquote>...</blockquote> to <pre>...</pre> (which is code block in HTML).

        # Helper to escape text but preserve code blocks we create
        # But wait, if we use HTML, we can just use <pre> tag!

        # Strategy:
        # 1. Replace <blockquote>...</blockquote> with a temporary unique placeholder
        # 2. Escape the rest of the text
        # 3. Replace placeholder with <pre>...escaped_content...</pre>
        # 4. Handle **bold** -> <b>bold</b> conversions manually or just leave as is?
        #    If we switch to HTML, **bold** won't render as bold unless we convert it.
        #    We should try to support basic markdown bold.

        from config import Config
        from utils.text import strip_blockquotes

        if not Config.DEBUG_MODE:
            text = strip_blockquotes(text)

        # Step 1: Extract blockquotes
        placeholders = []

        def save_blockquote(match):
            content = match.group(1).strip()
            placeholders.append(content)
            return f"BLOCKQUOTEPLACEHOLDER{len(placeholders) - 1}END"

        text_with_placeholders = re.sub(
            r"<\s*blockquote[^>]*>(.*?)<\s*/\s*blockquote\s*>",
            save_blockquote,
            text,
            flags=re.DOTALL | re.IGNORECASE,
        )

        # Step 2: Escape HTML in the main text
        escaped_text = html.escape(text_with_placeholders)

        # Step 3: Convert Markdown to HTML
        # Bold (**text**) -> <b>text</b>
        escaped_text = re.sub(r"\*\*(.*?)\*\*", r"<b>\1</b>", escaped_text)

        # Italic (*text* or _text_) -> <i>text</i>
        # Note: we use _text_ for italics but __text__ for underline to match Telegram expectations
        escaped_text = re.sub(
            r"(?<!\*)\*(?!\*)(.*?)(?<!\*)\*(?!\*)", r"<i>\1</i>", escaped_text
        )
        escaped_text = re.sub(
            r"(?<!_)_(?!_)(.*?)(?<!_)_(?!_)", r"<i>\1</i>", escaped_text
        )

        # Underline (__text__) -> <u>text</u>
        escaped_text = re.sub(r"__(.*?)__", r"<u>\1</u>", escaped_text)

        # Inline code (`code`) -> <code>code</code>
        escaped_text = re.sub(r"`(.*?)`", r"<code>\1</code>", escaped_text)

        # Strikethrough (~~text~~ or ~text~) -> <s>text</s>
        escaped_text = re.sub(r"~~(.*?)~~", r"<s>\1</s>", escaped_text)

        # Spoiler (||text||) -> <tg-spoiler>text</tg-spoiler>
        escaped_text = re.sub(
            r"\|\|(.*?)\|\|", r"<tg-spoiler>\1</tg-spoiler>", escaped_text
        )

        # Links ([text](url)) -> <a href="url">text</a>
        escaped_text = re.sub(
            r"\[(.*?)\]\((.*?)\)", r'<a href="\2">\1</a>', escaped_text
        )

        # Step 4: Restore blockquotes as <pre> blocks
        # We need to escape the content inside the blockquote too, because it's going into HTML
        def restore_blockquote(match):
            idx = int(match.group(1))
            original_content = placeholders[idx]
            escaped_content = html.escape(original_content)
            return f"<pre>{escaped_content}</pre>"

        final_text = re.sub(
            r"BLOCKQUOTEPLACEHOLDER(\d+)END", restore_blockquote, escaped_text
        )

        return final_text

    def _split_message_into_segments(
        self, text: str, max_length: int = 4000
    ) -> List[str]:
        """Split message into segments, keeping code blocks and blockquotes intact.

        Args:
            text: Formatted text for Telegram (HTML)
            max_length: Maximum length per segment (Telegram limit is ~4096)

        Returns:
            List of message segments
        """
        segments: List[str] = []

        def _append_segment(content: str) -> None:
            if content and content.strip():
                segments.append(content.strip())

        def _split_long_text(content: str, limit: int) -> List[str]:
            if len(content) <= limit:
                return [content]

            chunks: List[str] = []
            remaining = content

            while len(remaining) > limit:
                slice_text = remaining[:limit]
                split_index = max(slice_text.rfind("\n"), slice_text.rfind(" "))
                if split_index <= 0:
                    split_index = limit

                chunk = remaining[:split_index].strip()
                if chunk:
                    chunks.append(chunk)

                remaining = remaining[split_index:].lstrip()

            if remaining:
                chunks.append(remaining.strip())

            return chunks

        # Pattern to match code blocks (<pre>...</pre>) and blockquotes (<blockquote>...</blockquote>)
        # These should never be split
        pattern = r"(<pre>.*?</pre>|<blockquote>.*?</blockquote>)"

        # Split by the pattern, keeping delimiters
        parts = re.split(f"({pattern})", text, flags=re.DOTALL)

        for part in parts:
            if not part:
                continue

            # Check if this part is a code block or blockquote
            is_code_block = part.startswith("<pre>") and part.endswith("</pre>")
            is_blockquote = part.startswith("<blockquote>") and part.endswith(
                "</blockquote>"
            )

            if is_code_block or is_blockquote:
                # Always keep blocks intact as their own segments
                _append_segment(part)
                continue

            # Regular text - split by paragraph and send each paragraph separately
            paragraphs = [p for p in part.split("\n\n") if p.strip()]

            for para in paragraphs:
                paragraph_pieces = _split_long_text(para, max_length)
                for piece in paragraph_pieces:
                    _append_segment(piece)

        return [seg for seg in segments if seg]

    def _setup_tools(self):
        """Setup tool system for LLM"""
        tools = []

        # Add scheduled task tool
        if self.scheduled_task_tool_def:
            tools.append(self.scheduled_task_tool_def)
            logger.info("Added scheduled_task tool")

        # Add MCP tools (will be initialized async later)
        if self.config.ENABLE_MCP:
            self.mcp_client = MCPClient()
            self._mcp_connected = False
        else:
            self.mcp_client = None
            self._mcp_connected = False

        self._setup_basic_tools()

    def _setup_basic_tools(self):
        """Setup basic (non-MCP) tools"""
        tools = []

        if self.scheduled_task_tool_def:
            tools.append(self.scheduled_task_tool_def)
            logger.info("Added scheduled_task tool")

        # Add memory search tool
        session_id = self.memory.get_current_session_id()
        if not hasattr(self, "memory_search_tool") or self.memory_search_tool is None:
            self.memory_search_tool = MemorySearchTool(
                session_id=str(session_id),
                db=self.db,
                embedding_client=self.embedding_client,
                reranker_client=self.reranker_client,
            )

        memory_search_tool_def = {
            "type": "function",
            "function": {
                "name": self.memory_search_tool.name,
                "description": self.memory_search_tool.description,
                "parameters": self.memory_search_tool.parameters,
            },
        }
        tools.append(memory_search_tool_def)
        logger.info("Added memory_search tool")

        # Set tools and executor in LLM client
        self.llm_client.set_tools(tools)
        self.llm_client.set_tool_executor(self._execute_tool)

        logger.info(f"Basic tools registered: {len(tools)}")

    async def _ensure_mcp_connected(self):
        """Ensure MCP client is connected"""
        if self.mcp_client and not self._mcp_connected:
            try:
                await self.mcp_client.__aenter__()
                self._mcp_connected = True

                # Get and register MCP tools
                mcp_tools = await self.mcp_client.list_tools()
                logger.info(f"Connected MCP client with {len(mcp_tools)} tools")
                for tool in mcp_tools:
                    tool_func = tool.get("function", {})
                    name = tool_func.get("name", "Unknown")
                    desc = tool_func.get("description", "No description")
                    logger.debug(f"  - [MCP Tool] {name}: {desc}")

                # Rebuild all tools list
                all_tools = []

                # 1. Add scheduled task tool
                if self.scheduled_task_tool_def:
                    all_tools.append(self.scheduled_task_tool_def)

                # 2. Add MCP tools
                all_tools.extend(mcp_tools)

                # 3. Add memory search tool
                memory_search_tool_def = {
                    "type": "function",
                    "function": {
                        "name": self.memory_search_tool.name,
                        "description": self.memory_search_tool.description,
                        "parameters": self.memory_search_tool.parameters,
                    },
                }
                all_tools.append(memory_search_tool_def)

                self.llm_client.set_tools(all_tools)
                logger.info(
                    f"Updated tools: {len(all_tools)} total including {len(mcp_tools)} MCP tools"
                )
            except Exception as e:
                logger.error(f"Failed to connect MCP client: {e}")
                self._mcp_connected = False
                # Ensure we still have basic tools even if MCP fails
                self._setup_basic_tools()

    async def _execute_tool(self, tool_name: str, arguments_json: str) -> str:
        """Execute a tool call from LLM"""
        try:
            arguments = json.loads(arguments_json)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse tool arguments: {e}")
            return f"Error: Invalid JSON arguments: {e}"

        logger.info(f"Executing tool: {tool_name} with args: {arguments}")

        # Check if it's the memory search tool
        if tool_name == self.memory_search_tool.name:
            return await self.memory_search_tool.execute(**arguments)

        # Check if it's the scheduled task tool
        if self.scheduled_task_tool and tool_name == self.scheduled_task_tool.name:
            return await self.scheduled_task_tool.execute(**arguments)

        # Check if it's an MCP tool
        if self.mcp_client:
            # Ensure MCP is connected
            await self._ensure_mcp_connected()

            if self._mcp_connected:
                # Optimized check: search in cached tools if available
                mcp_tools = self.mcp_client.get_tools_sync()
                if any(t["function"]["name"] == tool_name for t in mcp_tools):
                    return await self.mcp_client.call_tool(tool_name, arguments)

        return f"Error: Tool not found: {tool_name}"

    async def handle_message(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle regular text messages

        Args:
            update: Telegram update object
            context: Telegram context
        """
        if not update.effective_user or not update.message or not update.message.text:
            return

        user_id = update.effective_user.id

        # Check authorization
        if user_id != self.config.TELEGRAM_USER_ID:
            await update.message.reply_text("Unauthorized access.")
            logger.warning(f"Unauthorized message from user {user_id}")
            return

        user_message = update.message.text
        logger.info(f"Received message: {user_message[:50]}...")

        async def _keep_typing_indicator():
            """Background task to keep typing indicator active"""
            while True:
                try:
                    await context.bot.send_chat_action(
                        chat_id=update.effective_chat.id, action="typing"
                    )
                    await asyncio.sleep(3)  # Send typing action every 3 seconds
                except Exception as e:
                    logger.warning(f"Typing indicator failed: {e}")
                    await asyncio.sleep(3)

        try:
            # Start background task to keep typing indicator active
            typing_task = asyncio.create_task(_keep_typing_indicator())

            try:
                # Process message through memory and LLM
                response = await self._process_message(user_message)

                # Send response using HTML parse mode
                # We always use HTML now because we rely on it for <pre> blockquotes
                # Split long messages into segments, keeping code blocks intact
                formatted_response = self._format_response_for_telegram(response)
                segments = self._split_message_into_segments(formatted_response)

                logger.debug(f"Response split into {len(segments)} segments")

                for i, segment in enumerate(segments):
                    try:
                        await update.message.reply_text(
                            segment,
                            parse_mode="HTML",
                        )
                        logger.debug(
                            f"Sent segment {i + 1}/{len(segments)} ({len(segment)} chars)"
                        )

                        # Add delay between segments (except after the last one)
                        if i < len(segments) - 1:
                            delay = random.uniform(1.0, 2.0)
                            logger.debug(f"Waiting {delay:.1f}s before next segment")
                            await asyncio.sleep(delay)
                    except Exception as e:
                        # If HTML parsing fails for this segment, try sending as plain text
                        error_msg = str(e)
                        logger.warning(
                            f"HTML parsing failed for segment {i + 1}, sending as plain text: {error_msg}"
                        )
                        try:
                            await update.message.reply_text(segment)
                        except Exception as e2:
                            logger.error(f"Failed to send segment {i + 1}: {e2}")
            finally:
                # Cancel typing indicator task
                typing_task.cancel()
                try:
                    await typing_task
                except asyncio.CancelledError:
                    pass

        except Exception as e:
            logger.error(f"Error handling message: {e}", exc_info=True)
            await update.message.reply_text(
                "Sorry, an error occurred while processing your message."
            )

    async def handle_new_session(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle /new command - archive current session and start new

        Args:
            update: Telegram update object
            context: Telegram context
        """
        if not update.effective_user or not update.message:
            return

        user_id = update.effective_user.id

        if user_id != self.config.TELEGRAM_USER_ID:
            await update.message.reply_text("Unauthorized access.")
            return

        try:
            logger.info("Creating new session")

            # Create new session (automatically closes old one and summarizes remaining conversations)
            new_session_id = await self.memory.new_session_async()
            logger.info(f"Created new session {new_session_id}")

            # Update memory_search_tool session_id
            if hasattr(self, "memory_search_tool") and self.memory_search_tool:
                self.memory_search_tool.session_id = int(new_session_id)
                logger.info(
                    f"Updated memory_search_tool session_id to {new_session_id}"
                )

            await update.message.reply_text(
                "✓ New session created! Previous conversations have been summarized and archived.\n\n"
                "I still remember our history and can recall it when relevant."
            )

        except Exception as e:
            logger.error(f"Error creating new session: {e}", exc_info=True)
            await update.message.reply_text("Error creating new session.")

    async def handle_reset_session(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle /reset command - delete current session

        Args:
            update: Telegram update object
            context: Telegram context
        """
        if not update.effective_user or not update.message:
            return

        user_id = update.effective_user.id

        if user_id != self.config.TELEGRAM_USER_ID:
            await update.message.reply_text("Unauthorized access.")
            return

        try:
            logger.info("Resetting session")

            # Reset session (delete current and create new)
            self.memory.reset_session()

            await update.message.reply_text(
                "✓ Session reset! Current conversation has been deleted.\n\n"
                "Starting fresh, but I still have memories from previous sessions."
            )

        except Exception as e:
            logger.error(f"Error resetting session: {e}", exc_info=True)
            await update.message.reply_text("Error resetting session.")

    async def _process_message(self, user_message: str) -> str:
        """Process user message through memory and LLM

        Args:
            user_message: User's message text

        Returns:
            Bot's response
        """
        try:
            # Step 1: Add user message to memory (and get embedding for reuse)
            logger.debug("Step 1: Adding user message to memory")
            conversation_id, user_embedding = await self.memory.add_user_message_async(
                user_message
            )

            # Step 2: Get current context (recent conversations + summaries)
            logger.debug("Step 2: Getting current context")
            current_context = self.memory.get_context_messages()

            # Step 3: Retrieve relevant memories from history
            logger.debug("Step 3: Retrieving relevant memories")
            # Get last bot message for dual-query retrieval
            last_bot_message = None
            if current_context:
                for msg in reversed(current_context):
                    if msg.get("role") == "assistant":
                        last_bot_message = msg.get("content", "")
                        break

            # Retrieve memories (reuse embedding from Step 1 to avoid re-vectorization)
            (
                retrieved_summaries,
                retrieved_conversations,
            ) = await self.memory.process_user_input_async(
                user_input=user_message,
                last_bot_message=last_bot_message,
                user_input_embedding=user_embedding,
            )

            logger.debug(
                f"Retrieved {len(retrieved_summaries)} summaries and {len(retrieved_conversations)} conversations"
            )

            # Step 4: Get recent summaries from context window
            logger.debug("Step 4: Getting recent summaries")
            recent_summaries = self.memory.get_recent_summaries()
            logger.debug(f"Got {len(recent_summaries)} recent summaries")

            # Step 5: Enable memory search tool for LLM to use
            logger.debug("Step 5: Enabling memory search tool")
            self.memory_search_tool.enable()

            # Step 5.5: Ensure MCP is connected so tools are available to LLM
            if self.mcp_client:
                logger.debug("Step 5.5: Ensuring MCP is connected")
                await self._ensure_mcp_connected()

            # Step 6: Call LLM with full context and tools
            logger.debug("Step 6: Calling LLM")
            response = await self.llm_client.chat_async(
                current_context=current_context,
                retrieved_summaries=retrieved_summaries,
                retrieved_conversations=retrieved_conversations,
                recent_summaries=recent_summaries,
            )

            # Step 7: Disable memory search tool during response generation
            logger.debug("Step 7: Disabling memory search tool")
            self.memory_search_tool.disable()

            # Step 8: Add assistant response to memory
            logger.debug("Step 8: Adding assistant response to memory")
            conversation_id, summary_id = await self.memory.add_assistant_message_async(
                response
            )

            if summary_id:
                logger.info(
                    f"Created new summary (ID: {summary_id}) during message processing"
                )

            # Step 9: Return response
            logger.debug("Message processing complete")
            return response

        except Exception as e:
            logger.error(f"Error in _process_message: {e}", exc_info=True)
            raise

    async def _process_scheduled_task(
        self, task_message: str, task_name: str = "Scheduled Task"
    ) -> str:
        """Process scheduled task message through LLM

        Similar to _process_message but:
        - Does NOT save the task message to database
        - Does NOT count toward unsummarized messages
        - Task message is transient and only exists for this LLM call
        - LLM response IS saved to database as part of session

        Args:
            task_message: Raw task message from scheduler

        Returns:
            Bot's response to the scheduled task
        """
        try:
            # Get current timestamp for task
            from utils.time import get_current_timestamp, timestamp_to_str

            trigger_time = get_current_timestamp()
            trigger_time_str = timestamp_to_str(trigger_time)

            # Wrap task message with [SYSTEM_SCHEDULED_TASK] marker
            wrapped_message = (
                f"[SYSTEM_SCHEDULED_TASK]\n"
                f"Task Name: {task_name}\n"
                f"Trigger Time: {trigger_time_str}\n"
                f"Task: {task_message}\n\n"
                f"Please respond proactively based on this scheduled task."
            )

            logger.debug(f"Wrapped scheduled task message: {wrapped_message[:100]}...")

            # Step 1: Get current context (recent conversations + summaries)
            # Note: We do NOT add the task message to memory/context_window
            logger.debug("Step 1: Getting current context for scheduled task")
            current_context = self.memory.get_context_messages()

            # Step 2: Retrieve relevant memories based on task content
            logger.debug("Step 2: Retrieving relevant memories for scheduled task")
            # Use task content for retrieval (not the wrapped version with marker)
            task_embedding = await self.embedding_client.get_embedding_async(
                task_message
            )

            # Get last bot message for dual-query retrieval
            last_bot_message = None
            if current_context:
                for msg in reversed(current_context):
                    if msg.get("role") == "assistant":
                        last_bot_message = msg.get("content", "")
                        break

            # Retrieve memories using task content and embedding
            (
                retrieved_summaries,
                retrieved_conversations,
            ) = await self.memory.process_user_input_async(
                user_input=task_message,
                last_bot_message=last_bot_message,
                user_input_embedding=task_embedding,
            )

            logger.debug(
                f"Retrieved {len(retrieved_summaries)} summaries and "
                f"{len(retrieved_conversations)} conversations for scheduled task"
            )

            # Step 3: Get recent summaries from context window
            logger.debug("Step 3: Getting recent summaries")
            recent_summaries = self.memory.get_recent_summaries()
            logger.debug(f"Got {len(recent_summaries)} recent summaries")

            # Step 4: Enable memory search tool for LLM to use
            logger.debug("Step 4: Enabling memory search tool")
            if self.memory_search_tool:
                self.memory_search_tool.enable()

            # Step 4.5: Ensure MCP is connected so tools are available to LLM
            if self.mcp_client:
                logger.debug("Step 4.5: Ensuring MCP is connected")
                await self._ensure_mcp_connected()

            # Step 5 & 6: Call LLM with custom user message (task message not in current_context)
            # Use chat_with_custom_message_async to handle message building and LLM calling
            logger.debug("Step 5-6: Calling LLM with custom task message")
            response_text = await self.llm_client.chat_with_custom_message_async(
                current_context=current_context,
                retrieved_summaries=retrieved_summaries,
                retrieved_conversations=retrieved_conversations,
                recent_summaries=recent_summaries,
                custom_user_message=wrapped_message,
            )

            # Step 7: Disable memory search tool
            logger.debug("Step 7: Disabling memory search tool")
            if self.memory_search_tool:
                self.memory_search_tool.disable()

            # Step 8: Add assistant response to memory (THIS IS SAVED!)
            logger.debug("Step 8: Adding assistant response to memory (scheduled task)")
            conversation_id, summary_id = await self.memory.add_assistant_message_async(
                response_text
            )

            if summary_id:
                logger.info(
                    f"Created new summary (ID: {summary_id}) during scheduled task processing"
                )

            # Step 9: Return response
            logger.info(
                f"Scheduled task processing complete, response: {response_text[:50]}..."
            )
            return response_text

        except Exception as e:
            logger.error(f"Error in _process_scheduled_task: {e}", exc_info=True)
            # Return a friendly error message that will be sent to user
            return f"[Scheduled Task] {task_message}\n\n(Error occurred while processing, please check logs)"
