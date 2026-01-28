# 大版本升级计划

本项目需要进行大版本升级，因此，可以接受大规模重写项目代码。本次升级的宏观要求有：

1. 旧代码只有参考意义，建议直接重写，然后删除旧代码
2. 升级、减少依赖库，使项目现代化
3. 注重模块化设计，必要时重构，添加可靠的单元测试（（不浪费真实的LLM调用），以及方便的debug手段
4. 提供旧数据的迁移工具
5. 更新文档，删除不必要的文档
6. 旧有的提示词很有价值，可以考虑复用
7. 在时和区时间戳问题上非常robust

为此，本计划中如有与旧代码和旧文档中不一致的地方，应以本计划为准。

## 技术栈选择

### 核心依赖
- **Python**: 3.11+
- **数据库**: SQLite + sqlite-vec（向量扩展）
- **Web框架**: python-telegram-bot（替代 Flask）
- **异步**: asyncio（核心机制）
- **测试**: pytest（+ pytest-asyncio + pytest-cov）
- **日志**: loguru（替代标准 logging）

### 移除的依赖
- lancedb（改用 sqlite-vec）
- flask（改用 Telegram）
- flask-socketio

## 主要变更

### 用户界面

取消CLI界面和Flask网页界面，专注于实现Telegram的Bot，因此也需要考虑输出格式的限制（**Telegram Markdown v2**）。由于模块化设计，保留未来加入其他协议的可能，例如Discord。

### 数据库一体化

使用带有向量功能的sqlite（sqlite-vec），不再额外用lancedb储存数据。重新设计数据库应确认schema的合理性。

#### 数据库 Schema 设计

```sql
-- =============================================================================
-- 元数据表（用于版本控制）
-- =============================================================================
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- 插入初始 schema 版本
INSERT OR IGNORE INTO meta (key, value) VALUES ('schema_version', '2.0');

-- =============================================================================
-- 向量表（使用 sqlite-vec，向量与 conversation_id/summary_id 绑定）
-- =============================================================================
CREATE VIRTUAL TABLE IF NOT EXISTS vec_conversations USING vec0(
    conversation_id INTEGER PRIMARY KEY,
    embedding(float32, EMBEDDING_DIMENSION)
);

CREATE VIRTUAL TABLE IF NOT EXISTS vec_summaries USING vec0(
    summary_id INTEGER PRIMARY KEY,
    embedding(float32, EMBEDDING_DIMENSION)
);

-- =============================================================================
-- 会话表
-- =============================================================================
CREATE TABLE IF IF NOT EXISTS sessions (
    session_id INTEGER PRIMARY KEY AUTOINCREMENT,
    start_timestamp INTEGER NOT NULL,
    end_timestamp INTEGER,  -- NULL 表示活跃会话
    status TEXT CHECK(status IN ('active', 'archived')) DEFAULT 'active'
);

-- 索引
CREATE INDEX IF NOT EXISTS idx_sessions_status ON sessions(status);

-- =============================================================================
-- 对话表
-- =============================================================================
CREATE TABLE IF NOT EXISTS conversations (
    conversation_id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL,
    timestamp INTEGER NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
    text TEXT NOT NULL,
    FOREIGN KEY(session_id) REFERENCES sessions(session_id)
);

-- 索引
CREATE INDEX IF NOT EXISTS idx_conversations_session ON conversations(session_id);
CREATE INDEX IF NOT EXISTS idx_conversations_timestamp ON conversations(timestamp DESC);

-- =============================================================================
-- 摘要表
-- =============================================================================
CREATE TABLE IF NOT EXISTS summaries (
    summary_id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL,
    summary TEXT NOT NULL,
    first_timestamp INTEGER NOT NULL,  -- 该摘要首条消息的时间戳
    last_timestamp INTEGER NOT NULL,   -- 该摘要末条消息的时间戳
    FOREIGN KEY(session_id) REFERENCES sessions(session_id)
);

-- 索引
CREATE INDEX IF NOT EXISTS idx_summaries_session ON summaries(session_id);
CREATE INDEX IF NOT EXISTS idx_summaries_last_timestamp ON summaries(last_timestamp DESC);

-- =============================================================================
-- 定时任务表
-- =============================================================================
CREATE TABLE IF NOT EXISTS scheduled_tasks (
    task_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    trigger_type TEXT NOT NULL CHECK(trigger_type IN ('once', 'interval')),
    trigger_config TEXT NOT NULL,  -- JSON: {"timestamp": 123, "interval": 3600}
    message TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    next_run_at INTEGER NOT NULL,
    last_run_at INTEGER,
    status TEXT CHECK(status IN ('active', 'paused', 'completed')) DEFAULT 'active'
);

-- 索引
CREATE INDEX IF NOT EXISTS idx_scheduled_tasks_next_run ON scheduled_tasks(next_run_at, status);
```

#### 时区处理区略



- 所有时间戳存储为 UTC Unix timestamp（INTEGER）
- 显示时根据 `TIMEZONE` 配置转换为本地区
- 使用 Python `zoneinfo` 处理时区转换
- 所有时间相关的比较和查询使用 UTC 时间戳，确保时区无关性

### 记忆机制

#### 短期记忆

Session 是手动管理的会话单元，用户通过命令控制：
- `/new`：总结当前会话，归档为 archived 状态，创建新 session
- `/reset`：删除当前 session 及其所有对话和摘要

当前 session 的对话保持在 context window 中（最近12条消息）。当对话积累到24条时，自动总结较早的12条为摘要并移出 context window。发送提示词时，保留2条最近的 summary。

**配置参数：**
- `NEW_SESSION_COMMAND`: /new（新建会话命令）
- `RESET_SESSION_COMMAND`: /reset（重置会话命令）
- `CONTEXT_WINDOW_KEEP_MIN`: 12（最少保留的消息数）
- `CONTEXT_WINDOW_TRIGGER_SUMMARY`: 24（触发总结的消息数）
- `RECENT_SUMMARIES_MAX`: 3（提示词中保留的最近摘要数）

#### 中期记忆

所有的对话和摘要都会被向量化存入数据库，对话还要储存时间戳，摘要则储存其中首条和末条信息的时间戳。召回时应使用Embedding模型和Rerank模型，遵循以下逻辑：

1. 首先分别向量化最近一条bot消息（已经向量化则可以从内存或数据库中读取）和用户输入消息。分别找到最多3条相关摘要（不包含加入提示词中的最近的3条摘要），然后在对应的摘要中，分别找到最多4条相关消息。现在，一共得到最多6条摘要和24条消息。
2. 以用户输入为判断标准，使用Rerank模型找出最有用的3条摘要和6条消息。
3. 给这些相关信息加上由时间戳人类可读的时间（基于 TIMEZONE 配置），最终成为提示词的一部分。

**配置参数：**
- `RECALL_SUMMARY_PER_QUERY`: 3（每个查询召回的摘要数）
- `RECALL_CONV_PER_SUMMARY`: 4（每个摘要召回的对话数）
- `RERANK_TOP_SUMMARIES`: 3（Rerank后保留的摘要数）
- `RERANK_TOP_CONVS`: 6（Rerank后保留的对话数）

如果没有Rerank，也应按相似度缩减召回数量到最大值3和6。

#### 长期记忆

始终是提示词的一部分。长期记忆以结构化 JSON 格式存储在 `seele.json` 文件中，**直接嵌入**到系统提示词中。

每次生成新摘要的同时，还应用那12条信息生成一个 JSON Patch，用于更新 `seele.json`。

**重要：系统提示词中嵌入的 `seele.json` 必须总是更新过的最新版本。通过内存缓存机制实现：`update_seele_json()` 同时更新缓存和磁盘，`load_seele_json()` 从缓存读取以保证一致性。**

#### seele.json 结构

`seele.json` 是合并后的bot人格和用户记忆，结构如下：

```json
{
    "bot": {
        "name": "Seelenmaschine",
        "gender": "neutral",
        "birthday": "2025-02-15",
        "role": "AI assistant",
        "appearance": "",
        "likes": [],
        "dislikes": [],
        "language_style": {
            "description": "concise and helpful",
            "examples": []
        },
        "personality": {
            "mbti": "",
            "description": "",
            "worldview_and_values": ""
        },
        "emotions_and_needs": {
            "long_term": "",
            "short_term": ""
        },
        "relationship_with_user": ""
    },
    "user": {
        "name": "",
        "gender": "",
        "birthday": "",
        "personal_facts": [],
        "abilities": [],
        "likes": [],
        "dislikes": [],
        "personality": {
            "mbti": "",
            "description": "",
            "worldview_and_values": ""
        },
        "emotions_and_needs": {
            "long_term": "",
            "short_term": ""
        }
    },
    "memorable_events": [
        {
            "time": "",
            "details": ""
        }
    ],
    "commands_and_agreements": []
}
```

### 工具能力

具备接入MCP和Skills的能力。

#### MCP (Model Context Protocol)

保留原有的MCP客户端能力，与Skills系统并行。

#### Skills 独立插件系统

设计独立的Skills插件系统，作为本地工具集：

**Skills 目录结构：**
```
skills/
  ├── __init__.py
  ├── base_skill.py
  ├── time_skill.py
  ├── weather_skill.py
  └── ...
```

**Skill 接口规范：**
```python
class BaseSkill:
    @property
    def name(self) -> str: ...
    @property
    def description(self) -> str: ...
    @property
    def parameters(self) -> dict: ...
    async def execute(self, **kwargs) -> str: ...
```

Skills注册机制：系统启动时自动发现并加载加载skills目录中的插件。

#### 定时任务

内置定时任务能力，支持两种触发方式：

1. **一次性任务**：在指定时间点执行
2. **间隔任务**：每隔指定秒数执行

任务存储在数据库 `scheduled_tasks` 表中，通过后台异步任务调度器执行。

**配置参数：**
- `SCHEDULED_TASKS_CONFIG_PATH`: `scheduled_tasks.json`（预设任务配置）

#### 自我查询记忆能力

内置工具 `search_memories(query, limit)`，允许LLM主动查询自己的记忆数据库。

**设计特点：**
- 统一查询工具，同时检索摘要和对话
- 使用简单标志位（全局变量）禁用工具，防止递归调用
- 在生成响应时禁用此工具
- 使用单独的工具调用上下文

## 项目结构

```
Seelenmaschine/
├── src/                          # 源代码目录
│   ├── main.py                   # Telegram Bot 入口
│   ├── config.py                 # 配置管理
│   ├── core/                     # 核心模块
│   │   ├── __init__.py
│   │   ├── database.py           # 数据库管理（sqlite-vec）
│   │   ├── memory.py             # 记忆系统（短期/中期/长期）
│   │   ├── context.py            # Context Window 管理
│   │   ├── retriever.py          # 记忆检索（Embedding + Rerank）
│   │   └── scheduler.py          # 定时任务调度器
│   ├── llm/                      # LLM 模块
│   │   ├── __init__.py
│   │   ├── client.py             # LLM 客户端
│   │   ├── embedding.py          # Embedding 客户端
│   │   └── reranker.py           # Rerank 客户端
│   ├── tools/                    # 工具系统
│   │   ├── __init__.py
│   │   ├── mcp_client.py         # MCP 客户端
│   │   ├── skill_manager.py      # Skills 管理器
│   │   ├── memory_search.py      # 自我查询工具
│   │   └── internal/             # 内置工具
│   ├── telegram/                 # Telegram 界面
│   │   ├── __init__.py
│   │   ├── bot.py                # Telegram Bot 主逻辑
│   │   └── handlers.py           # 消息处理器
│   ├── prompts/                  # 提示词
│   │   ├── __init__.py
│   │   ├── system.py             # 系统提示词
│   │   ├── summary.py            # 总结提示词
│   │   └── memory_update.py      # 记忆更新提示词（JSON Patch）
│   └── utils/                    # 工具函数
│       ├── __init__.py
│       ├── time.py               # 时间处理
│       └── logger.py             # 日志工具
├── skills/                        # Skills 插件
│   ├── __init__.py
│   ├── base_skill.py
│   └── ...
├── template/                      # 模板目录
│   └── seele.json                # 长期记忆模板
├── tests/                         # 单元测试
│   ├── __init__.py
│   ├── conftest.py               # pytest 配置
│   ├── test_database.py
│   ├── test_memory.py
│   ├── test_retriever.py
│   └── test_llm.py
├── migration/                      # 数据迁移工具
│   ├── __init__.py
│   ├── migrate.py                # 主迁移脚本
│   └── converter.py              # 旧数据转换（txt → json）
├── data/                          # 数据存储目录
│   └── <profile>/
│       ├── seele.json            # 人格和用户记忆
│       ├── chatbot.db            # SQLite 数据库
│       └── scheduled_tasks.json  # 预设任务
├── requirements.txt              # Python 依赖
├── requirements-dev.txt          # 开发依赖（pytest等）
├── <profile>.env                  # 环境配置（示例）
├── .env.example                   # 配置示例
├── AGENTS.md                      # AI 辅助开发指南
├── BREAKING.md                    # 本升级计划
├── README.md                      # 项目说明
└── LICENSE                        # 许可证
```

## 数据迁移工具

### 迁移范围

1. **人格记忆**: `persona_memory.txt` → `seele.json["bot"]`（需要转换）
2. **用户档案**: `user_profile.txt` → `seele.json["user"]`（需要转换）
3. **对话数据**: `lancedb/conversations` + `sqlite conversations` → 新数据库
4. **摘要数据**: `lancedb/summaries` + `sqlite summaries` → 新数据库

### 自由文本转换逻辑

`converter.py` 负责将旧的自由文本格式转换为新的结构化 JSON：

- `persona_memory.txt` → 解析并填充到 `seele.json["bot"]` 的各个字段
- `user_profile.txt` → 解析并填充到 `seele.json["user"]` 的各个字段

### 迁移步骤

1. 运行 `python migration/migrate.py <profile>`
2. 脚本自动读取旧数据
3. 转换为新格式（包括文本 → JSON 转换）
4. 写入新数据库和 `seele.json`
5. 验证数据完整性

### 回滚机制

迁移前自动备份旧数据到 `data/<profile>/backup/`。

## 单元测试区略

### 测试原则

- 不浪费真实的 LLM 调用
- 使用 Mock 对象模拟 LLM 响应
- 重点测试逻辑、数据处理、数据库操作

### 测试覆盖

- `test_database.py`: 数据库CRUD操作、向量查询
- `test_memory.py`: 记忆管理逻辑、context window 机制
- `test_retriever.py`: 检索逻辑、排序逻辑
- `test_llm.py`: 提示词构建、工具调用

### Mock 数据

使用 pytest fixture 提供标准的测试数据和 Mock 对象。

## Debug 手段

### 日志系统

使用 loguru 替代标准 logging，提供：
- 彩色输出
- 结构化日志
- 自动日志轮转
- 不同级别（DEBUG/INFO/WARNING/ERROR）

### Debug 配置

```ini
# .env
DEBUG_MODE=true
DEBUG_LOG_LEVEL=DEBUG
DEBUG_LOG_FILE=debug.log
DEBUG_SHOW_FULL_PROMPT=true
DEBUG_LOG_DATABASE_OPS=true
```

### 日志内容

- DEBUG 模式下记录：
  - 发送给 LLM 的完整提示词
  - 数据库读写操作（SQL + 结果）
  - 工具调用详情
  - Context Window 变化
  - 记忆检索结果

## 配置参数更新

### 新增配置

```ini
# Session 管理配置
NEW_SESSION_COMMAND=/new
RESET_SESSION_COMMAND=/reset

# Context Window 配置
CONTEXT_WINDOW_KEEP_MIN=12
CONTEXT_WINDOW_TRIGGER_SUMMARY=24
RECENT_SUMMARIES_MAX=3

# 记忆检索配置
RECALL_SUMMARY_PER_QUERY=3
RECALL_CONV_PER_SUMMARY=4
RERANK_TOP_SUMMARIES=3
RERANK_TOP_CONVS=6

# Chat API 配置
OPENAI_API_KEY=
OPENAI_API_BASE=https://api.openai.com/v1
CHAT_MODEL=gpt-4o
TOOL_MODEL=gpt-4o
CHAT_REASONING_EFFORT=low
TOOL_REASONING_EFFORT=medium

# Embedding 配置（用户可配置 model + base_url）
EMBEDDING_API_KEY=
EMBEDDING_MODEL=text-embedding-3-small
EMBEDDING_API_BASE=https://api.openai.com/v1
EMBEDDING_DIMENSION=1536

# Rerank 配置（可选）
RERANK_API_KEY=
RERANK_MODEL=
RERANK_API_BASE=

# Telegram 配置（单用户模式）
TELEGRAM_BOT_TOKEN=
TELEGRAM_USER_ID=

# 定时任务配置
SCHEDULED_TASKS_CONFIG_PATH=scheduled_tasks.json

# Skills 配置
ENABLE_SKILLS=true
SKILLS_DIR=skills/

# MCP 配置
ENABLE_MCP=false
MCP_CONFIG_PATH=mcp_servers.json

# Web Search 配置
ENABLE_WEB_SEARCH=false
JINA_API_KEY=

# 基础配置
DEBUG_MODE=false
DEBUG_LOG_LEVEL=INFO
DEBUG_SHOW_FULL_PROMPT=false
DEBUG_LOG_DATABASE_OPS=false
TIMEZONE=Asia/Shanghai
```

### 移除配置

- `MAX_CONV_NUM` → 改用 `CONTEXT_WINDOW_KEEP_MIN`
- `REFRESH_EVERY_CONV_NUM` → 改用 `CONTEXT_WINDOW_TRIGGER_SUMMARY`

## 提示词复用

以下旧提示词需要保留并适配：

- **系统提示词**: `prompts/system.py` → 保留人格设定，适配 Telegram Markdown v2 格式，**直接嵌入 seele.json（最新版本）**
- **总结提示词**: `prompts/summary.py` → 保留，适配新格式
- **记忆更新提示词**: `prompts/memory_update.py` → 改为生成 **JSON Patch**

### 新增提示词

- **Rerank 提示词**: 指导 LLM 重新排序检索结果
- **自我查询提示词**: 引导 LLM 生成记忆搜索查询

## 实施顺序

1. **阶段一：基础设施**
   - 设置项目结构
   - 实现数据库层（sqlite-vec）
   - 实现配置系统（更新）
   - 实现日志系统

2. **阶段二：核心模块**
   - 实现 Context Window 管理
   - 实现记忆系统
   - 实现 Embedding 和 Rerank
   - 实现检索器

3. **阶段三：LLM 集成**
   - 实现提示词构建（包含 seele.json 嵌入，使用内存缓存保证最新版本）
   - 实现 LLM 客户端
   - 实现工具系统（MCP + Skills + 自我查询）

4. **阶段四：界面**
   - 实现 Telegram Bot
   - 实现消息处理器（支持 Markdown v2）

5. **阶段五：迁移工具**
   - 编写自由文本转换器（txt → JSON）
   - 编写迁移脚本
   - 验证迁移结果

6. **阶段六：测试和文档**
   - 编写单元测试
   - 更新 README
   - 删除旧文档
   - 删除旧代码

7. **阶段七：定时任务**
   - 实现定时任务调度器
   - 集成到主循环
