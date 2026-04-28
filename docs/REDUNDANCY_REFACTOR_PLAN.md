# 冗余代码重构进度台账

最后更新：2026-04-29

## 目标

系统性移除项目中的冗余代码、过薄抽象层、旧同步兼容壳和测试维持的历史 API。执行时以现有架构方向为准：`core` 拥有运行时和业务流程，`adapter` 只处理 Telegram 边界，`memory / llm / tools` 走 async-first。

## 进度标记

- `[x]` 已完成，代码与测试已更新。
- `[~]` 部分完成，仍有明确保留的过渡桥接。
- `[ ]` 未开始或仍待执行。
- `[!]` 明确不建议在本轮继续删除。

## 当前验证状态

- `[x]` `.venv\Scripts\python.exe -m ruff check src tests`
- `[x]` `.venv\Scripts\python.exe -m pytest tests -q`
- 最近一次全量测试结果：`619 passed`

## 执行原则

- 不改 Telegram 用户可见行为：消息处理、文件收发、审批、调度任务、MCP 工具调用必须保持等价。
- 删除前先迁移引用，再删除旧符号和旧测试。
- 优先删除只做转发、无独立状态、无独立策略的层。
- `core / memory / llm / tools` 保持 async-first；同步 API 只在确有同步启动、关闭、bootstrap 或 schema repair 需要时保留。
- 不保留“为了测试存在”的兼容接口；测试应覆盖真实 owner。

## 阶段索引

原始计划中的四个大阶段已经执行完大部分工作。为了便于后续任务继续追踪，本文件将它们拆成更细的 9 个阶段：

| 阶段 | 范围 | 当前状态 |
|---|---|---|
| 阶段 1 | Telegram adapter 与包级门面低风险清理 | `[x]` |
| 阶段 2 | MCP deprecated 同步兼容壳清理 | `[x]` |
| 阶段 3 | Core adapter runtime 与 session owner 合并 | `[x]` |
| 阶段 4 | Core tool runtime 瘦身 | `[x]` |
| 阶段 5 | Memory coordination 层合并 | `[x]` |
| 阶段 6 | Memory 同步入口删除 | `[x]` |
| 阶段 7 | Prompts runtime 拆分与 prompt helper 整理 | `[x]` |
| 阶段 8 | LLM / MemoryClient 同步生成 facade 删除 | `[x]` |
| 阶段 9 | 剩余同步 wrapper 与保留桥接审计 | `[x]` |

## 分阶段进度

| 状态 | 阶段 | 项目/符号 | 当前结果 | 证据/验证 | 后续动作 |
|---|---|---|---|---|---|
| `[x]` | 阶段 1 | `src/adapter/telegram/adapter.py::TelegramApplicationSetup` | 已合并进 `TelegramAdapter`，类已删除 | Telegram 相关测试已纳入全量测试 | 无 |
| `[x]` | 阶段 1 | 空包级 `__init__.py` 门面 | 已清理无意义 `__all__` 和注释，保留空包文件 | ruff 通过 | 无 |
| `[x]` | 阶段 2 | `src/tools/mcp_client.py::get_tools_sync/call_tool_sync` | deprecated 同步兼容壳已删除 | MCP 相关测试已更新并通过 | 无 |
| `[x]` | 阶段 3 | `src/core/adapter_contracts.py::AdapterRuntimeCapabilities` | 已删除，`CoreBot.initialize_adapter_runtime(...)` 改为显式回调参数 | adapter runtime 合约测试已更新 | 无 |
| `[x]` | 阶段 3 | `src/core/session_service.py::SessionService` | 已并入 `CoreBot.create_new_session/reset_session`，文件已删除 | handlers/session 路径随全量测试通过 | 无 |
| `[x]` | 阶段 4 | `src/core/tools.py::ToolRuntime` | 运行时注册、publish、MCP warmup/connect 逻辑已移入 `CoreBot` | tool/runtime 相关测试已更新 | 无 |
| `[x]` | 阶段 4 | `src/core/tools.py::ToolRuntimeState` | 已折叠为 `CoreBot` 直接字段 | `ToolExecutor` 未受影响 | 无 |
| `[x]` | 阶段 4 | `CoreBot.get_tool_runtime/get_tool_executor_service/create_tool_runtime_state` | 公开惰性 getter 已移除 | 测试改为断言 LLM 注册和 `execute_tool` 行为 | 无 |
| `[x]` | 阶段 5 | `src/memory/summaries.py::SummaryGenerator` | 已内联进 `MemoryManager`，类和文件已删除 | memory summary 测试通过 | 无 |
| `[x]` | 阶段 5 | `src/memory/recall.py::MemoryRecall` | 检索协调逻辑已并入 `MemoryManager.process_user_input_async`，文件已删除 | memory/context 测试通过 | 无 |
| `[x]` | 阶段 6 | `src/memory/manager.py` 同步入口 | `new_session/process_user_input/add_user_message/add_assistant_message` 等旧同步入口已删除 | 测试已迁移到 async owner | 无 |
| `[x]` | 阶段 6 | `src/memory/sessions.py` 同步包装 | 旧同步包装和模块本地 event-loop helper 已删除 | session memory 测试通过 | 无 |
| `[x]` | 阶段 6 | `src/memory/vector_retriever.py::retrieve_related_memories` | 同步 wrapper 和本地 event-loop helper 已删除 | retriever 测试通过 | 无 |
| `[x]` | 阶段 7 | `src/prompts/__init__.py` 过重包初始化 | 运行时逻辑已迁移到 `src/prompts/runtime.py`，`__init__.py` 清空 | prompts 测试 patch 目标已迁移 | 无 |
| `[x]` | 阶段 7 | `src/prompts/memory_prompts.py` | 已抽取共享 prompt helper，降低重复上下文拼装 | prompts/memory 测试通过 | 后续只在语义调整时继续拆分 |
| `[x]` | 阶段 8 | `src/llm/memory_client.py` 同步生成方法 | 同步 prompt execution 和公开 sync repair/compaction 方法已删除 | LLM/memory 测试通过 | 无 |
| `[x]` | 阶段 8 | `src/llm/chat_client.py` 同步 memory generation facade | 不再需要的 public sync facade 已删除 | LLM 测试通过 | 无 |
| `[x]` | 阶段 9 | `src/llm/embedding.py::get_embedding` | 同步 embedding wrapper 已删除 | embedding 相关测试已更新 | 发布前审计外部脚本是否仍引用 |
| `[x]` | 阶段 9 | `src/llm/reranker.py::rerank` | 同步 rerank wrapper 已删除 | reranker 相关测试已更新 | 发布前审计外部脚本是否仍引用 |
| `[x]` | 阶段 9 | `src/llm/chat_client.py::close` | public sync close facade 已删除，保留 async close | LLM 测试通过 | 发布前审计外部脚本是否仍引用 |
| `[x]` | 阶段 9 | `src/memory/seele.py` repair/compaction 业务实现 | 已统一到 async 实现；同步入口只剩启动期薄 wrapper | focused tests 与全量测试通过 | 无 |
| `[x]` | 阶段 9 | `src/llm/chat_client.py::LLMClient._get_event_loop` | 已删除，event-loop 处理移到共享 `utils.async_utils` | `_get_event_loop` 无剩余引用 | 无 |
| `[x]` | 阶段 9 | `src/memory/seele.py::_write_complete_seele_json_async` | 已补 async 完整写入与 fallback compaction 回归测试 | `tests/test_memory.py` focused tests 通过 | 无 |
| `[x]` | 阶段 9 | `CoreBot` 启动/bootstrap | 已新增 `CoreBot.create_async()` / `initialize_async()`，Telegram main 改为 async bootstrap | main、core runtime、memory focused tests 与全量测试通过 | 无 |
| `[x]` | 阶段 9 | `src/memory/seele.py` 同步 bootstrap/schema repair wrapper | 已删除；schema repair、compaction、完整写入均走 async owner | `src` 无 `run_sync` 调用方 | 无 |

## 保留项与原因

| 状态 | 项目/符号 | 当前结果 | 保留原因 | 后续条件 |
|---|---|---|---|---|
| `[!]` | 数据库层同步 API | 未 async 化 | SQLite 层按项目说明不需要 async 化 | 本轮不处理 |
| `[!]` | `ToolExecutor`、`ToolRegistry`、`ToolSafetyPolicy`、`ToolTraceService` | 保留 | 它们有清晰职责，不属于冗余壳 | 不应作为精简目标 |
| `[!]` | `ConversationService` | 保留 | 虽由 `CoreBot` 持有，但承担完整对话编排职责 | 暂不折叠 |

## 本轮完成的后续任务

1. `[x]` 已为 `src/memory/seele.py` 的 async fallback 路径补充回归测试，覆盖 `_write_complete_seele_json_async` 和 async fallback compaction。
2. `[x]` 已将 repair/compaction 业务实现统一到 async 方法，并删除启动期同步 wrapper。
3. `[x]` 已删除 `LLMClient._get_event_loop`，不再让 LLM client 保存同步兼容事件循环状态。
4. `[x]` 已完成启动期 `Seele` schema validation/repair async 化：`CoreBot.__init__` 不再执行 schema bootstrap，Telegram main 通过 `CoreBot.create_async()` 显式初始化。
5. `[x]` 已将项目文档索引同步到当前 docs 文件集合，并标注 `ARCHITECTURE_REFACTOR_PLAN.md` 为历史计划。

## 未来可选任务

1. 发布前审计外部脚本、README、示例和私有运维脚本中是否仍引用已删除 public API，例如 `EmbeddingClient.get_embedding`、`RerankerClient.rerank`、`LLMClient.close`、包级 `prompts.*`。
2. 若后续继续整理 prompt，不做纯 cosmetic 拆分；只有在语义调整、测试隔离或复用收益明确时再拆 `src/prompts/memory_prompts.py`。

## 验收清单

- `[x]` 无生产代码引用已删除符号。
- `[x]` 无测试只为了旧兼容 API 存在而保留。
- `[x]` Telegram 启动、消息处理、文件处理、审批、调度、MCP 工具调用相关测试纳入全量测试。
- `[x]` memory/llm 主流程不再维护重复 sync/async 业务实现。
- `[x]` ruff 通过。
- `[x]` 全量 pytest 通过，最近结果为 `619 passed`。
- `[x]` `LLMClient._get_event_loop` 已删除。
- `[x]` `src/memory/seele.py` 同步 repair/compaction/schema bootstrap wrapper 已删除。
- `[x]` `src` 中无 `run_sync` 调用方；`run_sync` 仅作为共享工具保留并由自身单元测试覆盖。

## 后续任务执行规则

- 后续任务开始前先阅读本文件，以阶段索引、`[!]` 保留项和“未来可选任务”为入口。
- 删除任何保留桥接前，先补对应回归测试。
- 若发现新的冗余项，追加到“分阶段进度”或“保留项与原因”，不要只在聊天记录中说明。
- 每轮结束都更新“当前验证状态”和“最近一次全量测试结果”。
