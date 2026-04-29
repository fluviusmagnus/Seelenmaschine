import pytest
import tempfile
from pathlib import Path

from core.database import DatabaseManager


@pytest.fixture
def temp_db_path():
    """Create a temporary database file for testing."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        temp_path = Path(f.name)
        yield temp_path
    if temp_path.exists():
        temp_path.unlink()


@pytest.fixture
def db_manager(temp_db_path):
    """Initialize DatabaseManager with test database."""
    return DatabaseManager(db_path=temp_db_path)


class TestDatabaseManager:
    """Test DatabaseManager functionality."""

    def test_initialization(self, db_manager):
        """Test database is initialized correctly."""
        assert db_manager.db_path.exists()
        with db_manager._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT value FROM meta WHERE key = 'schema_version'")
            result = cursor.fetchone()
            assert result is not None
            assert result[0] == "3.3"

    def test_create_session(self, db_manager):
        """Test creating a new session."""
        session_id = db_manager.create_session(1234567890)
        assert session_id > 0

        active_session = db_manager.get_active_session()
        assert active_session is not None
        assert active_session["session_id"] == session_id
        assert active_session["start_timestamp"] == 1234567890
        assert active_session["status"] == "active"

    def test_get_active_session(self, db_manager):
        """Test getting active session."""
        session_id = db_manager.create_session(1234567890)
        active_session = db_manager.get_active_session()
        assert active_session is not None
        assert active_session["session_id"] == session_id

    def test_close_session(self, db_manager):
        """Test closing a session."""
        session_id = db_manager.create_session(1234567890)
        db_manager.close_session(session_id, 1234567900)

        active_session = db_manager.get_active_session()
        assert active_session is None

        with db_manager._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM sessions WHERE session_id = ?", (session_id,))
            row = cursor.fetchone()
            assert row is not None
            assert row["end_timestamp"] == 1234567900
            assert row["status"] == "archived"

    def test_delete_session(self, db_manager):
        """Test deleting a session."""
        session_id = db_manager.create_session(1234567890)
        db_manager.insert_conversation(session_id, 1234567891, "user", "Hello")
        db_manager.insert_summary(session_id, "Test summary", 1234567890, 1234567891)

        db_manager.delete_session(session_id)

        with db_manager._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM sessions WHERE session_id = ?", (session_id,))
            assert cursor.fetchone() is None
            cursor.execute("SELECT * FROM conversations WHERE session_id = ?", (session_id,))
            assert cursor.fetchone() is None
            cursor.execute("SELECT * FROM summaries WHERE session_id = ?", (session_id,))
            assert cursor.fetchone() is None

    def test_insert_conversation(self, db_manager):
        """Test inserting a conversation."""
        session_id = db_manager.create_session(1234567890)
        embedding = [0.1] * db_manager.embedding_dimension

        conv_id = db_manager.insert_conversation(
            session_id=session_id,
            timestamp=1234567891,
            role="user",
            text="Hello world",
            embedding=embedding
        )

        assert conv_id > 0

        with db_manager._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM conversations WHERE conversation_id = ?", (conv_id,))
            row = cursor.fetchone()
            assert row is not None
            assert row["session_id"] == session_id
            assert row["timestamp"] == 1234567891
            assert row["role"] == "user"
            assert row["text"] == "Hello world"
            assert row["message_type"] == "conversation"
            assert row["include_in_turn_count"] == 1
            assert row["include_in_summary"] == 1

    def test_insert_tool_context_conversation(self, db_manager):
        """Tool context messages should persist as non-conversation records."""
        session_id = db_manager.create_session(1234567890)

        conv_id = db_manager.insert_conversation(
            session_id=session_id,
            timestamp=1234567891,
            role="system",
            text="[Tool Call]",
            message_type="tool_call",
            include_in_turn_count=False,
            include_in_summary=False,
        )

        with db_manager._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM conversations WHERE conversation_id = ?", (conv_id,))
            row = cursor.fetchone()
            assert row is not None
            assert row["role"] == "system"
            assert row["message_type"] == "tool_call"
            assert row["include_in_turn_count"] == 0
            assert row["include_in_summary"] == 0

    def test_insert_summary(self, db_manager):
        """Test inserting a summary."""
        session_id = db_manager.create_session(1234567890)
        embedding = [0.2] * db_manager.embedding_dimension

        summary_id = db_manager.insert_summary(
            session_id=session_id,
            summary="Test summary",
            first_timestamp=1234567890,
            last_timestamp=1234567900,
            embedding=embedding
        )

        assert summary_id > 0

        with db_manager._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM summaries WHERE summary_id = ?", (summary_id,))
            row = cursor.fetchone()
            assert row is not None
            assert row["session_id"] == session_id
            assert row["summary"] == "Test summary"
            assert row["first_timestamp"] == 1234567890
            assert row["last_timestamp"] == 1234567900

    def test_insert_conversation_builds_ngram_index(self, db_manager):
        """Inserted conversations should populate the mixed-language n-gram index."""
        session_id = db_manager.create_session(1234567890)
        conv_id = db_manager.insert_conversation(
            session_id=session_id,
            timestamp=1234567891,
            role="user",
            text="电影配乐 OpenAI",
        )

        with db_manager._get_connection() as conn:
            rows = conn.execute(
                "SELECT gram FROM conversation_ngrams WHERE conversation_id = ? ORDER BY gram",
                (conv_id,),
            ).fetchall()

        grams = {row[0] for row in rows}
        assert "电影" in grams
        assert "配乐" in grams
        assert "openai" in grams

    def test_insert_summary_builds_ngram_index(self, db_manager):
        """Inserted summaries should populate the mixed-language n-gram index."""
        session_id = db_manager.create_session(1234567890)
        summary_id = db_manager.insert_summary(
            session_id=session_id,
            summary="東京旅行 Budgetplanung",
            first_timestamp=1234567890,
            last_timestamp=1234567900,
        )

        with db_manager._get_connection() as conn:
            rows = conn.execute(
                "SELECT gram FROM summary_ngrams WHERE summary_id = ? ORDER BY gram",
                (summary_id,),
            ).fetchall()

        grams = {row[0] for row in rows}
        assert "東京" in grams
        assert "旅行" in grams
        assert "budgetplanung" in grams

    def test_initialization_creates_hot_query_indexes(self, db_manager):
        """Hot path composite indexes should exist for new databases."""
        with db_manager._get_connection() as conn:
            rows = conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'index'"
            ).fetchall()

        index_names = {row[0] for row in rows}
        assert "idx_conversations_session_type_timestamp" in index_names
        assert "idx_conversations_timestamp_conversation" in index_names
        assert "idx_scheduled_tasks_status_next_run" in index_names

    def test_get_conversations_by_time_ranges_limits_each_range(self, db_manager):
        """Batch time-range retrieval should preserve per-summary limits."""
        session_id = db_manager.create_session(1234567890)
        first_id = db_manager.insert_conversation(session_id, 100, "user", "A")
        second_id = db_manager.insert_conversation(session_id, 110, "assistant", "B")
        third_id = db_manager.insert_conversation(session_id, 300, "user", "C")
        db_manager.insert_conversation(session_id, 500, "assistant", "outside")

        conversations = db_manager.get_conversations_by_time_ranges(
            ranges=[(90, 120), (290, 310)],
            limit_per_range=1,
        )

        assert conversations == [
            (second_id, session_id, 110, "assistant", "B"),
            (third_id, session_id, 300, "user", "C"),
        ]
        assert first_id not in {conversation[0] for conversation in conversations}

    def test_get_conversations_by_time_ranges_excludes_tool_calls(self, db_manager):
        """Similar-history time-range retrieval should exclude tool call records."""
        session_id = db_manager.create_session(1234567890)
        conversation_id = db_manager.insert_conversation(
            session_id, 100, "user", "ordinary conversation"
        )
        tool_call_id = db_manager.insert_conversation(
            session_id=session_id,
            timestamp=110,
            role="system",
            text='[Tool Call]\ntool_name: "search_memories"',
            message_type="tool_call",
            include_in_turn_count=False,
            include_in_summary=False,
        )
        assistant_id = db_manager.insert_conversation(
            session_id, 120, "assistant", "ordinary response"
        )

        conversations = db_manager.get_conversations_by_time_ranges(
            ranges=[(90, 130)],
            limit_per_range=10,
        )

        conversation_ids = {conversation[0] for conversation in conversations}
        assert conversation_ids == {conversation_id, assistant_id}
        assert tool_call_id not in conversation_ids

    def test_get_conversations_by_session(self, db_manager):
        """Test retrieving conversations by session."""
        session_id = db_manager.create_session(1234567890)

        db_manager.insert_conversation(session_id, 1234567891, "user", "Message 1")
        db_manager.insert_conversation(session_id, 1234567892, "assistant", "Message 2")

        conversations = db_manager.get_conversations_by_session(session_id)
        assert len(conversations) == 2
        assert conversations[0]["text"] == "Message 1"
        assert conversations[1]["text"] == "Message 2"

    def test_insert_scheduled_task(self, db_manager):
        """Test inserting a scheduled task."""
        task_id = "test_task_001"
        db_manager.insert_scheduled_task(
            task_id=task_id,
            name="Test Task",
            trigger_type="once",
            trigger_config={"timestamp": 1234567890},
            message="Test message",
            created_at=1234567880,
            next_run_at=1234567890,
            status="active"
        )

        task = db_manager.get_task(task_id)
        assert task is not None
        assert task["name"] == "Test Task"
        assert task["trigger_type"] == "once"
        assert task["trigger_config"]["timestamp"] == 1234567890

    def test_get_due_tasks(self, db_manager):
        """Test getting due tasks."""
        db_manager.insert_scheduled_task(
            task_id="task_001",
            name="Due Task",
            trigger_type="once",
            trigger_config={"timestamp": 1234567890},
            message="Test",
            created_at=1234567888,
            next_run_at=1234567890,
            status="active"
        )
        db_manager.insert_scheduled_task(
            task_id="task_002",
            name="Future Task",
            trigger_type="once",
            trigger_config={"timestamp": 1234567990},
            message="Test",
            created_at=1234567888,
            next_run_at=1234567990,
            status="active"
        )

        due_tasks = db_manager.get_due_tasks(1234567900)
        assert len(due_tasks) == 1
        assert due_tasks[0]["task_id"] == "task_001"

    def test_update_task_next_run(self, db_manager):
        """Test updating task next run time."""
        db_manager.insert_scheduled_task(
            task_id="task_001",
            name="Test Task",
            trigger_type="interval",
            trigger_config={"interval": 3600},
            message="Test",
            created_at=1234567888,
            next_run_at=1234567890,
            status="active"
        )

        db_manager.update_task_next_run("task_001", 1234567890, 1234561490)

        task = db_manager.get_task("task_001")
        assert task["next_run_at"] == 1234567890
        assert task["last_run_at"] == 1234561490
