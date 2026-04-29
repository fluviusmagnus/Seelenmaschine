# Debug Log Audit

This document tracks noisy debug logs and their ownership. The goal is to keep
`DEBUG_SHOW_FULL_PROMPT=true` useful for deep diagnosis while avoiding duplicate
copies of the same prompt, response, tool call, or persisted assistant text.

## Ownership Rules

- `src/llm/request_executor.py` owns single LLM request/response logging.
- `src/llm/tool_loop.py` owns tool-loop progress and tool response payloads.
- `src/core/conversation.py` owns persistence progress summaries.
- `src/core/tools.py` owns actual tool execution results.
- External terminal noise, such as PowerShell profile errors, is out of scope.

## Audit Decisions

| Area | Previous behavior | Decision | Test coverage |
| --- | --- | --- | --- |
| LLM normalized response | Full mode logged tool calls/content, then logged the normalized response containing the same data again. | Keep full tool call/content logs in `request_executor.py`; remove full normalized response dump. | `tests/test_llm.py::TestDebugLogReduction::test_request_executor_logs_full_response_once_when_full_prompt_enabled` |
| Tool-loop assistant text | Tool loop logged intermediate assistant text even though request logging already owns response content. | Do not log assistant text in tool loop; keep callback behavior unchanged. | `tests/test_llm.py::TestDebugLogReduction::test_tool_loop_skips_intermediate_preview_when_full_prompt_enabled` |
| Tool call arguments | Tool loop logged full tool call JSON while request logging already logs model tool calls. | Tool loop logs only the tool name before execution. | `tests/test_llm.py::TestDebugLogReduction::test_tool_loop_logs_full_tool_details_when_full_prompt_enabled` |
| Tool-loop final text | Tool loop logged final text and conversation events in full mode. | Keep only final loop counts; request logging owns final response content. | `tests/test_llm.py::TestDebugLogReduction::test_tool_loop_does_not_repeat_final_text_when_full_prompt_enabled` |
| Conversation persistence | Conversation service logged final response preview and every assistant message preview before persistence. | Log counts and final text length only; do not repeat assistant text. | Covered by existing conversation persistence tests and LLM log reduction tests. |
| Tool execution args | Tool executor logged full parsed arguments at info level. | Log an arguments preview using the existing trace preview limit. | Covered by existing tool execution behavior tests. |
| Seele complete JSON preview | Seele JSON diagnostics emitted length, head, and tail as three debug lines. | Collapse into one diagnostics line. | Covered by existing Seele JSON parsing behavior tests. |

## Notes

- `DEBUG_SHOW_FULL_PROMPT=true` still emits full prompt and full LLM response
  content from `request_executor.py`.
- Full tool result payloads remain in `tool_loop.py`, because they are not the
  same data as model responses and are useful for diagnosing tool reinjection.
- The recurring `oh-my-posh` PowerShell startup error is terminal environment
  noise, not an application log; this cleanup intentionally does not modify it.
