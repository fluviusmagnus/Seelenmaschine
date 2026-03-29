# Seelenmaschine

[English](README_EN.md) | 中文

![](static/logo-horizontal.png)

Seelenmaschine 是一个具有记忆和人格的 LLM 聊天机器人项目。它使用 Telegram Bot 进行交互，具有持久化的三层记忆系统：短期记忆（当前会话）、中期记忆（向量检索的历史对话）和长期记忆（结构化人格与用户档案）。

⚠️ 高强度 AI 编程警告！

## 主要特性

- 🤖 **支持多种大语言模型**（通过 OpenAI 兼容 API）
- 🧠 **三层记忆系统**：
  - **短期记忆**：Context Window 管理，自动总结和会话切换
  - **中期记忆**：基于 Embedding + Rerank 的智能检索
  - **长期记忆**：JSON 结构化人格和用户档案
- 💾 **一体化数据库**：SQLite + sqlite-vec，无需额外向量数据库
- 🔍 **智能记忆检索**：
  - 二阶检索（摘要 → 对话）
  - Rerank 模型重排序
  - 时间感知的上下文注入
  - FTS5 全文搜索（支持布尔运算符）
  - 自我查询工具（LLM 可主动搜索记忆）
- 🛠️ **完整的会话管理**：
  - `/new` - 归档当前会话并创建新会话
  - `/reset` - 删除当前会话
- 📱 **Telegram Bot 界面**：提供命令菜单、分段回复、文件上传/发送与定时主动消息
- 🔌 **MCP (Model Context Protocol) 支持**：
  - 动态连接外部工具和数据源
  - 支持多种传输方式（stdio、HTTP、SSE）
- ⏰ **定时任务**：支持一次性任务和间隔任务
- 🧾 **工具调用追踪**：记录工具执行历史，并支持 `query_tool_history` 查询
- 🛡️ **内置本地工具集**：
  - 文件操作工具（读取、写入、编辑、追加）
  - 文件搜索工具（Grep内容搜索、Glob模式匹配）
  - Shell命令执行（带危险命令检测和人工批准）
- 📤 **文件发送**：支持将生成的文件直接发送给当前用户
- 🤝 **人机协作(HITL)**：危险操作需要用户批准，避免意外修改

## 技术架构

- **语言模型**：支持 OpenAI 兼容 API 的任何模型
- **数据库**：SQLite + sqlite-vec（向量扩展）
- **Web 框架**：python-telegram-bot
- **异步框架**：asyncio
- **测试**：pytest + pytest-asyncio
- **日志**：loguru

## 快速开始

1. **克隆项目仓库**
   ```bash
   git clone https://github.com/fluviusmagnus/Seelenmaschine.git
   cd Seelenmaschine
   ```

2. **安装依赖**
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # Linux/macOS
   # .venv\Scripts\activate  # Windows
   pip install -r requirements.txt
   ```

3. **配置环境**
   ```bash
   cp .env.example hy.env  # 使用你喜欢的 profile 名称
   # 编辑 hy.env 填入必要的配置
   ```

4. **运行 Telegram Bot**
   ```bash
   python src/main_telegram.py hy
   # 或使用快捷脚本
   ./start-telegram.sh hy              # Linux/macOS
   start-telegram.bat hy               # Windows
   ```

## 配置说明

### Profile 配置系统

Seelenmaschine 支持多环境配置，通过 profile 参数可以使用不同的配置和数据目录。

1. 复制 `.env.example` 文件并重命名为 `<profile>.env`（例如 `hy.env`, `dev.env`）
2. 每个 profile 将使用独立的数据目录：`data/<profile>/`
3. 在 `<profile>.env` 文件中配置以下参数：

```ini
# 基础配置
DEBUG_MODE=false
# 留空时会根据 DEBUG_MODE 自动决定：
# - DEBUG_MODE=true  => DEBUG
# - DEBUG_MODE=false => INFO
# 只有在你想强制覆盖默认行为时才显式填写，例如 DEBUG / WARNING
DEBUG_LOG_LEVEL=
DEBUG_SHOW_FULL_PROMPT=false
DEBUG_LOG_DATABASE_OPS=false
TIMEZONE=Asia/Shanghai

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
OPENAI_API_KEY=your_api_key
OPENAI_API_BASE=https://api.openai.com/v1
CHAT_MODEL=gpt-4o
TOOL_MODEL=gpt-4o
CHAT_REASONING_EFFORT=low
TOOL_REASONING_EFFORT=medium

# Embedding 配置
EMBEDDING_API_KEY=your_api_key
EMBEDDING_MODEL=text-embedding-3-small
EMBEDDING_API_BASE=https://api.openai.com/v1
EMBEDDING_DIMENSION=1536

# Rerank 配置（可选）
RERANK_API_KEY=
RERANK_MODEL=
RERANK_API_BASE=

# Telegram 配置
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_USER_ID=your_user_id

# MCP 配置
ENABLE_MCP=false
MCP_CONFIG_PATH=mcp_servers.json

# 工作空间配置（限制本地文件操作范围）
# 可选，工作空间根目录，默认是 data/<profile>/workspace
WORKSPACE_DIR=
# 可选，媒体文件存储目录，默认是 WORKSPACE_DIR/media
MEDIA_DIR=
```

注意：当前配置文件示例**不使用行内 `#` 注释**。如需注释，请单独占一行书写，避免被解析为配置值的一部分。

### 数据目录结构

```
data/<profile>/
├── seele.json           # 长期记忆（人格和用户档案）
├── chatbot.db           # SQLite 数据库
└── workspace/           # 可访问工作空间目录（用于本地文件操作）
    └── media/           # 媒体文件存储目录
```

## 使用说明

### Telegram Bot 模式

启动 Telegram Bot：
```bash
python src/main_telegram.py <profile>

# 或使用快捷脚本（自动检测虚拟环境和依赖）
./start-telegram.sh <profile>         # Linux/macOS
start-telegram.bat <profile>          # Windows
```

示例：
```bash
# 使用 Python 直接运行
python src/main_telegram.py hy
python src/main_telegram.py dev

# 或使用快捷脚本
./start-telegram.sh test
start-telegram.bat hy
```

### 可用命令

- `/start` - 显示欢迎信息
- `/help` - 显示帮助信息
- `/new` - 归档当前会话并开始新会话
- `/reset` - 删除当前会话并创建新会话
- `/approve` - 批准待执行的危险操作

### 高级搜索功能

系统支持 FTS5 全文搜索，可通过自然语言让 LLM 调用 `search_memories` 工具：

示例查询：
```
搜索一下我们之前聊过的关于 Anna 和电影的内容
找一下我上周说过的话
查找包含"机器学习"或"AI"的对话
```

支持的搜索语法：
- 布尔运算符：`AND`, `OR`, `NOT`
- 精确短语：`"exact phrase"`
- 时间过滤：`last_day`, `last_week`, `last_month`
- 角色过滤：`role='user'` 或 `role='assistant'`
- 日期范围：`start_date`, `end_date`

详见 [搜索示例文档](docs/SEARCH_EXAMPLES.md)。

### 工具调用

系统集成了以下工具能力：

1. **内置本地工具集**
   - 文件操作（读/写/编辑/追加）
   - 文件搜索（Grep内容搜索/Glob模式匹配）
   - Shell 命令执行（带危险检测和人工批准）
2. **MCP (Model Context Protocol)** - 外部工具和数据源
3. **Memory Search** - 自我查询记忆
4. **Scheduled Tasks** - 定时任务管理
5. **File Send** - 向当前用户发送文件
6. **Tool Trace Query** - 查询最近的工具执行历史

通过配置文件控制各工具的启用状态。危险命令需要用户批准才能执行。

## 项目结构

```
Seelenmaschine/
├── src/                          # 源代码目录
│   ├── main_telegram.py          # Telegram Bot 入口
│   ├── adapter/                  # 平台适配层
│   │   └── telegram/
│   │       ├── adapter.py        # Telegram 应用装配与生命周期
│   │       ├── commands.py       # Telegram 命令处理
│   │       ├── controller.py     # Telegram 控制器与服务装配
│   │       ├── delivery.py       # Telegram 分段发送
│   │       ├── files.py          # Telegram 文件收发
│   │       ├── formatter.py      # Telegram 回复格式化
│   │       ├── messages.py       # 普通消息与文件消息流程
│   ├── core/                     # 核心模块
│   │   ├── approval.py           # 危险操作审批流程
│   │   ├── bot.py                # CoreBot 运行时根对象
│   │   ├── config.py             # 配置管理
│   │   ├── conversation.py       # 对话编排
│   │   ├── database.py           # 数据库管理（sqlite-vec）
│   │   ├── file_delivery_service.py # 文件发送策略与校验
│   │   ├── runtime.py            # 运行时生命周期辅助
│   │   ├── scheduler.py          # 定时任务调度器
│   │   ├── session_service.py    # 会话生命周期服务
│   │   └── tools.py              # 工具运行时/注册/执行编排
│   ├── llm/                      # LLM 模块
│   │   ├── chat_client.py        # 聊天客户端
│   │   ├── embedding.py          # Embedding 客户端
│   │   ├── memory_client.py      # 记忆相关模型调用
│   │   ├── message_builder.py    # 消息构建
│   │   ├── request_executor.py   # 请求执行器
│   │   ├── reranker.py           # Rerank 客户端
│   │   └── tool_loop.py          # 工具调用循环
│   ├── memory/                   # 记忆子系统
│   │   ├── context.py            # Context Window 管理
│   │   ├── manager.py            # 记忆总管理器
│   │   ├── recall.py             # 记忆召回
│   │   ├── seele.py              # 长期人格/档案更新
│   │   ├── sessions.py           # 会话管理
│   │   ├── summaries.py          # 摘要生成
│   │   └── vector_retriever.py   # 向量检索
│   ├── tools/                    # 工具系统
│   │   ├── mcp_client.py         # MCP 客户端
│   │   ├── memory_search.py      # 自我查询工具
│   │   ├── scheduled_tasks.py    # 定时任务工具
│   │   ├── send_file.py          # 文件发送工具
│   │   ├── file_io.py            # 文件操作工具
│   │   ├── file_search.py        # 文件搜索工具
│   │   ├── shell.py              # Shell 命令执行工具
│   │   └── tool_trace.py         # 工具调用追踪
│   ├── prompts/                  # 提示词
│   │   ├── memory_prompts.py     # 记忆相关提示词
│   │   └── system_prompt.py      # 系统提示词构造
│   └── utils/                    # 工具函数
│       ├── text.py               # 文本处理
│       ├── time.py               # 时间处理
│       └── logger.py             # 日志工具

├── template/                     # 模板目录
│   └── seele.json                # 长期记忆模板
├── tests/                        # 单元测试
│   ├── conftest.py               # pytest 配置
│   ├── test_database.py
│   ├── test_memory.py
│   ├── test_retriever.py
│   └── test_llm.py
├── migration/                    # 数据迁移工具
│   ├── migrate.py                # 统一迁移工具
│   └── README.md                 # 迁移工具文档
├── data/                         # 数据存储目录
│   └── <profile>/                # Profile 数据目录
├── requirements.txt              # Python 依赖
├── requirements-dev.txt          # 开发依赖
├── docs/                         # 文档目录
│   ├── SCHEDULED_TASKS.md        # 定时任务文档
│   └── SEARCH_EXAMPLES.md        # 搜索功能示例
├── <profile>.env                 # 环境配置
├── .env.example                  # 配置示例
├── start-telegram.sh             # 启动脚本（Linux/macOS）
├── start-telegram.bat            # 启动脚本（Windows）
├── migrate.sh                    # 迁移工具快捷脚本（Linux/macOS）
├── migrate.bat                   # 迁移工具快捷脚本（Windows）
├── AGENTS.md                     # AI 辅助开发指南
├── README.md                     # 项目说明
└── LICENSE                       # 许可证
```

## 记忆系统说明

### 短期记忆（Context Window）

- 当前会话的消息保持在内存中
- 当消息达到 `CONTEXT_WINDOW_TRIGGER_SUMMARY`（默认 24）时，自动总结较早的 `CONTEXT_WINDOW_KEEP_MIN`（默认 12）条消息
- 通过 `/new` 和 `/reset` 命令管理会话

### 中期记忆（向量检索）

- 所有对话和摘要都会被向量化存储
- 使用 Embedding 模型进行初步检索
- 使用 Rerank 模型进行精排（可选）
- 检索结果带上人类可读的时间戳注入到提示词

### 长期记忆（人格档案）

- 以结构化 JSON 格式存储在 `seele.json` 中
- 每次生成新摘要时同步更新
- 直接嵌入到系统提示词中

## 调试与运行说明

### Debug 模式

在 Debug 模式下，程序会：
- 记录发送给 LLM 的完整提示词（`DEBUG_SHOW_FULL_PROMPT=true`）
- 记录数据库读写操作（`DEBUG_LOG_DATABASE_OPS=true`）
- 将日志保存在外部文件中

日志级别规则如下：
- `DEBUG_MODE=true` 且 `DEBUG_LOG_LEVEL` 留空时，默认使用 `DEBUG`
- `DEBUG_MODE=false` 且 `DEBUG_LOG_LEVEL` 留空时，默认使用 `INFO`
- 如果显式设置了 `DEBUG_LOG_LEVEL`，则以该值为准

推荐把 `DEBUG_MODE` 当作主开关使用，`DEBUG_LOG_LEVEL` 仅在需要手动覆盖默认行为时再设置。

### 本地工具工作空间

- 相对路径文件操作默认相对于 `WORKSPACE_DIR`
- `WORKSPACE_DIR` 默认为 `data/<profile>/workspace`
- `MEDIA_DIR` 默认为 `WORKSPACE_DIR/media`
- 文件与 Shell 工具会限制在 `WORKSPACE_DIR` / `MEDIA_DIR` 范围内，越界操作需要审批或会被拒绝

## 运行测试

```bash
python -m pytest tests
python -m pytest -v tests           # 详细输出
python -m pytest tests --cov=src    # 测试覆盖率
```

## 数据迁移

重新按要求配置好环境变量后，使用统一迁移工具从旧版本迁移数据：

```bash
# 执行迁移
python migration/migrate.py <profile>

# 或使用快捷脚本（自动检测虚拟环境和依赖）
./migrate.sh <profile>                # Linux/macOS
migrate.bat <profile>                 # Windows
```

迁移工具会：
1. 自动检测需要的迁移任务（旧数据库迁移、文本转 JSON、FTS5 升级）
2. 自动备份现有数据
3. 执行迁移并验证结果

详见 [迁移指南](migration/README.md)。

## 文档索引

- [docs/README.md](docs/README.md) - 文档总览
- [docs/SCHEDULED_TASKS.md](docs/SCHEDULED_TASKS.md) - 定时任务说明
- [docs/SEARCH_EXAMPLES.md](docs/SEARCH_EXAMPLES.md) - 搜索示例
- [migration/README.md](migration/README.md) - 数据迁移说明

## 许可证

本项目采用 GPL-3.0 许可证。详见 [LICENSE](LICENSE) 文件。
