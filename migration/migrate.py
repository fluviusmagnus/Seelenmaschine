#!/usr/bin/env python3
"""Main migration script for Seelenmaschine v2 upgrade.

This script migrates old data format to the new SQLite + seele.json format.
"""

import sys
import shutil
import sqlite3
from pathlib import Path
from datetime import datetime
import argparse

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from config import init_config
from utils.logger import get_logger
sys.path.insert(0, str(Path(__file__).parent))
from converter import convert_txt_to_json

logger = get_logger()


class DataMigrator:
    def __init__(self, profile: str):
        self.profile = profile
        self.data_dir = Path(__file__).parent.parent / "data" / profile
        self.backup_dir = self.data_dir / "backup"
        self.seele_json_path = self.data_dir / "seele.json"
        self.new_db_path = self.data_dir / "chatbot.db"
        self.old_db_path = self.data_dir / "chat_sessions.db"
        self.lancedb_dir = self.data_dir / "lancedb"

    def migrate(self):
        logger.info(f"Starting migration for profile: {self.profile}")
        
        self._backup_old_data()
        self._convert_txt_to_json()
        self._create_new_database()
        self._migrate_conversations()
        self._migrate_summaries()
        
        logger.info("Migration completed successfully!")

    def _backup_old_data(self):
        logger.info("Backing up old data...")
        
        if self.backup_dir.exists():
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_with_ts = self.backup_dir.parent / f"backup_{timestamp}"
            shutil.move(str(self.backup_dir), str(backup_with_ts))
        
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        
        persona_txt = self.data_dir / "persona_memory.txt"
        user_txt = self.data_dir / "user_profile.txt"
        old_db = self.data_dir / "chat_sessions.db"
        
        if persona_txt.exists():
            shutil.copy2(persona_txt, self.backup_dir / "persona_memory.txt")
        if user_txt.exists():
            shutil.copy2(user_txt, self.backup_dir / "user_profile.txt")
        if old_db.exists():
            shutil.copy2(old_db, self.backup_dir / "chat_sessions.db")
        if self.lancedb_dir.exists():
            shutil.copytree(self.lancedb_dir, self.backup_dir / "lancedb", dirs_exist_ok=True)
        
        logger.info(f"Backup created at: {self.backup_dir}")

    def _convert_txt_to_json(self):
        logger.info("Converting persona_memory.txt and user_profile.txt to seele.json...")
        
        persona_txt = self.data_dir / "persona_memory.txt"
        user_txt = self.data_dir / "user_profile.txt"
        
        if not persona_txt.exists() or not user_txt.exists():
            logger.warning("Old text files not found, copying template...")
            template_path = Path(__file__).parent.parent / "template" / "seele.json"
            shutil.copy2(template_path, self.seele_json_path)
            return
        
        try:
            convert_txt_to_json(
                str(persona_txt),
                str(user_txt),
                str(self.seele_json_path)
            )
            logger.info(f"Created {self.seele_json_path}")
        except Exception as e:
            logger.error(f"Failed to convert text files: {e}")
            raise

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
                created_at INTEGER NOT NULL,
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
        
        conn.commit()
        conn.close()
        logger.info("New database schema created")

    def _migrate_conversations(self):
        logger.info("Migrating conversations from old database...")
        
        if not self.old_db_path.exists():
            logger.warning("Old database not found, skipping conversation migration")
            return
        
        old_conn = sqlite3.connect(str(self.old_db_path))
        new_conn = sqlite3.connect(str(self.new_db_path))
        
        old_cursor = old_conn.cursor()
        new_cursor = new_conn.cursor()
        
        try:
            old_cursor.execute("SELECT text_id, timestamp, role, text FROM conversation ORDER BY timestamp")
            rows = old_cursor.fetchall()
            
            for row in rows:
                text_id, timestamp, role, text = row
                
                new_cursor.execute(
                    "INSERT INTO conversations (text_id, timestamp, role, text) VALUES (?, ?, ?, ?)",
                    (text_id, timestamp, role, text)
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
        
        if not self.old_db_path.exists():
            logger.warning("Old database not found, skipping summary migration")
            return
        
        old_conn = sqlite3.connect(str(self.old_db_path))
        new_conn = sqlite3.connect(str(self.new_db_path))
        
        old_cursor = old_conn.cursor()
        new_cursor = new_conn.cursor()
        
        try:
            old_cursor.execute("SELECT session_id, summary FROM summary")
            rows = old_cursor.fetchall()
            
            for row in rows:
                session_id, summary = row
                
                old_cursor.execute(
                    "SELECT MIN(timestamp) as first_ts, MAX(timestamp) as last_ts FROM conversation WHERE session_id = ?",
                    (session_id,)
                )
                result = old_cursor.fetchone()
                
                if result:
                    first_ts, last_ts = result
                    text_id = f"summary_{session_id}_{last_ts}"
                    
                    new_cursor.execute(
                        "INSERT INTO summaries (text_id, summary, first_timestamp, last_timestamp) VALUES (?, ?, ?, ?)",
                        (text_id, summary, first_ts or 0, last_ts or 0)
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
    parser = argparse.ArgumentParser(description="Migrate Seold database to new format")
    parser.add_argument("profile", help="Profile name (e.g., 'hy')")
    args = parser.parse_args()
    
    init_config(args.profile)
    
    migrator = DataMigrator(args.profile)
    migrator.migrate()


if __name__ == "__main__":
    main()
