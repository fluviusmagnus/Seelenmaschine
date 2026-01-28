import sqlite3
import json
from pathlib import Path
from typing import List, Optional, Tuple, Dict, Any
import struct
from contextlib import contextmanager

from config import Config
from utils.logger import get_logger

logger = get_logger()


class DatabaseManager:
    def __init__(self, db_path: Optional[Path] = None):
        if db_path is None:
            config = Config()
            db_path = config.DB_PATH
        
        self.db_path = db_path
        config = Config()
        self.embedding_dimension = config.EMBEDDING_DIMENSION
        self._ensure_db_exists()
        self._initialize_schema()

    @contextmanager
    def _get_connection(self):
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.enable_load_extension(True)
        try:
            import sqlite_vec
            conn.load_extension(sqlite_vec.loadable_path())
        except Exception as e:
            logger.warning(f"Could not load sqlite-vec extension: {e}")
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        except Exception as e:
            conn.rollback()
            logger.error(f"Database error: {e}")
            raise
        finally:
            conn.close()

    def _ensure_db_exists(self):
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    def _initialize_schema(self):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT name FROM sqlite_master 
                WHERE type='table' AND name='meta'
            """)
            
            if cursor.fetchone() is None:
                logger.info("Initializing database schema")
                
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS meta (
                        key TEXT PRIMARY KEY,
                        value TEXT NOT NULL
                    )
                """)
                
                cursor.execute("INSERT OR IGNORE INTO meta (key, value) VALUES ('schema_version', '2.0')")
                
                cursor.execute(f"""
                    CREATE VIRTUAL TABLE IF NOT EXISTS vec_conversations USING vec0(
                        conversation_id INTEGER PRIMARY KEY,
                        embedding float[{self.embedding_dimension}]
                    )
                """)
                
                cursor.execute(f"""
                    CREATE VIRTUAL TABLE IF NOT EXISTS vec_summaries USING vec0(
                        summary_id INTEGER PRIMARY KEY,
                        embedding float[{self.embedding_dimension}]
                    )
                """)
                
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS sessions (
                        session_id INTEGER PRIMARY KEY AUTOINCREMENT,
                        start_timestamp INTEGER NOT NULL,
                        end_timestamp INTEGER,
                        status TEXT CHECK(status IN ('active', 'archived')) DEFAULT 'active'
                    )
                """)
                
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_sessions_status ON sessions(status)")
                
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS conversations (
                        conversation_id INTEGER PRIMARY KEY AUTOINCREMENT,
                        session_id INTEGER NOT NULL,
                        timestamp INTEGER NOT NULL,
                        role TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
                        text TEXT NOT NULL,
                        FOREIGN KEY(session_id) REFERENCES sessions(session_id)
                    )
                """)
                
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_conversations_session ON conversations(session_id)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_conversations_timestamp ON conversations(timestamp DESC)")
                
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS summaries (
                        summary_id INTEGER PRIMARY KEY AUTOINCREMENT,
                        session_id INTEGER NOT NULL,
                        summary TEXT NOT NULL,
                        first_timestamp INTEGER NOT NULL,
                        last_timestamp INTEGER NOT NULL,
                        FOREIGN KEY(session_id) REFERENCES sessions(session_id)
                    )
                """)
                
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_summaries_session ON summaries(session_id)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_summaries_last_timestamp ON summaries(last_timestamp DESC)")
                
                # Create FTS5 tables for full-text search
                cursor.execute("""
                    CREATE VIRTUAL TABLE IF NOT EXISTS fts_conversations USING fts5(
                        conversation_id UNINDEXED,
                        text,
                        content=conversations,
                        content_rowid=conversation_id
                    )
                """)
                
                cursor.execute("""
                    CREATE VIRTUAL TABLE IF NOT EXISTS fts_summaries USING fts5(
                        summary_id UNINDEXED,
                        summary,
                        content=summaries,
                        content_rowid=summary_id
                    )
                """)
                
                # Create triggers to keep FTS tables in sync
                cursor.execute("""
                    CREATE TRIGGER IF NOT EXISTS conversations_ai AFTER INSERT ON conversations BEGIN
                        INSERT INTO fts_conversations(rowid, conversation_id, text)
                        VALUES (new.conversation_id, new.conversation_id, new.text);
                    END
                """)
                
                cursor.execute("""
                    CREATE TRIGGER IF NOT EXISTS conversations_ad AFTER DELETE ON conversations BEGIN
                        INSERT INTO fts_conversations(fts_conversations, rowid, conversation_id, text)
                        VALUES('delete', old.conversation_id, old.conversation_id, old.text);
                    END
                """)
                
                cursor.execute("""
                    CREATE TRIGGER IF NOT EXISTS conversations_au AFTER UPDATE ON conversations BEGIN
                        INSERT INTO fts_conversations(fts_conversations, rowid, conversation_id, text)
                        VALUES('delete', old.conversation_id, old.conversation_id, old.text);
                        INSERT INTO fts_conversations(rowid, conversation_id, text)
                        VALUES (new.conversation_id, new.conversation_id, new.text);
                    END
                """)
                
                cursor.execute("""
                    CREATE TRIGGER IF NOT EXISTS summaries_ai AFTER INSERT ON summaries BEGIN
                        INSERT INTO fts_summaries(rowid, summary_id, summary)
                        VALUES (new.summary_id, new.summary_id, new.summary);
                    END
                """)
                
                cursor.execute("""
                    CREATE TRIGGER IF NOT EXISTS summaries_ad AFTER DELETE ON summaries BEGIN
                        INSERT INTO fts_summaries(fts_summaries, rowid, summary_id, summary)
                        VALUES('delete', old.summary_id, old.summary_id, old.summary);
                    END
                """)
                
                cursor.execute("""
                    CREATE TRIGGER IF NOT EXISTS summaries_au AFTER UPDATE ON summaries BEGIN
                        INSERT INTO fts_summaries(fts_summaries, rowid, summary_id, summary)
                        VALUES('delete', old.summary_id, old.summary_id, old.summary);
                        INSERT INTO fts_summaries(rowid, summary_id, summary)
                        VALUES (new.summary_id, new.summary_id, new.summary);
                    END
                """)
                
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS scheduled_tasks (
                        task_id TEXT PRIMARY KEY,
                        name TEXT NOT NULL,
                        trigger_type TEXT NOT NULL CHECK(trigger_type IN ('once', 'interval')),
                        trigger_config TEXT NOT NULL,
                        message TEXT NOT NULL,
                        created_at INTEGER NOT NULL,
                        next_run_at INTEGER NOT NULL,
                        last_run_at INTEGER,
                        status TEXT CHECK(status IN ('active', 'paused', 'completed')) DEFAULT 'active'
                    )
                """)
                
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_scheduled_tasks_next_run ON scheduled_tasks(next_run_at, status)")
                
                conn.commit()
                logger.info("Database schema initialized successfully")

    def _serialize_embedding(self, embedding: List[float]) -> bytes:
        return struct.pack(f"{len(embedding)}f", *embedding)

    def _deserialize_embedding(self, data: bytes) -> List[float]:
        return list(struct.unpack(f"{len(data)//4}f", data))

    def create_session(self, start_timestamp: int) -> int:
        """Create a new session and return its ID."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO sessions (start_timestamp, status) VALUES (?, 'active')",
                (start_timestamp,)
            )
            session_id = cursor.lastrowid or 0
            return int(session_id)
            
            if Config.DEBUG_LOG_DATABASE_OPS:
                logger.debug(f"Created session: {session_id}")
            
            return session_id

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
                (end_timestamp, session_id)
            )
            
            if Config.DEBUG_LOG_DATABASE_OPS:
                logger.debug(f"Closed session: {session_id}")

    def delete_session(self, session_id: int) -> None:
        """Delete a session and all related data."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM conversations WHERE session_id = ?", (session_id,))
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
        embedding: Optional[List[float]] = None
    ) -> int:
        """Insert a conversation and return its ID."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO conversations (session_id, timestamp, role, text) VALUES (?, ?, ?, ?)",
                (session_id, timestamp, role, text)
            )
            conversation_id = cursor.lastrowid or 0
            
            if embedding is not None:
                embedding_blob = self._serialize_embedding(embedding)
                cursor.execute("""
                    INSERT INTO vec_conversations (conversation_id, embedding) 
                    VALUES (?, ?)
                """, (conversation_id, embedding_blob))
            
            if Config.DEBUG_LOG_DATABASE_OPS:
                logger.debug(f"Inserted conversation: conversation_id={conversation_id}, text={text[:50]}...")
            
            return conversation_id

    def insert_summary(
        self,
        session_id: int,
        summary: str,
        first_timestamp: int,
        last_timestamp: int,
        embedding: Optional[List[float]] = None
    ) -> int:
        """Insert a summary and return its ID."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO summaries (session_id, summary, first_timestamp, last_timestamp)
                VALUES (?, ?, ?, ?)
                """,
                (session_id, summary, first_timestamp, last_timestamp)
            )
            summary_id = cursor.lastrowid or 0
            
            if embedding is not None:
                embedding_blob = self._serialize_embedding(embedding)
                cursor.execute("""
                    INSERT INTO vec_summaries (summary_id, embedding)
                    VALUES (?, ?)
                """, (summary_id, embedding_blob))
            
            if Config.DEBUG_LOG_DATABASE_OPS:
                logger.debug(f"Inserted summary: summary_id={summary_id}, text={summary[:50]}...")
            
            return summary_id

    def search_conversations(
        self,
        query_embedding: List[float],
        limit: int = 10
    ) -> List[Tuple[int, int, str, str, float]]:
        """Search conversations by vector similarity."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            embedding_blob = self._serialize_embedding(query_embedding)
            
            try:
                cursor.execute("""
                    SELECT 
                        c.conversation_id, c.timestamp, c.role, c.text,
                        distance
                    FROM vec_conversations
                    JOIN conversations c ON vec_conversations.conversation_id = c.conversation_id
                    WHERE vec_conversations.embedding MATCH ? AND k = ?
                    ORDER BY distance
                """, (embedding_blob, limit))
                
                results = []
                for row in cursor.fetchall():
                    conversation_id = row["conversation_id"]
                    timestamp = row["timestamp"]
                    role = row["role"]
                    text = row["text"]
                    distance = row["distance"]
                    results.append((conversation_id, timestamp, role, text, distance))
                
                return results
            except sqlite3.OperationalError as e:
                logger.error(f"Vector search not available: {e}")
                return []

    def search_summaries(
        self,
        query_embedding: List[float],
        limit: int = 5,
        exclude_ids: Optional[List[int]] = None
    ) -> List[Tuple[int, str, int, int, float]]:
        """Search summaries by vector similarity.
        
        Args:
            query_embedding: Query embedding vector
            limit: Maximum number of results to return
            exclude_ids: Optional list of summary_ids to exclude from results
            
        Returns:
            List of tuples: (summary_id, summary, first_timestamp, last_timestamp, distance)
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            embedding_blob = self._serialize_embedding(query_embedding)
            
            try:
                # Build query with optional exclusion
                if exclude_ids and len(exclude_ids) > 0:
                    placeholders = ','.join('?' * len(exclude_ids))
                    query = f"""
                        SELECT 
                            s.summary_id, s.summary, s.first_timestamp, s.last_timestamp,
                            distance
                        FROM vec_summaries
                        JOIN summaries s ON vec_summaries.summary_id = s.summary_id
                        WHERE vec_summaries.embedding MATCH ? AND k = ?
                            AND s.summary_id NOT IN ({placeholders})
                        ORDER BY distance
                    """
                    params = (embedding_blob, limit + len(exclude_ids)) + tuple(exclude_ids)
                else:
                    query = """
                        SELECT 
                            s.summary_id, s.summary, s.first_timestamp, s.last_timestamp,
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
                    summary = row["summary"]
                    first_timestamp = row["first_timestamp"]
                    last_timestamp = row["last_timestamp"]
                    distance = row["distance"]
                    results.append((summary_id, summary, first_timestamp, last_timestamp, distance))
                
                # Limit results after exclusion
                return results[:limit]
            except sqlite3.OperationalError as e:
                logger.error(f"Vector search not available: {e}")
                return []

    def get_conversations_by_session(
        self,
        session_id: int,
        limit: Optional[int] = None
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
            
            if limit:
                # Get most recent N conversations, then reverse to chronological order
                query = """
                    SELECT * FROM (
                        SELECT * FROM conversations 
                        WHERE session_id = ?
                        ORDER BY timestamp DESC
                        LIMIT ?
                    ) ORDER BY timestamp ASC
                """
                params = [session_id, limit]
            else:
                # Get all conversations in chronological order
                query = """
                    SELECT * FROM conversations 
                    WHERE session_id = ?
                    ORDER BY timestamp ASC
                """
                params = [session_id]
            
            cursor.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]

    def get_summaries_by_session(self, session_id: int) -> List[Dict[str, Any]]:
        """Get all summaries for a session, ordered by last_timestamp DESC (most recent first)."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM summaries WHERE session_id = ? ORDER BY last_timestamp DESC",
                (session_id,)
            )
            return [dict(row) for row in cursor.fetchall()]
    
    def get_summary_by_id(self, summary_id: int) -> Optional[Dict[str, Any]]:
        """Get a single summary by its ID."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM summaries WHERE summary_id = ?",
                (summary_id,)
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
                (session_id,)
            )
            result = cursor.fetchone()
            
            if result is None:
                # No summaries exist, return all conversations
                cursor.execute(
                    "SELECT * FROM conversations WHERE session_id = ? ORDER BY timestamp ASC",
                    (session_id,)
                )
            else:
                # Return only conversations after the last summary
                last_summary_timestamp = result[0]
                cursor.execute(
                    "SELECT * FROM conversations WHERE session_id = ? AND timestamp > ? ORDER BY timestamp ASC",
                    (session_id, last_summary_timestamp)
                )
            
            return [dict(row) for row in cursor.fetchall()]

    def insert_scheduled_task(
        self,
        task_id: str,
        name: str,
        trigger_type: str,
        trigger_config: Dict[str, Any],
        message: str,
        created_at: int,
        next_run_at: int,
        status: str = "active"
    ) -> None:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            trigger_config_json = json.dumps(trigger_config)
            cursor.execute("""
                INSERT INTO scheduled_tasks 
                (task_id, name, trigger_type, trigger_config, message, created_at, next_run_at, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (task_id, name, trigger_type, trigger_config_json, message, created_at, next_run_at, status))

    def get_due_tasks(self, current_timestamp: int) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM scheduled_tasks 
                WHERE status = 'active' AND next_run_at <= ?
                ORDER BY next_run_at ASC
            """, (current_timestamp,))
            results = []
            for row in cursor.fetchall():
                task = dict(row)
                task["trigger_config"] = json.loads(task["trigger_config"])
                results.append(task)
            return results

    def update_task_next_run(self, task_id: str, next_run_at: int, last_run_at: int) -> None:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE scheduled_tasks 
                SET next_run_at = ?, last_run_at = ?
                WHERE task_id = ?
            """, (next_run_at, last_run_at, task_id))

    def get_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM scheduled_tasks WHERE task_id = ?", (task_id,))
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
                    (status,)
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
                (status, task_id)
            )
    
    def search_conversations_by_keyword(
        self,
        query: Optional[str] = None,
        limit: int = 10,
        exclude_session_id: Optional[int] = None,
        role: Optional[str] = None,
        start_timestamp: Optional[int] = None,
        end_timestamp: Optional[int] = None
    ) -> List[Tuple[int, int, str, str, float]]:
        """Search conversations by keyword and/or filters using FTS5.
        
        Args:
            query: Search query (supports FTS5 query syntax). If None, returns all matching filters.
            limit: Maximum number of results
            exclude_session_id: Optional session_id to exclude (e.g., current session)
            role: Optional role filter ('user' or 'assistant')
            start_timestamp: Optional start time (Unix timestamp)
            end_timestamp: Optional end time (Unix timestamp)
            
        Returns:
            List of tuples: (conversation_id, timestamp, role, text, rank)
        """
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
                            c.conversation_id, c.timestamp, c.role, c.text,
                            fts.rank
                        FROM fts_conversations fts
                        JOIN conversations c ON fts.conversation_id = c.conversation_id
                    """
                    conditions.append("fts.text MATCH ?")
                    params.append(query)
                else:
                    base_query = """
                        SELECT 
                            c.conversation_id, c.timestamp, c.role, c.text,
                            0.0 as rank
                        FROM conversations c
                    """
                
                if exclude_session_id is not None:
                    conditions.append("c.session_id != ?")
                    params.append(exclude_session_id)
                
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
                    timestamp = row["timestamp"]
                    role_val = row["role"]
                    text = row["text"]
                    rank = row["rank"]
                    results.append((conversation_id, timestamp, role_val, text, rank))
                
                return results
            except sqlite3.OperationalError as e:
                logger.error(f"Conversation search failed: {e}")
                return []
    
    def search_summaries_by_keyword(
        self,
        query: Optional[str] = None,
        limit: int = 5,
        exclude_session_id: Optional[int] = None,
        start_timestamp: Optional[int] = None,
        end_timestamp: Optional[int] = None
    ) -> List[Tuple[int, str, int, int, float]]:
        """Search summaries by keyword and/or filters using FTS5.
        
        Args:
            query: Search query (supports FTS5 query syntax). If None, returns all matching filters.
            limit: Maximum number of results
            exclude_session_id: Optional session_id to exclude (e.g., current session)
            start_timestamp: Optional start time (Unix timestamp) - matches if summary's last_timestamp >= this
            end_timestamp: Optional end time (Unix timestamp) - matches if summary's first_timestamp <= this
            
        Returns:
            List of tuples: (summary_id, summary, first_timestamp, last_timestamp, rank)
        """
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
                            s.summary_id, s.summary, s.first_timestamp, s.last_timestamp,
                            fts.rank
                        FROM fts_summaries fts
                        JOIN summaries s ON fts.summary_id = s.summary_id
                    """
                    conditions.append("fts.summary MATCH ?")
                    params.append(query)
                else:
                    base_query = """
                        SELECT 
                            s.summary_id, s.summary, s.first_timestamp, s.last_timestamp,
                            0.0 as rank
                        FROM summaries s
                    """
                
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
                order_by = "ORDER BY fts.rank" if query else "ORDER BY s.last_timestamp DESC"
                
                full_query = f"{base_query} {where_clause} {order_by} LIMIT ?"
                params.append(limit)
                
                cursor.execute(full_query, params)
                
                results = []
                for row in cursor.fetchall():
                    summary_id = row["summary_id"]
                    summary = row["summary"]
                    first_timestamp = row["first_timestamp"]
                    last_timestamp = row["last_timestamp"]
                    rank = row["rank"]
                    results.append((summary_id, summary, first_timestamp, last_timestamp, rank))
                
                return results
            except sqlite3.OperationalError as e:
                logger.error(f"Summary search failed: {e}")
                return []
