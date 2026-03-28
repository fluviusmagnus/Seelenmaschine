# Seelenmaschine Architecture Refactor Plan

## Goal

This document proposes an incremental refactor plan for the Seelenmaschine codebase.

The goal is not to rewrite the project from scratch, but to gradually improve:

- module boundaries
- maintainability
- testability
- dependency direction
- readability of the main execution flow

This plan follows the currently preferred top-level structure:

- `core`
- `memory`
- `prompts`
- `llm`
- `adapter`
- `tools`
- `utils`


## Short Execution Checklist

If we need a compact version of this plan during implementation, use this list:

1. Extract Telegram formatter from `adapter/telegram/handlers.py`
2. Extract approval workflow into `core`
3. Extract conversation orchestration from `adapter/telegram/handlers.py`
4. Extract tool registry and tool executor responsibilities
5. Split the prompt entrypoints and memory profile storage concerns
6. Split the memory manager into focused memory modules
7. Split the LLM chat layer into focused chat and memory-generation modules
8. Reduce new direct `Config` usage in extracted modules

Implementation rule:

- preserve behavior
- keep old wrappers temporarily when useful
- run focused tests after each step


## Current Status

The first refactor wave is largely complete.

Completed structural work:

- extracted Telegram formatting from the Telegram handler layer
- extracted approval workflow into `core/approval.py`
- extracted conversation orchestration into `core/conversation.py`
- moved shared configuration into `core/config.py` and consolidated tool orchestration into `core/tools.py`
- consolidated prompt entrypoints in `prompts/__init__.py`
- split the memory manager into focused memory services
- moved `ContextWindow`, `MemoryRetriever`, and `MemoryManager` fully under `memory/`
- split the LLM chat layer into message building, request execution, tool-loop, and memory-generation helpers
- extracted bootstrap and Telegram application setup from the entrypoint/bot layer
- extracted scheduled message sending, file upload handling, session command handling, proactive file delivery, and tool setup from Telegram adapter code
- split Telegram command and message flows into `adapter/telegram/commands.py` and `adapter/telegram/messages.py`
- moved Telegram adapter modules under `adapter/telegram/`
- removed the old `tg_bot/` package after updating runtime imports and tests

Current file sizes after this wave:

- `src/adapter/telegram/handlers.py`: 631 lines
- `src/memory/manager.py`: 528 lines
- `src/llm/chat_client.py`: 503 lines
- `src/adapter/telegram/app.py`: Telegram adapter entrypoint and runtime module
- `src/prompts/__init__.py`: package entrypoint for prompt helpers

Interpretation:

- `bot.py` is now comfortably thin, and prompt entrypoints no longer live in a stray `system.py`
- `memory/manager.py` and `llm/chat_client.py` are much healthier and mostly act as facades plus a few shared helpers
- `handlers.py` is still one of the larger files, but command handling, message/file flows, and tool runtime setup have already been moved out
- `adapter/telegram/` is now the canonical home for Telegram-specific modules
- the old Telegram package split has been removed, so runtime structure now matches the intended directory shape much more closely
- `core/` now owns runtime configuration and tool orchestration, so `tools/` is reserved for concrete LLM-callable capabilities

Recommended stop point for this wave:

- avoid splitting `handlers.py` further unless new Telegram features force clearer boundaries
- prefer continuing future cleanup by renaming or relocating whole responsibilities, not by creating many tiny one-off modules


## Design Principles

### 1. Keep `utils` small and low-level

`utils` should only contain generic helpers with very weak business meaning, such as:

- logging helpers
- time formatting/parsing helpers
- text cleanup helpers
- small path helpers

Modules with state, workflow logic, approval rules, external protocol handling, or user-facing product semantics should not go into `utils`.

### 2. Keep external integrations out of `core`

`core` should coordinate application flow, but should not directly own Telegram formatting details, prompt file persistence, or MCP protocol details.

### 3. Keep prompt construction separate from persistence

`prompts` should build prompt strings only.
It should not own `seele.json` storage logic.

### 4. Keep memory logic cohesive

The memory system is important enough to deserve its own top-level module.
Session handling, context window behavior, retrieval, summary triggers, and long-term memory updates should live in the `memory` area, with clearer internal sub-boundaries.

### 5. Use `tools` for LLM-callable capabilities

If a capability is exposed to the model as a tool, it belongs in `tools`.
That includes MCP-related tool integration in this project.

### 6. Prefer incremental migration

Each refactor step should be independently mergeable and should keep behavior stable.
Avoid a large "big bang" move.


## Proposed Top-Level Responsibilities

### `core`

Application orchestration and workflow coordination.

Examples:

- message processing flow
- scheduled task processing flow
- approval flow
- session orchestration
- tool execution coordination

`core` answers: "How does the app behave end-to-end?"

### `memory`

Memory-domain logic and persistence related to conversation memory.

Examples:

- context window
- session lifecycle
- summary trigger logic
- retrieval logic
- memory database access
- long-term memory profile update flow

`memory` answers: "How is conversational memory stored, summarized, recalled, and updated?"

### `prompts`

Prompt builders only.

Examples:

- system prompt construction
- summary prompt construction
- memory update prompt construction

`prompts` answers: "What text do we send to the model?"

### `llm`

Model-facing clients and AI-specific gateways.

Examples:

- chat completion client
- embedding client
- reranker client
- memory generation client

`llm` answers: "How do we call models?"

### `adapter`

Adapters for external application interfaces.

Examples:

- Telegram bot integration
- Telegram formatting / message sending bridge

`adapter` answers: "How does the app connect to outside interfaces?"

### `tools`

LLM-callable tool definitions, registries, tool execution wrappers, and capability modules.

Examples:

- shell tool
- file I/O tool
- file search tool
- memory search tool
- scheduled task tool
- MCP integration for tool exposure
- Telegram file send tool

`tools` answers: "What capabilities can the model invoke?"

### `utils`

Small generic helpers without meaningful domain ownership.

Examples:

- logger
- time helpers
- text helpers


## Target Directory Shape

This is a suggested target shape, not a mandatory one-shot move:

```text
src/
  core/
    config.py
    conversation.py
    approval.py
    tools.py
    session_service.py

  memory/
    context.py
    manager.py
    recall.py
    vector_retriever.py
    sessions.py
    summaries.py
    seele.py

  prompts/
    system_prompt.py
    memory_prompts.py

  llm/
    chat_client.py
    memory_client.py
    request_executor.py
    tool_loop.py
    message_builder.py
    embedding.py
    reranker.py

  adapter/
    telegram/
      app.py
      bot.py
      commands.py
      files.py
      handlers.py
      formatter.py
      messages.py
      scheduled_sender.py

  tools/
    mcp_client.py
    shell.py
    file_io.py
    file_search.py
    memory_search.py
    scheduled_tasks.py
    send_telegram_file.py
    tool_trace.py

  utils/
    logger.py
    text.py
    time.py
    path.py

  config.py
  main_telegram.py
```


## Current Pain Points

### 1. `adapter/telegram/handlers.py` is overloaded

It currently mixes:

- Telegram update handling
- dependency construction
- tool registration
- tool dispatch
- approval workflow
- response formatting
- file handling
- main conversation orchestration
- scheduled task orchestration

This makes it difficult to reason about or change safely.

### 2. `memory/manager.py` is still partially overloaded

It currently mixes:

- context window logic
- session lifecycle
- retrieval orchestration
- summary creation
- long-term memory update logic
- fallback JSON generation
- `seele.json` update behavior

This should be split into smaller, more focused components.

### 3. Prompt entrypoints and storage helpers were previously mixed together

It currently handles both:

- prompt building
- loading and updating `seele.json`

Those responsibilities should be separated.

### 4. the LLM chat layer was originally too broad

It currently handles:

- normal chat
- tool loop
- summary generation
- memory update generation
- complete memory JSON generation
- sync and async wrappers

This makes the client harder to test and evolve.

### 5. Global `Config` usage is very wide

This is acceptable for now, but should gradually be reduced in newly extracted services.


## File Migration Proposal

### Immediate mapping proposal

- `src/memory/context.py` is now the home of the context window types
- `src/core/database.py` -> `src/memory/database.py`
- `src/memory/vector_retriever.py` is now the home of vector retrieval logic
- `src/memory/manager.py` -> split across:
  - `src/memory/sessions.py`
  - `src/memory/summaries.py`
  - `src/memory/recall.py`
  - `src/memory/seele.py`
- prompt entrypoints now live in `src/prompts/__init__.py`, with implementation split across:
  - `src/prompts/system_prompt.py`
  - `src/prompts/memory_prompts.py`
- `src/adapter/telegram/app.py` is now the Telegram bot entry module
- `src/adapter/telegram/handlers.py` -> split across:
  - `src/adapter/telegram/formatter.py`
  - `src/core/conversation.py`
  - `src/core/approval.py`
  - `src/core/tools.py`
- `src/tools/mcp_client.py` -> `src/tools/mcp.py`
- `src/llm/chat_client.py` -> split across:
  - `src/llm/chat_client.py`
  - `src/llm/memory_client.py`
  - `src/llm/request_executor.py`
  - `src/llm/tool_loop.py`
  - `src/llm/message_builder.py`


## Recommended Refactor Phases

## Phase 1: Write down boundaries and prepare tests

### Goal

Stabilize the system before moving code.

### Tasks

- document module responsibilities
- identify hot paths that must remain behaviorally stable
- add or strengthen tests for:
  - normal message processing
  - scheduled task processing
  - tool execution and approval flow
  - `seele.json` update and fallback flow
  - Telegram formatting and segmentation
  - session create/reset behavior

### Expected result

Refactor work can proceed with lower regression risk.


## Phase 2: Extract Telegram formatting from handlers

### Goal

Reduce `handlers.py` size without changing behavior.

### Tasks

- create `adapter/telegram/formatter.py`
- move response formatting logic there
- move message segmentation logic there
- keep `handlers.py` as a thin caller

### Expected result

The Telegram-specific presentation layer becomes isolated and easier to test.


## Phase 3: Extract approval flow into `core`

### Goal

Remove stateful approval logic from the Telegram handler.

### Tasks

- create `core/approval.py`
- move pending approval state and lifecycle logic there
- expose simple methods like:
  - `register_request(...)`
  - `approve_pending(...)`
  - `reject_or_timeout_pending(...)`
- keep Telegram command handlers as thin adapters

### Expected result

Approval becomes reusable and testable independently from Telegram transport code.


## Phase 4: Extract conversation orchestration from handlers

### Goal

Move the main business flow out of Telegram interface code.

### Tasks

- create `core/conversation.py`
- move `_process_message(...)`
- move `_process_scheduled_task(...)`
- move high-level orchestration of:
  - saving user input
  - retrieving memory
  - enabling relevant tools
  - calling the LLM
  - persisting assistant output

### Expected result

Telegram becomes an adapter, not the owner of core application flow.


## Phase 5: Extract tool registration and dispatch

### Goal

Separate "tool system management" from message handling.

### Tasks

- create `core/tools.py`
- move tool registration code out of the Telegram handler
- move tool dispatch and dangerous command approval integration out of the Telegram handler

### Expected result

Tooling becomes a more explicit subsystem instead of being embedded in one large class.


## Phase 6: Separate prompt entrypoints from prompt builders

### Goal

Separate prompt generation from `seele.json` storage/update responsibilities.

### Tasks

- create `prompts/system_prompt.py`
- create `prompts/memory_prompts.py`
- move prompt builders into those files
- create `memory/profile_store.py` for:
  - load `seele.json`
  - update `seele.json`
  - cache invalidation

### Expected result

Prompt code becomes easier to reason about and memory profile persistence gets its own home.


## Phase 7: Split the memory manager

### Goal

Separate core memory domain responsibilities.

### Suggested internal split

#### `memory/manager.py`

Owns:

- session lifecycle
- context window updates
- memory retrieval entry points
- assistant/user message persistence coordination

#### `memory/summaries.py`

Owns:

- summary generation calls
- summary persistence
- summary trigger helpers

#### `memory/profile_store.py`

Owns:

- long-term profile load/update
- patch application
- complete JSON fallback generation path

### Expected result

The memory subsystem becomes internally modular rather than centered on one very large class.


## Phase 8: Split the LLM chat layer

### Goal

Separate chat functionality from memory-generation functionality.

### Suggested split

#### `llm/chat_client.py`

Owns:

- normal conversation requests
- tool call loop
- assistant message extraction
- tool response sanitization

#### `llm/memory_client.py`

Owns:

- summary generation
- memory patch generation
- complete JSON generation

### Expected result

Model access becomes easier to understand and maintain.


## Phase 9: Reduce direct global `Config` coupling

### Goal

Gradually reduce hidden dependencies.

### Tasks

- keep `Config` for compatibility
- allow newly extracted services to accept explicit config or selected values
- prefer constructor injection for new modules
- avoid new code that imports `Config` deep inside helper methods unless necessary

### Expected result

Testing and future architecture changes become easier.


## Dependency Direction Rules

The following rules should guide future changes:

- `adapter` may call `core`
- `core` may call `memory`, `llm`, and `tools`
- `memory` may call `llm` for model-backed memory operations
- `prompts` should not call `adapter`
- `prompts` should not own persistence logic
- `utils` should not depend on high-level modules
- `tools` may depend on `utils`, `llm`, or dedicated services as needed
- `adapter` should avoid owning business rules that belong in `core`


## What Should Not Be Put Into `utils`

To keep the structure healthy, avoid putting these into `utils`:

- approval workflow
- MCP client logic
- Telegram transport logic
- tool registry / tool dispatch logic
- file tools with workspace/business constraints
- long-term memory profile storage

These modules are too stateful or too semantically important to be treated as generic utilities.


## Recommended First PR Sequence

To minimize risk, the first pull requests should be:

1. Extract Telegram formatter
2. Extract approval service
3. Extract conversation service
4. Extract tool registry and tool executor
5. Split prompt entrypoints from prompt builders
6. Split `memory.py`
7. Split the LLM chat layer

This sequence keeps the highest-risk behavior changes for later, after the structure is already improving.


## Definition of Done for Each Refactor Step

Each step should satisfy most of the following:

- behavior remains unchanged
- tests still pass
- moved code has a clearer owner
- the old source file becomes smaller
- the new module name matches its responsibility
- dependency direction becomes more obvious
- no new cross-cutting logic is hidden inside `utils`


## Out of Scope for the First Refactor Wave

The following are useful but should not block the first refactor wave:

- replacing `Config` with a full DI container
- redesigning all database abstractions
- changing the user-facing Telegram behavior
- rewriting prompts for quality rather than structure
- replacing the current memory strategy


## Final Recommendation

The best strategy is to treat this as a structural cleanup of a working system.

Do not optimize for elegance first.
Optimize for:

- smaller ownership boundaries
- fewer overloaded classes
- clearer data and control flow
- safer future feature work

If this plan is approved, the first implementation step should be extracting Telegram formatting and approval management from the current handler, because that gives immediate clarity with relatively low migration risk.
