import pytest
from unittest.mock import patch

from core.context import ContextWindow, Message, Summary


@pytest.fixture
def context_window():
    """Create a fresh ContextWindow for each test."""
    return ContextWindow()


class TestMessage:
    """Test Message dataclass."""

    def test_message_creation(self):
        """Test creating a message."""
        msg = Message(role="user", text="Hello")
        assert msg.role == "user"
        assert msg.text == "Hello"

    def test_message_to_dict(self):
        """Test converting message to dict."""
        msg = Message(role="assistant", text="Hi there")
        msg_dict = msg.to_dict()
        assert msg_dict == {"role": "assistant", "content": "Hi there"}

    def test_message_from_dict(self):
        """Test creating message from dict."""
        msg_dict = {"role": "user", "text": "Test message"}
        msg = Message.from_dict(msg_dict)
        assert msg.role == "user"
        assert msg.text == "Test message"


class TestSummary:
    """Test Summary dataclass."""

    def test_summary_creation(self):
        """Test creating a summary."""
        summary = Summary(summary="Test summary text", summary_id=1)
        assert summary.summary == "Test summary text"
        assert summary.summary_id == 1

    def test_summary_to_dict(self):
        """Test converting summary to dict."""
        summary = Summary(summary="Summary text", summary_id=5)
        summary_dict = summary.to_dict()
        assert summary_dict == {"summary": "Summary text", "summary_id": 5}

    def test_summary_from_dict(self):
        """Test creating summary from dict."""
        summary_dict = {"summary": "Dict summary", "summary_id": 10}
        summary = Summary.from_dict(summary_dict)
        assert summary.summary == "Dict summary"
        assert summary.summary_id == 10


class TestContextWindow:
    """Test ContextWindow functionality."""

    def test_initialization(self, context_window):
        """Test context window initializes correctly."""
        assert context_window.context_window == []
        assert context_window.recent_summaries == []

    def test_add_message(self, context_window):
        """Test adding a message."""
        context_window.add_message("user", "Hello world")
        assert len(context_window.context_window) == 1
        assert context_window.context_window[0].role == "user"
        assert context_window.context_window[0].text == "Hello world"

    def test_add_multiple_messages(self, context_window):
        """Test adding multiple messages."""
        context_window.add_message("user", "First")
        context_window.add_message("assistant", "Second")
        context_window.add_message("user", "Third")
        assert len(context_window.context_window) == 3
        assert context_window.context_window[0].text == "First"
        assert context_window.context_window[1].text == "Second"
        assert context_window.context_window[2].text == "Third"

    def test_add_summary(self, context_window):
        """Test adding a summary."""
        context_window.add_summary("Test summary", 1)
        assert len(context_window.recent_summaries) == 1
        assert context_window.recent_summaries[0].summary == "Test summary"
        assert context_window.recent_summaries[0].summary_id == 1

    def test_add_multiple_summaries(self, context_window):
        """Test adding multiple summaries."""
        context_window.add_summary("Summary 1", 1)
        context_window.add_summary("Summary 2", 2)
        context_window.add_summary("Summary 3", 3)
        assert len(context_window.recent_summaries) == 3
        assert context_window.recent_summaries[0].summary_id == 1
        assert context_window.recent_summaries[2].summary_id == 3

    def test_add_summary_trims_old(self, context_window, monkeypatch):
        """Test that old summaries are trimmed when max is exceeded."""
        from config import Config
        monkeypatch.setattr(Config, 'RECENT_SUMMARIES_MAX', 3)

        context_window.add_summary("Summary 1", 1)
        context_window.add_summary("Summary 2", 2)
        context_window.add_summary("Summary 3", 3)
        context_window.add_summary("Summary 4", 4)

        assert len(context_window.recent_summaries) == 3
        assert context_window.recent_summaries[0].summary_id == 2
        assert context_window.recent_summaries[1].summary_id == 3
        assert context_window.recent_summaries[2].summary_id == 4

    def test_get_messages_for_summary(self, context_window):
        """Test getting messages for summary."""
        context_window.add_message("user", "Msg 1")
        context_window.add_message("assistant", "Msg 2")
        context_window.add_message("user", "Msg 3")

        messages = context_window.get_messages_for_summary(2)
        assert len(messages) == 2
        assert messages[0].text == "Msg 1"
        assert messages[1].text == "Msg 2"

    def test_get_messages_for_summary_count_exceeds_available(self, context_window):
        """Test getting more messages than available."""
        context_window.add_message("user", "Msg 1")
        context_window.add_message("assistant", "Msg 2")

        messages = context_window.get_messages_for_summary(5)
        assert len(messages) == 2

    def test_remove_earliest_messages(self, context_window):
        """Test removing earliest messages."""
        context_window.add_message("user", "Msg 1")
        context_window.add_message("assistant", "Msg 2")
        context_window.add_message("user", "Msg 3")
        context_window.add_message("assistant", "Msg 4")

        removed = context_window.remove_earliest_messages(2)

        assert len(removed) == 2
        assert removed[0].text == "Msg 1"
        assert removed[1].text == "Msg 2"
        assert len(context_window.context_window) == 2
        assert context_window.context_window[0].text == "Msg 3"
        assert context_window.context_window[1].text == "Msg 4"

    def test_remove_all_messages(self, context_window):
        """Test removing all messages."""
        context_window.add_message("user", "Msg 1")
        context_window.add_message("assistant", "Msg 2")

        removed = context_window.remove_earliest_messages(2)

        assert len(removed) == 2
        assert len(context_window.context_window) == 0

    def test_get_total_message_count(self, context_window):
        """Test getting total message count."""
        assert context_window.get_total_message_count() == 0

        context_window.add_message("user", "Msg 1")
        assert context_window.get_total_message_count() == 1

        context_window.add_message("assistant", "Msg 2")
        context_window.add_message("user", "Msg 3")
        assert context_window.get_total_message_count() == 3

    def test_get_context_as_messages(self, context_window):
        """Test getting context as list of message dicts."""
        context_window.add_message("user", "Hello")
        context_window.add_message("assistant", "Hi there")

        context = context_window.get_context_as_messages()

        assert len(context) == 2
        assert context[0] == {"role": "user", "content": "Hello"}
        assert context[1] == {"role": "assistant", "content": "Hi there"}

    def test_get_context_as_messages_empty(self, context_window):
        """Test getting empty context."""
        context = context_window.get_context_as_messages()
        assert context == []

    def test_get_recent_summaries_as_text(self, context_window):
        """Test getting recent summaries as text."""
        context_window.add_summary("Summary 1", 1)
        context_window.add_summary("Summary 2", 2)

        summaries = context_window.get_recent_summaries_as_text()

        assert len(summaries) == 2
        assert summaries[0] == "Summary 1"
        assert summaries[1] == "Summary 2"

    def test_get_recent_summaries_as_text_empty(self, context_window):
        """Test getting empty summaries."""
        summaries = context_window.get_recent_summaries_as_text()
        assert summaries == []

    def test_get_recent_summary_ids(self, context_window):
        """Test getting recent summary IDs."""
        context_window.add_summary("Summary 1", 10)
        context_window.add_summary("Summary 2", 20)
        context_window.add_summary("Summary 3", 30)

        ids = context_window.get_recent_summary_ids()

        assert ids == [10, 20, 30]

    def test_get_recent_summary_ids_empty(self, context_window):
        """Test getting summary IDs when empty."""
        ids = context_window.get_recent_summary_ids()
        assert ids == []

    def test_clear(self, context_window):
        """Test clearing context window."""
        context_window.add_message("user", "Msg 1")
        context_window.add_message("assistant", "Msg 2")
        context_window.add_summary("Summary 1", 1)

        assert len(context_window.context_window) == 2
        assert len(context_window.recent_summaries) == 1

        context_window.clear()

        assert len(context_window.context_window) == 0
        assert len(context_window.recent_summaries) == 0

    def test_message_order_preserved(self, context_window):
        """Test that message order is preserved."""
        for i in range(10):
            context_window.add_message("user" if i % 2 == 0 else "assistant", f"Message {i}")

        messages = context_window.get_context_as_messages()
        assert len(messages) == 10
        for i in range(10):
            assert f"Message {i}" in messages[i]["content"]

    def test_integration_flow(self, context_window, monkeypatch):
        """Test typical usage flow."""
        from config import Config
        monkeypatch.setattr(Config, 'RECENT_SUMMARIES_MAX', 3)

        initial_count = context_window.get_total_message_count()
        assert initial_count == 0

        context_window.add_message("user", "What's the weather?")
        context_window.add_message("assistant", "It's sunny today.")
        assert context_window.get_total_message_count() == 2

        context = [msg.text for msg in context_window.context_window]
        assert "What's the weather?" in context
        assert "It's sunny today." in context

        context_window.add_summary("User asked about weather", 1)
        context_window.add_summary("Bot responded with weather info", 2)

        summaries = context_window.get_recent_summaries_as_text()
        assert len(summaries) == 2
        assert "weather" in summaries[0]
