# Text Catalog Refactor Plan

## Goal

Centralize non-prompt copy that is shown to users, returned by tools, or stored
as synthetic event/system messages. Prompt templates in `src/prompts/` remain in
their existing builder modules for this pass.

## Scope

Migrated into `src/texts/catalog.py`:

- Telegram command/help/status/error copy.
- Human-in-the-loop approval messages and stop reasons.
- Scheduled task tool descriptions, parameter descriptions, and common result
  text.
- File I/O, file search, send-file, and memory-search tool descriptions or
  validation helper text.
- Persisted synthetic event text for file upload, file delivery, scheduled task
  triggers, and tool-returned file artifacts.

Intentionally not migrated:

- `src/prompts/system_prompt.py`
- `src/prompts/memory_prompts.py`
- `src/prompts/runtime.py`
- SQL, log-only strings, internal debug strings, test fixtures, and dynamic
  user/LLM content.

## Current Status

- `[x]` Add `src/texts/` package and public exports.
- `[x]` Add representative catalog tests.
- `[x]` Route Telegram and approval copy through the catalog.
- `[x]` Route persisted file/scheduled-task event templates through the catalog.
- `[x]` Route first-pass tool descriptions/results through the catalog.
- `[ ]` Audit remaining non-prompt strings after this pass and migrate only when
  they are user-visible or persisted static copy.

## Maintenance Rule

New non-prompt copy that is shown to a user, returned by a tool, or persisted as
a fixed synthetic event should be added to `src/texts/catalog.py` first, then
referenced from the implementation.
