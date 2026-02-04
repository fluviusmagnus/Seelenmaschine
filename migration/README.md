# 数据迁移工具

[English](README_EN.md) | 中文

本目录包含 Seelenmaschine 的数据迁移工具，用于将旧版本的数据（Legacy Database 和 Text Profiles）升级到最新的 3.1 版本。

## 统一迁移工具 (`migrate.py`)

`migration/migrate.py` 是现在推荐使用的统一迁移工具。它会自动检测并执行所需的迁移任务。

### 主要功能

1.  **自动检测源文件**：自动在 `data/<profile>/` 或 `data/<profile>/backup/` 中查找旧数据。
2.  **文本转 JSON**：利用 LLM 将旧的 `persona_memory.txt` 和 `user_profile.txt` 转换为新的 `seele.json` 格式。
3.  **数据库迁移**：将旧的 `chat_sessions.db` 迁移到新的 `chatbot.db`，并应用 3.1 版本的最新 Schema（支持 FTS5 全文搜索等）。
4.  **自动备份**：在修改前会自动将现有数据备份到 `migration_backup_YYYYMMDD_HHMMSS` 目录。

### 如何使用

例如对于 `test.env` 配置文件，在按最新要求重新设置环境变量后，你可以通过以下命令运行迁移：

```bash
# 迁移特定配置文件 (例如 test)
python migration/migrate.py test
```

或者使用项目根目录下的快捷脚本：

```bash
# Linux/macOS
./migrate.sh test

# Windows
migrate.bat test
```

## 验证迁移

迁移完成后，可以通过以下步骤验证：

1.  **检查数据库版本**：
    ```bash
    sqlite3 data/<profile>/chatbot.db "SELECT value FROM meta WHERE key='schema_version';"
    # 应输出: 3.1
    ```

2.  **检查全文搜索表**：
    ```bash
    sqlite3 data/<profile>/chatbot.db "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'fts_%';"
    # 应输出:
    # fts_conversations
    # fts_summaries
    ```

3.  **检查数据**：
    使用 SQLite 查看器检查 `conversations` 和 `summaries` 表，确认历史记录已成功搬迁。

## 备份与恢复

虽然迁移工具会自动创建备份，但我们仍建议在操作前手动备份 `data/<profile>/` 目录。如果迁移失败，你可以从生成的备份目录中恢复文件。

## 下拉菜单 (旧文档参考)

- [MIGRATION_GUIDE.md](../MIGRATION_GUIDE.md) (已删除，其内容已整合至此)
- [README.md](../README.md) - 项目主说明文档
