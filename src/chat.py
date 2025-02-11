from typing import Dict, List
import json
from datetime import datetime
from pathlib import Path

from config import (
    CHAT_MODEL,
    RECALL_SESSION_NUM,
    RECALL_CONV_NUM,
    OPENAI_API_KEY,
    OPENAI_API_BASE,
    DEBUG_MODE,
)
from prompts import (
    CHATBOT_SYSTEM_PROMPT,
    build_personality_context,
)
from memory import Memory
from openai import OpenAI


class ChatBot:
    def __init__(self):
        # Initialize OpenAI client with explicit configuration
        self.client = OpenAI(
            api_key=OPENAI_API_KEY,
            base_url=OPENAI_API_BASE,
        )
        self.memory = Memory()
        if DEBUG_MODE:
            # Only create logs directory if debug mode is enabled
            self.logs_dir = Path("logs")
            self.logs_dir.mkdir(exist_ok=True)

    def _log_messages(self, messages: List[Dict[str, str]]) -> None:
        """Log messages to a debug file"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_file = self.logs_dir / f"debug_{timestamp}.log"

        with log_file.open("w", encoding="utf-8") as f:
            f.write(f"Debug Log - {datetime.now().isoformat()}\n")
            f.write("=" * 80 + "\n\n")
            f.write("Messages sent to API:\n")
            f.write(json.dumps(messages, ensure_ascii=False, indent=2))
            f.write("\n")

    def _build_system_prompt(self) -> str:
        """Build the system prompt that guides the AI's behavior"""
        return CHATBOT_SYSTEM_PROMPT

    def _build_messages(self, user_input: str) -> List[Dict[str, str]]:
        """Build the complete message list for the API call"""
        messages = [{"role": "system", "content": self._build_system_prompt()}]

        # Add personality context
        personality_context = build_personality_context(
            self.memory.self_persona,
            self.memory.user_persona,
        )
        messages.append({"role": "system", "content": personality_context})

        # Add conversation summary if exists
        if self.memory.conversation_summary:
            messages.append(
                {
                    "role": "system",
                    "content": f"Summary of earlier conversation: {self.memory.conversation_summary}",
                }
            )

        # Find and add relevant past conversations
        relevant_sessions = self.memory.find_relevant_memories(user_input)
        if relevant_sessions:
            relevant_context = []
            for session in relevant_sessions[:RECALL_SESSION_NUM]:
                relevant_context.append(f"Session summary: {session['summary']}")
                # Add specific conversations from this session
                convs = session["conversations"]
                if len(convs) > RECALL_CONV_NUM:
                    convs = convs[-RECALL_CONV_NUM:]  # Get most recent conversations
                for conv in convs:
                    relevant_context.append(f"{conv['role']}: {conv['content']}")

            messages.append(
                {
                    "role": "system",
                    "content": "Relevant past interactions:\n"
                    + "\n".join(relevant_context),
                }
            )

        # Add current conversation context
        for conv in self.memory.current_conversations:
            # Map 'assistant' role to 'assistant' for compatibility
            role = "assistant" if conv["role"] == "assistant" else conv["role"]
            messages.append(
                {
                    "role": role,
                    "content": conv["content"],
                }
            )

        # Add current user input
        messages.append({"role": "user", "content": user_input})

        return messages

    def chat(self, user_input: str) -> str:
        """Process user input and return response"""
        # Build messages
        messages = self._build_messages(user_input)

        try:
            # Log messages before sending to API if debug mode is enabled
            if DEBUG_MODE:
                self._log_messages(messages)

            # Get response from API using gpt-3.5-turbo model
            response = self.client.chat.completions.create(
                model=CHAT_MODEL,
                messages=messages,
            )
            assistant_response = response.choices[0].message.content

            # Save to memory
            self.memory.add_conversation("user", user_input)
            self.memory.add_conversation("assistant", assistant_response)

            return assistant_response
        except Exception as e:
            print(f"\nDebug - API Request:")
            print(f"Base URL: {self.client.base_url}")
            print(f"Model: {CHAT_MODEL}")
            print(f"Error: {str(e)}")
            raise

    def archive_session(self) -> None:
        """Archive current session and start a new empty one"""
        self.memory.archive_session()

    def clear_conversations(self) -> None:
        """Clear current conversations while keeping session"""
        self.memory.clear_conversations()

    def save_and_preserve(self) -> None:
        """Save current session while preserving conversations for next startup"""
        self.memory.update_personas()
        self.memory.save_session()
