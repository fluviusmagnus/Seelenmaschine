"""Centralized non-prompt text catalog."""

from texts.catalog import ApprovalTexts
from texts.catalog import EventTexts
from texts.catalog import TelegramTexts
from texts.catalog import ToolTexts

__all__ = [
    "ApprovalTexts",
    "EventTexts",
    "TelegramTexts",
    "ToolTexts",
]
