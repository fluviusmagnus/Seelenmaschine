import sqlite3
import json
import re
import struct
import unicodedata
from contextlib import contextmanager
from pathlib import Path
from typing import Any, ClassVar, Dict, List, Optional, Tuple

from core.config import Config
from utils.logger import get_logger

logger = get_logger()


class DatabaseManager:
    _sqlite_vec_loadable_path: ClassVar[Optional[str]] = None
    _sqlite_vec_unavailable: ClassVar[bool] = False
    _sqlite_vec_warning_logged: ClassVar[bool] = False

    def __init__(self, db_path: Optional[Path] = None):
        if db_path is None:
            config = Config()
            db_path = config.DB_PATH

        self.db_path = db_path
        config = Config()
        self.embedding_dimension = config.EMBEDDING_DIMENSION
        self._wal_configured = False
        self._ensure_db_exists()
        self._initialize_schema()

    @contextmanager
    def _get_connection(self):
        conn = sqlite3.connect(str(self.db_path), timeout=30.0)
        conn.row_factory = sqlite3.Row
        self._load_sqlite_vec_extension(conn)
        self._configure_connection(conn)
        try:
            yield conn
            conn.commit()
        except Exception as e:
            conn.rollback()
            logger.error(f"Database error: {e}")
            raise
        finally:
            conn.close()

    def _configure_connection(self, conn: sqlite3.Connection) -> None:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 30000")
        if not self._wal_configured:
            conn.execute("PRAGMA journal_mode = WAL")
            self._wal_configured = True

    @classmethod
    def _load_sqlite_vec_extension(cls, conn: sqlite3.Connection) -> None:
        if cls._sqlite_vec_unavailable:
            return

        try:
            if cls._sqlite_vec_loadable_path is None:
                import sqlite_vec

                cls._sqlite_vec_loadable_path = sqlite_vec.loadable_path()

            conn.enable_load_extension(True)
            conn.load_extension(cls._sqlite_vec_loadable_path)
        except Exception as error:
            cls._sqlite_vec_unavailable = True
            if not cls._sqlite_vec_warning_logged:
                logger.warning(f"Could not load sqlite-vec extension: {error}")
                cls._sqlite_vec_warning_logged = True
        finally:
            try:
                conn.enable_load_extension(False)
            except Exception:
                pass

    def _ensure_db_exists(self):
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _contains_cjk(text: str) -> bool:
        """Return whether a string contains CJK characters."""
        return any("\u4e00" <= char <= "\u9fff" or "\u3040" <= char <= "\u30ff" for char in text)

    @staticmethod
    def _normalize_for_ngram(text: str) -> str:
        """Normalize text before extracting mixed-language search units."""
        return unicodedata.normalize("NFKC", text).lower()

    @classmethod
    def _extract_search_units(cls, text: str) -> list[str]:
        """Extract mixed-language search units.

        - CJK runs are indexed as bigrams, with single-character fallback.
        - Non-CJK alphanumeric runs are indexed as whole lowercase tokens.
        """
        normalized = cls._normalize_for_ngram(text)
        units: list[str] = []
        current_cjk: list[str] = []
        current_non_cjk: list[str] = []

        def flush_cjk() -> None:
            nonlocal current_cjk
            if not current_cjk:
                return
            run = "".join(current_cjk)
            if len(run) == 1:
                units.append(run)
            else:
                units.extend(run[index : index + 2] for index in range(len(run) - 1))
            current_cjk = []

        def flush_non_cjk() -> None:
            nonlocal current_non_cjk
            if current_non_cjk:
                units.append("".join(current_non_cjk))
                current_non_cjk = []

        for char in normalized:
            if "\u4e00" <= char <= "\u9fff" or "\u3040" <= char <= "\u30ff":
                flush_non_cjk()
                current_cjk.append(char)
            elif char.isalnum():
                flush_cjk()
                current_non_cjk.append(char)
            else:
                flush_cjk()
                flush_non_cjk()

        flush_cjk()
        flush_non_cjk()
        return list(dict.fromkeys(unit for unit in units if unit))

    @staticmethod
    def _tokenize_boolean_query(query: str) -> list[str]:
        """Tokenize a boolean query for the n-gram search parser."""
        return re.findall(r"\(|\)|\bAND\b|\bOR\b|\bNOT\b|[^\s()]+", query, flags=re.IGNORECASE)

    @classmethod
    def _parse_ngram_query(cls, query: str) -> Any:
        """Parse a simple boolean query into an expression tree."""
        tokens = cls._tokenize_boolean_query(query)
        position = 0

        def peek() -> str | None:
            return tokens[position] if position < len(tokens) else None

        def consume() -> str:
            nonlocal position
            token = tokens[position]
            position += 1
            return token

        def parse_or() -> Any:
            node = parse_and()
            while True:
                token = peek()
                if token is not None and token.upper() == "OR":
                    consume()
                    node = ("OR", node, parse_and())
                else:
                    return node

        def parse_and() -> Any:
            node = parse_not()
            while True:
                token = peek()
                if token is None or token == ")" or token.upper() == "OR":
                    return node
                if token.upper() == "AND":
                    consume()
                node = ("AND", node, parse_not())

        def parse_not() -> Any:
            token = peek()
            if token is not None and token.upper() == "NOT":
                consume()
                return ("NOT", parse_not())
            return parse_primary()

        def parse_primary() -> Any:
            token = peek()
            if token is None:
                raise ValueError("Unexpected end of query")
            if token == "(":
                consume()
                node = parse_or()
                if peek() != ")":
                    raise ValueError("Unmatched parentheses in query")
                consume()
                return node
            if token == ")":
                raise ValueError("Unexpected closing parenthesis")
            return ("TERM", consume())

        if not tokens:
            raise ValueError("Empty query")

        tree = parse_or()
        if position != len(tokens):
            raise ValueError(f"Unexpected token '{tokens[position]}'")
        return tree

    def _ensure_ngram_schema(self, cursor: sqlite3.Cursor) -> None:
        """Create auxiliary mixed-language n-gram index tables."""
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS conversation_ngrams (
                conversation_id INTEGER NOT NULL,
                gram TEXT NOT NULL,
                PRIMARY KEY (conversation_id, gram),
                FOREIGN KEY(conversation_id) REFERENCES conversations(conversation_id) ON DELETE CASCADE
            )
            """
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_conversation_ngrams_gram ON conversation_ngrams(gram)"
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS summary_ngrams (
                summary_id INTEGER NOT NULL,
                gram TEXT NOT NULL,
                PRIMARY KEY (summary_id, gram),
                FOREIGN KEY(summary_id) REFERENCES summaries(summary_id) ON DELETE CASCADE
            )
            """
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_summary_ngrams_gram ON summary_ngrams(gram)"
        )

    def _refresh_conversation_ngrams_with_cursor(
        self, cursor: sqlite3.Cursor, conversation_id: int, text: str
    ) -> None:
        """Refresh n-gram index rows for a conversation."""
        cursor.execute(
            "DELETE FROM conversation_ngrams WHERE conversation_id = ?", (conversation_id,)
        )
        grams = self._extract_search_units(text)
        if grams:
            cursor.executemany(
                "INSERT OR IGNORE INTO conversation_ngrams (conversation_id, gram) VALUES (?, ?)",
                [(conversation_id, gram) for gram in grams],
            )

    def _refresh_summary_ngrams_with_cursor(
        self, cursor: sqlite3.Cursor, summary_id: int, summary: str
    ) -> None:
        """Refresh n-gram index rows for a summary."""
        cursor.execute("DELETE FROM summary_ngrams WHERE summary_id = ?", (summary_id,))
        grams = self._extract_search_units(summary)
        if grams:
            cursor.executemany(
                "INSERT OR IGNORE INTO summary_ngrams (summary_id, gram) VALUES (?, ?)",
                [(summary_id, gram) for gram in grams],
            )

    @staticmethod
    def _ensure_performance_indexes_with_cursor(cursor: sqlite3.Cursor) -> None:
        """Create low-risk composite indexes for hot query paths."""
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_conversations_session_type_timestamp "
            "ON conversations(session_id, message_type, timestamp DESC, conversation_id DESC)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_conversations_timestamp_conversation "
            "ON conversations(timestamp DESC, conversation_id DESC)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_scheduled_tasks_status_next_run "
            "ON scheduled_tasks(status, next_run_at)"
        )

    def _rebuild_ngram_indexes_with_cursor(self, cursor: sqlite3.Cursor) -> None:
        """Backfill n-gram indexes from existing conversations and summaries."""
        cursor.execute("DELETE FROM conversation_ngrams")
        cursor.execute("DELETE FROM summary_ngrams")

        cursor.execute("SELECT conversation_id, text FROM conversations")
        for row in cursor.fetchall():
            self._refresh_conversation_ngrams_with_cursor(
                cursor, row["conversation_id"], row["text"]
            )

        cursor.execute("SELECT summary_id, summary FROM summaries")
        for row in cursor.fetchall():
            self._refresh_summary_ngrams_with_cursor(
                cursor, row["summary_id"], row["summary"]
            )

    def _should_use_ngram_search(self, query: Optional[str]) -> bool:
        """Decide whether a query should use mixed-language n-gram search."""
        return bool(query and self._contains_cjk(query))

    def _initialize_schema(self):
        with self._get_connection() as conn:
            cursor = conn.cursor()

            cursor.execute(
                """
                SELECT name FROM sqlite_master 
                WHERE type='table' AND name='meta'
            """
            )

            if cursor.fetchone() is None:
                logger.info("Initializing database schema")

                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS meta (
                        key TEXT PRIMARY KEY,
                        value TEXT NOT NULL
                    )
                """
                )

                cursor.execute(
                    "INSERT OR IGNORE INTO meta (key, value) VALUES ('schema_version', '3.3')"
                )

                cursor.execute(
                    f"""
                    CREATE VIRTUAL TABLE IF NOT EXISTS vec_conversations USING vec0(
                        conversation_id INTEGER PRIMARY KEY,
                        embedding float[{self.embedding_dimension}]
                    )
                """
                )

                cursor.execute(
                    f"""
                    CREATE VIRTUAL TABLE IF NOT EXISTS vec_summaries USING vec0(
                        summary_id INTEGER PRIMARY KEY,
                        embedding float[{self.embedding_dimension}]
                    )
                """
                )

                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS sessions (
                        session_id INTEGER PRIMARY KEY AUTOINCREMENT,
                        start_timestamp INTEGER NOT NULL,
                        end_timestamp INTEGER,
                        status TEXT CHECK(status IN ('active', 'archived')) DEFAULT 'active'
                    )
                """
                )

                cursor.execute(
                    "CREATE INDEX IF NOT EXISTS idx_sessions_status ON sessions(status)"
                )

                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS conversations (
                        conversation_id INTEGER PRIMARY KEY AUTOINCREMENT,
                        session_id INTEGER NOT NULL,
                        timestamp INTEGER NOT NULL,
                        role TEXT NOT NULL CHECK(role IN ('user', 'assistant', 'system')),
                        text TEXT NOT NULL,
                        message_type TEXT NOT NULL DEFAULT 'conversation',
                        include_in_turn_count INTEGER NOT NULL DEFAULT 1,
                        include_in_summary INTEGER NOT NULL DEFAULT 1,
                        FOREIGN KEY(session_id) REFERENCES sessions(session_id)
                    )
                """
                )

                cursor.execute(
                    "CREATE INDEX IF NOT EXISTS idx_conversations_session ON conversations(session_id)"
                )
                cursor.execute(
                    "CREATE INDEX IF NOT EXISTS idx_conversations_timestamp ON conversations(timestamp DESC)"
                )

                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS summaries (
                        summary_id INTEGER PRIMARY KEY AUTOINCREMENT,
                        session_id INTEGER NOT NULL,
                        summary TEXT NOT NULL,
                        first_timestamp INTEGER NOT NULL,
                        last_timestamp INTEGER NOT NULL,
                        FOREIGN KEY(session_id) REFERENCES sessions(session_id)
                    )
                """
                )

                cursor.execute(
                    "CREATE INDEX IF NOT EXISTS idx_summaries_session ON summaries(session_id)"
                )
                cursor.execute(
                    "CREATE INDEX IF NOT EXISTS idx_summaries_last_timestamp ON summaries(last_timestamp DESC)"
                )

                # Create FTS5 tables for full-text search
                cursor.execute(
                    """
                    CREATE VIRTUAL TABLE IF NOT EXISTS fts_conversations USING fts5(
                        conversation_id UNINDEXED,
                        text,
                        content=conversations,
                        content_rowid=conversation_id
                    )
                """
                )

                cursor.execute(
                    """
                    CREATE VIRTUAL TABLE IF NOT EXISTS fts_summaries USING fts5(
                        summary_id UNINDEXED,
                        summary,
                        content=summaries,
                        content_rowid=summary_id
                    )
                """
                )

                # Create triggers to keep FTS tables in sync
                cursor.execute(
                    """
                    CREATE TRIGGER IF NOT EXISTS conversations_ai AFTER INSERT ON conversations BEGIN
                        INSERT INTO fts_conversations(rowid, conversation_id, text)
                        VALUES (new.conversation_id, new.conversation_id, new.text);
                    END
                """
                )

                cursor.execute(
                    """
                    CREATE TRIGGER IF NOT EXISTS conversations_ad AFTER DELETE ON conversations BEGIN
                        INSERT INTO fts_conversations(fts_conversations, rowid, conversation_id, text)
                        VALUES('delete', old.conversation_id, old.conversation_id, old.text);
                    END
                """
                )

                cursor.execute(
                    """
                    CREATE TRIGGER IF NOT EXISTS conversations_au AFTER UPDATE ON conversations BEGIN
                        INSERT INTO fts_conversations(fts_conversations, rowid, conversation_id, text)
                        VALUES('delete', old.conversation_id, old.conversation_id, old.text);
                        INSERT INTO fts_conversations(rowid, conversation_id, text)
                        VALUES (new.conversation_id, new.conversation_id, new.text);
                    END
                """
                )

                cursor.execute(
                    """
                    CREATE TRIGGER IF NOT EXISTS summaries_ai AFTER INSERT ON summaries BEGIN
                        INSERT INTO fts_summaries(rowid, summary_id, summary)
                        VALUES (new.summary_id, new.summary_id, new.summary);
                    END
                """
                )

                cursor.execute(
                    """
                    CREATE TRIGGER IF NOT EXISTS summaries_ad AFTER DELETE ON summaries BEGIN
                        INSERT INTO fts_summaries(fts_summaries, rowid, summary_id, summary)
                        VALUES('delete', old.summary_id, old.summary_id, old.summary);
                    END
                """
                )

                cursor.execute(
                    """
                    CREATE TRIGGER IF NOT EXISTS summaries_au AFTER UPDATE ON summaries BEGIN
                        INSERT INTO fts_summaries(fts_summaries, rowid, summary_id, summary)
                        VALUES('delete', old.summary_id, old.summary_id, old.summary);
                        INSERT INTO fts_summaries(rowid, summary_id, summary)
                        VALUES (new.summary_id, new.summary_id, new.summary);
                    END
                """
                )

                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS scheduled_tasks (
                        task_id TEXT PRIMARY KEY,
                        name TEXT NOT NULL,
                        trigger_type TEXT NOT NULL CHECK(trigger_type IN ('once', 'interval')),
                        trigger_config TEXT NOT NULL,
                        message TEXT NOT NULL,
                        created_at INTEGER NOT NULL,
                        next_run_at INTEGER NOT NULL,
                        last_run_at INTEGER,
                        status TEXT CHECK(status IN ('active', 'paused', 'completed', 'running')) DEFAULT 'active'
                    )
                """
                )

                cursor.execute(
                    "CREATE INDEX IF NOT EXISTS idx_scheduled_tasks_next_run ON scheduled_tasks(next_run_at, status)"
                )

                self._ensure_ngram_schema(cursor)
                self._rebuild_ngram_indexes_with_cursor(cursor)
                self._ensure_performance_indexes_with_cursor(cursor)

                conn.commit()
                logger.info("Database schema initialized successfully")

            # Run any pending migrations
            self._run_migrations()

            self._ensure_performance_indexes_with_cursor(cursor)

    def _run_migrations(self):
        """Run database migrations based on schema version"""
        current_version = self.get_schema_version()
        if current_version == "unknown":
            return

        with self._get_connection() as conn:
            cursor = conn.cursor()

            # Migration 2.0 -> 3.0: Add FTS5 tables if they don't exist
            if current_version == "2.0":
                logger.info("Migrating database from version 2.0 to 3.0 (Adding FTS5)")

                # Check if FTS tables exist
                cursor.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='fts_conversations'"
                )
                if cursor.fetchone() is None:
                    # Create FTS5 tables and triggers (omitted for brevity, but logically same as _initialize_schema)
                    # For a robust implementation, we should call a specific method or repeat the SQL here
                    # Since we are moving through versions, let's do it properly
                    self._upgrade_to_3_0(cursor)

                cursor.execute(
                    "UPDATE meta SET value = '3.0' WHERE key = 'schema_version'"
                )
                current_version = "3.0"

            # Migration 3.0 -> 3.1: Add 'running' to scheduled_tasks status CHECK constraint
            if current_version == "3.0":
                logger.info(
                    "Migrating database from version 3.0 to 3.1 (Updating scheduled_tasks constraint)"
                )

                # Recreate scheduled_tasks table to update CHECK constraint
                cursor.execute("PRAGMA foreign_keys=OFF")

                cursor.execute(
                    """
                    CREATE TABLE scheduled_tasks_new (
                        task_id TEXT PRIMARY KEY,
                        name TEXT NOT NULL,
                        trigger_type TEXT NOT NULL CHECK(trigger_type IN ('once', 'interval')),
                        trigger_config TEXT NOT NULL,
                        message TEXT NOT NULL,
                        created_at INTEGER NOT NULL,
                        next_run_at INTEGER NOT NULL,
                        last_run_at INTEGER,
                        status TEXT CHECK(status IN ('active', 'paused', 'completed', 'running')) DEFAULT 'active'
                    )
                """
                )

                cursor.execute(
                    "INSERT INTO scheduled_tasks_new SELECT * FROM scheduled_tasks"
                )
                cursor.execute("DROP TABLE scheduled_tasks")
                cursor.execute(
                    "ALTER TABLE scheduled_tasks_new RENAME TO scheduled_tasks"
                )
                cursor.execute(
                    "CREATE INDEX idx_scheduled_tasks_next_run ON scheduled_tasks(next_run_at, status)"
                )

                cursor.execute("PRAGMA foreign_keys=ON")

                cursor.execute(
                    "UPDATE meta SET value = '3.1' WHERE key = 'schema_version'"
                )
                logger.info("Successfully migrated to version 3.1")
                current_version = "3.1"

            # Migration 3.1 -> 3.2: extend conversations with system/tool metadata
            if current_version == "3.1":
                logger.info(
                    "Migrating database from version 3.1 to 3.2 (Adding conversation metadata)"
                )
                cursor.execute("PRAGMA foreign_keys=OFF")

                cursor.execute(
                    """
                    CREATE TABLE conversations_new (
                        conversation_id INTEGER PRIMARY KEY AUTOINCREMENT,
                        session_id INTEGER NOT NULL,
                        timestamp INTEGER NOT NULL,
                        role TEXT NOT NULL CHECK(role IN ('user', 'assistant', 'system')),
                        text TEXT NOT NULL,
                        message_type TEXT NOT NULL DEFAULT 'conversation',
                        include_in_turn_count INTEGER NOT NULL DEFAULT 1,
                        include_in_summary INTEGER NOT NULL DEFAULT 1,
                        FOREIGN KEY(session_id) REFERENCES sessions(session_id)
                    )
                """
                )

                cursor.execute(
                    """
                    INSERT INTO conversations_new (
                        conversation_id, session_id, timestamp, role, text,
                        message_type, include_in_turn_count, include_in_summary
                    )
                    SELECT conversation_id, session_id, timestamp, role, text,
                           'conversation', 1, 1
                    FROM conversations
                """
                )

                cursor.execute("DROP TABLE conversations")
                cursor.execute(
                    "ALTER TABLE conversations_new RENAME TO conversations"
                )
                cursor.execute(
                    "CREATE INDEX idx_conversations_session ON conversations(session_id)"
                )
                cursor.execute(
                    "CREATE INDEX idx_conversations_timestamp ON conversations(timestamp DESC)"
                )

                cursor.execute("DROP TRIGGER IF EXISTS conversations_ai")
                cursor.execute("DROP TRIGGER IF EXISTS conversations_ad")
                cursor.execute("DROP TRIGGER IF EXISTS conversations_au")
                cursor.execute("DROP TABLE IF EXISTS fts_conversations")
                self._upgrade_to_3_0(cursor)

                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.execute(
                    "UPDATE meta SET value = '3.2' WHERE key = 'schema_version'"
                )
                logger.info("Successfully migrated to version 3.2")
                current_version = "3.2"

            if current_version == "3.2":
                logger.info(
                    "Migrating database from version 3.2 to 3.3 (Adding n-gram search indexes)"
                )
                self._ensure_ngram_schema(cursor)
                self._rebuild_ngram_indexes_with_cursor(cursor)
                cursor.execute(
                    "UPDATE meta SET value = '3.3' WHERE key = 'schema_version'"
                )
                logger.info("Successfully migrated to version 3.3")

    def _upgrade_to_3_0(self, cursor):
        """Helper to create FTS5 tables and triggers for 2.0 -> 3.0 migration"""
        # Create FTS5 tables
        cursor.execute(
            """
            CREATE VIRTUAL TABLE IF NOT EXISTS fts_conversations USING fts5(
                conversation_id UNINDEXED,
                text,
                content=conversations,
                content_rowid=conversation_id
            )
        """
        )
        cursor.execute(
            """
            CREATE VIRTUAL TABLE IF NOT EXISTS fts_summaries USING fts5(
                summary_id UNINDEXED,
                summary,
                content=summaries,
                content_rowid=summary_id
            )
        """
        )

        # Triggers (AI, AD, AU for conversations and summaries)
        # Using INSERT OR IGNORE and CREATE TRIGGER IF NOT EXISTS for safety
        cursor.execute(
            """
            CREATE TRIGGER IF NOT EXISTS conversations_ai AFTER INSERT ON conversations BEGIN
                INSERT INTO fts_conversations(rowid, conversation_id, text)
                VALUES (new.conversation_id, new.conversation_id, new.text);
            END
        """
        )
        cursor.execute(
            """
            CREATE TRIGGER IF NOT EXISTS conversations_ad AFTER DELETE ON conversations BEGIN
                INSERT INTO fts_conversations(fts_conversations, rowid, conversation_id, text)
                VALUES('delete', old.conversation_id, old.conversation_id, old.text);
            END
        """
        )
        cursor.execute(
            """
            CREATE TRIGGER IF NOT EXISTS conversations_au AFTER UPDATE ON conversations BEGIN
                INSERT INTO fts_conversations(fts_conversations, rowid, conversation_id, text)
                VALUES('delete', old.conversation_id, old.conversation_id, old.text);
                INSERT INTO fts_conversations(rowid, conversation_id, text)
                VALUES (new.conversation_id, new.conversation_id, new.text);
            END
        """
        )
        cursor.execute(
            """
            CREATE TRIGGER IF NOT EXISTS summaries_ai AFTER INSERT ON summaries BEGIN
                INSERT INTO fts_summaries(rowid, summary_id, summary)
                VALUES (new.summary_id, new.summary_id, new.summary);
            END
        """
        )
        cursor.execute(
            """
            CREATE TRIGGER IF NOT EXISTS summaries_ad AFTER DELETE ON summaries BEGIN
                INSERT INTO fts_summaries(fts_summaries, rowid, summary_id, summary)
                VALUES('delete', old.summary_id, old.summary_id, old.summary);
            END
        """
        )
        cursor.execute(
            """
            CREATE TRIGGER IF NOT EXISTS summaries_au AFTER UPDATE ON summaries BEGIN
                INSERT INTO fts_summaries(fts_summaries, rowid, summary_id, summary)
                VALUES('delete', old.summary_id, old.summary_id, old.summary);
                INSERT INTO fts_summaries(rowid, summary_id, summary)
                VALUES (new.summary_id, new.summary_id, new.summary);
            END
        """
        )

        # Backfill existing data
        cursor.execute(
            "INSERT OR IGNORE INTO fts_conversations(rowid, conversation_id, text) SELECT conversation_id, conversation_id, text FROM conversations"
        )
        cursor.execute(
            "INSERT OR IGNORE INTO fts_summaries(rowid, summary_id, summary) SELECT summary_id, summary_id, summary FROM summaries"
        )

    def _serialize_embedding(self, embedding: List[float]) -> bytes:
        return struct.pack(f"{len(embedding)}f", *embedding)

    def _deserialize_embedding(self, data: bytes) -> List[float]:
        return list(struct.unpack(f"{len(data)//4}f", data))

    def get_schema_version(self) -> str:
        """Get the current database schema version.

        Returns:
            The schema version string from the meta table.
            Returns 'unknown' if the meta table or schema_version key doesn't exist.
        """
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT value FROM meta WHERE key = 'schema_version'")
                row = cursor.fetchone()
                if row:
                    return row[0]
                return "unknown"
        except Exception as e:
            logger.warning(f"Failed to get schema version: {e}")
            return "unknown"

    def create_session(self, start_timestamp: int) -> int:
        """Create a new session and return its ID."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO sessions (start_timestamp, status) VALUES (?, 'active')",
                (start_timestamp,),
            )
            session_id = cursor.lastrowid
            if session_id is None:
                raise RuntimeError("Failed to create session: lastrowid is None")

            if Config.DEBUG_LOG_DATABASE_OPS:
                logger.debug(f"Created session: {session_id}")

            return int(session_id)

    def get_active_session(self) -> Optional[Dict[str, Any]]:
        """Get currently active session."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM sessions WHERE status = 'active' ORDER BY session_id DESC LIMIT 1"
            )
            row = cursor.fetchone()
            if row:
                return dict(row)
            return None

    def close_session(self, session_id: int, end_timestamp: int) -> None:
        """Close a session by setting end_timestamp and status."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE sessions SET end_timestamp = ?, status = 'archived' WHERE session_id = ?",
                (end_timestamp, session_id),
            )

            if Config.DEBUG_LOG_DATABASE_OPS:
                logger.debug(f"Closed session: {session_id}")

    def delete_session(self, session_id: int) -> None:
        """Delete a session and all related data."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "DELETE FROM conversations WHERE session_id = ?", (session_id,)
            )
            cursor.execute("DELETE FROM summaries WHERE session_id = ?", (session_id,))
            cursor.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))

            if Config.DEBUG_LOG_DATABASE_OPS:
                logger.debug(f"Deleted session: {session_id}")

    def insert_conversation(
        self,
        session_id: int,
        timestamp: int,
        role: str,
        text: str,
        embedding: Optional[List[float]] = None,
        *,
        message_type: str = "conversation",
        include_in_turn_count: bool = True,
        include_in_summary: bool = True,
    ) -> int:
        """Insert a conversation and return its ID."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO conversations (
                    session_id, timestamp, role, text,
                    message_type, include_in_turn_count, include_in_summary
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    timestamp,
                    role,
                    text,
                    message_type,
                    int(include_in_turn_count),
                    int(include_in_summary),
                ),
            )
            conversation_id = cursor.lastrowid or 0

            if embedding is not None:
                embedding_blob = self._serialize_embedding(embedding)
                cursor.execute(
                    """
                    INSERT INTO vec_conversations (conversation_id, embedding) 
                    VALUES (?, ?)
                """,
                    (conversation_id, embedding_blob),
                )

            self._refresh_conversation_ngrams_with_cursor(cursor, conversation_id, text)

            if Config.DEBUG_LOG_DATABASE_OPS:
                logger.debug(
                    f"Inserted conversation: conversation_id={conversation_id}, text={text[:50]}..."
                )

            return conversation_id

    def insert_summary(
        self,
        session_id: int,
        summary: str,
        first_timestamp: int,
        last_timestamp: int,
        embedding: Optional[List[float]] = None,
    ) -> int:
        """Insert a summary and return its ID."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO summaries (session_id, summary, first_timestamp, last_timestamp)
                VALUES (?, ?, ?, ?)
                """,
                (session_id, summary, first_timestamp, last_timestamp),
            )
            summary_id = cursor.lastrowid or 0

            if embedding is not None:
                embedding_blob = self._serialize_embedding(embedding)
                cursor.execute(
                    """
                    INSERT INTO vec_summaries (summary_id, embedding)
                    VALUES (?, ?)
                """,
                    (summary_id, embedding_blob),
                )

            self._refresh_summary_ngrams_with_cursor(cursor, summary_id, summary)

            if Config.DEBUG_LOG_DATABASE_OPS:
                logger.debug(
                    f"Inserted summary: summary_id={summary_id}, text={summary[:50]}..."
                )

            return summary_id

    def search_conversations(
        self,
        query_embedding: List[float],
        limit: int = 10,
        exclude_ids: Optional[List[int]] = None,
        session_id: Optional[int] = None,
        exclude_session_id: Optional[int] = None,
        exclude_recent_from_session_id: Optional[int] = None,
        exclude_recent_limit: int = 0,
        role: Optional[str] = None,
        start_timestamp: Optional[int] = None,
        end_timestamp: Optional[int] = None,
    ) -> List[Tuple[int, int, int, str, str, float]]:
        """Search conversations by vector similarity with optional filters."""
        with self._get_connection() as conn:
            cursor = conn.cursor()

            embedding_blob = self._serialize_embedding(query_embedding)

            try:
                conditions = ["c.message_type = 'conversation'"]
                params: list[Any] = [embedding_blob, limit]

                if exclude_ids and len(exclude_ids) > 0:
                    placeholders = ",".join("?" * len(exclude_ids))
                    conditions.append(f"c.conversation_id NOT IN ({placeholders})")
                    params.extend(exclude_ids)
                if session_id is not None:
                    conditions.append("c.session_id = ?")
                    params.append(session_id)
                if exclude_session_id is not None:
                    conditions.append("c.session_id != ?")
                    params.append(exclude_session_id)
                if exclude_recent_from_session_id is not None and exclude_recent_limit > 0:
                    conditions.append(
                        """
                        c.conversation_id NOT IN (
                            SELECT recent.conversation_id
                            FROM conversations recent
                            WHERE recent.session_id = ?
                              AND recent.message_type = 'conversation'
                            ORDER BY recent.timestamp DESC, recent.conversation_id DESC
                            LIMIT ?
                        )
                        """
                    )
                    params.extend([exclude_recent_from_session_id, exclude_recent_limit])
                if role is not None:
                    conditions.append("c.role = ?")
                    params.append(role)
                if start_timestamp is not None:
                    conditions.append("c.timestamp >= ?")
                    params.append(start_timestamp)
                if end_timestamp is not None:
                    conditions.append("c.timestamp <= ?")
                    params.append(end_timestamp)

                where_clause = "WHERE vec_conversations.embedding MATCH ? AND k = ?"
                if conditions:
                    where_clause += " AND " + " AND ".join(conditions)

                cursor.execute(
                    f"""
                    SELECT 
                        c.conversation_id, c.session_id, c.timestamp, c.role, c.text,
                        distance
                    FROM vec_conversations
                    JOIN conversations c ON vec_conversations.conversation_id = c.conversation_id
                    {where_clause}
                    ORDER BY distance
                """,
                    params,
                )

                results = []
                for row in cursor.fetchall():
                    conversation_id = row["conversation_id"]
                    session_id = row["session_id"]
                    timestamp = row["timestamp"]
                    role = row["role"]
                    text = row["text"]
                    distance = row["distance"]
                    results.append((conversation_id, session_id, timestamp, role, text, distance))

                return results
            except sqlite3.OperationalError as e:
                logger.error(f"Vector search not available: {e}")
                return []

    def search_summaries(
        self,
        query_embedding: List[float],
        limit: int = 5,
        exclude_ids: Optional[List[int]] = None,
    ) -> List[Tuple[int, int, str, int, int, float]]:
        """Search summaries by vector similarity.

        Args:
            query_embedding: Query embedding vector
            limit: Maximum number of results to return
            exclude_ids: Optional list of summary_ids to exclude from results

        Returns:
            List of tuples: (summary_id, session_id, summary, first_timestamp, last_timestamp, distance)
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()

            embedding_blob = self._serialize_embedding(query_embedding)

            try:
                # Build query with optional exclusion
                if exclude_ids and len(exclude_ids) > 0:
                    placeholders = ",".join("?" * len(exclude_ids))
                    query = f"""
                        SELECT 
                            s.summary_id, s.session_id, s.summary, s.first_timestamp, s.last_timestamp,
                            distance
                        FROM vec_summaries
                        JOIN summaries s ON vec_summaries.summary_id = s.summary_id
                        WHERE vec_summaries.embedding MATCH ? AND k = ?
                            AND s.summary_id NOT IN ({placeholders})
                        ORDER BY distance
                    """
                    params = (embedding_blob, limit + len(exclude_ids)) + tuple(
                        exclude_ids
                    )
                else:
                    query = """
                        SELECT 
                            s.summary_id, s.session_id, s.summary, s.first_timestamp, s.last_timestamp,
                            distance
                        FROM vec_summaries
                        JOIN summaries s ON vec_summaries.summary_id = s.summary_id
                        WHERE vec_summaries.embedding MATCH ? AND k = ?
                        ORDER BY distance
                    """
                    params = (embedding_blob, limit)

                cursor.execute(query, params)

                results = []
                for row in cursor.fetchall():
                    summary_id = row["summary_id"]
                    session_id = row["session_id"]
                    summary = row["summary"]
                    first_timestamp = row["first_timestamp"]
                    last_timestamp = row["last_timestamp"]
                    distance = row["distance"]
                    results.append(
                        (
                            summary_id,
                            session_id,
                            summary,
                            first_timestamp,
                            last_timestamp,
                            distance,
                        )
                    )

                # Limit results after exclusion
                return results[:limit]
            except sqlite3.OperationalError as e:
                logger.error(f"Vector search not available: {e}")
                return []

    def get_conversations_by_session(
        self,
        session_id: int,
        limit: Optional[int] = None,
        *,
        include_in_summary_only: bool = False,
    ) -> List[Dict[str, Any]]:
        """Get conversations for a session, optionally limited to most recent N.

        Args:
            session_id: The session ID
            limit: If provided, returns the most recent N conversations

        Returns:
            List of conversations in chronological order (oldest first)
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()

            filters = ["session_id = ?"]
            params: List[Any] = [session_id]

            if include_in_summary_only:
                filters.append("include_in_summary = 1")

            where_clause = " AND ".join(filters)

            if limit:
                # Get most recent N conversations, then reverse to chronological order
                query = f"""
                    SELECT * FROM (
                        SELECT * FROM conversations 
                        WHERE {where_clause}
                        ORDER BY timestamp DESC
                        LIMIT ?
                    ) ORDER BY timestamp ASC
                """
                params.append(limit)
            else:
                # Get all conversations in chronological order
                query = f"""
                    SELECT * FROM conversations 
                    WHERE {where_clause}
                    ORDER BY timestamp ASC
                """

            cursor.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]

    def get_summaries_by_session(self, session_id: int) -> List[Dict[str, Any]]:
        """Get all summaries for a session, ordered by last_timestamp DESC (most recent first)."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM summaries WHERE session_id = ? ORDER BY last_timestamp DESC",
                (session_id,),
            )
            return [dict(row) for row in cursor.fetchall()]

    def get_summary_by_id(self, summary_id: int) -> Optional[Dict[str, Any]]:
        """Get a single summary by its ID."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM summaries WHERE summary_id = ?", (summary_id,)
            )
            row = cursor.fetchone()
            return dict(row) if row else None

    def get_unsummarized_conversations(self, session_id: int) -> List[Dict[str, Any]]:
        """Get conversations that haven't been summarized yet.

        Returns conversations whose timestamp is greater than the last_timestamp
        of the most recent summary, or all conversations if no summaries exist.

        Args:
            session_id: The session ID

        Returns:
            List of unsummarized conversations in chronological order (oldest first)
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()

            # Get the most recent summary's last_timestamp
            cursor.execute(
                "SELECT last_timestamp FROM summaries WHERE session_id = ? ORDER BY last_timestamp DESC LIMIT 1",
                (session_id,),
            )
            result = cursor.fetchone()

            if result is None:
                # No summaries exist, return all conversations
                cursor.execute(
                    "SELECT * FROM conversations WHERE session_id = ? ORDER BY timestamp ASC",
                    (session_id,),
                )
            else:
                # Return only conversations after the last summary
                last_summary_timestamp = result[0]
                cursor.execute(
                    "SELECT * FROM conversations WHERE session_id = ? AND timestamp > ? ORDER BY timestamp ASC",
                    (session_id, last_summary_timestamp),
                )

            return [dict(row) for row in cursor.fetchall()]

    def get_conversations_by_time_range(
        self,
        start_timestamp: int,
        end_timestamp: int,
        limit: int = 4,
    ) -> List[Tuple[int, int, int, str, str]]:
        """Get conversations within a time range.

        Retrieves conversations that fall within the specified time window.
        Used for retrieving related conversations from a summary's time range.

        Args:
            start_timestamp: Start of time range (inclusive)
            end_timestamp: End of time range (inclusive)
            limit: Maximum number of conversations to return

        Returns:
            List of tuples: (conversation_id, session_id, timestamp, role, text)
            Ordered by timestamp DESC (most recent first)
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()

            cursor.execute(
                """
                SELECT conversation_id, session_id, timestamp, role, text
                FROM conversations
                WHERE timestamp >= ? AND timestamp <= ?
                ORDER BY timestamp DESC
                LIMIT ?
                """,
                (start_timestamp, end_timestamp, limit),
            )

            results = []
            for row in cursor.fetchall():
                results.append(
                    (
                        row["conversation_id"],
                        row["session_id"],
                        row["timestamp"],
                        row["role"],
                        row["text"],
                    )
                )

            if Config.DEBUG_LOG_DATABASE_OPS:
                logger.debug(
                    f"get_conversations_by_time_range: found {len(results)} conversations "
                    f"between {start_timestamp} and {end_timestamp}"
                )

            return results

    def get_conversations_by_time_ranges(
        self,
        ranges: List[Tuple[int, int]],
        limit_per_range: int = 4,
    ) -> List[Tuple[int, int, int, str, str]]:
        """Get conversations within multiple time ranges in one database round-trip."""
        if not ranges:
            return []

        normalized_ranges = [
            (min(start, end), max(start, end)) for start, end in ranges
        ]
        range_filters = " OR ".join(
            "(timestamp >= ? AND timestamp <= ?)" for _ in normalized_ranges
        )
        params: list[int] = []
        for start_timestamp, end_timestamp in normalized_ranges:
            params.extend([start_timestamp, end_timestamp])

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                f"""
                SELECT conversation_id, session_id, timestamp, role, text
                FROM conversations
                WHERE {range_filters}
                ORDER BY timestamp DESC, conversation_id DESC
                """,
                tuple(params),
            )

            rows = cursor.fetchall()

        results_by_range: list[list[Tuple[int, int, int, str, str]]] = [
            [] for _ in normalized_ranges
        ]
        seen_by_range: list[set[int]] = [set() for _ in normalized_ranges]

        for row in rows:
            timestamp = row["timestamp"]
            conversation_id = row["conversation_id"]
            for index, (start_timestamp, end_timestamp) in enumerate(normalized_ranges):
                if len(results_by_range[index]) >= limit_per_range:
                    continue
                if not start_timestamp <= timestamp <= end_timestamp:
                    continue
                if conversation_id in seen_by_range[index]:
                    continue
                seen_by_range[index].add(conversation_id)
                results_by_range[index].append(
                    (
                        conversation_id,
                        row["session_id"],
                        timestamp,
                        row["role"],
                        row["text"],
                    )
                )

        results = [conversation for group in results_by_range for conversation in group]

        if Config.DEBUG_LOG_DATABASE_OPS:
            logger.debug(
                f"get_conversations_by_time_ranges: found {len(results)} conversations "
                f"across {len(normalized_ranges)} ranges"
            )

        return results

    def insert_scheduled_task(
        self,
        task_id: str,
        name: str,
        trigger_type: str,
        trigger_config: Dict[str, Any],
        message: str,
        created_at: int,
        next_run_at: int,
        status: str = "active",
    ) -> None:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            trigger_config_json = json.dumps(trigger_config)
            cursor.execute(
                """
                INSERT INTO scheduled_tasks 
                (task_id, name, trigger_type, trigger_config, message, created_at, next_run_at, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    task_id,
                    name,
                    trigger_type,
                    trigger_config_json,
                    message,
                    created_at,
                    next_run_at,
                    status,
                ),
            )

    def get_due_tasks(self, current_timestamp: int) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT * FROM scheduled_tasks 
                WHERE status = 'active' AND next_run_at <= ?
                ORDER BY next_run_at ASC
            """,
                (current_timestamp,),
            )
            results = []
            for row in cursor.fetchall():
                task = dict(row)
                task["trigger_config"] = json.loads(task["trigger_config"])
                results.append(task)
            return results

    def claim_due_tasks(self, current_timestamp: int) -> List[Dict[str, Any]]:
        """Atomically claim due tasks by setting their status to 'running'"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            # Use RETURNING if supported, otherwise use a transaction with separate SELECT and UPDATE
            try:
                cursor.execute(
                    """
                    UPDATE scheduled_tasks 
                    SET status = 'running'
                    WHERE status = 'active' AND next_run_at <= ?
                    RETURNING *
                """,
                    (current_timestamp,),
                )
                results = []
                for row in cursor.fetchall():
                    task = dict(row)
                    task["trigger_config"] = json.loads(task["trigger_config"])
                    results.append(task)
                return results
            except sqlite3.OperationalError as e:
                # Fallback for older sqlite versions without RETURNING
                if "RETURNING" in str(e).upper():
                    cursor.execute(
                        "SELECT task_id FROM scheduled_tasks WHERE status = 'active' AND next_run_at <= ?",
                        (current_timestamp,),
                    )
                    ids = [row[0] for row in cursor.fetchall()]
                    if not ids:
                        return []

                    placeholders = ",".join("?" * len(ids))
                    cursor.execute(
                        f"UPDATE scheduled_tasks SET status = 'running' WHERE task_id IN ({placeholders})",
                        tuple(ids),
                    )

                    # Fetch full task data
                    cursor.execute(
                        f"SELECT * FROM scheduled_tasks WHERE task_id IN ({placeholders})",
                        tuple(ids),
                    )
                    results = []
                    for row in cursor.fetchall():
                        task = dict(row)
                        task["trigger_config"] = json.loads(task["trigger_config"])
                        results.append(task)
                    return results
                else:
                    raise

    def check_task_exists(self, name: str, status: str = "active") -> bool:
        """Check if an active task with the same name already exists"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT 1 FROM scheduled_tasks WHERE name = ? AND status = ? LIMIT 1",
                (name, status),
            )
            return cursor.fetchone() is not None

    def update_task_next_run(
        self, task_id: str, next_run_at: int, last_run_at: int
    ) -> None:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE scheduled_tasks 
                SET next_run_at = ?, last_run_at = ?, status = 'active'
                WHERE task_id = ?
            """,
                (next_run_at, last_run_at, task_id),
            )

    def get_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM scheduled_tasks WHERE task_id = ?", (task_id,)
            )
            row = cursor.fetchone()
            if row:
                task = dict(row)
                task["trigger_config"] = json.loads(task["trigger_config"])
                return task
            return None

    def get_all_tasks(self, status: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get all tasks, optionally filtered by status"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            if status:
                cursor.execute(
                    "SELECT * FROM scheduled_tasks WHERE status = ? ORDER BY next_run_at ASC",
                    (status,),
                )
            else:
                cursor.execute("SELECT * FROM scheduled_tasks ORDER BY next_run_at ASC")

            results = []
            for row in cursor.fetchall():
                task = dict(row)
                task["trigger_config"] = json.loads(task["trigger_config"])
                results.append(task)
            return results

    def update_task_status(self, task_id: str, status: str) -> None:
        """Update the status of a task"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE scheduled_tasks SET status = ? WHERE task_id = ?",
                (status, task_id),
            )

    def update_task_status_and_last_run(
        self, task_id: str, status: str, last_run_at: int
    ) -> None:
        """Update the status and last_run_at of a task"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE scheduled_tasks SET status = ?, last_run_at = ? WHERE task_id = ?",
                (status, last_run_at, task_id),
            )

    def reset_running_tasks(self) -> int:
        """Reset tasks stuck in running state to active.

        Returns:
            Number of tasks reset.
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE scheduled_tasks SET status = 'active' WHERE status = 'running'"
            )
            return cursor.rowcount

    def _ngram_term_condition(
        self,
        text_expression: str,
        owner_alias: str,
        id_column: str,
        table_name: str,
        term: str,
        params: list[Any],
    ) -> str:
        """Build an EXISTS-based condition for a single n-gram term."""
        grams = self._extract_search_units(term)
        if not grams:
            params.append(self._normalize_for_ngram(term))
            return f"instr(lower({text_expression}), ?) > 0"

        clauses = []
        for gram in grams:
            clauses.append(
                f"EXISTS (SELECT 1 FROM {table_name} ng WHERE ng.{id_column} = {owner_alias}.{id_column} AND ng.gram = ?)"
            )
            params.append(gram)
        return "(" + " AND ".join(clauses) + ")"

    def _compile_ngram_expression(
        self,
        node: Any,
        text_expression: str,
        owner_alias: str,
        id_column: str,
        table_name: str,
        params: list[Any],
    ) -> str:
        """Compile a parsed boolean expression tree into SQL."""
        kind = node[0]
        if kind == "TERM":
            return self._ngram_term_condition(
                text_expression, owner_alias, id_column, table_name, node[1], params
            )
        if kind == "NOT":
            return (
                "NOT ("
                + self._compile_ngram_expression(
                    node[1], text_expression, owner_alias, id_column, table_name, params
                )
                + ")"
            )
        if kind in {"AND", "OR"}:
            left = self._compile_ngram_expression(
                node[1], text_expression, owner_alias, id_column, table_name, params
            )
            right = self._compile_ngram_expression(
                node[2], text_expression, owner_alias, id_column, table_name, params
            )
            return f"({left} {kind} {right})"
        raise ValueError(f"Unsupported expression node: {kind}")

    def _search_conversations_by_ngram(
        self,
        query: str,
        limit: int = 10,
        session_id: Optional[int] = None,
        exclude_session_id: Optional[int] = None,
        exclude_recent_from_session_id: Optional[int] = None,
        exclude_recent_limit: int = 0,
        role: Optional[str] = None,
        start_timestamp: Optional[int] = None,
        end_timestamp: Optional[int] = None,
    ) -> List[Tuple[int, int, int, str, str, float]]:
        """Search conversations using mixed-language n-gram fallback."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            params: list[Any] = []
            conditions = ["c.message_type = 'conversation'"]

            expression = self._parse_ngram_query(query)
            conditions.append(
                self._compile_ngram_expression(
                    expression,
                    "c.text",
                    "c",
                    "conversation_id",
                    "conversation_ngrams",
                    params,
                )
            )

            if session_id is not None:
                conditions.append("c.session_id = ?")
                params.append(session_id)
            if exclude_session_id is not None:
                conditions.append("c.session_id != ?")
                params.append(exclude_session_id)
            if (
                exclude_recent_from_session_id is not None
                and exclude_recent_limit > 0
            ):
                conditions.append(
                    """
                    c.conversation_id NOT IN (
                        SELECT recent.conversation_id
                        FROM conversations recent
                        WHERE recent.session_id = ?
                          AND recent.message_type = 'conversation'
                        ORDER BY recent.timestamp DESC, recent.conversation_id DESC
                        LIMIT ?
                    )
                    """
                )
                params.extend([exclude_recent_from_session_id, exclude_recent_limit])
            if role is not None:
                conditions.append("c.role = ?")
                params.append(role)
            if start_timestamp is not None:
                conditions.append("c.timestamp >= ?")
                params.append(start_timestamp)
            if end_timestamp is not None:
                conditions.append("c.timestamp <= ?")
                params.append(end_timestamp)

            where_clause = "WHERE " + " AND ".join(conditions)
            full_query = f"""
                SELECT c.conversation_id, c.session_id, c.timestamp, c.role, c.text, 0.0 as rank
                FROM conversations c
                {where_clause}
                ORDER BY c.timestamp DESC
                LIMIT ?
            """
            params.append(limit)
            cursor.execute(full_query, params)
            return [
                (
                    row["conversation_id"],
                    row["session_id"],
                    row["timestamp"],
                    row["role"],
                    row["text"],
                    row["rank"],
                )
                for row in cursor.fetchall()
            ]

    def _search_summaries_by_ngram(
        self,
        query: str,
        limit: int = 5,
        session_id: Optional[int] = None,
        exclude_session_id: Optional[int] = None,
        start_timestamp: Optional[int] = None,
        end_timestamp: Optional[int] = None,
    ) -> List[Tuple[int, int, str, int, int, float]]:
        """Search summaries using mixed-language n-gram fallback."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            params: list[Any] = []
            conditions: list[str] = []
            expression = self._parse_ngram_query(query)
            conditions.append(
                self._compile_ngram_expression(
                    expression,
                    "s.summary",
                    "s",
                    "summary_id",
                    "summary_ngrams",
                    params,
                )
            )
            if session_id is not None:
                conditions.append("s.session_id = ?")
                params.append(session_id)
            if exclude_session_id is not None:
                conditions.append("s.session_id != ?")
                params.append(exclude_session_id)
            if start_timestamp is not None:
                conditions.append("s.last_timestamp >= ?")
                params.append(start_timestamp)
            if end_timestamp is not None:
                conditions.append("s.first_timestamp <= ?")
                params.append(end_timestamp)

            where_clause = "WHERE " + " AND ".join(conditions)
            full_query = f"""
                SELECT s.summary_id, s.session_id, s.summary, s.first_timestamp, s.last_timestamp, 0.0 as rank
                FROM summaries s
                {where_clause}
                ORDER BY s.last_timestamp DESC
                LIMIT ?
            """
            params.append(limit)
            cursor.execute(full_query, params)
            return [
                (
                    row["summary_id"],
                    row["session_id"],
                    row["summary"],
                    row["first_timestamp"],
                    row["last_timestamp"],
                    row["rank"],
                )
                for row in cursor.fetchall()
            ]

    def search_conversations_by_keyword(
        self,
        query: Optional[str] = None,
        limit: int = 10,
        session_id: Optional[int] = None,
        exclude_session_id: Optional[int] = None,
        exclude_recent_from_session_id: Optional[int] = None,
        exclude_recent_limit: int = 0,
        role: Optional[str] = None,
        start_timestamp: Optional[int] = None,
        end_timestamp: Optional[int] = None,
    ) -> List[Tuple[int, int, int, str, str, float]]:
        """Search conversations by keyword and/or filters using FTS5.

        Args:
            query: Search query (supports FTS5 query syntax). If None, returns all matching filters.
            limit: Maximum number of results
            session_id: Optional session_id to include exclusively
            exclude_session_id: Optional session_id to exclude (e.g., current session)
            exclude_recent_from_session_id: Optional session_id whose most recent
                conversation messages should be excluded from results
            exclude_recent_limit: Number of most recent conversation messages to
                exclude for exclude_recent_from_session_id
            role: Optional role filter ('user' or 'assistant')
            start_timestamp: Optional start time (Unix timestamp)
            end_timestamp: Optional end time (Unix timestamp)

        Returns:
            List of tuples: (conversation_id, session_id, timestamp, role, text, rank)
        """
        if self._should_use_ngram_search(query):
            return self._search_conversations_by_ngram(
                query=query or "",
                limit=limit,
                session_id=session_id,
                exclude_session_id=exclude_session_id,
                exclude_recent_from_session_id=exclude_recent_from_session_id,
                exclude_recent_limit=exclude_recent_limit,
                role=role,
                start_timestamp=start_timestamp,
                end_timestamp=end_timestamp,
            )

        with self._get_connection() as conn:
            cursor = conn.cursor()

            try:
                # Build query dynamically based on filters
                conditions = []
                params = []

                # Use FTS if query is provided, otherwise regular search
                if query:
                    base_query = """
                        SELECT 
                            c.conversation_id, c.session_id, c.timestamp, c.role, c.text,
                            fts.rank
                        FROM fts_conversations fts
                        JOIN conversations c ON fts.conversation_id = c.conversation_id
                    """
                    conditions.append("fts.text MATCH ?")
                    params.append(query)
                else:
                    base_query = """
                        SELECT 
                            c.conversation_id, c.session_id, c.timestamp, c.role, c.text,
                            0.0 as rank
                        FROM conversations c
                    """

                conditions.append("c.message_type = 'conversation'")

                if session_id is not None:
                    conditions.append("c.session_id = ?")
                    params.append(session_id)

                if exclude_session_id is not None:
                    conditions.append("c.session_id != ?")
                    params.append(exclude_session_id)

                if (
                    exclude_recent_from_session_id is not None
                    and exclude_recent_limit > 0
                ):
                    conditions.append(
                        """
                        c.conversation_id NOT IN (
                            SELECT recent.conversation_id
                            FROM conversations recent
                            WHERE recent.session_id = ?
                              AND recent.message_type = 'conversation'
                            ORDER BY recent.timestamp DESC, recent.conversation_id DESC
                            LIMIT ?
                        )
                        """
                    )
                    params.extend(
                        [exclude_recent_from_session_id, exclude_recent_limit]
                    )

                if role is not None:
                    conditions.append("c.role = ?")
                    params.append(role)

                if start_timestamp is not None:
                    conditions.append("c.timestamp >= ?")
                    params.append(start_timestamp)

                if end_timestamp is not None:
                    conditions.append("c.timestamp <= ?")
                    params.append(end_timestamp)

                # Combine conditions
                if conditions:
                    where_clause = "WHERE " + " AND ".join(conditions)
                else:
                    where_clause = ""

                # Order by rank if FTS, otherwise by timestamp
                order_by = "ORDER BY fts.rank" if query else "ORDER BY c.timestamp DESC"

                full_query = f"{base_query} {where_clause} {order_by} LIMIT ?"
                params.append(limit)

                cursor.execute(full_query, params)

                results = []
                for row in cursor.fetchall():
                    conversation_id = row["conversation_id"]
                    session_id_val = row["session_id"]
                    timestamp = row["timestamp"]
                    role_val = row["role"]
                    text = row["text"]
                    rank = row["rank"]
                    results.append(
                        (
                            conversation_id,
                            session_id_val,
                            timestamp,
                            role_val,
                            text,
                            rank,
                        )
                    )

                return results
            except sqlite3.OperationalError as e:
                logger.error(f"Conversation search failed: {e}")
                return []

    def search_summaries_by_keyword(
        self,
        query: Optional[str] = None,
        limit: int = 5,
        session_id: Optional[int] = None,
        exclude_session_id: Optional[int] = None,
        start_timestamp: Optional[int] = None,
        end_timestamp: Optional[int] = None,
    ) -> List[Tuple[int, int, str, int, int, float]]:
        """Search summaries by keyword and/or filters using FTS5.

        Args:
            query: Search query (supports FTS5 query syntax). If None, returns all matching filters.
            limit: Maximum number of results
            session_id: Optional session_id to include exclusively
            exclude_session_id: Optional session_id to exclude (e.g., current session)
            start_timestamp: Optional start time (Unix timestamp) - matches if summary's last_timestamp >= this
            end_timestamp: Optional end time (Unix timestamp) - matches if summary's first_timestamp <= this

        Returns:
            List of tuples: (summary_id, session_id, summary, first_timestamp, last_timestamp, rank)
        """
        if self._should_use_ngram_search(query):
            return self._search_summaries_by_ngram(
                query=query or "",
                limit=limit,
                session_id=session_id,
                exclude_session_id=exclude_session_id,
                start_timestamp=start_timestamp,
                end_timestamp=end_timestamp,
            )

        with self._get_connection() as conn:
            cursor = conn.cursor()

            try:
                # Build query dynamically based on filters
                conditions = []
                params = []

                # Use FTS if query is provided, otherwise regular search
                if query:
                    base_query = """
                        SELECT 
                            s.summary_id, s.session_id, s.summary, s.first_timestamp, s.last_timestamp,
                            fts.rank
                        FROM fts_summaries fts
                        JOIN summaries s ON fts.summary_id = s.summary_id
                    """
                    conditions.append("fts.summary MATCH ?")
                    params.append(query)
                else:
                    base_query = """
                        SELECT 
                            s.summary_id, s.session_id, s.summary, s.first_timestamp, s.last_timestamp,
                            0.0 as rank
                        FROM summaries s
                    """

                if session_id is not None:
                    conditions.append("s.session_id = ?")
                    params.append(session_id)

                if exclude_session_id is not None:
                    conditions.append("s.session_id != ?")
                    params.append(exclude_session_id)

                if start_timestamp is not None:
                    conditions.append("s.last_timestamp >= ?")
                    params.append(start_timestamp)

                if end_timestamp is not None:
                    conditions.append("s.first_timestamp <= ?")
                    params.append(end_timestamp)

                # Combine conditions
                if conditions:
                    where_clause = "WHERE " + " AND ".join(conditions)
                else:
                    where_clause = ""

                # Order by rank if FTS, otherwise by timestamp
                order_by = (
                    "ORDER BY fts.rank" if query else "ORDER BY s.last_timestamp DESC"
                )

                full_query = f"{base_query} {where_clause} {order_by} LIMIT ?"
                params.append(limit)

                cursor.execute(full_query, params)

                results = []
                for row in cursor.fetchall():
                    summary_id = row["summary_id"]
                    session_id_val = row["session_id"]
                    summary = row["summary"]
                    first_timestamp = row["first_timestamp"]
                    last_timestamp = row["last_timestamp"]
                    rank = row["rank"]
                    results.append(
                        (
                            summary_id,
                            session_id_val,
                            summary,
                            first_timestamp,
                            last_timestamp,
                            rank,
                        )
                    )

                return results
            except sqlite3.OperationalError as e:
                logger.error(f"Summary search failed: {e}")
                return []
