# Data Migration Tool

[中文](README.md)

This directory contains Seelenmaschine's data migration tool for upgrading old version data (Legacy Database and Text Profiles) to the latest version 3.1.

## Unified Migration Tool (`migrate.py`)

`migration/migrate.py` is the now-recommended unified migration tool. It automatically detects and executes required migration tasks.

### Main Features

1.  **Automatic source file detection**: Automatically finds old data in `data/<profile>/` or `data/<profile>/backup/`.
2.  **Text to JSON**: Uses LLM to convert old `persona_memory.txt` and `user_profile.txt` to the new `seele.json` format.
3.  **Database migration**: Migrates old `chat_sessions.db` to the new `chatbot.db` and applies the latest version 3.1 Schema (supports FTS5 full-text search, etc.).
4.  **Automatic backup**: Automatically backs up existing data to the `migration_backup_YYYYMMDD_HHMMSS` directory before modification.

### How to Use

For example, for the `test.env` configuration file, after reconfiguring environment variables according to the latest requirements, you can run the migration with the following command:

```bash
# Migrate specific profile (e.g., test)
python migration/migrate.py test
```

Or use the quick script in the project root directory:

```bash
# Linux/macOS
./migrate.sh test

# Windows
migrate.bat test
```

## Verify Migration

After migration is complete, you can verify with the following steps:

1.  **Check database version**:
    ```bash
    sqlite3 data/<profile>/chatbot.db "SELECT value FROM meta WHERE key='schema_version';"
    # Should output: 3.1
    ```

2.  **Check full-text search tables**:
    ```bash
    sqlite3 data/<profile>/chatbot.db "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'fts_%';"
    # Should output:
    # fts_conversations
    # fts_summaries
    ```

3.  **Check data**:
    Use an SQLite viewer to check the `conversations` and `summaries` tables to confirm historical records have been successfully migrated.

## Backup and Recovery

Although the migration tool automatically creates backups, we still recommend manually backing up the `data/<profile>/` directory before operations. If migration fails, you can restore files from the generated backup directory.

## Dropdown Menu (Old Document Reference)

- [MIGRATION_GUIDE.md](../MIGRATION_GUIDE.md) (Deleted, content integrated here)
- [README_EN.md](../README_EN.md) - Main project documentation
