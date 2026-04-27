"""Advanced tests for DatabaseManager behavior that basic tests do not cover."""

import sqlite3
import sys
import tempfile
import types
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
        assert results[0][4] == "alpha project update"

    def test_search_conversations_by_keyword_fuzzy(self, db_manager):
        """FTS prefix syntax should match word prefixes."""
        session_id = db_manager.create_session(1000)
        db_manager.insert_conversation(session_id, 1100, "user", "programming language")
        db_manager.insert_conversation(session_id, 1200, "assistant", "gardening notes")

        results = db_manager.search_conversations_by_keyword("programm*", limit=10)

        assert len(results) == 1
        assert results[0][4] == "programming language"

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
        assert results[0][2] == "Late summary"

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
        assert results[0][3] == "assistant"
        assert results[0][4] == "alpha assistant note"

    def test_search_conversations_by_keyword_uses_ngram_for_chinese(self, db_manager):
        """Chinese substring queries should use the n-gram fallback path."""
        session_id = db_manager.create_session(1000)
        db_manager.insert_conversation(session_id, 1100, "user", "今天讨论了电影配乐")
        db_manager.insert_conversation(session_id, 1200, "assistant", "完全无关")

        results = db_manager.search_conversations_by_keyword("电影", limit=10)

        assert len(results) == 1
        assert results[0][4] == "今天讨论了电影配乐"

    def test_search_summaries_by_keyword_supports_mixed_language_boolean(self, db_manager):
        """Mixed-language boolean queries should work on the n-gram fallback path."""
        session_id = db_manager.create_session(1000)
        db_manager.insert_summary(
            session_id=session_id,
            summary="Reisekosten 和 東京旅行安排",
            first_timestamp=1000,
            last_timestamp=1500,
        )
        db_manager.insert_summary(
            session_id=session_id,
            summary="Reisekosten 但没有日本部分",
            first_timestamp=1600,
            last_timestamp=1700,
        )

        results = db_manager.search_summaries_by_keyword(
            query="Reisekosten AND 東京",
            limit=10,
        )

        assert len(results) == 1
        assert results[0][2] == "Reisekosten 和 東京旅行安排"


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


class TestDatabaseConnectionSetup:
    """Test connection setup optimizations."""

    def test_connection_sets_busy_timeout_and_wal_mode(self, db_manager):
        """Connections should use safer defaults for concurrent bot access."""
        with db_manager._get_connection() as conn:
            busy_timeout = conn.execute("PRAGMA busy_timeout").fetchone()[0]
            journal_mode = conn.execute("PRAGMA journal_mode").fetchone()[0]

        assert busy_timeout == 30000
        assert journal_mode.lower() == "wal"

    def test_sqlite_vec_load_failure_is_cached_and_warned_once(self):
        """Repeated connection setup should not spam logs when sqlite-vec is unavailable."""
        old_path = DatabaseManager._sqlite_vec_loadable_path
        old_unavailable = DatabaseManager._sqlite_vec_unavailable
        old_warning_logged = DatabaseManager._sqlite_vec_warning_logged
        fake_sqlite_vec = types.SimpleNamespace(
            loadable_path=Mock(side_effect=RuntimeError("missing extension"))
        )

        try:
            DatabaseManager._sqlite_vec_loadable_path = None
            DatabaseManager._sqlite_vec_unavailable = False
            DatabaseManager._sqlite_vec_warning_logged = False
            conn = Mock()

            with patch.dict(sys.modules, {"sqlite_vec": fake_sqlite_vec}):
                with patch("core.database.logger") as mock_logger:
                    DatabaseManager._load_sqlite_vec_extension(conn)
                    DatabaseManager._load_sqlite_vec_extension(conn)

            fake_sqlite_vec.loadable_path.assert_called_once()
            mock_logger.warning.assert_called_once()
        finally:
            DatabaseManager._sqlite_vec_loadable_path = old_path
            DatabaseManager._sqlite_vec_unavailable = old_unavailable
            DatabaseManager._sqlite_vec_warning_logged = old_warning_logged
