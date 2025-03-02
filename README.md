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
- 🖥 提供用户友好的WebUI

## 技术架构

- 语言模型:支持OpenAI兼容API的任何模型
- 向量数据库:lancedb
- 关系数据库:SQLite
- 开发语言:Python
- WebUI: Gradio

## 快速开始

1. 确保已安装好Python
2. 克隆项目仓库
   ```bash
   git clone https://github.com/fluviusmagnus/Seelenmaschine.git
   ```
3. 按下文说明配置好`.env`文件
3. 运行
   - Windows: `start.bat` 或 `start-webui.bat`
   - Linux:
     1. 赋予权限
       ```bash
       chmod +x start.sh start-webui.sh
       ```
     2. 执行 `start.sh` 或 `start-webui.sh`
       ```bash
       ./start.sh
       ```
       或者
       ```bash
       ./start-webui.sh
       ```
4. (WebUI的情况下)浏览器访问`http://localhost:7860`即可

## 手动安装说明

1. 克隆项目仓库
2. 建立虚拟环境(可选)
3. 安装依赖包(需要Python 3.11+)
```bash
pip install -r requirements.txt
```

## 配置说明

1. 复制`.env.example`文件并重命名为`.env`
2. 在`.env`文件中配置以下参数:

```ini
# Debug设置
DEBUG_MODE=false  # 调试模式开关 true/false

# 基本身份设定
AI_NAME=Seelenmachine
USER_NAME=User

# OpenAI API设置
OPENAI_API_KEY=your_api_key
OPENAI_API_BASE=your_api_base
CHAT_MODEL=your_preferred_model  # 例如:anthropic/claude-3.5-haiku
TOOL_MODEL=your_tool_model  # 用于记忆管理。建议使用推理模型,例如:deepdeek/deepseek-r1
EMBEDDING_MODEL=your_embedding_model  # 例如:text-embedding-3-small
EMBEDDING_DIMENSION=1536

# 记忆系统设置
MAX_CONV_NUM=20  # 最大对话轮数
REFRESH_EVERY_CONV_NUM=10  # 每次总结的对话轮数
RECALL_SESSION_NUM=2  # 检索相关会话数量
RECALL_CONV_NUM=4  # 从相关会话检索的对话数量
```

3. (可选) 在`data`文件夹中创建`persona_memory.txt`和`user_profile.txt`,填入人格记忆和用户形象

更多配置建议和使用技巧请参考项目 [Wiki](https://github.com/fluviusmagnus/Seelenmaschine/wiki/%E4%BD%BF%E7%94%A8%E6%8A%80%E5%B7%A7).

## 使用说明

直接在终端中进入CLI模式:
```bash
python src/main.py
```

或者,启动WebUI提供的网页应用:

```bash
python src/main.py --webui [--host HOST] [--port PORT]
```

参数说明:
```
--webui: 启动Web界面
--host: 指定主机地址（默认: 127.0.0.1）
--port: 指定端口号（默认: 7860）
```

### CLI模式可用命令
- `/reset`, `/r` - 重置当前会话
- `/save`, `/s` - 归档当前会话,开始新会话
- `/saveandexit`, `/sq`  - 归档当前会话,退出程序
- `/exit`, `/quit`, `/q`   - 暂存当前状态并退出程序
- `/help`, `/h`          - 显示此帮助信息

## 项目结构

```
src/
├── main.py          # 主程序入口,控制流程
├── chatbot.py       # 聊天逻辑实现
├── llm.py           # 大语言模型接口
├── memory.py        # 记忆系统实现
├── config.py        # 配置管理
├── prompts.py       # 提示词模板
└── utils.py         # 工具函数

data/               # 数据存储目录
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
