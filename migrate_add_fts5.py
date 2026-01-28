#!/usr/bin/env python3
"""
Database migration script to add FTS5 full-text search tables.

This script:
1. Checks current schema version
2. Adds FTS5 virtual tables for conversations and summaries
3. Creates triggers to keep FTS5 tables in sync
4. Backfills existing data into FTS5 tables
5. Updates schema version to 3.0

Usage:
    python migrate_add_fts5.py <profile>
    
Example:
    python migrate_add_fts5.py test
"""

import sys
import sqlite3
from pathlib import Path


def get_db_path(profile: str) -> Path:
    """Get database path for profile"""
    return Path.cwd() / "data" / profile / "chatbot.db"


def get_schema_version(conn: sqlite3.Connection) -> str:
    """Get current schema version"""
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT value FROM meta WHERE key = 'schema_version'")
        row = cursor.fetchone()
        return row[0] if row else "unknown"
    except sqlite3.OperationalError:
        return "unknown"


def check_fts_tables_exist(conn: sqlite3.Connection) -> bool:
    """Check if FTS5 tables already exist"""
    cursor = conn.cursor()
    cursor.execute("""
        SELECT name FROM sqlite_master 
        WHERE type='table' AND name IN ('fts_conversations', 'fts_summaries')
    """)
    results = cursor.fetchall()
    return len(results) == 2


def create_fts_tables(conn: sqlite3.Connection):
    """Create FTS5 virtual tables and triggers"""
    cursor = conn.cursor()
    
    print("Creating FTS5 virtual tables...")
    
    # Create FTS5 tables
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
    
    print("Creating triggers...")
    
    # Create triggers for conversations
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
    
    # Create triggers for summaries
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
    
    conn.commit()
    print("FTS5 tables and triggers created successfully!")


def backfill_fts_data(conn: sqlite3.Connection):
    """Backfill existing data into FTS5 tables"""
    cursor = conn.cursor()
    
    print("\nBackfilling existing data...")
    
    # Count existing records
    cursor.execute("SELECT COUNT(*) FROM conversations")
    conv_count = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM summaries")
    summary_count = cursor.fetchone()[0]
    
    print(f"Found {conv_count} conversations and {summary_count} summaries")
    
    if conv_count > 0:
        print("Backfilling conversations...")
        cursor.execute("""
            INSERT INTO fts_conversations(rowid, conversation_id, text)
            SELECT conversation_id, conversation_id, text FROM conversations
        """)
        print(f"✓ Backfilled {conv_count} conversations")
    
    if summary_count > 0:
        print("Backfilling summaries...")
        cursor.execute("""
            INSERT INTO fts_summaries(rowid, summary_id, summary)
            SELECT summary_id, summary_id, summary FROM summaries
        """)
        print(f"✓ Backfilled {summary_count} summaries")
    
    conn.commit()


def update_schema_version(conn: sqlite3.Connection):
    """Update schema version to 3.0"""
    cursor = conn.cursor()
    cursor.execute("""
        INSERT OR REPLACE INTO meta (key, value) VALUES ('schema_version', '3.0')
    """)
    conn.commit()
    print("\n✓ Schema version updated to 3.0")


def load_sqlite_vec(conn: sqlite3.Connection) -> bool:
    """Try to load sqlite-vec extension"""
    try:
        import sqlite_vec
        conn.enable_load_extension(True)
        conn.load_extension(sqlite_vec.loadable_path())
        return True
    except Exception as e:
        print(f"Warning: Could not load sqlite-vec extension: {e}")
        return False


def migrate(profile: str):
    """Run migration for given profile"""
    db_path = get_db_path(profile)
    
    if not db_path.exists():
        print(f"Error: Database not found at {db_path}")
        print("Please run the application first to create the database.")
        return False
    
    print(f"Migrating database: {db_path}")
    print("=" * 60)
    
    # Connect to database
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    
    # Try to load sqlite-vec (optional)
    load_sqlite_vec(conn)
    
    # Check current version
    current_version = get_schema_version(conn)
    print(f"Current schema version: {current_version}")
    
    # Check if FTS tables already exist
    if check_fts_tables_exist(conn):
        print("\n⚠ FTS5 tables already exist!")
        print("Migration may have already been run.")
        response = input("Do you want to continue anyway? (yes/no): ")
        if response.lower() not in ['yes', 'y']:
            print("Migration cancelled.")
            conn.close()
            return False
    
    try:
        # Create FTS5 tables and triggers
        create_fts_tables(conn)
        
        # Backfill existing data
        backfill_fts_data(conn)
        
        # Update schema version
        update_schema_version(conn)
        
        print("\n" + "=" * 60)
        print("✓ Migration completed successfully!")
        print("\nYou can now use the memory_search tool with:")
        print("  - Boolean operators: AND, OR, NOT")
        print("  - Exact phrases: \"phrase\"")
        print("  - Time filters: time_period, start_date, end_date")
        print("  - Role filters: role='user' or 'assistant'")
        
    except Exception as e:
        print(f"\n✗ Migration failed: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()
    
    return True


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    
    profile = sys.argv[1]
    success = migrate(profile)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
