使用Python语言设计一个具有记忆和人格的LLM聊天机器人。

# 技术选型

- 在终端中进行纯文本聊天。
- 外接大模型，包括语言模型和嵌入模型：OpenAI兼容API，用户自己设定使用何种模型，环境变量OPENAI_API_KEY，OPENAI_API_BASE，CHAT_MODEL，EMBEDDING_MODEL保存在.env配置文件中。
- 本地向量数据库lancedb：储存对话以及summary的向量，包含text_id，type, session_id，vector字段。type取值为"summary"或"conversation"。
- 本地数据库sqlite：储存对话总结和所有对话。为此需要3个表：summary，conversation，session。数据结构：
  - session：包含session_id，start_timestamp, end_timestamp，status，current_conv_count字段。status有两种取值："active","archived"。
  - summary：包含session_id,  summary, text_id字段。
  - conversation：session_id, timestamp, role, text, text_id字段。text在储存时，开头需要额外添加类似“User: ”的role说明以便区分说话人。

# 实现逻辑

## 记忆模型

聊天机器人具有以下几种记忆类型：

1. 人格记忆。包括自我认知和用户形象两个分开的部分。session结束时，将已有自我认知和用户形象分别与当前session的summary一并提交给大模型，形成更新的记忆。永久保存在外部配置文件中。格式：纯文本。
2. 对话总结。包含当前session中因超出轮数限制而省略的较早对话的总结。要求临时忽略引用标签。新session开始时为空。当对话轮数超过MAX_CONV_NUM轮后，较早的REFRESH_EVERY_CONV_NUM轮对话退出当前上下文，并经由大模型总结后，保存为对话总结。如果对话总结不为空，则将已有总结与新退出的对话一并提交给大模型，形成更新的总结。session结束时，永久保存。
3. 当前对话。正在使用的对话上下文。每次有新对话时都及时保存到数据库。

## 对话流程

- 开始聊天时，需初始化当前session。检查数据库中是否有上次未归档的session（status="active"）。
  - 如果有，则按需求读取此session的对话记录，在屏幕上显示最后MAX_CONV_NUM轮对话。
  - 如果没有要载入的session，则新建session。
- 无论是否是新session，显示当前session的id和开始时间，方便用户判断是否是新session。

- 获取用户输入对话或命令。

- 根据最大轮数限制，视需求更新对话总结。

- 获取相关信息。记忆数据库中搜索，与当前话题（根据最后一轮对话以及当前用户输入分别判断）相关的RECALL_SESSION_NUM条对话总结，以及相关session中的RECALL_CONV_NUM条对话。不搜索当前session。

- 每次对话向服务器发送的提示词包含以下部分：

  1. 系统提示词。指导LLM将对话进行下去。要求LLM使用引用标签 `<blockquote> </blockquote>` 复述重要的记忆检索。
  2. 自我认知。
  3. 用户形象。
  4. 对话总结。
  5. 记忆中的相关对话总结和相关对话。
  5. 当前对话。
  6. 用户输入。

- 如果得到大模型正确响应，更新当前对话到数据库。然后继续对话。

- 如果session用 `/save` 命令正常结束，则进行对话总结和人格记忆的更新。删除本session的引用标签。将本session的status设定为archived，然后开始新session。

# 用户界面

- 除了正常对话，用户可输入指令：
  1. `/reset`命令重置当前session。清空这个session中的当前对话和summary，包括数据库中本sesseion的对话和summary数据。
  2. `/save`命令归档当前session记忆后开始新的session。
  3. `/exit`会保留当前session的所有数据，包括当前对话和summary，下次启动程序时恢复到退出时的状态。
- 有一个可以开关的debug模式，该模式下，会在外部的log文件中详细记录所有最终提交给大模型的内容，以及每次数据库的读写操作的内容。

# 模块化设计

- main.py 控制流程，负责与用户交互。
- llm.py 负责与大模型的交互，包括语言模型和嵌入模型。
- memory.py 负责数据库中各种记忆的检索与更新。
- config.py 将所有配置集中管理。
- prompts.py 将所有与大模型交互的提示词模板统一管理。
