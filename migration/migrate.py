#!/usr/bin/env python3
"""Unified migration script for Seelenmaschine v3.1 upgrade.

This script consolidates all migration tasks:
1. Detect source files in the backup directory if not in the profile root.
2. Convert old text-based profiles (persona_memory.txt, user_profile.txt) to seele.json using LLM.
3. Migrate old database (chat_sessions.db) to the new SQLite format (chatbot.db) with the 3.1 schema.
4. Set up FTS5 full-text search and scheduled tasks with the latest constraints.
"""

import sys
import shutil
import sqlite3
import json
import asyncio
import time
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, Optional, List, Tuple
import argparse

# Add src to path for imports
root_dir = Path(__file__).parent.parent
sys.path.insert(0, str(root_dir / "src"))

from config import Config, init_config
from utils.logger import get_logger
from openai import AsyncOpenAI
import struct
import sqlite_vec
from llm.embedding import EmbeddingClient

logger = get_logger()


class LLMConverter:
    """Helper class to convert text profiles to JSON using LLM."""

    def __init__(self):
        self.client = AsyncOpenAI(
            api_key=Config.OPENAI_API_KEY, base_url=Config.OPENAI_API_BASE
        )
        self.model = Config.TOOL_MODEL or "gpt-4o"

    async def convert_async(
        self, persona_text: str, user_text: str, schema_template: Dict[str, Any]
    ) -> Dict[str, Any]:
        schema_str = json.dumps(schema_template, ensure_ascii=False, indent=2)

        system_prompt = (
            "You are a data conversion expert. Your task is to extract information from unstructured text profiles "
            "and populate a JSON object based on a provided schema template.\n"
            "Ensure that:\n"
            "1. You expect the output to be valid JSON matching the schema structure exactly.\n"
            "2. You extract all available details from the input text.\n"
            "3. If a field is missing in the text, leave it as empty string or empty list as per the template.\n"
            "4. Do not translate the content; keep it in the original language (likely Chinese).\n"
            "5. The 'likes' and 'dislikes' fields should be arrays of strings.\n"
            "6. 'memorable_events' and 'commands_and_agreements' should be arrays of objects if data exists, otherwise empty arrays."
        )

        user_prompt = (
            f"Please convert the following text profiles into the target JSON format.\n\n"
            f"### Target Schema Template\n"
            f"```json\n{schema_str}\n```\n\n"
            f"### Input 1: Persona Memory\n"
            f"{persona_text}\n\n"
            f"### Input 2: User Profile\n"
            f"{user_text}"
        )

        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                response_format={"type": "json_object"},
            )

            content = response.choices[0].message.content
            if not content:
                raise ValueError("Empty response from LLM")

            return json.loads(content)

        except Exception as e:
            logger.error(f"LLM conversion failed: {e}")
            raise
        finally:
            await self.client.close()


class DataMigrator:
    def __init__(self, profile: str):
        self.profile = profile
        self.data_dir = root_dir / "data" / profile
        self.backup_dir = self.data_dir / "backup"

        # Target files
        self.seele_json_path = self.data_dir / "seele.json"
        self.new_db_path = self.data_dir / "chatbot.db"

        # Potential source files (current or backup)
        self.old_db_name = "chat_sessions.db"
        self.persona_txt_name = "persona_memory.txt"
        self.user_txt_name = "user_profile.txt"

        self.source_db: Optional[Path] = None
        self.source_persona: Optional[Path] = None
        self.source_user: Optional[Path] = None

    def _find_source_files(self):
        """Locate source files, preferring profile root, then backup/."""
        # 1. Look for old database
        if (self.data_dir / self.old_db_name).exists():
            self.source_db = self.data_dir / self.old_db_name
        elif (self.backup_dir / self.old_db_name).exists():
            self.source_db = self.backup_dir / self.old_db_name

        # 2. Look for persona memory
        if (self.data_dir / self.persona_txt_name).exists():
            self.source_persona = self.data_dir / self.persona_txt_name
        elif (self.backup_dir / self.persona_txt_name).exists():
            self.source_persona = self.backup_dir / self.persona_txt_name

        # 3. Look for user profile
        if (self.data_dir / self.user_txt_name).exists():
            self.source_user = self.data_dir / self.user_txt_name
        elif (self.backup_dir / self.user_txt_name).exists():
            self.source_user = self.backup_dir / self.user_txt_name

        if self.source_db:
            logger.info(f"Source database found: {self.source_db}")
        if self.source_persona:
            logger.info(f"Source persona file found: {self.source_persona}")
        if self.source_user:
            logger.info(f"Source user file found: {self.source_user}")

    def _backup_existing_data(self):
        """Create a backup of the current target files if they exist."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        active_backup_dir = self.data_dir / f"migration_backup_{timestamp}"

        needed = False
        if self.seele_json_path.exists():
            active_backup_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(self.seele_json_path, active_backup_dir / "seele.json")
            needed = True
        if self.new_db_path.exists():
            active_backup_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(self.new_db_path, active_backup_dir / "chatbot.db")
            needed = True

        if needed:
            logger.info(f"Existing data backed up to: {active_backup_dir}")

    def migrate(self):
        logger.info(f"Starting unified migration for profile: {self.profile}")

        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._find_source_files()
        self._backup_existing_data()

        # Step 1: Memory File Migration
        if not self.seele_json_path.exists():
            if self.source_persona and self.source_user:
                self._convert_txt_to_json()
            else:
                logger.warning(
                    "Old text files not found, copying template seele.json..."
                )
                template_path = root_dir / "template" / "seele.json"
                if template_path.exists():
                    shutil.copy2(template_path, self.seele_json_path)
                    logger.info("Copied template seele.json")
                else:
                    logger.error("Template seele.json not found!")

        # Step 2: Database Migration
        self._create_new_database()
        if self.source_db:
            self._migrate_database_content()
        else:
            logger.info("No old database found to migrate.")

        # Step 3: Rebuild Missing Vectors
        asyncio.run(self._rebuild_vectors())

        logger.info("Migration completed successfully!")

    def _convert_txt_to_json(self):
        logger.info("Converting old text files to seele.json...")

        persona_content = self.source_persona.read_text(encoding="utf-8")
        user_content = self.source_user.read_text(encoding="utf-8")

        # Load template for schema reference
        template_path = root_dir / "template" / "seele.json"
        if template_path.exists():
            schema_template = json.loads(template_path.read_text(encoding="utf-8"))
        else:
            schema_template = {
                "bot": {"name": "", "gender": "", "likes": [], "dislikes": []},
                "user": {"name": "", "gender": "", "likes": [], "dislikes": []},
                "memorable_events": [],
                "commands_and_agreements": [],
            }

        converter = LLMConverter()
        try:
            result = asyncio.run(
                converter.convert_async(persona_content, user_content, schema_template)
            )

            # Ensure we have an object, not a list
            if isinstance(result, list) and len(result) > 0:
                result = result[0]

            with open(self.seele_json_path, "w", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False, indent=4)
            logger.info(f"Successfully created {self.seele_json_path}")
        except Exception as e:
            logger.error(f"Failed to convert text files: {e}")
            raise

    def _create_new_database(self):
        """Create or upgrade database to 3.1 schema."""
        if not self.new_db_path.exists():
            self._create_fresh_3_1_database()
        else:
            self._upgrade_existing_database()

    def _create_fresh_3_1_database(self):
        """Create fresh database with 3.1 schema including FTS5."""
        logger.info("Initializing new database with 3.1 schema...")

        conn = sqlite3.connect(str(self.new_db_path))
        cursor = conn.cursor()

        # Meta table
        cursor.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        cursor.execute("INSERT INTO meta (key, value) VALUES ('schema_version', '3.1')")

        # Sessions table
        cursor.execute(
            """
            CREATE TABLE sessions (
                session_id INTEGER PRIMARY KEY AUTOINCREMENT,
                start_timestamp INTEGER NOT NULL,
                end_timestamp INTEGER,
                status TEXT CHECK(status IN ('active', 'archived')) DEFAULT 'active'
            )
        """
        )
        cursor.execute("CREATE INDEX idx_sessions_status ON sessions(status)")

        # Conversations table
        cursor.execute(
            """
            CREATE TABLE conversations (
                conversation_id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER NOT NULL,
                timestamp INTEGER NOT NULL,
                role TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
                text TEXT NOT NULL,
                FOREIGN KEY(session_id) REFERENCES sessions(session_id)
            )
        """
        )
        cursor.execute(
            "CREATE INDEX idx_conversations_session ON conversations(session_id)"
        )
        cursor.execute(
            "CREATE INDEX idx_conversations_timestamp ON conversations(timestamp DESC)"
        )

        # Summaries table
        cursor.execute(
            """
            CREATE TABLE summaries (
                summary_id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER NOT NULL,
                summary TEXT NOT NULL,
                first_timestamp INTEGER NOT NULL,
                last_timestamp INTEGER NOT NULL,
                FOREIGN KEY(session_id) REFERENCES sessions(session_id)
            )
        """
        )
        cursor.execute("CREATE INDEX idx_summaries_session ON summaries(session_id)")
        cursor.execute(
            "CREATE INDEX idx_summaries_last_timestamp ON summaries(last_timestamp DESC)"
        )

        # Scheduled tasks (v3.1 schema)
        cursor.execute(
            """
            CREATE TABLE scheduled_tasks (
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

        # Vector tables (vec0)
        cursor.execute(
            f"CREATE VIRTUAL TABLE IF NOT EXISTS vec_conversations USING vec0(conversation_id INTEGER PRIMARY KEY, embedding float[{Config.EMBEDDING_DIMENSION}])"
        )
        cursor.execute(
            f"CREATE VIRTUAL TABLE IF NOT EXISTS vec_summaries USING vec0(summary_id INTEGER PRIMARY KEY, embedding float[{Config.EMBEDDING_DIMENSION}])"
        )

        # FTS5 tables
        cursor.execute(
            """
            CREATE VIRTUAL TABLE fts_conversations USING fts5(
                conversation_id UNINDEXED,
                text,
                content=conversations,
                content_rowid=conversation_id
            )
        """
        )
        cursor.execute(
            """
            CREATE VIRTUAL TABLE fts_summaries USING fts5(
                summary_id UNINDEXED,
                summary,
                content=summaries,
                content_rowid=summary_id
            )
        """
        )

        # FTS triggers
        cursor.execute(
            """
            CREATE TRIGGER conversations_ai AFTER INSERT ON conversations BEGIN
                INSERT INTO fts_conversations(rowid, conversation_id, text)
                VALUES (new.conversation_id, new.conversation_id, new.text);
            END
        """
        )
        cursor.execute(
            """
            CREATE TRIGGER summaries_ai AFTER INSERT ON summaries BEGIN
                INSERT INTO fts_summaries(rowid, summary_id, summary)
                VALUES (new.summary_id, new.summary_id, new.summary);
            END
        """
        )

        conn.commit()
        conn.close()
        logger.info("3.1 database schema created")

    def _upgrade_existing_database(self):
        """Upgrade existing chatbot.db to 3.1 version."""
        logger.info("Checking for database upgrades...")

        conn = sqlite3.connect(str(self.new_db_path))
        cursor = conn.cursor()

        try:
            cursor.execute("SELECT value FROM meta WHERE key = 'schema_version'")
            version = cursor.fetchone()[0]
        except Exception:
            version = "unknown"

        if version == "unknown":
            logger.warning("Unknown database version, cannot upgrade safely.")
            conn.close()
            return

        if version == "2.0":
            logger.info("Upgrading from 2.0 to 3.0 (Adding FTS5)...")
            # Create FTS tables and backfill (logic omitted for brevity, but same as _create_fresh_3_1_database)
            # Actually I should implement it here for a complete "unified" script
            self._add_fts5_to_existing(cursor)
            cursor.execute("UPDATE meta SET value = '3.0' WHERE key = 'schema_version'")
            version = "3.0"

        if version == "3.0":
            logger.info(
                "Upgrading from 3.0 to 3.1 (Updating scheduled_tasks status)..."
            )
            self._add_running_status_to_tasks(cursor)
            cursor.execute("UPDATE meta SET value = '3.1' WHERE key = 'schema_version'")
            version = "3.1"

        conn.commit()
        conn.close()
        logger.info(f"Database is at version {version}")

    def _add_fts5_to_existing(self, cursor):
        """Add FTS5 tables to an existing 2.0 database."""
        cursor.execute(
            "CREATE VIRTUAL TABLE IF NOT EXISTS fts_conversations USING fts5(conversation_id UNINDEXED, text, content=conversations, content_rowid=conversation_id)"
        )
        cursor.execute(
            "CREATE VIRTUAL TABLE IF NOT EXISTS fts_summaries USING fts5(summary_id UNINDEXED, summary, content=summaries, content_rowid=summary_id)"
        )

        cursor.execute(
            "INSERT OR IGNORE INTO fts_conversations(rowid, conversation_id, text) SELECT conversation_id, conversation_id, text FROM conversations"
        )
        cursor.execute(
            "INSERT OR IGNORE INTO fts_summaries(rowid, summary_id, summary) SELECT summary_id, summary_id, summary FROM summaries"
        )

        # Add triggers (ai)
        cursor.execute(
            "CREATE TRIGGER IF NOT EXISTS conversations_ai AFTER INSERT ON conversations BEGIN INSERT INTO fts_conversations(rowid, conversation_id, text) VALUES (new.conversation_id, new.conversation_id, new.text); END"
        )
        cursor.execute(
            "CREATE TRIGGER IF NOT EXISTS summaries_ai AFTER INSERT ON summaries BEGIN INSERT INTO fts_summaries(rowid, summary_id, summary) VALUES (new.summary_id, new.summary_id, new.summary); END"
        )

    def _add_running_status_to_tasks(self, cursor):
        """Update scheduled_tasks table to include 'running' status."""
        cursor.execute("PRAGMA foreign_keys=OFF")
        cursor.execute(
            "CREATE TABLE scheduled_tasks_new (task_id TEXT PRIMARY KEY, name TEXT NOT NULL, trigger_type TEXT NOT NULL CHECK(trigger_type IN ('once', 'interval')), trigger_config TEXT NOT NULL, message TEXT NOT NULL, created_at INTEGER NOT NULL, next_run_at INTEGER NOT NULL, last_run_at INTEGER, status TEXT CHECK(status IN ('active', 'paused', 'completed', 'running')) DEFAULT 'active')"
        )
        cursor.execute("INSERT INTO scheduled_tasks_new SELECT * FROM scheduled_tasks")
        cursor.execute("DROP TABLE scheduled_tasks")
        cursor.execute("ALTER TABLE scheduled_tasks_new RENAME TO scheduled_tasks")
        cursor.execute(
            "CREATE INDEX idx_scheduled_tasks_next_run ON scheduled_tasks(next_run_at, status)"
        )
        cursor.execute("PRAGMA foreign_keys=ON")

    def _serialize_embedding(self, embedding: List[float]) -> bytes:
        return struct.pack(f"{len(embedding)}f", *embedding)

    async def _rebuild_vectors(self):
        """Rebuild missing vectors for conversations and summaries with rate limiting."""
        logger.info("Checking for missing vectors...")

        # Initialize EmbeddingClient
        client = EmbeddingClient()
        batch_size = 50
        rpm_limit = 120
        # 120 RPM = 2 requests per second. To be safe, wait 0.6s between batches.
        # However, RPM is about API calls. 1 batch = 1 API call.
        current_db = sqlite3.connect(str(self.new_db_path))
        current_db.row_factory = sqlite3.Row
        cursor = current_db.cursor()

        try:
            # 1. Process Conversations
            cursor.execute(
                """
                SELECT c.conversation_id, c.text FROM conversations c
                LEFT JOIN vec_conversations v ON c.conversation_id = v.conversation_id
                WHERE v.conversation_id IS NULL
            """
            )
            missing_convs = cursor.fetchall()

            if missing_convs:
                total = len(missing_convs)
                logger.info(f"Rebuilding {total} conversation vectors...")
                for i in range(0, total, batch_size):
                    batch = missing_convs[i : i + batch_size]
                    ids = [row["conversation_id"] for row in batch]
                    texts = [row["text"] for row in batch]

                    embeddings = await client.get_embeddings_batch_async(texts)

                    for conv_id, vector in zip(ids, embeddings):
                        blob = self._serialize_embedding(vector)
                        cursor.execute(
                            "INSERT INTO vec_conversations (conversation_id, embedding) VALUES (?, ?)",
                            (conv_id, blob),
                        )
                    current_db.commit()

                    progress = min(100, (i + len(batch)) * 100 // total)
                    print(
                        f"  Conversations: [{('#' * (progress // 5)).ljust(20, '-')}] {progress}% ({i + len(batch)}/{total})",
                        end="\r",
                        flush=True,
                    )

                    if i + batch_size < total:
                        await asyncio.sleep(0.6)  # Maintain RPM < 120
                print()

            # 2. Process Summaries
            cursor.execute(
                """
                SELECT s.summary_id, s.summary FROM summaries s
                LEFT JOIN vec_summaries v ON s.summary_id = v.summary_id
                WHERE v.summary_id IS NULL
            """
            )
            missing_sums = cursor.fetchall()

            if missing_sums:
                total = len(missing_sums)
                logger.info(f"Rebuilding {total} summary vectors...")
                for i in range(0, total, batch_size):
                    batch = missing_sums[i : i + batch_size]
                    ids = [row["summary_id"] for row in batch]
                    texts = [row["summary"] for row in batch]

                    embeddings = await client.get_embeddings_batch_async(texts)

                    for sum_id, vector in zip(ids, embeddings):
                        blob = self._serialize_embedding(vector)
                        cursor.execute(
                            "INSERT INTO vec_summaries (summary_id, embedding) VALUES (?, ?)",
                            (sum_id, blob),
                        )
                    current_db.commit()

                    progress = min(100, (i + len(batch)) * 100 // total)
                    print(
                        f"  Summaries:     [{('#' * (progress // 5)).ljust(20, '-')}] {progress}% ({i + len(batch)}/{total})",
                        end="\r",
                        flush=True,
                    )

                    if i + batch_size < total:
                        await asyncio.sleep(0.6)  # Maintain RPM < 120
                print()

        except Exception as e:
            logger.error(f"Failed to rebuild vectors: {e}")
            raise
        finally:
            current_db.close()
            await client._async_close()

    def _migrate_database_content(self):
        """Migrate data from source_db to new_db_path."""
        logger.info(f"Migrating data from {self.source_db}...")

        old_conn = sqlite3.connect(str(self.source_db))
        new_conn = sqlite3.connect(str(self.new_db_path))

        old_cursor = old_conn.cursor()
        new_cursor = new_conn.cursor()

        try:
            # 1. Sessions
            old_cursor.execute(
                "SELECT session_id, start_timestamp, end_timestamp, status FROM session ORDER BY start_timestamp"
            )
            sessions = old_cursor.fetchall()
            old_to_new_session_id = {}

            for old_sid, start_ts, end_ts, status in sessions:
                new_cursor.execute(
                    "INSERT INTO sessions (start_timestamp, end_timestamp, status) VALUES (?, ?, ?)",
                    (start_ts, end_ts, status),
                )
                old_to_new_session_id[old_sid] = new_cursor.lastrowid

            logger.info(f"Migrated {len(sessions)} sessions")

            # 2. Conversations
            old_cursor.execute(
                "SELECT conversation_id, session_id, timestamp, role, text FROM conversation ORDER BY timestamp"
            )
            conversations = old_cursor.fetchall()
            for old_cid, old_sid, ts, role, text in conversations:
                new_sid = old_to_new_session_id.get(old_sid)
                if new_sid:
                    new_cursor.execute(
                        "INSERT INTO conversations (session_id, timestamp, role, text) VALUES (?, ?, ?, ?)",
                        (new_sid, ts, role, text),
                    )
                    # Trigger will populate FTS
            logger.info(f"Migrated {len(conversations)} conversations")

            # 3. Summaries
            old_cursor.execute("SELECT summary_id, session_id, summary FROM summary")
            summaries = old_cursor.fetchall()
            for old_sum_id, old_sid, summary_text in summaries:
                new_sid = old_to_new_session_id.get(old_sid)
                if new_sid:
                    # Need to find first/last timestamp
                    old_cursor.execute(
                        "SELECT MIN(timestamp), MAX(timestamp) FROM conversation WHERE session_id = ?",
                        (old_sid,),
                    )
                    first_ts, last_ts = old_cursor.fetchone()

                    new_cursor.execute(
                        "INSERT INTO summaries (session_id, summary, first_timestamp, last_timestamp) VALUES (?, ?, ?, ?)",
                        (new_sid, summary_text, first_ts or 0, last_ts or 0),
                    )
            logger.info(f"Migrated {len(summaries)} summaries")

            new_conn.commit()
        except Exception as e:
            logger.error(f"Failed to migrate data: {e}")
            new_conn.rollback()
            raise
        finally:
            old_conn.close()
            new_conn.close()


def main():
    parser = argparse.ArgumentParser(
        description="Consolidated Seelenmaschine Migration Tool"
    )
    parser.add_argument("profile", help="Profile name (e.g., 'hy')")
    args = parser.parse_args()

    init_config(args.profile)
    migrator = DataMigrator(args.profile)
    migrator.migrate()


if __name__ == "__main__":
    main()
