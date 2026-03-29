from dataclasses import dataclass
from typing import Dict, List, Optional
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.logger import get_logger

logger = get_logger()


@dataclass
class Message:
    role: str
    text: str
    embedding: Optional[List[float]] = None
    message_type: str = "conversation"
    include_in_turn_count: bool = True
    include_in_summary: bool = True

    def to_dict(self) -> Dict[str, str]:
        return {"role": self.role, "content": self.text}

    @classmethod
    def from_dict(cls, data: Dict[str, str]) -> "Message":
        return cls(
            role=data["role"],
            text=data["text"],
            message_type=data.get("message_type", "conversation"),
            include_in_turn_count=data.get("include_in_turn_count", True),
            include_in_summary=data.get("include_in_summary", True),
        )


@dataclass
class Summary:
    summary: str
    summary_id: int


class ContextWindow:
    """Pure in-memory context window manager."""

    def __init__(self):
        self.context_window: List[Message] = []
        self.recent_summaries: List[Summary] = []
        logger.debug("ContextWindow initialized")

    def add_message(
        self,
        role: str,
        text: str,
        embedding: Optional[List[float]] = None,
        *,
        message_type: str = "conversation",
        include_in_turn_count: bool = True,
        include_in_summary: bool = True,
    ) -> None:
        self.context_window.append(
            Message(
                role=role,
                text=text,
                embedding=embedding,
                message_type=message_type,
                include_in_turn_count=include_in_turn_count,
                include_in_summary=include_in_summary,
            )
        )
        logger.debug(
            "Added message: "
            f"role={role}, type={message_type}, text length={len(text)}, "
            f"with_embedding={embedding is not None}, "
            f"counts={include_in_turn_count}, summary={include_in_summary}"
        )

    def add_summary(self, summary: str, summary_id: int) -> None:
        self.recent_summaries.append(Summary(summary=summary, summary_id=summary_id))

        from core.config import Config

        max_summaries = Config.RECENT_SUMMARIES_MAX
        if len(self.recent_summaries) > max_summaries:
            self.recent_summaries = self.recent_summaries[-max_summaries:]
            logger.debug(f"Trimmed summaries to max {max_summaries}")

    def get_messages_for_summary(self, count: int) -> List[Message]:
        selected: List[Message] = []
        for message in self.context_window:
            if message.include_in_summary:
                selected.append(message)
            if len(selected) >= count:
                break
        return selected

    def remove_earliest_messages(self, count: int) -> List[Message]:
        if count <= 0:
            return []

        removed_countable = 0
        cutoff = 0
        for idx, message in enumerate(self.context_window, start=1):
            cutoff = idx
            if message.include_in_turn_count:
                removed_countable += 1
            if removed_countable >= count:
                break

        removed = self.context_window[:cutoff]
        self.context_window = self.context_window[cutoff:]
        logger.debug(f"Removed {count} earliest messages from context window")
        return removed

    def get_total_message_count(self) -> int:
        return sum(1 for m in self.context_window if m.include_in_turn_count)

    def get_messages(self) -> List[Message]:
        """Get all messages in the context window.

        Returns:
            List of Message objects
        """
        return self.context_window.copy()

    def get_summarizable_messages(self) -> List[Message]:
        """Get messages eligible for summary generation."""
        return [m for m in self.context_window if m.include_in_summary]

    def get_context_as_messages(self) -> List[Dict[str, str]]:
        """Get all messages as dictionaries (for LLM API).

        Returns:
            List of message dictionaries with 'role' and 'content' keys
        """
        return [m.to_dict() for m in self.context_window]

    def get_recent_summaries_as_text(self) -> List[str]:
        return [s.summary for s in self.recent_summaries]

    def get_recent_summary_ids(self) -> List[int]:
        """Get IDs of recent summaries in context window."""
        return [s.summary_id for s in self.recent_summaries]

    def clear(self) -> None:
        self.context_window = []
        self.recent_summaries = []
        logger.debug("Context window cleared")

