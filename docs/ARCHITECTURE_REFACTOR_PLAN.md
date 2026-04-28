# Architecture Refactor Plan

> Status: historical plan. Most of this direction has been executed and tracked in
> [REDUNDANCY_REFACTOR_PLAN.md](REDUNDANCY_REFACTOR_PLAN.md), which is the current
> authoritative progress ledger for completed refactor phases, retained components,
> and verification status.

## Goal

This refactor removes unnecessary indirection and restores the intended ownership model:

- `adapter` only owns transport-specific I/O
- `core` owns runtime behavior, session flow, tool execution, approval flow, and policy
- `memory / llm / tools` follow **async-first + thin sync wrapper**
- unreasonable compatibility layers should be deleted, not preserved

This document is intentionally biased toward simplification over compatibility. If an API exists only to support a bad shape, remove it.

## Current Problems

### 1. Core runtime leaks Telegram details

Symptoms:

- `src/core/runtime.py` imports `telegram.ext.Application`
- scheduler startup/shutdown is modeled as Telegram hooks instead of core lifecycle
- core code touches `TaskScheduler._task` directly

Impact:

- `core` cannot stand on its own without Telegram semantics
- lifecycle ownership is split between `core`, `main_telegram.py`, and adapter code

### 2. Runtime assembly is spread across too many owners

Symptoms:

- `CoreBot`, `AdapterRuntimeAssembler`, and `ToolRuntime` all hold parts of runtime state
- adapter initialization mutates multiple `CoreBot` private fields
- `CoreBot.execute_tool()` re-syncs executor fields before each call

Impact:

- no single owner of runtime state
- private field mutation is part of normal control flow
- future refactors will keep adding glue instead of removing it

### 3. Async-first direction is only partially applied

Symptoms:

- `src/memory/sessions.py` still contains large parallel sync/async business logic
- `MemoryManager` exposes a broad forwarding surface around duplicated logic

Impact:

- behavior can drift between sync and async paths
- refactors require touching multiple versions of the same workflow

### 4. Telegram path has too many pass-through layers

Symptoms:

- `TelegramController -> TelegramMessages -> CoreBot -> ConversationService`
- several methods only forward calls without owning state or policy
- duplicated helper code such as preview/error/status-message formatting

Impact:

- harder tracing and testing
- more files to change for one behavior
- ownership becomes less obvious over time

### 5. Tool execution has hidden coupling

Symptoms:

- `ToolExecutor` introspects `record_tool_trace.__self__`
- trace sanitization depends on concrete implementation details of the trace service

Impact:

- interface boundaries are fake
- substituting implementations becomes fragile

## Target Architecture

### Core

`CoreBot` is the single core runtime entry point.

It should directly own:

- config and long-lived dependencies
- conversation service
- session service
- approval service / stop controller
- tool runtime state
- tool executor
- runtime startup hooks that are transport-agnostic

It should not depend on:

- Telegram application types
- adapter lifecycle hooks
- adapter-specific status-message implementations beyond explicit injected callables

### Adapter

`adapter.telegram` should only own:

- Telegram `Update` / `Context` handling
- Telegram bot command registration
- Telegram-specific formatting and delivery
- translating Telegram events into calls on `CoreBot`

It should not own:

- core runtime assembly
- session logic
- tool runtime state
- scheduler lifecycle policy

### Memory

`SessionMemory` and adjacent memory services should use:

- one async business implementation
- sync wrappers only where there is a real synchronous caller

If a sync API has no meaningful owner after cleanup, remove it instead of wrapping it forever.

## Planned Deletions

These are the main deletions this plan expects:

1. Delete `src/core/runtime_assembly.py`
2. Delete `src/core/runtime.py`
3. Delete pass-through methods that only relay between controller/messages/core without adding ownership
4. Delete duplicated sync business implementations in `src/memory/sessions.py`
5. Delete compatibility-oriented runtime state mutation on `CoreBot` private fields

If deleting one of these reveals a real missing abstraction, add the smallest possible replacement with explicit ownership.

## Refactor Phases

### Phase 1. Collapse runtime assembly into `CoreBot`

Changes:

- move `AdapterRuntimeAssembler.initialize()` into `CoreBot.initialize_adapter_runtime()`
- stop mutating scattered private fields across files
- create tool runtime state, conversation service, session service, and executor in one place
- make `CoreBot` the only place that wires tool runtime dependencies

Rules:

- no new façade class
- no new host/bridge/manager layer
- avoid lazy state if eager initialization is simpler and safe

Success criteria:

- `src/core/runtime_assembly.py` is gone
- adapter runtime initialization touches one owner: `CoreBot`

### Phase 2. Move Telegram lifecycle back to adapter

Changes:

- remove Telegram `Application` imports from `core`
- move scheduler `post_init/post_shutdown` wiring into `adapter.telegram.adapter`
- add transport-agnostic scheduler lifecycle methods if needed, for example:
  - `TaskScheduler.start()`
  - `TaskScheduler.stop()`
  - `TaskScheduler.wait_stopped()`
- stop writing `scheduler._task` from outside `TaskScheduler`

Rules:

- `core` may expose lifecycle operations, but not Telegram hook shapes
- adapter translates Telegram lifecycle into those operations

Success criteria:

- `src/core/runtime.py` is gone
- no `telegram.*` import remains under `src/core/`
- `TaskScheduler` owns its own task lifecycle

### Phase 3. Simplify Telegram boundary

Changes:

- reduce `TelegramController` to composition and injection only
- either merge `TelegramController` and `TelegramMessages`, or make one clearly own only composition
- remove pure pass-through methods that add no policy
- centralize Telegram-only helpers:
  - preview text formatting
  - user-facing exception formatting
  - status message sending

Recommended direction:

- keep one Telegram boundary class for handling updates/commands
- keep delivery/formatter/files as support services
- avoid both controller and messages being mini-orchestrators

Success criteria:

- one obvious Telegram entry owner
- fewer hop-by-hop relays for normal message processing

### Phase 4. Enforce async-first in memory/session flow

Changes:

- make async implementations the only business logic in `SessionMemory`
- convert remaining sync methods into thin wrappers using shared async utilities
- remove duplicated sync code blocks for:
  - new session creation
  - summary creation
  - user/assistant message persistence
- reevaluate `MemoryManager` forwarding surface and delete wrappers that no longer add value

Rules:

- do not keep dual-track business logic for convenience
- if a sync API is retained, it must be a thin wrapper and must reject async-context usage clearly

Success criteria:

- no large sync/async duplicate blocks remain in `src/memory/sessions.py`
- tests explicitly cover sync-wrapper behavior only where sync APIs still exist

### Phase 5. Clean tool runtime contracts

Changes:

- replace implicit trace-service introspection with explicit interfaces
- pass a real result-sanitizer dependency into `ToolExecutor`
- keep tool runtime state and executor contracts narrow and explicit
- re-check whether `ToolRuntimeDependencies` should remain a dedicated object or be inlined

Rules:

- no `__self__` introspection
- no reliance on concrete implementation internals through callback objects

Success criteria:

- `ToolExecutor` depends on explicit interfaces only
- swapping trace implementations does not require hidden knowledge

## API Policy During Refactor

This plan does **not** preserve bad APIs for compatibility.

Apply these rules:

- if an API exists only because ownership used to be wrong, remove it
- if a wrapper only forwards a call and adds no policy, remove it
- if a sync API is unused or unjustified, remove it
- rename methods freely if the result is clearer and the old name only reflects transitional structure

The preferred migration style is:

1. move ownership to the correct module
2. update callers
3. delete the obsolete layer immediately

Do not leave long-lived shims unless an external caller truly requires them.

## Testing Strategy

Add or update focused tests after each phase.

Priority coverage:

- core runtime initializes without Telegram-specific types
- adapter can still bootstrap Telegram application and scheduler correctly
- scheduled tasks still execute and deliver messages
- message processing and tool execution still persist memory/tool events correctly
- sync wrappers, if any remain, succeed in sync contexts and fail in async contexts

Preferred test style:

- target the real owner of behavior
- avoid tests that depend on transitional wrapper layers
- remove tests whose only purpose is to preserve old structure

## Recommended Execution Order

1. Collapse runtime assembly into `CoreBot`
2. Move scheduler lifecycle ownership out of `core/runtime.py`
3. Simplify Telegram controller/messages structure
4. Remove duplicated sync business logic from `memory/sessions.py`
5. Tighten `ToolExecutor` contracts
6. Prune obsolete tests and add focused regression coverage

## End State Checklist

- `src/core/` contains no Telegram imports
- `CoreBot` is the direct runtime entry surface
- no adapter-facing runtime assembler remains
- `TaskScheduler` owns its lifecycle state
- Telegram boundary is thin and obvious
- memory/session logic is async-first with only justified sync wrappers
- `ToolExecutor` uses explicit contracts instead of hidden implementation coupling
- dead wrappers and transitional seams are deleted
