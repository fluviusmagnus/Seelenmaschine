# TODO

## 当前工作流：sync/async 冗余治理（完整计划）

目标：把项目收敛为 **async-first** 架构，避免在 `core / memory / llm / tools` 内部长期维护 sync/async 两套主体逻辑。

### 总体原则

- 核心业务逻辑只保留一份主实现
- async 作为主实现
- sync 仅作为薄包装（兼容层）
- 所有 sync wrapper 统一事件循环与报错策略
- 补测试，防止 sync/async 行为再次分叉

### 分阶段计划

#### Phase 1：统一基础调用约定

- [x] 新增统一 async/sync wrapper 工具（建议放在 `src/utils/async_utils.py`）
- [x] 提供统一能力：
      - `ensure_not_in_async_context(...)`
      - `run_sync(...)`
- [x] 将以下模块改为使用统一 helper，而不是各自手写 `run_until_complete`：
      - `src/llm/memory_client.py`
      - `src/llm/embedding.py`
      - `src/llm/reranker.py`
      - `src/tools/mcp_client.py`
      - `src/llm/chat_client.py`

#### Phase 2：先收敛重复最重的 memory 主流程

- [x] 重构 `src/memory/sessions.py`
      - 收敛以下重复对：
        - `new_session` / `new_session_async`
        - `add_user_message` / `add_user_message_async`
        - `add_assistant_message` / `add_assistant_message_async`
        - `check_and_create_summary` / `check_and_create_summary_async`
      - 目标：sync 只做包装，主流程只保留一份

- [x] 重构 `src/memory/vector_retriever.py`
      - 收敛 `retrieve_related_memories` / `retrieve_related_memories_async`
      - 抽公共 helper：summary/conversation 组装、rerank 结果映射、日志与截断策略

- [x] 重构 `src/memory/seele.py`
      - 收敛以下重复对：
        - `_generate_with_llm_client` / `_generate_with_llm_client_async`
        - `_apply_generated_patch` / `_apply_generated_patch_async`
        - `_handle_patch_update_error` / `_handle_patch_update_error_async`
        - `_retry_complete_json_generation` / `_retry_complete_json_generation_async`
        - `update_long_term_memory` / `update_long_term_memory_async`
        - `fallback_to_complete_json` / `fallback_to_complete_json_async`
      - 目标：patch/fallback/retry 只保留一份主控制流

#### Phase 3：收缩 manager / recall 门面层

- [x] 重构 `src/memory/manager.py`
      - 改成 async-first 门面
      - sync 方法仅保留薄包装
      - 删除只做 sync->sync / async->async 转发的重复私有中间层

- [x] 重构 `src/memory/recall.py`
      - 收敛 `process_user_input` / `process_user_input_async`
      - 保持 async 版本的 embedding 复用优势

#### Phase 4：统一基础客户端层风格

- [x] `src/llm/embedding.py`
      - async 为真实实现
      - sync 使用统一 helper
      - `close()` 增加 async-context guard，和 `get_embedding()` 保持一致

- [x] `src/llm/reranker.py`
      - async 为真实实现
      - sync 使用统一 helper
      - `close()` 增加 async-context guard

- [x] `src/tools/mcp_client.py`
      - `get_tools_sync()` / `call_tool_sync()` 改为统一 helper
      - 明确禁止在 async context 中调用 sync wrapper
      - 进一步审计是否仍需要公开 sync API

- [x] `src/llm/memory_client.py`
      - 去掉文件内重复的 wrapper 工具实现
      - 改为复用公共 helper

- [x] `src/llm/chat_client.py`
      - 保留 async 主接口
      - sync 保持 thin forwarding
      - `close()` 使用统一 wrapper 风格

#### Phase 5：清理不必要的 sync API 表面积

- [x] 审计下列 sync API 的实际调用点：
      - `MemoryManager.*` sync 入口
      - `VectorRetriever.retrieve_related_memories`
      - `Seele.generate_memory_update`
      - `Seele.generate_complete_memory_json`
      - `Seele.update_long_term_memory`
      - `MCPClient.get_tools_sync`
      - `MCPClient.call_tool_sync`
      - `EmbeddingClient.get_embedding`
      - `RerankerClient.rerank`
- [ ] 删除无外部必要性的 sync API，或降为内部兼容接口
      - [x] `MCPClient.get_tools_sync()` / `MCPClient.call_tool_sync()` 已改为 deprecated compatibility shim；主运行时不再依赖它们
      - [ ] 继续评估 memory / llm 层 sync API 是否还能进一步移除

### 测试计划

- [x] 为统一 wrapper 增加测试：
      - sync 方法在普通上下文可调用
      - sync 方法在 async context 中报清晰错误
- [x] 为 memory 主流程增加回归测试：
      - session close summary 生成
      - assistant message 触发 summary 的时机
      - long-term memory patch -> fallback -> retry 流程
      - retrieval / rerank / 截断行为不变
- [x] 跑重点测试集：
      - `tests/test_embedding.py`
      - `tests/test_reranker.py`
      - `tests/test_mcp_client.py`
      - `tests/test_memory*.py`
      - `tests/test_llm*.py`

### 当前进度补充

- [x] 已运行针对性测试集，当前通过：`110 passed`
- [x] 已继续审计剩余 sync API：MCP sync API 现以 deprecated shim 形式保留，兼顾安全与兼容；其余 memory / llm sync API 目前仍被测试与兼容入口使用
- [x] 已明确后续约束方向：新代码默认采用 async-first + thin sync wrapper，不再新增双轨主体逻辑

### 注意事项

- [ ] 这次重构的重点是“消除重复逻辑”，**不是** 把 SQLite 层一起改成异步
- [ ] 先把 sync 版本改成 thin wrapper，再决定是否删除，避免一次性破坏兼容性
- [ ] 对 `seele.py` 这类 fallback 密集区，优先补 focused regression tests 再继续压缩

