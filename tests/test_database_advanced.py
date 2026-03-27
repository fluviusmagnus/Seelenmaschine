"""Advanced tests for DatabaseManager behavior that basic tests do not cover."""

import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from core.database import DatabaseManager


@pytest.fixture
def db_manager():
    """Create a temporary database manager."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = Path(f.name)
    try:
        yield DatabaseManager(db_path=db_path)
    finally:
        if db_path.exists():
            db_path.unlink()


class TestDatabaseVectorSearch:
    """Test vector-search related behavior."""

    def test_search_conversations_vector_gracefully_falls_back_when_unavailable(
        self, db_manager
    ):
        """Vector search should return an empty list if sqlite-vec is unavailable."""
        mock_cursor = Mock()
        mock_cursor.execute.side_effect = sqlite3.OperationalError("no such module: vec0")
        mock_conn = Mock()
        mock_conn.cursor.return_value = mock_cursor

        with patch.object(db_manager, "_get_connection") as mock_get_connection:
            mock_get_connection.return_value.__enter__.return_value = mock_conn
            results = db_manager.search_conversations(
                [0.1] * db_manager.embedding_dimension, limit=3
            )

        assert results == []

    def test_search_conversations_vector_empty(self, db_manager):
        """Empty vector search results should be returned unchanged."""
        mock_cursor = Mock()
        mock_cursor.fetchall.return_value = []
        mock_conn = Mock()
        mock_conn.cursor.return_value = mock_cursor

        with patch.object(db_manager, "_get_connection") as mock_get_connection:
            mock_get_connection.return_value.__enter__.return_value = mock_conn
            results = db_manager.search_conversations(
                [0.1] * db_manager.embedding_dimension, limit=5
            )

        assert results == []

    def test_embedding_roundtrip_serialization(self, db_manager):
        """Serialized embeddings should roundtrip through the helper methods."""
        embedding = [0.1, -0.2, 3.5, 42.0]

        serialized = db_manager._serialize_embedding(embedding)
        restored = db_manager._deserialize_embedding(serialized)

        assert len(restored) == len(embedding)
        assert restored == pytest.approx(embedding)


class TestDatabaseFTSSearch:
    """Test FTS5 keyword search and filters."""

    def test_search_conversations_by_keyword_exact(self, db_manager):
        """Keyword search should find matching conversation text."""
        session_id = db_manager.create_session(1000)
        db_manager.insert_conversation(session_id, 1100, "user", "alpha project update")
        db_manager.insert_conversation(session_id, 1200, "assistant", "unrelated note")

        results = db_manager.search_conversations_by_keyword("alpha", limit=10)

        assert len(results) == 1
        assert results[0][3] == "alpha project update"

    def test_search_conversations_by_keyword_fuzzy(self, db_manager):
        """FTS prefix syntax should match word prefixes."""
        session_id = db_manager.create_session(1000)
        db_manager.insert_conversation(session_id, 1100, "user", "programming language")
        db_manager.insert_conversation(session_id, 1200, "assistant", "gardening notes")

        results = db_manager.search_conversations_by_keyword("programm*", limit=10)

        assert len(results) == 1
        assert results[0][3] == "programming language"

    def test_search_with_filters_timestamp(self, db_manager):
        """Timestamp filters should narrow summary search results."""
        session_id = db_manager.create_session(1000)
        db_manager.insert_summary(
            session_id=session_id,
            summary="Early summary",
            first_timestamp=1000,
            last_timestamp=1500,
        )
        db_manager.insert_summary(
            session_id=session_id,
            summary="Late summary",
            first_timestamp=3000,
            last_timestamp=3500,
        )

        results = db_manager.search_summaries_by_keyword(
            query=None,
            start_timestamp=2000,
            end_timestamp=4000,
            limit=10,
        )

        assert len(results) == 1
        assert results[0][1] == "Late summary"

    def test_search_with_filters_role(self, db_manager):
        """Role filters should only return conversations for the requested role."""
        session_id = db_manager.create_session(1000)
        db_manager.insert_conversation(session_id, 1100, "user", "alpha user note")
        db_manager.insert_conversation(session_id, 1200, "assistant", "alpha assistant note")

        results = db_manager.search_conversations_by_keyword(
            query="alpha",
            role="assistant",
            limit=10,
        )

        assert len(results) == 1
        assert results[0][2] == "assistant"
        assert results[0][3] == "alpha assistant note"


class TestDatabaseTransactions:
    """Test connection lifecycle and rollback behavior."""

    def test_transaction_rollback_on_error(self, db_manager):
        """Changes inside _get_connection should be rolled back on exception."""
        with pytest.raises(RuntimeError):
            with db_manager._get_connection() as conn:
                conn.execute(
                    "INSERT INTO meta (key, value) VALUES (?, ?)",
                    ("rollback_test", "value"),
                )
                raise RuntimeError("force rollback")

        with db_manager._get_connection() as conn:
            row = conn.execute(
                "SELECT value FROM meta WHERE key = ?", ("rollback_test",)
            ).fetchone()

        assert row is None

    def test_connection_cleanup_on_exception(self, db_manager):
        """Connections should still be closed when the context exits with an error."""
        real_connect = sqlite3.connect
        connection_holder = {}

        def tracking_connect(*args, **kwargs):
            conn = real_connect(*args, **kwargs)
            connection_holder["conn"] = conn
            return conn

        with patch("core.database.sqlite3.connect", side_effect=tracking_connect):
            with pytest.raises(RuntimeError):
                with db_manager._get_connection() as conn:
                    conn.execute("SELECT 1")
                    raise RuntimeError("boom")

        with pytest.raises(sqlite3.ProgrammingError):
            connection_holder["conn"].cursor()
