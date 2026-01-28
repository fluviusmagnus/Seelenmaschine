"""Message handlers for Telegram bot"""
import json
from telegram import Update
from telegram.ext import ContextTypes

from config import Config
from core.database import DatabaseManager
from core.memory import MemoryManager
from core.scheduler import TaskScheduler
from llm.embedding import EmbeddingClient
from llm.reranker import RerankerClient
from tools.skill_manager import SkillManager
from tools.memory_search import MemorySearchTool
from tools.mcp_client import MCPClient
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
            reranker_client=self.reranker_client
        )
        
        # Initialize scheduler
        self.scheduler = TaskScheduler(self.db)
        
        # Initialize skill manager and load skills
        self.skill_manager = SkillManager()
        
        # Load scheduled task skill with scheduler
        if self.config.ENABLE_SKILLS:
            self._register_scheduled_task_skill()
        
        # Initialize LLM client
        self.llm_client = LLMClient()
        
        # Setup tools for LLM
        self._setup_tools()
        
        # Setup scheduler callback (will be started as Application job in bot.py)
        self.scheduler.set_message_callback(self._handle_scheduled_message)
        logger.info("Task scheduler callback registered")
        
        logger.info("MessageHandler initialized")
    
    def _register_scheduled_task_skill(self):
        """Register the scheduled task skill with scheduler instance"""
        try:
            from skills.scheduled_task_skill import ScheduledTaskSkill
            scheduled_task_skill = ScheduledTaskSkill(self.scheduler)
            self.skill_manager._skills[scheduled_task_skill.name] = scheduled_task_skill
            # Clear tools cache to force rebuild
            self.skill_manager._tools_cache = None
            logger.info("Registered scheduled_task skill with scheduler")
        except Exception as e:
            logger.error(f"Failed to register scheduled_task skill: {e}")
    
    def _handle_scheduled_message(self, message: str):
        """Handle messages from scheduled tasks"""
        # This will be called by the scheduler when a task triggers
        # For now, just log it - in production, send via Telegram
        logger.info(f"Scheduled task message: {message}")
        # TODO: Send message to user via Telegram
    
    def _setup_tools(self):
        """Setup tool system for LLM"""
        tools = []
        
        # Add skills tools
        if self.config.ENABLE_SKILLS:
            skill_tools = self.skill_manager.get_tools()
            tools.extend(skill_tools)
            logger.info(f"Added {len(skill_tools)} skill tools")
        
        # Add MCP tools (will be initialized async later)
        if self.config.ENABLE_MCP:
            self.mcp_client = MCPClient()
            self._mcp_connected = False
        else:
            self.mcp_client = None
            self._mcp_connected = False
        
        # Add memory search tool
        session_id = self.memory.get_current_session_id()
        self.memory_search_tool = MemorySearchTool(
            session_id=str(session_id),
            db=self.db,
            embedding_client=self.embedding_client,
            reranker_client=self.reranker_client
        )
        
        memory_search_tool_def = {
            "type": "function",
            "function": {
                "name": self.memory_search_tool.name,
                "description": self.memory_search_tool.description,
                "parameters": self.memory_search_tool.parameters
            }
        }
        tools.append(memory_search_tool_def)
        logger.info("Added memory_search tool")
        
        # Set tools and executor in LLM client
        self.llm_client.set_tools(tools)
        self.llm_client.set_tool_executor(self._execute_tool)
        
        logger.info(f"Total tools registered: {len(tools)}")
    
    async def _ensure_mcp_connected(self):
        """Ensure MCP client is connected"""
        if self.mcp_client and not self._mcp_connected:
            try:
                await self.mcp_client.__aenter__()
                self._mcp_connected = True
                
                # Get and register MCP tools
                mcp_tools = await self.mcp_client.list_tools()
                logger.info(f"Connected MCP client with {len(mcp_tools)} tools")
                
                # Update tools in LLM client
                all_tools = []
                if self.config.ENABLE_SKILLS:
                    all_tools.extend(self.skill_manager.get_tools())
                all_tools.extend(mcp_tools)
                
                # Add memory search tool
                memory_search_tool_def = {
                    "type": "function",
                    "function": {
                        "name": self.memory_search_tool.name,
                        "description": self.memory_search_tool.description,
                        "parameters": self.memory_search_tool.parameters
                    }
                }
                all_tools.append(memory_search_tool_def)
                
                self.llm_client.set_tools(all_tools)
                logger.info(f"Updated tools: {len(all_tools)} total")
            except Exception as e:
                logger.error(f"Failed to connect MCP client: {e}")
                self._mcp_connected = False
    
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
        
        # Check if it's a skill
        if tool_name in self.skill_manager._skills:
            return await self.skill_manager.execute_skill(tool_name, arguments)
        
        # Check if it's an MCP tool
        if self.mcp_client:
            # Ensure MCP is connected
            await self._ensure_mcp_connected()
            
            if self._mcp_connected:
                mcp_tools = await self.mcp_client.list_tools()
                if tool_name in [t["function"]["name"] for t in mcp_tools]:
                    return await self.mcp_client.call_tool(tool_name, arguments)
        
        return f"Error: Tool not found: {tool_name}"
    
    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
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
        
        try:
            # Send typing indicator
            await update.message.chat.send_action("typing")
            
            # Process message through memory and LLM
            response = await self._process_message(user_message)
            
            # Send response with automatic fallback on markdown errors
            use_markdown = getattr(self.config, 'TELEGRAM_USE_MARKDOWN', True)
            if use_markdown:
                try:
                    # Try to send with MarkdownV2
                    await update.message.reply_text(
                        response,
                        parse_mode='MarkdownV2'
                    )
                except Exception as e:
                    # If markdown parsing fails, fall back to plain text
                    error_msg = str(e)
                    if "can't parse entities" in error_msg.lower() or "can't find end" in error_msg.lower():
                        logger.warning(f"MarkdownV2 parsing failed, sending as plain text: {error_msg}")
                        await update.message.reply_text(response)
                    else:
                        # Re-raise if it's not a parsing error
                        raise
            else:
                # Send as plain text
                await update.message.reply_text(response)
            
        except Exception as e:
            logger.error(f"Error handling message: {e}", exc_info=True)
            await update.message.reply_text(
                "Sorry, an error occurred while processing your message."
            )
    
    async def handle_new_session(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
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
            
            await update.message.reply_text(
                "✓ New session created! Previous conversations have been summarized and archived.\n\n"
                "I still remember our history and can recall it when relevant."
            )
            
        except Exception as e:
            logger.error(f"Error creating new session: {e}", exc_info=True)
            await update.message.reply_text("Error creating new session.")
    
    async def handle_reset_session(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
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
            conversation_id, user_embedding = await self.memory.add_user_message_async(user_message)
            
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
            retrieved_summaries, retrieved_conversations = await self.memory.process_user_input_async(
                user_input=user_message,
                last_bot_message=last_bot_message,
                user_input_embedding=user_embedding
            )
            
            logger.debug(f"Retrieved {len(retrieved_summaries)} summaries and {len(retrieved_conversations)} conversations")
            
            # Step 4: Get recent summaries from context window
            logger.debug("Step 4: Getting recent summaries")
            recent_summaries = self.memory.get_recent_summaries()
            logger.debug(f"Got {len(recent_summaries)} recent summaries")
            
            # Step 5: Enable memory search tool for LLM to use
            logger.debug("Step 5: Enabling memory search tool")
            self.memory_search_tool.enable()
            
            # Step 6: Call LLM with full context and tools
            logger.debug("Step 6: Calling LLM")
            response = await self.llm_client.chat_async(
                current_context=current_context,
                retrieved_summaries=retrieved_summaries,
                retrieved_conversations=retrieved_conversations,
                recent_summaries=recent_summaries
            )
            
            # Step 7: Disable memory search tool during response generation
            logger.debug("Step 7: Disabling memory search tool")
            self.memory_search_tool.disable()
            
            # Step 8: Add assistant response to memory
            logger.debug("Step 8: Adding assistant response to memory")
            conversation_id, summary_id = await self.memory.add_assistant_message_async(response)
            
            if summary_id:
                logger.info(f"Created new summary (ID: {summary_id}) during message processing")
            
            # Step 9: Return response
            logger.debug("Message processing complete")
            return response
            
        except Exception as e:
            logger.error(f"Error in _process_message: {e}", exc_info=True)
            raise
