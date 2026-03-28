import os
from pathlib import Path
from typing import Optional, Dict, Any

from core.config import Config
from utils.logger import get_logger

logger = get_logger()

# Limit constraints consistently applied
_MAX_FILE_SIZE = 2 * 1024 * 1024  # 2 MB


def _resolve_file_path(file_path: str) -> str:
    """Resolve a tool-provided path into a normalized absolute path.

    Rules:
    - expand ``~`` to the user home directory
    - resolve relative paths from ``WORKSPACE_DIR``
    - normalize ``.`` / ``..`` segments
    """
    path = Path(file_path).expanduser()
    if not path.is_absolute():
        path = Path(Config.WORKSPACE_DIR) / path
    return str(path.resolve(strict=False))


class ReadFileTool:
    """Tool for LLM to read contents of local files."""

    @property
    def name(self) -> str:
        return "read_file"

    @property
    def description(self) -> str:
        return """Read a file. Relative paths resolve from WORKSPACE_DIR.

Use start_line/end_line to read a specific line range (output includes line numbers). Omit both to read the full file.
"""

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Path to the file.",
                },
                "start_line": {
                    "type": "integer",
                    "description": "First line to read (1-based, inclusive).",
                },
                "end_line": {
                    "type": "integer",
                    "description": "Last line to read (1-based, inclusive).",
                },
            },
            "required": ["file_path"],
        }

    async def execute(
        self,
        file_path: str,
        start_line: Optional[int] = None,
        end_line: Optional[int] = None,
    ) -> str:
        if start_line is not None:
            try:
                start_line = int(start_line)
            except (ValueError, TypeError):
                return f"Error: start_line must be an integer, got {start_line!r}."

        if end_line is not None:
            try:
                end_line = int(end_line)
            except (ValueError, TypeError):
                return f"Error: end_line must be an integer, got {end_line!r}."

        resolved_path = _resolve_file_path(file_path)

        if not os.path.exists(resolved_path):
            return f"Error: The file {resolved_path} does not exist."

        if not os.path.isfile(resolved_path):
            return f"Error: The path {resolved_path} is not a file."

        try:
            if os.path.getsize(resolved_path) > _MAX_FILE_SIZE:
                return f"Error: File is too large. Max size is {_MAX_FILE_SIZE} bytes."

            with open(resolved_path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()

            all_lines = content.split("\n")
            total = len(all_lines)

            # Determine read range
            s = max(1, start_line if start_line is not None else 1)
            e = min(total, end_line if end_line is not None else total)

            if s > total:
                return f"Error: start_line {s} exceeds file length ({total} lines)."

            if s > e:
                return f"Error: start_line ({s}) > end_line ({e})."

            # Extract selected lines and format with line numbers
            selected_lines = all_lines[s - 1 : e]
            text = "\n".join(
                f"{s + i}: {line}" for i, line in enumerate(selected_lines)
            )

            # Truncate if too long (optional simple logic)
            if len(text) > 20000:
                text = text[:20000] + "\n...[truncated due to length]..."

            # Add continuation hint if partial read
            if e < total:
                remaining = total - e
                text = (
                    f"{resolved_path}  (lines {s}-{e} of {total})\n{text}\n\n"
                    f"[{remaining} more lines. Use start_line={e + 1} to continue.]"
                )

            text += "\n\n[Note: The line numbers prefixed to each line are for your reference only. DO NOT include them when using replace_file_content!]"

            return text

        except Exception as e:
            return f"Error: Read file failed due to \n{e}"


class WriteFileTool:
    """Tool for LLM to write completely new content to a local file."""

    @property
    def name(self) -> str:
        return "write_file"

    @property
    def description(self) -> str:
        return "Create or overwrite a file. Relative paths resolve from WORKSPACE_DIR."

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Path to the file.",
                },
                "content": {
                    "type": "string",
                    "description": "Content to write to the file.",
                },
            },
            "required": ["file_path", "content"],
        }

    async def execute(self, file_path: str, content: str) -> str:
        if not file_path:
            return "Error: No `file_path` provided."

        resolved_path = _resolve_file_path(file_path)

        try:
            # Ensure parent directories exist
            Path(resolved_path).parent.mkdir(parents=True, exist_ok=True)

            with open(resolved_path, "w", encoding="utf-8") as f:
                f.write(content)
            return f"Wrote {len(content)} characters to {resolved_path}."
        except Exception as e:
            return f"Error: Write file failed due to \n{e}"


class ReplaceFileContentTool:
    """Tool for LLM to edit a local file by replacing specific text."""

    @property
    def name(self) -> str:
        return "replace_file_content"

    @property
    def description(self) -> str:
        return "Replace a specific contiguous block of text in a file with new content. Use this for editing existing files. Requires exact match of the target text (including indentation and spaces). DO NOT include line numbers in target_text or replacement_text."

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Path to the file.",
                },
                "target_text": {
                    "type": "string",
                    "description": "The exact string to be replaced. Must be an exact character-sequence match including whitespace/indentation.",
                },
                "replacement_text": {
                    "type": "string",
                    "description": "The new content to insert in place of the target text.",
                },
                "allow_multiple": {
                    "type": "boolean",
                    "description": "If true, replace all occurrences. If false, fails if target_text appears more than once. Default is false.",
                    "default": False,
                },
            },
            "required": ["file_path", "target_text", "replacement_text"],
        }

    async def execute(
        self,
        file_path: str,
        target_text: str,
        replacement_text: str,
        allow_multiple: bool = False,
    ) -> str:
        if not file_path:
            return "Error: No `file_path` provided."

        if not target_text:
            return "Error: `target_text` is empty, nothing to replacing."

        resolved_path = _resolve_file_path(file_path)

        if not os.path.exists(resolved_path):
            return f"Error: The file {resolved_path} does not exist."

        if not os.path.isfile(resolved_path):
            return f"Error: The path {resolved_path} is not a file."

        try:
            if os.path.getsize(resolved_path) > _MAX_FILE_SIZE:
                return f"Error: File is too large. Max size is {_MAX_FILE_SIZE} bytes."

            with open(resolved_path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()

            occurrences = content.count(target_text)

            if occurrences == 0:
                import re

                # Heuristic: LLM copied line numbers from read_file output
                stripped_lines = [
                    re.sub(r"^\d+:\s?", "", line) for line in target_text.splitlines()
                ]
                stripped_target = "\n".join(stripped_lines)
                if (
                    stripped_target
                    and stripped_target != target_text
                    and content.count(stripped_target) > 0
                ):
                    return "Error: The `target_text` was not found. However, a match was found for the text WITHOUT line numbers. Did you accidentally copy the line numbers from `read_file`? Please strictly remove the line numbers (e.g., '12: ') from both `target_text` and `replacement_text` and try again."

                return "Error: The `target_text` was not found in the file. Make sure you matched indentation and line breaks exactly."

            if occurrences > 1 and not allow_multiple:
                return f"Error: Found {occurrences} instances of `target_text`. Set `allow_multiple` to true if you intend to replace all of them, or provide a more specific `target_text` block with surrounding context."

            new_content = content.replace(target_text, replacement_text)

            with open(resolved_path, "w", encoding="utf-8") as f:
                f.write(new_content)

            return f"Successfully replaced {occurrences} occurrence(s) of the target text in {resolved_path}."
        except Exception as e:
            return f"Error: Edit file failed due to \n{e}"


class AppendFileTool:
    """Tool for LLM to append content to a local file."""

    @property
    def name(self) -> str:
        return "append_file"

    @property
    def description(self) -> str:
        return "Append content to the end of a file. Relative paths resolve from WORKSPACE_DIR. Safely handles newlines and cross-platform writing."

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Path to the file.",
                },
                "content": {
                    "type": "string",
                    "description": "Content to append to the end of the file.",
                },
            },
            "required": ["file_path", "content"],
        }

    async def execute(self, file_path: str, content: str) -> str:
        if not file_path:
            return "Error: No `file_path` provided."

        resolved_path = _resolve_file_path(file_path)

        try:
            # Ensure parent directories exist
            Path(resolved_path).parent.mkdir(parents=True, exist_ok=True)

            with open(resolved_path, "a", encoding="utf-8") as f:
                f.write(content)
            return f"Appended {len(content)} characters to {resolved_path}."
        except Exception as e:
            return f"Error: Append file failed due to \n{e}"

