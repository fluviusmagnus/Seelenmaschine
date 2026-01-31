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
            assert result[0] == "2.0"

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
