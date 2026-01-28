from typing import List, Dict
from dataclasses import dataclass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.logger import get_logger

logger = get_logger()


@dataclass
class Message:
    role: str
    text: str

    def to_dict(self) -> Dict[str, str]:
        return {"role": self.role, "content": self.text}

    @classmethod
    def from_dict(cls, data: Dict[str, str]) -> "Message":
        return cls(role=data["role"], text=data["text"])


@dataclass
class Summary:
    summary: str
    summary_id: int

    def to_dict(self) -> Dict[str, any]:
        return {"summary": self.summary, "summary_id": self.summary_id}

    @classmethod
    def from_dict(cls, data: Dict[str, any]) -> "Summary":
        return cls(summary=data["summary"], summary_id=data["summary_id"])


class ContextWindow:
    """Pure in-memory context window manager."""
    
    def __init__(self):
        self.context_window: List[Message] = []
        self.recent_summaries: List[Summary] = []
        logger.debug("ContextWindow initialized")

    def add_message(self, role: str, text: str) -> None:
        self.context_window.append(Message(role=role, text=text))
        logger.debug(f"Added message: role={role}, text length={len(text)}")

    def add_summary(self, summary: str, summary_id: int) -> None:
        self.recent_summaries.append(Summary(summary=summary, summary_id=summary_id))
        
        from config import Config
        max_summaries = Config.RECENT_SUMMARIES_MAX
        if len(self.recent_summaries) > max_summaries:
            self.recent_summaries = self.recent_summaries[-max_summaries:]
            logger.debug(f"Trimmed summaries to max {max_summaries}")

    def get_messages_for_summary(self, count: int) -> List[Message]:
        return self.context_window[:count]

    def remove_earliest_messages(self, count: int) -> List[Message]:
        removed = self.context_window[:count]
        self.context_window = self.context_window[count:]
        logger.debug(f"Removed {count} earliest messages from context window")
        return removed

    def get_total_message_count(self) -> int:
        return len(self.context_window)

    def get_context_as_messages(self) -> List[Dict[str, str]]:
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
