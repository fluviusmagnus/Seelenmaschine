# Seelenmaschine Migration Tools

This directory contains migration tools for upgrading Seelenmaschine databases and data files.

## Quick Start

Use the unified migration tool:

```bash
# Check migration status
python migration/migrator.py <profile>

# Auto-detect and migrate
python migration/migrator.py <profile> --auto

# Force re-run migration
python migration/migrator.py <profile> --force
```

## Files

- **migrator.py** - Unified migration tool (recommended)
- **migrate.py** - Legacy v2 migration (deprecated, use migrator.py)
- **remigrate.py** - Legacy database migration (deprecated, use migrator.py)
- **converter.py** - Text to JSON converter (used by migrator.py)

## Migration Types

### 1. FTS5 Upgrade (Schema v2.0 → v3.0)

Adds full-text search capabilities:
- Creates FTS5 virtual tables
- Creates auto-sync triggers
- Backfills existing data

### 2. Legacy Database Migration

Migrates from old `chat_sessions.db` to new `chatbot.db`:
- Creates new schema
- Migrates sessions, conversations, summaries
- Remaps session IDs

### 3. Text to JSON Conversion

Converts old text files to structured JSON:
- `persona_memory.txt` → `seele.json["bot"]`
- `user_profile.txt` → `seele.json["user"]`

## Usage Examples

### Interactive Mode

```bash
# Run with interactive prompts
python migration/migrator.py test

# Output:
# Migration Status for Profile: test
# ...
# ⚠ Migrations Needed:
#   - fts5_upgrade
# 
# Options:
#   a - Run all migrations
#   1, 2, 3... - Run specific migration
#   q - Quit
```

### Automatic Mode

```bash
# Auto-detect and run all needed migrations
python migration/migrator.py test --auto

# Output:
# 🤖 Auto mode: Running 1 migration(s)...
# 📦 Creating backup...
# ✓ Backup created at: data/test/backup_20260128_143025
# ...
# ✓ All migrations completed successfully!
```

### Force Mode

```bash
# Force re-run migration even if already done
python migration/migrator.py test --force
```

### Skip Backup (Not Recommended)

```bash
# Skip automatic backup creation
python migration/migrator.py test --auto --no-backup
```

## Backup and Recovery

### Automatic Backups

By default, the migration tool creates automatic backups:

```
data/<profile>/backup_20260128_143025/
├── chatbot.db
├── chat_sessions.db
├── seele.json
├── persona_memory.txt
└── user_profile.txt
```

### Manual Recovery

```bash
# Find latest backup
ls -lt data/<profile>/backup_*

# Restore database
cp data/<profile>/backup_YYYYMMDD_HHMMSS/chatbot.db data/<profile>/chatbot.db

# Restore memory files
cp data/<profile>/backup_YYYYMMDD_HHMMSS/seele.json data/<profile>/seele.json
```

## Validation

After migration, verify the results:

```bash
# Check migration status again
python migration/migrator.py <profile>

# Expected output:
# ✓ No migrations needed

# Verify FTS5 tables
sqlite3 data/<profile>/chatbot.db \
  "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'fts_%';"

# Expected output:
# fts_conversations
# fts_summaries
```

## Troubleshooting

### Migration Failed

1. Check error message in output
2. Restore from backup:
   ```bash
   cp data/<profile>/backup_*/chatbot.db data/<profile>/chatbot.db
   ```
3. Re-run with `--force` if needed
4. Report issue with error log

### FTS5 Tables Not Created

```bash
# Force re-run FTS5 migration
python migration/migrator.py <profile> --force
```

### Missing Dependencies

```bash
# Install required packages
pip install -r requirements.txt

# Ensure sqlite-vec is available
python -c "import sqlite_vec; print(sqlite_vec.loadable_path())"
```

## Development

### Adding New Migration Types

1. Add to `MigrationType` enum in `migrator.py`
2. Implement detection in `MigrationStatus.needs_migration()`
3. Implement execution in `Migrator._run_migration()`
4. Update documentation

### Testing

```bash
# Create test profile
mkdir -p data/test_migration

# Run migration
python migration/migrator.py test_migration --auto

# Verify
python migration/migrator.py test_migration
```

## See Also

- [MIGRATION_GUIDE.md](../MIGRATION_GUIDE.md) - Detailed migration guide
- [BREAKING.md](../BREAKING.md) - Breaking changes and upgrade plan
- [README.md](../README.md) - Main project README
