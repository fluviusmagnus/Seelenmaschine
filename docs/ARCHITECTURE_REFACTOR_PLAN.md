# Seelenmaschine Architecture Refactor Plan

## Goal

This document is the current working refactor plan for the Seelenmaschine codebase.

It is not a historical note. It should reflect:

- the architecture we are aiming for
- the refactor work already completed
- the remaining structural problems
- the exact order of the next cleanup steps

Primary goals:

- make `core` the real system owner
- make `adapter` a thin I/O boundary
- reduce overloaded files and fake facades
- improve testability by making ownership explicit
- keep behavior stable while structure changes


## Current Architectural Rule

The most important rule is:

- `adapter` talks to the outside world
- `core` owns system behavior

This is the rule every future refactor step should follow.


## Adapter/Core Boundary

### `core` owns

- the real runtime root object
- conversation orchestration
- session lifecycle orchestration
- tool runtime, tool registry, tool tracing, tool safety policy, and tool executor wiring
- memory, scheduler, approval, and database coordination
- any state or workflow that should still exist if Telegram disappears

Practical test:

- if the code would still make sense in CLI, web, or another chat adapter, it belongs in `core`

### `adapter` owns

- Telegram `Application` setup and handler registration
- Telegram command, message, and file ingress
- Telegram formatting and segmented delivery
- typing indicators
- Telegram-specific proactive sending
- Telegram approval/status display wiring
- conversion between Telegram `Update` objects and core calls

Practical test:

- if the code depends on Telegram update/message semantics or Telegram output formatting, it belongs in `adapter`

### Boundary questions

When deciding where code should live, ask:

1. Would this still exist if Telegram were removed tomorrow?
2. Is this describing system behavior, or just platform I/O?

If the answer is "yes" to the first question, or "system behavior" to the second, move it toward `core`.


## Current Status

The first large refactor wave is complete, and the second wave is underway.

### Completed structural work

- introduced [src/core/bot.py](../src/core/bot.py) as the primary core dependency owner and emerging runtime root
- moved approval lifecycle into `core/approval.py`
- moved conversation orchestration into `core/conversation.py`
- moved session lifecycle into `core/session_service.py`
- consolidated tool safety, trace, registry, and runtime bookkeeping into `core/tools.py`
- moved tool-host ownership under `CoreBot`
- renamed the Telegram runtime shell from `bot.py` to [src/adapter/telegram/adapter.py](../src/adapter/telegram/adapter.py)
- removed [src/adapter/telegram/app.py](../src/adapter/telegram/app.py)
- split Telegram responsibilities across:
  - [src/adapter/telegram/commands.py](../src/adapter/telegram/commands.py)
  - [src/adapter/telegram/messages.py](../src/adapter/telegram/messages.py)
  - [src/adapter/telegram/files.py](../src/adapter/telegram/files.py)
  - [src/adapter/telegram/formatter.py](../src/adapter/telegram/formatter.py)
  - [src/adapter/telegram/delivery.py](../src/adapter/telegram/delivery.py)
  - [src/adapter/telegram/tool_bridge.py](../src/adapter/telegram/tool_bridge.py)
- moved file-upload extraction and file-event message construction from `messages.py` into `files.py`
- removed the generic handler component resolver/dispatcher patterns from `adapter/telegram/handlers.py` in favor of explicit component accessors
- simplified `adapter/telegram/messages.py` and `adapter/telegram/adapter.py` to depend on direct adapter-owned helpers instead of extra indirection
- removed a large amount of duplicated sync/async memory and chat wrapper logic
- removed many placeholder tests and empty skipped tests

### Meaningful current ownership

- `CoreBot` owns:
  - config
  - db
  - embedding client
  - reranker client
  - memory
  - scheduler
  - llm client
  - conversation service
  - session service
  - tool host
  - tool runtime state

- `ToolRuntimeState` now owns the mutable tool-side bookkeeping:
  - tool trace store
  - tool trace query tool
  - tool trace service
  - registry service
  - legacy registry mirror
  - safety policy
  - memory search tool
  - scheduled task tool
  - send Telegram file tool
  - MCP client
  - MCP connected flag

- `MessageHandler` is no longer the true owner of that tool state
- however, it still acts as the main adapter-facing compatibility shell and runtime access surface during the transition

### Current file sizes

Current line counts:

- `src/adapter/telegram/handlers.py`: 511
- `src/core/bot.py`: 254
- `src/adapter/telegram/messages.py`: 193
- `src/core/tools.py`: 689
- `src/llm/chat_client.py`: 563
- `src/memory/manager.py`: 352

Interpretation:

- `handlers.py` is smaller than before, but still too large for a pure Telegram boundary object
- `core/tools.py` has become the real center of tool runtime ownership, which is directionally correct, but it is now one of the next major complexity hotspots
- `memory/manager.py` is much healthier than before
- `messages.py` is now much closer to a valid adapter module: it handles message ingress, not file storage mechanics


## Current Pain Points

### 1. `adapter/telegram/handlers.py` still has too much skeleton

Even after moving real ownership out, it still carries:

- a large initialization sequence
- several methods that only forward to another object

This means the file is no longer the old owner, but it still acts like a large composition shell.

### 2. `core/tools.py` is now broad

This is partly healthy, because tool ownership belongs in `core`.
But the file now combines:

- safety policy
- registry
- runtime state
- runtime setup
- trace service
- executor
- MCP merge logic

This is likely the next major structural split point inside `core`.

### 3. `CoreBot` still exposes low-level creation methods instead of enough high-level capabilities

`CoreBot` already owns the right subsystems, but adapters still sometimes reach into:

- service getters
- tool runtime getters
- compatibility properties

The next step is to expose higher-level bot capabilities so adapters do less assembly work.

This means `CoreBot` should be treated today as:

- the primary core dependency owner
- an emerging runtime root
- not yet a fully mature high-level application facade

So future cleanup should reduce adapter-side orchestration first, then tighten this description further.

### 4. Adapter-side compatibility layers still exist for tests and transition safety

Some compatibility properties and fallback paths still exist because:

- tests were historically centered on `MessageHandler`
- a number of mocks still assume old boundaries

These should be reduced deliberately, not all at once.

### 5. `llm/chat_client.py` and `core/tools.py` are now stronger candidates for the next cleanup wave than `messages.py`

`messages.py` is no longer the biggest problem.
The deeper complexity is now concentrated more in:

- [src/core/tools.py](../src/core/tools.py)
- [src/llm/chat_client.py](../src/llm/chat_client.py)
- the remaining controller skeleton in [src/adapter/telegram/handlers.py](../src/adapter/telegram/handlers.py)


## Updated Assessment of Telegram Modules

### `messages.py`

Current judgment:

- mostly reasonable now
- no longer a major ownership hotspot
- still contains transition scaffolding that should shrink later

It should remain responsible for:

- Telegram text message ingress
- scheduled message ingress
- forwarding text payloads into the conversation pipeline
- sending formatted multi-segment Telegram responses

It should not regain responsibility for:

- file metadata extraction
- file saving and download mechanics
- direct construction of core services except narrow compatibility fallbacks

It should also gradually lose:

- handler-callable resolution shims
- fallback service lookup paths kept only for historical tests and transition safety

### `files.py`

Current judgment:

- correct as a dedicated Telegram file adapter

It should own:

- attachment extraction
- upload normalization
- save path generation
- Telegram download mechanics
- Telegram proactive file sending
- file event message construction

### `delivery.py`

Current judgment:

- still reasonable as a shared Telegram transport helper

It should remain a small, transport-oriented utility module for:

- typing indicators
- segmented text sending
- HTML-first fallback delivery behavior

### `handlers.py`

Current judgment:

- directionally improved, but still too large

It should continue shrinking toward:

- Telegram controller / boundary object
- adapter entrypoint that delegates to commands, messages, tool bridge, and `CoreBot`

It should stop behaving like:

- a giant compatibility shell
- a pseudo composition root
- a place that mirrors core-owned state


## Target Top-Level Responsibilities

### `core`

Owns application behavior and runtime state.

Examples:

- `CoreBot`
- conversation flow
- session flow
- approval flow
- tool runtime and execution flow

Question answered by `core`:

- "How does the system behave?"

### `memory`

Owns memory-domain behavior and persistence coordination.

Examples:

- context handling
- session archive logic
- recall and summaries
- profile / Seele-related memory behavior

Question answered by `memory`:

- "How is conversational memory stored, recalled, summarized, and updated?"

### `llm`

Owns model-facing gateways and AI request orchestration.

Examples:

- chat requests
- tool loop requests
- embeddings
- reranking
- memory generation requests

Question answered by `llm`:

- "How do we talk to models?"

### `adapter`

Owns transport and platform translation.

Examples:

- Telegram adapter
- Telegram commands/messages/files
- Telegram delivery formatting and bridge helpers

Question answered by `adapter`:

- "How does this system connect to Telegram?"

### `tools`

Owns concrete LLM-callable capabilities.

Examples:

- shell tool
- file tools
- search tools
- memory search tool
- scheduled task tool
- MCP client
- Telegram file send tool

Question answered by `tools`:

- "What capabilities can the model invoke?"

### `utils`

Owns only small generic helpers.

Examples:

- logger
- time helpers
- text helpers


## Current Target Directory Shape

This reflects the current intended shape more accurately than the older draft.

```text
src/
  core/
    approval.py
    bot.py
    config.py
    conversation.py
    database.py
    scheduler.py
    session_service.py
    tools.py

  memory/
    context.py
    manager.py
    recall.py
    seele.py
    sessions.py
    summaries.py
    vector_retriever.py

  prompts/
    __init__.py
    memory_prompts.py
    system_prompt.py

  llm/
    chat_client.py
    embedding.py
    memory_client.py
    message_builder.py
    request_executor.py
    reranker.py
    tool_loop.py

  adapter/
    telegram/
      __init__.py
      adapter.py
      commands.py
      delivery.py
      files.py
      formatter.py
      handlers.py
      messages.py
      scheduled_sender.py
      tool_bridge.py

  tools/
    file_io.py
    file_search.py
    mcp_client.py
    memory_search.py
    scheduled_tasks.py
    send_telegram_file.py
    shell.py
    tool_trace.py

  utils/
    logger.py
    text.py
    time.py

  main_telegram.py
```


## Execution Rules For The Next Phase

These rules are strict and should guide future changes:

1. Move ownership to `core` before introducing new adapter helpers.
2. Do not create new adapter-side host/manager/runtime layers for core behavior.
3. If a module in `adapter` starts accumulating stateful workflow logic, stop and re-evaluate.
4. Prefer deleting obsolete compatibility layers after tests are migrated, not preserving them indefinitely.
5. When a test still targets an outdated boundary, prefer rewriting the test to match the new ownership model.
6. Keep behavior stable, but do not keep fake facades forever just because they are familiar.


## Next Refactor Steps

The next phase should follow this order.

### Step 1. Raise more high-level capabilities onto `CoreBot`

Goal:

- let adapters call bot-level capabilities instead of assembling service calls themselves

Examples:

- message processing entrypoints
- scheduled message processing entrypoints
- session reset / new-session entrypoints
- tool-execution-related entrypoints where appropriate

Definition of success:

- adapter modules invoke higher-level bot behavior instead of stitching workflows together locally
- `CoreBot` becomes a clearer runtime entry surface, not just a dependency holder with factory methods

### Step 2. Shrink `handlers.py` as a real controller cleanup

Goal:

- reduce `handlers.py` from a broad compatibility shell into a thin Telegram controller

Tasks:

- remove compatibility getters that are no longer needed
- reduce initialization boilerplate
- replace direct helper-resolution patterns with clearer bot-level or controller-level delegation where possible
- re-evaluate whether `MessageHandler` is still the best name after this stage

Definition of success:

- `handlers.py` no longer exposes broad core subsystem properties except a minimal adapter contract
- `handlers.py` no longer constructs fallback core services directly in normal runtime paths
- most adapter modules depend on `CoreBot` capabilities or thin controller delegation, not handler getter indirection
- `handlers.py` stops looking like the historical system center

### Step 3. Reduce transition scaffolding in adapter modules

Goal:

- remove temporary resolver patterns that still preserve old boundaries longer than necessary

Focus:

- continue reducing remaining compatibility access patterns in `messages.py` and `handlers.py`
- remove fallback service lookup paths once tests no longer rely on them
- keep adapter modules thin without introducing new adapter-owned runtime layers

Definition of success:

- adapter modules still handle Telegram I/O, but contain far fewer transition shims

### Step 4. Revisit `core/tools.py` structure only when ownership is more stable

Goal:

- keep tool ownership in `core` without prematurely churning module boundaries

Current recommendation:

- do not split `core/tools.py` yet
- first finish ownership cleanup around `CoreBot`, `handlers.py`, and adapter-facing capabilities
- only revisit an internal split after the public ownership boundaries stop moving

Important rule:

- do not push this complexity back into `adapter`

Definition of success:

- tool runtime remains core-owned and the file does not grow by reabsorbing adapter logic
- any later split is driven by stable ownership boundaries, not by file size alone

### Step 5. Revisit adapter naming after responsibility reduction

Goal:

- make remaining adapter names match real responsibilities

Questions to re-evaluate later:

- should `handlers.py` stay as `handlers.py`
- should a smaller `controller.py` shape replace it
- are some wrappers now so thin that they can be merged or deleted

Definition of success:

- module names describe their real job, not historical leftovers

### Step 6. Continue structural cleanup in `llm/chat_client.py`

Goal:

- reduce remaining breadth in the chat client

Focus:

- further separate general chat flow from specialized memory-generation behavior
- keep sync/async wrappers from multiplying
- avoid new responsibility creep

Definition of success:

- chat client remains a chat-layer owner, not a grab bag of all LLM behavior


## Testing Strategy For Refactor Work

Every refactor step should keep behavior stable and re-run focused tests.

Current high-value test groups include:

- `tests/test_handlers.py`
- `tests/test_message_handler.py`
- `tests/test_tg_bot.py`
- `tests/test_main_telegram.py`
- `tests/test_telegram_file_helpers.py`
- tool- and memory-specific focused suites when touching those areas

Testing rule:

- when ownership changes, update tests to the new architecture instead of preserving outdated construction assumptions forever
- prefer constructing `CoreBot` and the real owner of behavior directly over mocking `MessageHandler` as a god object
- new or rewritten tests should target the current owner of behavior, not the historical delegator shell


## Dependency Direction Rules

The dependency rules remain:

- `adapter` may call `core`
- `core` may call `memory`, `llm`, and `tools`
- `memory` may call `llm` when model-backed memory behavior is needed
- `prompts` should not own persistence logic
- `prompts` should not depend on `adapter`
- `utils` should not depend on high-level modules
- `adapter` should not own business rules that belong in `core`


## What Should Not Go Into `utils`

Do not hide meaningful architecture inside `utils`.

In particular, do not move these there:

- approval workflow
- Telegram transport lifecycle
- MCP integration
- tool registry or tool execution logic
- file tools with workspace rules
- long-term memory profile storage
- adapter/core bridge logic


## Definition of Done For Each Refactor Step

Each step should satisfy most of the following:

- behavior remains stable
- focused tests pass
- ownership is clearer than before
- the old oversized file actually loses responsibility, not just body text
- new module names match real responsibilities
- dependency direction becomes more obvious
- no new adapter-side fake hosts are introduced for core behavior


## Out of Scope

These topics are still useful, but should not block the current structural refactor:

- replacing `Config` with a full dependency injection container
- redesigning all database abstractions
- changing end-user Telegram behavior for product reasons
- rewriting prompts for quality instead of structure
- replacing the current memory strategy


## Working Recommendation

Treat the next phase as ownership cleanup, not helper extraction.

Do not optimize for elegance first.
Optimize for:

- correct ownership
- thinner adapter boundaries
- smaller overloaded modules
- fewer fake facades
- safer future changes

If there is doubt during implementation, prefer this rule:

- if a change only moves code but leaves the same object owning the same state, it is not enough
