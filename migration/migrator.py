#!/usr/bin/env python3
"""
Unified migration tool for Seelenmaschine database upgrades.

This script handles all migration scenarios:
1. Schema upgrades (v2.0 -> v3.0, etc.)
2. Legacy database migration (chat_sessions.db -> chatbot.db)
3. Text file conversion (persona_memory.txt + user_profile.txt -> seele.json)

Usage:
    python migration/migrator.py <profile> [--auto] [--force] [--no-backup]
    
Examples:
    python migration/migrator.py test                    # Interactive mode
    python migration/migrator.py test --auto             # Auto-detect and migrate
    python migration/migrator.py test --force            # Force migration even if already done
    python migration/migrator.py test --no-backup        # Skip backup (not recommended)
"""

import sys
import sqlite3
import shutil
import json
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Tuple
from enum import Enum

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).parent))

# Try to import logger, fallback to basic logging if not available
try:
    from utils.logger import get_logger
    logger = get_logger()
except ImportError:
    import logging
    logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
    logger = logging.getLogger(__name__)


class MigrationType(Enum):
    """Types of migrations that can be performed"""
    LEGACY_DB = "legacy_db"           # chat_sessions.db -> chatbot.db
    TEXT_TO_JSON = "text_to_json"     # txt files -> seele.json
    SCHEMA_UPGRADE = "schema_upgrade"  # Schema version upgrades
    FTS5_UPGRADE = "fts5_upgrade"      # Add FTS5 tables (v2.0 -> v3.0)


class MigrationStatus:
    """Stores the current migration status"""
    def __init__(self, profile: str):
        self.profile = profile
        self.data_dir = Path.cwd() / "data" / profile
        self.backup_dir = self.data_dir / "backup"
        
        # Database paths
        self.new_db_path = self.data_dir / "chatbot.db"
        self.old_db_path = self.data_dir / "chat_sessions.db"
        
        # Memory file paths
        self.seele_json_path = self.data_dir / "seele.json"
        self.persona_txt_path = self.data_dir / "persona_memory.txt"
        self.user_txt_path = self.data_dir / "user_profile.txt"
        
        # Cached status
        self._schema_version: Optional[str] = None
    
    def get_schema_version(self) -> Optional[str]:
        """Get current schema version from database"""
        if self._schema_version is not None:
            return self._schema_version
            
        if not self.new_db_path.exists():
            return None
            
        try:
            conn = sqlite3.connect(str(self.new_db_path))
            cursor = conn.cursor()
            cursor.execute("SELECT value FROM meta WHERE key = 'schema_version'")
            row = cursor.fetchone()
            self._schema_version = row[0] if row else None
            conn.close()
            return self._schema_version
        except sqlite3.OperationalError:
            return None
    
    def has_fts5_tables(self) -> bool:
        """Check if FTS5 tables exist"""
        if not self.new_db_path.exists():
            return False
            
        try:
            conn = sqlite3.connect(str(self.new_db_path))
            cursor = conn.cursor()
            cursor.execute("""
                SELECT name FROM sqlite_master 
                WHERE type='table' AND name IN ('fts_conversations', 'fts_summaries')
            """)
            results = cursor.fetchall()
            conn.close()
            return len(results) == 2
        except Exception:
            return False
    
    def needs_migration(self) -> List[MigrationType]:
        """Detect which migrations are needed"""
        needed = []
        
        # Check if legacy database exists and needs migration
        if self.old_db_path.exists() and not self.new_db_path.exists():
            needed.append(MigrationType.LEGACY_DB)
        
        # Check if text files need conversion
        if (self.persona_txt_path.exists() or self.user_txt_path.exists()) and not self.seele_json_path.exists():
            needed.append(MigrationType.TEXT_TO_JSON)
        
        # Check if database needs schema upgrade
        if self.new_db_path.exists():
            version = self.get_schema_version()
            if version == "2.0" and not self.has_fts5_tables():
                needed.append(MigrationType.FTS5_UPGRADE)
        
        return needed
    
    def print_status(self):
        """Print current migration status"""
        print("\n" + "=" * 70)
        print(f"Migration Status for Profile: {self.profile}")
        print("=" * 70)
        
        print("\nDatabase Status:")
        print(f"  New DB (chatbot.db):     {'✓ Exists' if self.new_db_path.exists() else '✗ Not found'}")
        if self.new_db_path.exists():
            version = self.get_schema_version()
            print(f"  Schema Version:          {version or 'unknown'}")
            print(f"  FTS5 Tables:             {'✓ Present' if self.has_fts5_tables() else '✗ Not found'}")
        
        print(f"  Old DB (chat_sessions):  {'✓ Exists' if self.old_db_path.exists() else '✗ Not found'}")
        
        print("\nMemory Files:")
        print(f"  seele.json:              {'✓ Exists' if self.seele_json_path.exists() else '✗ Not found'}")
        print(f"  persona_memory.txt:      {'✓ Exists' if self.persona_txt_path.exists() else '✗ Not found'}")
        print(f"  user_profile.txt:        {'✓ Exists' if self.user_txt_path.exists() else '✗ Not found'}")
        
        print("\nBackup Status:")
        print(f"  Backup directory:        {'✓ Exists' if self.backup_dir.exists() else '✗ Not found'}")
        
        needed = self.needs_migration()
        if needed:
            print("\n⚠ Migrations Needed:")
            for migration_type in needed:
                print(f"  - {migration_type.value}")
        else:
            print("\n✓ No migrations needed")
        
        print("=" * 70 + "\n")


class Migrator:
    """Main migrator class that orchestrates all migrations"""
    
    def __init__(self, profile: str, auto: bool = False, force: bool = False, no_backup: bool = False):
        self.profile = profile
        self.auto = auto
        self.force = force
        self.no_backup = no_backup
        self.status = MigrationStatus(profile)
        
    def run(self) -> bool:
        """Run migrations"""
        logger.info(f"Starting migration for profile: {self.profile}")
        
        # Print current status
        self.status.print_status()
        
        # Check what needs to be migrated
        needed = self.status.needs_migration()
        
        if not needed and not self.force:
            print("✓ All migrations are up to date!")
            return True
        
        if self.force:
            print("⚠ Force mode enabled - will re-run migrations")
            needed = [MigrationType.FTS5_UPGRADE]  # Default to FTS5 in force mode
        
        # In auto mode, run all needed migrations
        if self.auto:
            return self._run_auto_migrations(needed)
        else:
            return self._run_interactive_migrations(needed)
    
    def _run_auto_migrations(self, needed: List[MigrationType]) -> bool:
        """Run migrations automatically without user interaction"""
        print(f"\n🤖 Auto mode: Running {len(needed)} migration(s)...\n")
        
        # Create backup first
        if not self.no_backup:
            if not self._create_backup():
                logger.error("Backup failed, aborting migration")
                return False
        
        # Run each migration in order
        for migration_type in needed:
            print(f"\n{'='*70}")
            print(f"Running: {migration_type.value}")
            print('='*70)
            
            success = self._run_migration(migration_type)
            if not success:
                logger.error(f"Migration {migration_type.value} failed")
                return False
        
        print("\n" + "="*70)
        print("✓ All migrations completed successfully!")
        print("="*70)
        return True
    
    def _run_interactive_migrations(self, needed: List[MigrationType]) -> bool:
        """Run migrations with user interaction"""
        if not needed:
            print("\n✓ No migrations needed!")
            return True
        
        print(f"\nThe following migrations are available:")
        for i, migration_type in enumerate(needed, 1):
            print(f"  {i}. {migration_type.value}")
        
        print("\nOptions:")
        print("  a - Run all migrations")
        print("  1, 2, 3... - Run specific migration")
        print("  q - Quit")
        
        choice = input("\nYour choice: ").strip().lower()
        
        if choice == 'q':
            print("Migration cancelled")
            return False
        
        # Create backup if running migrations
        if not self.no_backup and choice != 'q':
            print("\n📦 Creating backup...")
            if not self._create_backup():
                logger.error("Backup failed, aborting")
                return False
        
        if choice == 'a':
            # Run all
            for migration_type in needed:
                print(f"\n{'='*70}")
                print(f"Running: {migration_type.value}")
                print('='*70)
                if not self._run_migration(migration_type):
                    return False
            return True
        else:
            # Run specific migration
            try:
                index = int(choice) - 1
                if 0 <= index < len(needed):
                    migration_type = needed[index]
                    print(f"\n{'='*70}")
                    print(f"Running: {migration_type.value}")
                    print('='*70)
                    return self._run_migration(migration_type)
                else:
                    print("Invalid choice")
                    return False
            except ValueError:
                print("Invalid choice")
                return False
    
    def _run_migration(self, migration_type: MigrationType) -> bool:
        """Run a specific migration"""
        try:
            if migration_type == MigrationType.LEGACY_DB:
                return self._migrate_legacy_db()
            elif migration_type == MigrationType.TEXT_TO_JSON:
                return self._migrate_text_to_json()
            elif migration_type == MigrationType.FTS5_UPGRADE:
                return self._migrate_fts5()
            else:
                logger.error(f"Unknown migration type: {migration_type}")
                return False
        except Exception as e:
            logger.error(f"Migration failed: {e}", exc_info=True)
            return False
    
    def _create_backup(self) -> bool:
        """Create backup of existing data"""
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_dir = self.status.data_dir / f"backup_{timestamp}"
            backup_dir.mkdir(parents=True, exist_ok=True)
            
            # Backup new database if exists
            if self.status.new_db_path.exists():
                shutil.copy2(self.status.new_db_path, backup_dir / "chatbot.db")
                logger.info(f"Backed up: chatbot.db")
            
            # Backup old database if exists
            if self.status.old_db_path.exists():
                shutil.copy2(self.status.old_db_path, backup_dir / "chat_sessions.db")
                logger.info(f"Backed up: chat_sessions.db")
            
            # Backup memory files if exist
            if self.status.seele_json_path.exists():
                shutil.copy2(self.status.seele_json_path, backup_dir / "seele.json")
                logger.info(f"Backed up: seele.json")
            
            if self.status.persona_txt_path.exists():
                shutil.copy2(self.status.persona_txt_path, backup_dir / "persona_memory.txt")
                logger.info(f"Backed up: persona_memory.txt")
            
            if self.status.user_txt_path.exists():
                shutil.copy2(self.status.user_txt_path, backup_dir / "user_profile.txt")
                logger.info(f"Backed up: user_profile.txt")
            
            print(f"✓ Backup created at: {backup_dir}")
            return True
            
        except Exception as e:
            logger.error(f"Backup failed: {e}")
            return False
    
    def _migrate_legacy_db(self) -> bool:
        """Migrate from old chat_sessions.db to new chatbot.db"""
        from migration.remigrate import DatabaseRemigrator
        
        print("\n📊 Migrating legacy database...")
        print("  Source: chat_sessions.db")
        print("  Target: chatbot.db\n")
        
        remigrator = DatabaseRemigrator(self.profile)
        return remigrator.migrate()
    
    def _migrate_text_to_json(self) -> bool:
        """Convert text files to seele.json"""
        from migration.converter import convert_txt_to_json
        
        print("\n📝 Converting text files to JSON...")
        print("  Source: persona_memory.txt, user_profile.txt")
        print("  Target: seele.json\n")
        
        # Check if text files exist
        if not self.status.persona_txt_path.exists() and not self.status.user_txt_path.exists():
            logger.warning("No text files found, copying template")
            template_path = Path(__file__).parent.parent / "template" / "seele.json"
            if template_path.exists():
                shutil.copy2(template_path, self.status.seele_json_path)
                print("✓ Copied template seele.json")
                return True
            else:
                logger.error("Template not found")
                return False
        
        try:
            convert_txt_to_json(
                str(self.status.persona_txt_path),
                str(self.status.user_txt_path),
                str(self.status.seele_json_path)
            )
            print("✓ Conversion completed")
            return True
        except Exception as e:
            logger.error(f"Text conversion failed: {e}")
            return False
    
    def _migrate_fts5(self) -> bool:
        """Add FTS5 tables to existing database"""
        print("\n🔍 Adding FTS5 full-text search tables...")
        print("  Schema: v2.0 -> v3.0\n")
        
        if not self.status.new_db_path.exists():
            logger.error("Database not found, cannot add FTS5 tables")
            return False
        
        try:
            conn = sqlite3.connect(str(self.status.new_db_path))
            conn.row_factory = sqlite3.Row
            
            # Load sqlite-vec if available
            try:
                import sqlite_vec
                conn.enable_load_extension(True)
                conn.load_extension(sqlite_vec.loadable_path())
            except Exception as e:
                logger.warning(f"Could not load sqlite-vec: {e}")
            
            cursor = conn.cursor()
            
            # Create FTS5 tables
            print("Creating FTS5 virtual tables...")
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
            
            # Create triggers
            print("Creating triggers...")
            
            # Conversations triggers
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
            
            # Summaries triggers
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
            
            # Backfill existing data
            print("Backfilling existing data...")
            
            cursor.execute("SELECT COUNT(*) FROM conversations")
            conv_count = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM summaries")
            summary_count = cursor.fetchone()[0]
            
            print(f"Found {conv_count} conversations and {summary_count} summaries")
            
            if conv_count > 0:
                cursor.execute("""
                    INSERT INTO fts_conversations(rowid, conversation_id, text)
                    SELECT conversation_id, conversation_id, text FROM conversations
                """)
                print(f"✓ Backfilled {conv_count} conversations")
            
            if summary_count > 0:
                cursor.execute("""
                    INSERT INTO fts_summaries(rowid, summary_id, summary)
                    SELECT summary_id, summary_id, summary FROM summaries
                """)
                print(f"✓ Backfilled {summary_count} summaries")
            
            # Update schema version
            cursor.execute("""
                INSERT OR REPLACE INTO meta (key, value) VALUES ('schema_version', '3.0')
            """)
            
            conn.commit()
            conn.close()
            
            print("✓ FTS5 migration completed")
            print("\nYou can now use advanced search with:")
            print("  - Boolean operators: AND, OR, NOT")
            print("  - Exact phrases: \"phrase\"")
            print("  - Role filters: role='user' or 'assistant'")
            
            return True
            
        except Exception as e:
            logger.error(f"FTS5 migration failed: {e}")
            if 'conn' in locals():
                conn.rollback()
                conn.close()
            return False


def main():
    """Main entry point"""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Unified migration tool for Seelenmaschine",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python migration/migrator.py test                    # Interactive mode
  python migration/migrator.py test --auto             # Auto-detect and migrate
  python migration/migrator.py test --force            # Force migration
  python migration/migrator.py test --no-backup        # Skip backup (not recommended)
        """
    )
    
    parser.add_argument("profile", help="Profile name (e.g., 'test', 'hy')")
    parser.add_argument("--auto", action="store_true", help="Automatically run all needed migrations")
    parser.add_argument("--force", action="store_true", help="Force migration even if already done")
    parser.add_argument("--no-backup", action="store_true", help="Skip backup creation (not recommended)")
    
    args = parser.parse_args()
    
    # Create migrator and run
    migrator = Migrator(
        profile=args.profile,
        auto=args.auto,
        force=args.force,
        no_backup=args.no_backup
    )
    
    success = migrator.run()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
