# Database Migration Guide

本指南介绍如何使用 Seelenmaschine 的统一迁移工具来升级数据库和数据文件。

---

## 统一迁移工具

Seelenmaschine 提供了一个统一的迁移工具 `migration/migrator.py`，可以自动检测并执行所需的迁移。

### 快速开始

```bash
# 检查迁移状态并交互式运行
python migration/migrator.py <profile>

# 自动检测并运行所有需要的迁移
python migration/migrator.py <profile> --auto

# 强制重新运行迁移（如FTS5升级）
python migration/migrator.py <profile> --force

# 跳过自动备份（不推荐）
python migration/migrator.py <profile> --no-backup
```

### 示例

```bash
# 交互式迁移 test 配置文件
python migration/migrator.py test

# 自动迁移 hy 配置文件
python migration/migrator.py hy --auto
```

---

## 迁移类型

统一迁移工具可以处理以下类型的迁移：

### 1. FTS5 全文搜索升级 (v2.0 → v3.0)

**何时需要：** 当你的数据库版本为 2.0 但缺少 FTS5 表时

**错误提示：**
```
ERROR | core.database:search_summaries_by_keyword:738 - Summary search failed: no such table: fts_summaries
ERROR | core.database:search_conversations_by_keyword:651 - Conversation search failed: no such table: fts_conversations
```

**迁移内容：**
- 创建 `fts_conversations` 和 `fts_summaries` 虚拟表
- 创建自动同步触发器（INSERT/UPDATE/DELETE）
- 回填所有现有的对话和摘要数据
- 更新 schema 版本到 3.0

### 2. 旧数据库迁移 (chat_sessions.db → chatbot.db)

**何时需要：** 当你有旧的 `chat_sessions.db` 但没有新的 `chatbot.db` 时

**迁移内容：**
- 创建新数据库结构
- 迁移 sessions 表数据
- 迁移 conversations 表数据
- 迁移 summaries 表数据
- 重新映射 session_id

### 3. 文本文件转 JSON (txt → seele.json)

**何时需要：** 当你有 `persona_memory.txt` 或 `user_profile.txt` 但没有 `seele.json` 时

**迁移内容：**
- 解析 `persona_memory.txt` 并转换为结构化 JSON
- 解析 `user_profile.txt` 并转换为结构化 JSON
- 生成完整的 `seele.json` 文件
- 如果源文件不存在，从模板复制

---

## 使用统一迁移工具

### 步骤 1: 检查状态

运行迁移工具查看当前状态：

```bash
python migration/migrator.py test
```

输出示例：

```
======================================================================
Migration Status for Profile: test
======================================================================

Database Status:
  New DB (chatbot.db):     ✓ Exists
  Schema Version:          2.0
  FTS5 Tables:             ✗ Not found
  Old DB (chat_sessions):  ✗ Not found

Memory Files:
  seele.json:              ✓ Exists
  persona_memory.txt:      ✗ Not found
  user_profile.txt:        ✗ Not found

Backup Status:
  Backup directory:        ✓ Exists

⚠ Migrations Needed:
  - fts5_upgrade

======================================================================
```

### 步骤 2: 运行迁移

根据检测到的迁移需求，选择运行方式：

#### 交互式模式（推荐新手）

```bash
python migration/migrator.py test
```

工具会显示可用的迁移选项：

```
The following migrations are available:
  1. fts5_upgrade

Options:
  a - Run all migrations
  1, 2, 3... - Run specific migration
  q - Quit

Your choice: a
```

#### 自动模式（推荐熟悉用户）

```bash
python migration/migrator.py test --auto
```

工具会自动运行所有需要的迁移，无需交互。

### 步骤 3: 验证迁移

迁移完成后，再次运行工具检查状态：

```bash
python migration/migrator.py test
```

应该看到：

```
✓ No migrations needed
```

---

## 备份和恢复

### 自动备份

默认情况下，迁移工具会在执行迁移前自动创建备份：

```
📦 Creating backup...
✓ Backup created at: data/test/backup_20260128_143025
```

备份包含：
- `chatbot.db` (如果存在)
- `chat_sessions.db` (如果存在)
- `seele.json` (如果存在)
- `persona_memory.txt` (如果存在)
- `user_profile.txt` (如果存在)

### 手动恢复

如果迁移失败或需要回滚：

```bash
# 找到最新的备份目录
ls -lt data/<profile>/backup_*

# 恢复数据库
cp data/<profile>/backup_20260128_143025/chatbot.db data/<profile>/chatbot.db

# 恢复内存文件
cp data/<profile>/backup_20260128_143025/seele.json data/<profile>/seele.json
```

### 跳过备份（不推荐）

如果你确定不需要备份（例如测试环境），可以使用 `--no-backup` 选项：

```bash
python migration/migrator.py test --auto --no-backup
```

---

## 迁移脚本详解

### FTS5 升级

FTS5 升级会做以下操作：

1. **创建 FTS5 虚拟表**
   ```sql
   CREATE VIRTUAL TABLE fts_conversations USING fts5(
       conversation_id UNINDEXED,
       text,
       content=conversations,
       content_rowid=conversation_id
   );
   ```

2. **创建触发器**
   - INSERT 触发器：新记录自动加入 FTS5
   - UPDATE 触发器：更新时同步 FTS5
   - DELETE 触发器：删除时同步 FTS5

3. **回填现有数据**
   - 将所有现有的 conversations 导入 FTS5
   - 将所有现有的 summaries 导入 FTS5

4. **更新版本**
   - Schema version: 2.0 → 3.0

### 旧数据库迁移

旧数据库迁移会做以下操作：

1. **创建新数据库结构**
   - 按照 BREAKING.md 中定义的新 schema
   - 包含所有索引和约束

2. **迁移数据**
   - Sessions: 复制所有会话记录
   - Conversations: 复制所有对话，重新映射 session_id
   - Summaries: 复制所有摘要，重新映射 session_id

### 文本到 JSON 转换

文本到 JSON 转换会做以下操作：

1. **解析文本文件**
   - 识别各个章节（基础信息、性格观念等）
   - 提取结构化数据

2. **生成 JSON**
   - 填充 `bot` 字段（从 persona_memory.txt）
   - 填充 `user` 字段（从 user_profile.txt）
   - 初始化空的 `memorable_events` 和 `commands_and_agreements`

---

## 常见问题

### Q: 迁移会删除我的数据吗？

**A**: 不会！迁移只添加新表、触发器或转换格式，不会删除现有数据。而且默认会自动备份。

### Q: 迁移失败了怎么办？

**A**: 
1. 检查错误信息
2. 从最新备份恢复：
   ```bash
   cp data/<profile>/backup_YYYYMMDD_HHMMSS/chatbot.db data/<profile>/chatbot.db
   ```
3. 如果问题持续，请提交 issue 并附上错误日志

### Q: 可以重复运行迁移吗？

**A**: 
- 正常情况：工具会检测已完成的迁移，不会重复运行
- 使用 `--force`: 可以强制重新运行迁移（例如重新生成 FTS5 表）

### Q: 迁移需要多长时间？

**A**: 取决于数据量：
- < 1000 条记录：几秒钟
- 1000-10000 条：几十秒到一分钟
- > 10000 条：可能需要几分钟

### Q: 新数据库还需要迁移吗？

**A**: 不需要！新创建的数据库已经包含最新的 schema（包括 FTS5）。只有旧数据库才需要迁移。

### Q: 如何验证 FTS5 功能正常？

**A**: 运行以下命令检查：

```bash
sqlite3 data/<profile>/chatbot.db "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'fts_%';"
```

应该看到：
```
fts_conversations
fts_summaries
```

测试搜索功能：

```bash
sqlite3 data/<profile>/chatbot.db
```

```sql
-- 搜索包含特定词的对话
SELECT conversation_id, text 
FROM fts_conversations 
WHERE text MATCH 'keyword' 
LIMIT 5;
```

---

## 数据库版本历史

| 版本 | 功能 | 创建时间 |
|------|------|---------|
| 1.0 | 初始版本 | - |
| 2.0 | 添加 vec0 向量搜索 | - |
| **3.0** | 添加 FTS5 全文搜索 | 2026-01-28 |

---

## 旧迁移脚本（已弃用）

以下脚本仍然可用，但建议使用新的统一迁移工具：

- `migrate_add_fts5.py` - 仅 FTS5 升级（已整合到 `migrator.py`）
- `migration/migrate.py` - 旧版迁移脚本（已整合到 `migrator.py`）
- `migration/remigrate.py` - 旧数据库迁移（已整合到 `migrator.py`）

---

## 高级用法

### 仅检查状态不迁移

```bash
python migration/migrator.py test
# 然后选择 'q' 退出
```

### 强制重建 FTS5 表

```bash
python migration/migrator.py test --force
```

### 批量迁移多个配置文件

```bash
for profile in test hy prod; do
    echo "Migrating $profile..."
    python migration/migrator.py $profile --auto
done
```

---

## 迁移后的新功能

### FTS5 全文搜索

迁移到 v3.0 后，可以使用高级搜索功能：

```python
# 在代码中使用
db.search_conversations_by_keyword(
    query="Anna AND movie",
    role="user",
    limit=10
)

# 布尔运算符
"Anna AND movie"        # 同时包含
"movie OR music"        # 包含任一
"Anna NOT John"         # 包含 Anna 但不包含 John

# 精确短语
'"artificial intelligence"'  # 精确匹配短语

# 角色过滤
role="user"           # 仅搜索用户消息
role="assistant"      # 仅搜索助手回复
```

通过 LLM 工具使用：

```
你能搜索一下我们之前聊过的关于 Anna 和电影的内容吗？
```

---

## 遇到问题？

如果迁移失败或遇到问题：

1. **检查日志输出** - 查看详细错误信息
2. **确认备份存在** - 检查 `data/<profile>/backup_*` 目录
3. **尝试恢复备份** - 使用上述恢复命令
4. **提交 issue**，包含：
   - 完整的错误信息
   - Schema 版本（`SELECT * FROM meta`）
   - 记录数量
   - 使用的命令

---

## 开发者信息

### 添加新的迁移类型

如果需要添加新的迁移类型，编辑 `migration/migrator.py`：

1. 在 `MigrationType` 枚举中添加新类型
2. 在 `MigrationStatus.needs_migration()` 中添加检测逻辑
3. 在 `Migrator._run_migration()` 中添加执行逻辑
4. 实现迁移函数

### 测试迁移

```bash
# 创建测试配置文件
mkdir -p data/test_migration

# 复制旧数据
cp data/old_profile/chat_sessions.db data/test_migration/

# 运行迁移
python migration/migrator.py test_migration --auto

# 验证结果
python migration/migrator.py test_migration
```

---

## 总结

使用统一迁移工具的推荐流程：

1. **备份重要数据**（工具会自动备份，但手动备份更安全）
2. **检查状态** - `python migration/migrator.py <profile>`
3. **运行迁移** - 交互式或使用 `--auto`
4. **验证结果** - 再次检查状态
5. **测试功能** - 启动应用确认一切正常

如有问题，随时查看备份目录并恢复数据。
