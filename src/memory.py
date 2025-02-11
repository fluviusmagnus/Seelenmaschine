import json
from datetime import datetime
from typing import List, Dict
from pathlib import Path
import uuid

from config import (
    SELF_PERSONA_PATH,
    USER_PERSONA_PATH,
    DEFAULT_SELF_PERSONA,
    DEFAULT_USER_PERSONA,
    MAX_CONV_NUM,
    REFRESH_EVERY_CONV_NUM,
    OPENAI_API_KEY,
    OPENAI_API_BASE,
    CHAT_MODEL,
)
from prompts import (
    SUMMARIZER_SYSTEM_PROMPT,
    PERSONA_ANALYZER_SYSTEM_PROMPT,
    build_summary_prompt,
    build_self_persona_prompt,
    build_user_persona_prompt,
)
from database import Database
from openai import OpenAI


class Memory:
    def __init__(self):
        self.client = OpenAI(
            api_key=OPENAI_API_KEY,
            base_url=OPENAI_API_BASE,
        )
        self.db = Database()

        # Load personas
        self.self_persona = self._load_persona(SELF_PERSONA_PATH, DEFAULT_SELF_PERSONA)
        self.user_persona = self._load_persona(USER_PERSONA_PATH, DEFAULT_USER_PERSONA)

        # Try to load last session first
        last_session = self.db.get_last_session()
        if last_session:
            # Restore existing session
            self.session_id = last_session["session_id"]
            self.start_time = last_session.get("start_time", datetime.now())
            self.conversation_summary = last_session["summary"]
            self.current_conversations = last_session["conversations"]
            print("\nRestored existing session:", self.session_id)
        else:
            # Create new session if none exists
            self.session_id = str(uuid.uuid4())
            self.start_time = datetime.now()
            self.current_conversations = []
            self.conversation_summary = ""
            print("\nCreated new session:", self.session_id)

    def _load_persona(self, path: Path, default: str) -> str:
        """Load persona from file or create with default values"""
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                return f.read()

        with open(path, "w", encoding="utf-8") as f:
            f.write(default)
        return default

    def _save_persona(self, path: Path, persona: str) -> None:
        """Save persona to file"""
        with open(path, "w", encoding="utf-8") as f:
            f.write(persona)

    def add_conversation(self, role: str, content: str) -> None:
        """Add a new conversation entry"""
        self.current_conversations.append(
            {
                "role": role,
                "content": content,
                "timestamp": datetime.now().isoformat(),
            }
        )

        # Check if we need to refresh summary
        if len(self.current_conversations) >= MAX_CONV_NUM:
            old_convs = self.current_conversations[:REFRESH_EVERY_CONV_NUM]
            self.current_conversations = self.current_conversations[
                REFRESH_EVERY_CONV_NUM:
            ]

            # Update summary
            old_text = "\n".join([f"{c['role']}: {c['content']}" for c in old_convs])
            prompt = build_summary_prompt(self.conversation_summary, old_text)

            response = self.client.chat.completions.create(
                model=CHAT_MODEL,
                messages=[
                    {"role": "system", "content": SUMMARIZER_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
            )
            self.conversation_summary = response.choices[0].message.content

            # Save current state
            self.save_session()

    def find_relevant_memories(self, query: str) -> List[Dict]:
        """Find relevant past conversations"""
        return self.db.find_relevant_sessions(query)

    def save_session(self) -> None:
        """Save current session to database"""
        self.db.save_session(
            self.session_id,
            self.conversation_summary,
            self.current_conversations,
            self.start_time,
        )

    def update_personas(self) -> None:
        """Update personas based on current session"""
        if not self.current_conversations:
            return

        # Prepare conversation history
        conv_text = "\n".join(
            [f"{c['role']}: {c['content']}" for c in self.current_conversations]
        )

        # Update self persona
        self_prompt = build_self_persona_prompt(self.self_persona, conv_text)

        response = self.client.chat.completions.create(
            model=CHAT_MODEL,
            messages=[
                {"role": "system", "content": PERSONA_ANALYZER_SYSTEM_PROMPT},
                {"role": "user", "content": self_prompt},
            ],
        )
        self.self_persona = response.choices[0].message.content
        self._save_persona(SELF_PERSONA_PATH, self.self_persona)

        # Update user persona
        user_prompt = build_user_persona_prompt(self.user_persona, conv_text)

        response = self.client.chat.completions.create(
            model=CHAT_MODEL,
            messages=[
                {"role": "system", "content": PERSONA_ANALYZER_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
        )
        self.user_persona = response.choices[0].message.content
        self._save_persona(USER_PERSONA_PATH, self.user_persona)

    def archive_session(self) -> None:
        """Archive current session and start a new empty one"""
        self.update_personas()  # Update personas before archiving
        self.save_session()  # Save current state to database

        # Start completely new session
        self.session_id = str(uuid.uuid4())
        self.start_time = datetime.now()
        self.current_conversations = []
        self.conversation_summary = ""

    def clear_conversations(self) -> None:
        """Clear current conversations and session data"""
        self.current_conversations = []
        self.conversation_summary = ""

        # Clear session data from database by saving empty state
        self.db.save_session(
            self.session_id,
            "",  # Empty summary
            [],  # Empty conversations
            self.start_time,
        )

    def reset_session(self) -> None:
        """Reset the current session while preserving recent conversation history"""
        # This is now only used for /exit to preserve state for next startup
        self.update_personas()  # Update personas before resetting

        # Keep last MAX_CONV_NUM conversations
        preserved_conversations = (
            self.current_conversations[-MAX_CONV_NUM:]
            if self.current_conversations
            else []
        )

        # Get current session's summary before resetting
        old_summary = self.conversation_summary

        # Create new session
        self.session_id = str(uuid.uuid4())
        self.start_time = datetime.now()
        self.current_conversations = preserved_conversations
        self.conversation_summary = old_summary  # Preserve the existing summary
