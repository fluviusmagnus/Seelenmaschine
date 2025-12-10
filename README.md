# Seelenmaschine

[English](README_EN.md)

![](static/logo-horizontal.png)

Seelenmaschine是一个具有记忆和人格的LLM聊天机器人项目。它能够通过终端或WebUI进行纯文本对话,并具有持久化的记忆系统,可以记住与用户的对话历史,并形成对用户的理解。

⚠️ 高强度AI编程警告！

## 主要特性

- 🤖 支持多种大语言模型(通过OpenAI兼容API)
- 🧠 复杂的记忆系统,包含:
  - 人格记忆(自我认知和用户形象)
  - 对话和对话总结(长期记忆)
  - 当前对话(短期记忆)
- 💾 本地数据持久化
  - 使用lancedb存储向量数据
  - 使用SQLite存储对话和会话信息
- 🔍 智能记忆检索
  - 自动检索相关历史对话
  - 检索结果智能判定嵌入上下文
  - 动态生成对话总结
- 🛠️ 完整的会话管理功能
- 🖥 提供用户友好的WebUI (Flask界面)
- 🛜 自动判断并调用实时网络搜索功能
- 🔌 **MCP (Model Context Protocol) 支持**
  - 动态连接外部工具和数据源
  - 支持多种传输方式（stdio、HTTP、SSE）
  - 工具与主应用解耦，易于扩展
  - 详见 [MCP使用指南](MCP_USAGE.md)

## 技术架构

- 语言模型:支持OpenAI兼容API的任何模型
- 向量数据库:lancedb
- 关系数据库:SQLite
- 开发语言:Python
- WebUI: Flask
- 网络搜索: Jina Deepsearch

## 快速开始

1. 确保已安装好Python
2. 克隆项目仓库
   ```bash
   git clone https://github.com/fluviusmagnus/Seelenmaschine.git
   ```
3. 按下文说明配置好`<profile>.env`文件（例如 `dev.env` 或 `production.env`）
4. 运行
   - Windows: `start.bat <profile>` 或 `start-flask-webui.bat <profile>`
     ```cmd
     start.bat dev
     ```
     或者
     ```cmd
     start-flask-webui.bat dev
     ```
   - Linux:
     1. 赋予权限
       ```bash
       chmod +x start.sh start-flask-webui.sh
       ```
     2. 执行 `start.sh <profile>` 或 `start-flask-webui.sh <profile>`
       ```bash
       ./start.sh dev
       ```
       或者
       ```bash
       ./start-flask-webui.sh dev
       ```
5. (WebUI的情况下)浏览器访问`http://localhost:7860`即可

## 手动安装说明

1. 克隆项目仓库
2. 建立虚拟环境(可选)
3. 安装依赖包(需要Python 3.11+)
```bash
pip install -r requirements.txt
```

## 配置说明

### Profile 配置系统

Seelenmaschine 支持多环境配置，通过 profile 参数可以使用不同的配置和数据目录。

1. 复制`.env.example`文件并重命名为`<profile>.env`（例如 `dev.env`, `production.env`）
2. 每个 profile 将使用独立的数据目录：`data/<profile>/`
3. 在 `<profile>.env` 文件中配置以下参数:

```ini
# Debug设置
DEBUG_MODE=false  # 调试模式开关 true/false

# 基本身份设定
AI_NAME=Seelenmachine
USER_NAME=User

# Timezone settings
# 用户的时区,尤其注意服务器时间与用户时间不同的情况
# 中国标准时间默认填写 `Asia/Shanghai``
# 时区代码可参考 https://en.wikipedia.org/wiki/List_of_tz_database_time_zones
TIMEZONE=Asia/Shanghai

# OpenAI API设置
OPENAI_API_KEY=your_api_key
OPENAI_API_BASE=your_api_base
CHAT_MODEL=your_preferred_model  # 例如:gpt-4o。如要使用搜索等功能,需支持工具调用
TOOL_MODEL=your_tool_model  # 用于记忆管理。建议使用推理模型,例如:deepdeek/deepseek-r1
CHAT_REASONING_EFFORT=low # 参考API供应商的提示
TOOL_REASONING_EFFORT=medium
EMBEDDING_MODEL=your_embedding_model  # 例如:text-embedding-3-small
EMBEDDING_DIMENSION=1536

# 记忆系统设置
MAX_CONV_NUM=20  # 最大对话条数
REFRESH_EVERY_CONV_NUM=10  # 每次总结的对话条数
RECALL_SESSION_NUM=2  # 检索相关会话数量
RECALL_CONV_NUM=4  # 从相关会话检索的对话数量

# Tools settings
# 使用Jina Deepsearch API进行网络搜索
ENABLE_WEB_SEARCH=false
# 可留空,因目前允许免费使用
JINA_API_KEY=

# MCP settings
# 启用MCP (Model Context Protocol) 支持
ENABLE_MCP=true
# MCP服务器配置文件路径
MCP_CONFIG_PATH=mcp_servers.json

```

3. (可选) 在`data`文件夹中创建`persona_memory.txt`和`user_profile.txt`,填入人格记忆和用户形象

更多配置建议和使用技巧请参考项目 [Wiki](https://github.com/fluviusmagnus/Seelenmaschine/wiki/%E4%BD%BF%E7%94%A8%E6%8A%80%E5%B7%A7).

## 使用说明

### CLI 模式

直接在终端中进入CLI模式:
```bash
python src/main.py <profile>
```

示例:
```bash
python src/main.py dev
python src/main.py production
```

或使用启动脚本:
```bash
# Linux/macOS
./start.sh dev

# Windows
start.bat dev
```

### Web UI 模式

启动 Flask Web 界面:
```bash
python src/main.py <profile> --flask [--host HOST] [--port PORT]
```

示例:
```bash
python src/main.py dev --flask
python src/main.py production --flask --host 0.0.0.0 --port 8080
```

或使用便捷启动脚本:
```bash
# Linux/macOS
./start-flask-webui.sh dev
./start-flask-webui.sh dev --host 0.0.0.0 --port 8080

# Windows
start-flask-webui.bat dev
start-flask-webui.bat dev --host 0.0.0.0 --port 8080
```

参数说明:
```
<profile>: 必需参数，指定使用的配置文件（例如: dev, production）
--flask: 启动Flask Web界面
--host: 指定主机地址（默认: 127.0.0.1）
--port: 指定端口号（默认: 7860）
```

### Web界面特性

**Flask界面**:
- 🎨 现代化响应式设计
- ⚡ 实时WebSocket通信
- 🌓 深色/浅色主题切换
- 📱 移动端友好
- 🔄 实时状态指示器
- ✨ 优雅的动画效果
- 📝 Markdown渲染支持
-  完整的CLI功能复刻

### CLI模式可用命令
- `/reset`, `/r` - 重置当前会话
- `/save`, `/s` - 归档当前会话,开始新会话
- `/saveandexit`, `/sq`  - 归档当前会话,退出程序
- `/exit`, `/quit`, `/q`   - 暂存当前状态并退出程序
- `/tools`, `/t` - 切换工具调用权限(临时设置)
- `/help`, `/h`          - 显示此帮助信息

### 工具调用控制

系统提供了两级工具控制机制：

**配置级开关** (需重启生效)：
- `ENABLE_WEB_SEARCH`: 控制是否加载网络搜索工具
- `ENABLE_MCP`: 控制是否加载MCP工具

**运行时开关** (即时生效，临时设置)：
- **CLI模式**: 使用 `/t` 或 `/tools` 命令切换工具调用权限
- **Web模式**: 在侧边栏设置面板中切换"工具调用"开关

运行时开关允许您在对话过程中临时禁用或启用工具调用，而无需修改配置文件或重启应用。这对于需要纯文本对话或测试不同场景非常有用。

**注意**: 运行时开关仅在配置级工具已启用时有效。如果配置中未启用任何工具，运行时开关将无效果。

## 项目结构

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

## 记忆系统说明

### 人格记忆
- 包含自我认知和用户形象
- 在会话结束时更新
- 永久保存在配置文件中

### 对话总结
- 自动总结结束并归档的会话
- 通过检索回顾历史对话，提供长期记忆
- 二阶检索，通过对话总结进一步定位具体对话
- 保存在数据库中

### 当前对话
- 实时记录当前会话内容
- 超出最大轮数时自动总结早期对话
- 支持会话恢复功能

## Debug模式

在debug模式下,程序会:
- 记录所有提交给大模型的内容
- 记录数据库的读写操作（未完成）
- 将日志保存在外部文件中

这些日志对于开发调试和优化系统非常有帮助。
