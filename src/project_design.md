# Seelenmaschine 项目设计文档

## 项目概述

Seelenmaschine是一个具有记忆和人格的LLM聊天机器人项目。它使用Python语言开发，能够通过终端CLI或Web界面进行对话，并具有复杂的记忆系统来维持长期的对话上下文和人格特征。

## 技术选型

### 核心技术栈
- **开发语言**: Python 3.11+
- **大语言模型**: OpenAI兼容API
  - CHAT_MODEL: 用于日常对话的主模型
  - TOOL_MODEL: 用于记忆管理和推理的专用模型（推荐使用推理模型如DeepSeek-R1）
  - EMBEDDING_MODEL: 用于文本向量化的嵌入模型
- **向量数据库**: LanceDB - 存储对话和总结的向量表示
- **关系数据库**: SQLite - 存储结构化的对话和会话数据
- **Web框架**: Flask - 提供现代化的Web界面
- **实时通信**: WebSocket (Flask-SocketIO) - 实现实时对话
- **外部工具集成**: 
  - Jina Deepsearch - 网络搜索功能
  - MCP (Model Context Protocol) - 动态工具扩展

### 配置管理
所有配置通过 `.env` 文件管理，包括：
- API密钥和端点
- 模型选择和参数
- 记忆系统参数
- 工具启用开关
- MCP服务器配置路径
- 时区设置
- Debug模式

## 数据库设计

### SQLite 数据库结构

#### session 表
存储会话信息：
- `session_id` (TEXT PRIMARY KEY): 会话唯一标识符
- `start_timestamp` (INTEGER): 会话开始时间戳
- `end_timestamp` (INTEGER): 会话结束时间戳
- `status` (TEXT): 会话状态 ("active" 或 "archived")
- `current_conv_count` (INTEGER): 当前会话的对话计数

#### conversation 表
存储所有对话记录：
- `session_id` (TEXT): 关联的会话ID
- `timestamp` (INTEGER): 对话时间戳
- `role` (TEXT): 角色 ("user" 或 "assistant")
- `text` (TEXT): 对话内容
- `text_id` (TEXT): 文本唯一标识符（用于向量数据库关联）

#### summary 表
存储会话总结：
- `session_id` (TEXT): 关联的会话ID
- `summary` (TEXT): 总结内容
- `text_id` (TEXT): 文本唯一标识符

### LanceDB 向量数据库结构

存储对话和总结的向量表示，用于相似度搜索：
- `text_id` (TEXT): 文本唯一标识符
- `type` (TEXT): 类型标识 ("summary" 或 "conversation")
- `session_id` (TEXT): 关联的会话ID
- `vector` (VECTOR): 文本的向量表示

## 记忆系统

### 三层记忆模型

#### 1. 人格记忆（永久记忆）
- **自我认知** (`persona_memory.txt`): AI的自我认知和性格特征
- **用户形象** (`user_profile.txt`): 对用户的理解和印象
- **更新机制**: 在会话结束时，结合当前会话总结更新
- **存储方式**: 纯文本文件，永久保存

#### 2. 对话总结（长期记忆）
- **内容**: 已归档会话的高层次总结
- **作用**: 提供跨会话的长期记忆
- **生成时机**: 
  - 会话中：当对话轮数超过 `MAX_CONV_NUM` 时，对最早的 `REFRESH_EVERY_CONV_NUM` 轮对话生成总结
  - 会话结束时：对整个会话生成总结并归档
- **检索机制**: 
  - 基于向量相似度搜索相关的 `RECALL_SESSION_NUM` 个会话总结
  - 从相关会话中进一步检索 `RECALL_CONV_NUM` 条具体对话
- **存储方式**: SQLite + LanceDB（向量索引）

#### 3. 当前对话（短期记忆）
- **内容**: 当前活跃会话的对话历史
- **管理**: 
  - 实时保存每轮对话
  - 维持最近 `MAX_CONV_NUM` 轮对话在上下文中
  - 超出部分自动总结并移出当前上下文
- **恢复机制**: 程序重启时自动恢复未归档的会话

## 核心功能模块

### 1. main.py - 程序入口与流程控制
- 初始化日志系统
- 解析命令行参数
- 启动CLI或Web界面
- 处理用户命令（`/reset`, `/save`, `/exit`, `/saveandexit` 等）
- 会话生命周期管理

### 2. chatbot.py - 聊天逻辑核心
主要类：`ChatBot`

**关键方法**：
- `__init__()`: 初始化记忆管理器和LLM客户端
- `reset_session()`: 重置当前会话
- `finalize_session()`: 归档会话并更新人格记忆
- `_update_persona()`: 更新自我认知
- `_update_profile()`: 更新用户形象
- `_update_summaries()`: 更新对话总结
- `process_user_input()`: 处理用户输入，生成响应

**对话流程**：
1. 检查是否需要更新对话总结（超出MAX_CONV_NUM）
2. 从记忆中检索相关历史信息
3. 构建完整的提示词（系统提示词 + 人格记忆 + 相关记忆 + 当前对话）
4. 调用LLM生成响应（支持工具调用）
5. 保存对话到数据库
6. 返回响应

### 3. llm.py - 大语言模型接口
主要类：`LLMClient`

**功能**：
- 管理与OpenAI兼容API的连接
- 支持工具调用（Tool Calling）
- MCP工具集成和调用
- 多轮工具调用链
- 文本嵌入生成

**工具系统**：
- 本地工具（`tools.py`）
- MCP动态工具（通过MCP服务器获取）
- 工具调用优先级：MCP工具优先，失败时回退到本地工具
- 支持多轮工具调用（LLM可以连续调用多个工具）

**关键方法**：
- `generate_response()`: 生成对话响应，处理工具调用
- `get_embedding()`: 获取文本向量
- `_get_tools()`: 获取可用工具列表（本地+MCP）
- `_call_tool()`: 调用工具（本地或MCP）

### 4. memory.py - 记忆管理系统
主要类：`MemoryManager`

**功能**：
- SQLite和LanceDB的初始化和管理
- 会话生命周期管理
- 对话和总结的存储与检索
- 向量相似度搜索
- 人格记忆文件管理

**关键方法**：
- `get_or_create_session()`: 获取或创建会话
- `add_conversation()`: 添加对话记录
- `update_summary()`: 更新会话总结
- `search_related_memories()`: 搜索相关记忆
- `get_persona_memory()` / `update_persona_memory()`: 人格记忆管理
- `get_user_profile()` / `update_user_profile()`: 用户形象管理

### 5. prompts.py - 提示词模板管理
提供所有与LLM交互的提示词模板：

**系统提示词**：
- 聊天系统提示词（引导对话风格，要求使用引用标签标记记忆检索）

**动态提示词构建**：
- `build_chat_prompt()`: 构建完整的对话提示词
- `build_summary_prompt()`: 构建总结提示词
- `build_persona_update_prompt()`: 构建自我认知更新提示词
- `build_user_profile_update_prompt()`: 构建用户形象更新提示词

### 6. config.py - 配置管理
主要类：`Config`

从 `.env` 文件加载所有配置项：
- API配置
- 模型选择
- 记忆系统参数
- 工具开关
- 文件路径
- 时区设置

### 7. tools.py - 工具实现
**当前工具**：
- `search_web()`: 使用Jina Deepsearch进行网络搜索

**工具定义**：
- 符合OpenAI Function Calling格式
- 包含工具描述和参数schema

### 8. mcp_client.py - MCP客户端
主要类：`MCPClient`

**功能**：
- 连接到MCP服务器
- 获取动态工具列表
- 调用MCP工具
- 支持stdio和HTTP/SSE传输方式
- 处理bearerToken认证

**特性**：
- 使用fastmcp库实现
- 异步上下文管理
- 自动格式转换（MCP格式 ↔ OpenAI格式）
- 配置文件管理（`mcp_servers.json`）

### 9. flask_webui.py - Web界面
**功能**：
- 提供现代化的Web聊天界面
- WebSocket实时通信
- 会话管理（重置、保存）
- 深色/浅色主题切换
- Markdown渲染
- 移动端适配

**路由**：
- `/`: 主界面
- `/session_info`: 获取会话信息（API）
- WebSocket事件：message, reset_session, save_session

### 10. utils.py - 工具函数
- `remove_blockquote_tags()`: 移除引用标签
- 时间处理函数（时区感知）
- 时间戳转换函数

### 11. database_maintenance.py - 数据库维护
**功能**：
- SQLite数据库优化（VACUUM, ANALYZE）
- 索引创建和优化
- LanceDB表优化
- 自动备份
- 完整性检查

## 对话流程详解

### 会话初始化
1. 检查数据库中是否存在未归档会话（status="active"）
2. 如果存在，加载会话数据
3. 如果不存在，创建新会话
4. 显示会话ID和开始时间

### 用户输入处理
1. 接收用户输入
2. 检查是否为命令（如 `/reset`, `/save`, `/exit`, `/saveandexit`）
3. 如果是命令，执行相应操作
4. 如果是对话，进入对话生成流程

### 对话生成流程
1. **检查总结更新需求**
   - 如果对话轮数超过 `MAX_CONV_NUM`
   - 总结最早的 `REFRESH_EVERY_CONV_NUM` 轮对话
   - 更新当前对话总结

2. **记忆检索**
   - 基于当前话题搜索相关的历史会话总结
   - 从相关会话中检索具体对话
   - 排除当前会话的内容

3. **提示词构建**
   - 系统提示词
   - 自我认知
   - 用户形象
   - 当前会话总结（如果存在）
   - 检索到的相关记忆
   - 当前对话历史
   - 用户输入

4. **LLM调用**
   - 发送提示词到CHAT_MODEL
   - 如果LLM请求工具调用：
     - 调用相应工具（MCP或本地）
     - 将工具结果添加到对话历史
     - 继续调用LLM（支持多轮工具调用）
   - 获取最终响应

5. **保存对话**
   - 保存用户输入到数据库
   - 保存AI响应到数据库
   - 更新会话对话计数

### 会话结束流程（/save 命令）
1. **生成会话总结**
   - 将当前会话的所有对话总结为一段文字
   - 保存到summary表和向量数据库

2. **更新人格记忆**
   - 基于会话总结更新自我认知
   - 基于会话总结更新用户形象
   - 保存到文件

3. **清理引用标签**
   - 从所有对话中移除 `<blockquote>` 标签

4. **归档会话**
   - 设置会话状态为 "archived"
   - 记录结束时间

5. **开始新会话**
   - 创建新的会话记录

## MCP集成架构

### MCP (Model Context Protocol)
MCP是一个标准化协议，允许LLM应用动态连接到外部工具和数据源。

**优势**：
- 工具与主应用解耦
- 支持任何语言编写工具服务器
- 工具可在多个项目间共享
- 动态添加/删除工具无需修改代码

### 集成方式
1. **配置文件** (`mcp_servers.json`)
   - 定义MCP服务器连接信息
   - 支持stdio、HTTP、SSE传输方式
   - 环境变量替换支持

2. **工具获取**
   - 启动时连接到所有配置的MCP服务器
   - 获取服务器提供的工具列表
   - 转换为OpenAI Function Calling格式

3. **工具调用**
   - LLM请求工具调用时
   - 通过MCP协议发送请求到相应服务器
   - 获取结果并返回给LLM
   - 支持多轮调用链

### 工具优先级
1. 首先尝试调用MCP工具
2. 如果MCP调用失败，回退到本地工具
3. 本地工具和MCP工具可以共存

## 用户界面

### CLI模式
**可用命令**：
- `/reset` 或 `/r`: 重置当前会话（清空对话和总结）
- `/save` 或 `/s`: 归档当前会话并开始新会话
- `/saveandexit` 或 `/sq`: 归档当前会话并退出程序
- `/exit`, `/quit` 或 `/q`: 保存当前状态并退出
- `/help` 或 `/h`: 显示帮助信息

**启动方式**：
```bash
python src/main.py
```

### Web界面 (Flask)
**特性**：
- 现代化响应式设计
- 实时WebSocket通信
- 深色/浅色主题切换
- Markdown渲染
- 移动端友好
- 会话管理按钮
- 实时状态指示器

**启动方式**：
```bash
python src/main.py --flask [--host HOST] [--port PORT]
```

或使用便捷脚本：
- Windows: `start-flask-webui.bat`
- Linux/macOS: `start-flask-webui.sh`

## Debug模式

启用方式：在 `.env` 中设置 `DEBUG_MODE=true`

**功能**：
- 记录所有提交给LLM的完整提示词
- 记录数据库读写操作（部分实现）
- 保存详细日志到外部文件
- 有助于开发调试和系统优化

## 项目文件结构

```
Seelenmaschine/
├── src/                          # 源代码目录
│   ├── main.py                  # 程序入口
│   ├── chatbot.py               # 聊天核心逻辑
│   ├── llm.py                   # LLM接口
│   ├── memory.py                # 记忆管理
│   ├── config.py                # 配置管理
│   ├── prompts.py               # 提示词模板
│   ├── tools.py                 # 工具实现
│   ├── mcp_client.py            # MCP客户端
│   ├── flask_webui.py           # Flask Web界面
│   ├── utils.py                 # 工具函数
│   ├── templates/               # HTML模板
│   │   ├── base.html
│   │   └── index.html
│   └── static/                  # 静态资源
│       ├── css/
│       │   └── main.css
│       └── js/
│           └── main.js
├── data/                         # 数据存储目录
│   ├── persona_memory.txt       # 自我认知
│   ├── user_profile.txt         # 用户形象
│   ├── chat_sessions.db         # SQLite数据库
│   └── lancedb/                 # LanceDB向量数据库
├── database_maintenance.py       # 数据库维护脚本
├── maintenance.sh / .bat         # 维护脚本快捷方式
├── start.sh / .bat              # CLI启动脚本
├── start-flask-webui.sh / .bat  # Web界面启动脚本
├── requirements.txt              # Python依赖
├── mcp_servers.json             # MCP服务器配置
├── .env                         # 环境配置
├── .env.example                 # 配置示例
├── README.md                    # 项目说明（中文）
├── README_EN.md                 # 项目说明（英文）
├── MCP_USAGE.md                 # MCP使用指南
├── DATABASE_MAINTENANCE_README.md  # 数据库维护说明
└── LICENSE                      # 许可证
```

## 技术亮点

1. **分层记忆架构**：人格记忆、长期记忆（总结）、短期记忆（当前对话）三层设计
2. **智能记忆检索**：基于向量相似度的二阶检索（总结→具体对话）
3. **动态工具扩展**：通过MCP协议支持动态添加工具
4. **多模型支持**：区分对话模型和推理模型，优化性能和成本
5. **完整的会话管理**：支持会话恢复、重置、归档
6. **现代化Web界面**：实时通信、主题切换、响应式设计
7. **数据库维护**：自动化的数据库优化和备份机制

## 未来扩展方向

- 多用户支持
- 更丰富的工具集成
- 更精细的记忆管理策略
