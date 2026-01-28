#!/usr/bin/env python3
"""Migrate data from old chat_sessions.db to new chatbot.db.

This script creates a new chatbot.db from old chat_sessions.db
with the correct schema according to BREAKING.md.
"""

import sqlite3
from pathlib import Path
import sys
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from utils.logger import get_logger

logger = get_logger()


class DatabaseRemigrator:
    def __init__(self, profile: str):
        self.profile = profile
        self.data_dir = Path(__file__).parent.parent / "data" / profile
        self.new_db_path = self.data_dir / "chatbot.db"
        self.old_db_path = self.data_dir / "chat_sessions.db"

    def migrate(self):
        logger.info(f"Starting re-migration for profile: {self.profile}")
        
        if not self.old_db_path.exists():
            logger.error(f"Old database not found: {self.old_db_path}")
            return False
        
        self._backup_existing_db()
        self._create_new_database()
        self._migrate_sessions()
        self._migrate_conversations()
        self._migrate_summaries()
        
        logger.info("Re-migration completed successfully!")
        return True

    def _backup_existing_db(self):
        logger.info("Checking for existing database...")
        
        if self.new_db_path.exists():
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_path = self.new_db_path.parent / f"chatbot.db.backup_{timestamp}"
            
            import shutil
            shutil.move(str(self.new_db_path), str(backup_path))
            logger.info(f"Existing database backed up to: {backup_path}")

    def _create_new_database(self):
        logger.info("Creating new database schema...")
        
        conn = sqlite3.connect(str(self.new_db_path))
        cursor = conn.cursor()
        
        cursor.execute("DROP TABLE IF EXISTS vec_conversations")
        cursor.execute("DROP TABLE IF EXISTS vec_summaries")
        cursor.execute("DROP TABLE IF EXISTS sessions")
        cursor.execute("DROP TABLE IF EXISTS conversations")
        cursor.execute("DROP TABLE IF EXISTS summaries")
        cursor.execute("DROP TABLE IF EXISTS scheduled_tasks")
        cursor.execute("DROP TABLE IF EXISTS meta")
        
        cursor.execute("""
            CREATE TABLE meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)
        
        cursor.execute("INSERT OR IGNORE INTO meta (key, value) VALUES ('schema_version', '2.0')")
        
        cursor.execute("""
            CREATE TABLE sessions (
                session_id INTEGER PRIMARY KEY AUTOINCREMENT,
                start_timestamp INTEGER NOT NULL,
                end_timestamp INTEGER,
                status TEXT CHECK(status IN ('active', 'archived')) DEFAULT 'active'
            )
        """)
        
        cursor.execute("""
            CREATE TABLE conversations (
                conversation_id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER NOT NULL,
                timestamp INTEGER NOT NULL,
                role TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
                text TEXT NOT NULL,
                FOREIGN KEY(session_id) REFERENCES sessions(session_id)
            )
        """)
        
        cursor.execute("""
            CREATE TABLE summaries (
                summary_id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER NOT NULL,
                summary TEXT NOT NULL,
                first_timestamp INTEGER NOT NULL,
                last_timestamp INTEGER NOT NULL,
                FOREIGN KEY(session_id) REFERENCES sessions(session_id)
            )
        """)
        
        cursor.execute("""
            CREATE TABLE scheduled_tasks (
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
        
        cursor.execute("CREATE INDEX idx_sessions_status ON sessions(status)")
        cursor.execute("CREATE INDEX idx_conversations_session ON conversations(session_id)")
        cursor.execute("CREATE INDEX idx_conversations_timestamp ON conversations(timestamp DESC)")
        cursor.execute("CREATE INDEX idx_summaries_session ON summaries(session_id)")
        cursor.execute("CREATE INDEX idx_summaries_last_timestamp ON summaries(last_timestamp DESC)")
        cursor.execute("CREATE INDEX idx_scheduled_tasks_next_run ON scheduled_tasks(next_run_at, status)")
        
        conn.commit()
        conn.close()
        logger.info("New database schema created")

    def _migrate_sessions(self):
        logger.info("Migrating sessions from old database...")
        
        old_conn = sqlite3.connect(str(self.old_db_path))
        new_conn = sqlite3.connect(str(self.new_db_path))
        
        old_cursor = old_conn.cursor()
        new_cursor = new_conn.cursor()
        
        try:
            old_cursor.execute("SELECT session_id, start_timestamp, end_timestamp, status FROM session ORDER BY start_timestamp")
            rows = old_cursor.fetchall()
            
            for old_session_id, start_timestamp, end_timestamp, status in rows:
                new_cursor.execute(
                    "INSERT INTO sessions (start_timestamp, end_timestamp, status) VALUES (?, ?, ?)",
                    (start_timestamp, end_timestamp, status)
                )
            
            new_conn.commit()
            logger.info(f"Migrated {len(rows)} sessions")
        except Exception as e:
            logger.error(f"Failed to migrate sessions: {e}")
            raise
        finally:
            old_conn.close()
            new_conn.close()

    def _migrate_conversations(self):
        logger.info("Migrating conversations from old database...")
        
        old_conn = sqlite3.connect(str(self.old_db_path))
        new_conn = sqlite3.connect(str(self.new_db_path))
        
        old_cursor = old_conn.cursor()
        new_cursor = new_conn.cursor()
        
        try:
            old_cursor.execute("SELECT conversation_id, session_id, timestamp, role, text FROM conversation ORDER BY timestamp")
            rows = old_cursor.fetchall()
            
            session_id_map = {}
            old_cursor.execute("SELECT session_id, rowid FROM session")
            for old_sid, new_sid in old_cursor.fetchall():
                session_id_map[old_sid] = new_sid
            
            for conversation_id, old_session_id, timestamp, role, text in rows:
                new_session_id = session_id_map.get(old_session_id)
                if new_session_id:
                    new_cursor.execute(
                        "INSERT INTO conversations (conversation_id, session_id, timestamp, role, text) VALUES (?, ?, ?, ?, ?)",
                        (conversation_id, new_session_id, timestamp, role, text)
                    )
            
            new_conn.commit()
            logger.info(f"Migrated {len(rows)} conversations")
        except Exception as e:
            logger.error(f"Failed to migrate conversations: {e}")
            raise
        finally:
            old_conn.close()
            new_conn.close()

    def _migrate_summaries(self):
        logger.info("Migrating summaries from old database...")
        
        old_conn = sqlite3.connect(str(self.old_db_path))
        new_conn = sqlite3.connect(str(self.new_db_path))
        
        old_cursor = old_conn.cursor()
        new_cursor = new_conn.cursor()
        
        try:
            old_cursor.execute("SELECT summary_id, session_id, summary FROM summary")
            rows = old_cursor.fetchall()
            
            session_id_map = {}
            old_cursor.execute("SELECT session_id, rowid FROM session")
            for old_sid, new_sid in old_cursor.fetchall():
                session_id_map[old_sid] = new_sid
            
            for summary_id, old_session_id, summary in rows:
                old_cursor.execute(
                    "SELECT MIN(timestamp) as first_ts, MAX(timestamp) as last_ts FROM conversation WHERE session_id = ?",
                    (old_session_id,)
                )
                result = old_cursor.fetchone()
                
                if result:
                    first_ts, last_ts = result
                    new_session_id = session_id_map.get(old_session_id)
                    if new_session_id:
                        new_cursor.execute(
                            "INSERT INTO summaries (summary_id, session_id, summary, first_timestamp, last_timestamp) VALUES (?, ?, ?, ?, ?)",
                            (summary_id, new_session_id, summary, first_ts or 0, last_ts or 0)
                        )
            
            new_conn.commit()
            logger.info(f"Migrated {len(rows)} summaries")
        except Exception as e:
            logger.error(f"Failed to migrate summaries: {e}")
            raise
        finally:
            old_conn.close()
            new_conn.close()


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Migrate data from old chat_sessions.db")
    parser.add_argument("profile", help="Profile name (e.g., 'hy')")
    args = parser.parse_args()
    
    migrator = DatabaseRemigrator(args.profile)
    success = migrator.migrate()
    
    if not success:
        sys.exit(1)


if __name__ == "__main__":
    main()
