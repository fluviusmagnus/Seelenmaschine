"""Telegram response formatting helpers."""

import html
import re
from typing import List, Optional

from core.config import Config
from utils.text import strip_blockquotes


class TelegramResponseFormatter:
    """Format assistant responses for Telegram HTML delivery."""

    _INLINE_TAGS = {
        "**": "b",
        "__": "u",
        "~~": "s",
        "||": "tg-spoiler",
        "*": "i",
        "_": "i",
    }
    _TABLE_SEPARATOR_CELL_RE = re.compile(r"^:?-{3,}:?$")

    @staticmethod
    def _is_word_char(char: str) -> bool:
        """Return whether a character should count as part of a word."""
        return char.isalnum() or char == "_"

    def _is_valid_single_marker_open(self, text: str, index: int, marker: str) -> bool:
        """Check whether a single-character emphasis marker can open a span."""
        if index + 1 >= len(text):
            return False

        prev_char = text[index - 1] if index > 0 else ""
        next_char = text[index + 1]

        if next_char.isspace() or next_char == marker:
            return False

        return not self._is_word_char(prev_char)

    def _is_valid_single_marker_close(self, text: str, index: int, marker: str) -> bool:
        """Check whether a single-character emphasis marker can close a span."""
        if index <= 0:
            return False

        prev_char = text[index - 1]
        next_char = text[index + 1] if index + 1 < len(text) else ""

        if prev_char.isspace():
            return False

        return not self._is_word_char(next_char)

    def _find_single_marker_close(self, text: str, start: int, marker: str) -> int:
        """Find the matching close position for a single-character marker."""
        search_index = start
        while True:
            match_index = text.find(marker, search_index)
            if match_index == -1:
                return -1
            if self._is_valid_single_marker_close(text, match_index, marker):
                return match_index
            search_index = match_index + 1

    @staticmethod
    def _find_double_marker_close(text: str, start: int, marker: str) -> int:
        """Find the matching close position for a double-character marker."""
        return text.find(marker, start)

    @staticmethod
    def _try_parse_link(text: str, start: int) -> tuple[str, str, int] | None:
        """Parse a markdown-style inline link starting at ``start`` when present."""
        if text[start] != "[":
            return None

        label_end = text.find("]", start + 1)
        if label_end == -1 or label_end + 1 >= len(text) or text[label_end + 1] != "(":
            return None

        url_end = text.find(")", label_end + 2)
        if url_end == -1:
            return None

        label = text[start + 1 : label_end]
        url = text[label_end + 2 : url_end]
        if not label or not url:
            return None

        return label, url, url_end + 1

    def _render_inline_markdown(self, text: str) -> str:
        """Render inline markdown-like syntax into Telegram-safe HTML."""
        rendered: list[str] = []
        index = 0

        while index < len(text):
            link = self._try_parse_link(text, index)
            if link is not None:
                label, url, next_index = link
                rendered.append(
                    f'<a href="{html.escape(url, quote=True)}">'
                    f"{self._render_inline_markdown(label)}</a>"
                )
                index = next_index
                continue

            matched = False
            for marker in ("**", "__", "~~", "||", "*", "_"):
                if not text.startswith(marker, index):
                    continue

                if len(marker) == 1:
                    if not self._is_valid_single_marker_open(text, index, marker):
                        continue
                    close_index = self._find_single_marker_close(
                        text, index + 1, marker
                    )
                else:
                    close_index = self._find_double_marker_close(
                        text, index + len(marker), marker
                    )

                if close_index == -1:
                    continue

                inner = text[index + len(marker) : close_index]
                if not inner:
                    continue

                tag = self._INLINE_TAGS[marker]
                rendered.append(f"<{tag}>{self._render_inline_markdown(inner)}</{tag}>")
                index = close_index + len(marker)
                matched = True
                break

            if matched:
                continue

            rendered.append(html.escape(text[index]))
            index += 1

        return "".join(rendered)

    @staticmethod
    def _split_markdown_table_row(line: str) -> list[str] | None:
        """Split a Markdown table row into cells when it looks table-like."""
        stripped = line.strip()
        if "|" not in stripped:
            return None

        if stripped.startswith("|"):
            stripped = stripped[1:]
        if stripped.endswith("|"):
            stripped = stripped[:-1]

        cells = [cell.strip() for cell in stripped.split("|")]
        if len(cells) < 2:
            return None
        return cells

    @classmethod
    def _is_markdown_table_separator(cls, line: str) -> bool:
        """Return whether a line is a Markdown table separator row."""
        cells = cls._split_markdown_table_row(line)
        if cells is None:
            return False
        return all(cls._TABLE_SEPARATOR_CELL_RE.fullmatch(cell) for cell in cells)

    @classmethod
    def _format_markdown_table(cls, rows: list[list[str]]) -> str:
        """Render Markdown table rows as an aligned plain-text table."""
        widths = [0] * max(len(row) for row in rows)
        normalized_rows = []

        for row in rows:
            normalized_row = row + [""] * (len(widths) - len(row))
            normalized_rows.append(normalized_row)
            for index, cell in enumerate(normalized_row):
                widths[index] = max(widths[index], len(cell))

        widths = [max(width, 3) for width in widths]
        rendered_rows = []
        for row_index, row in enumerate(normalized_rows):
            rendered_rows.append(
                " | ".join(
                    cell if index == len(row) - 1 else cell.ljust(widths[index])
                    for index, cell in enumerate(row)
                )
            )
            if row_index == 0:
                rendered_rows.append("-+-".join("-" * width for width in widths))

        return "\n".join(rendered_rows)

    def _replace_markdown_tables(self, text: str, save_table) -> str:
        """Replace Markdown tables with preformatted placeholders."""
        lines = text.splitlines(keepends=True)
        result: list[str] = []
        index = 0

        while index < len(lines):
            current_line = lines[index].rstrip("\r\n")
            next_line = lines[index + 1].rstrip("\r\n") if index + 1 < len(lines) else ""
            header = self._split_markdown_table_row(current_line)

            if header is None or not self._is_markdown_table_separator(next_line):
                result.append(lines[index])
                index += 1
                continue

            separator = self._split_markdown_table_row(next_line)
            if separator is None or len(separator) != len(header):
                result.append(lines[index])
                index += 1
                continue

            table_rows = [header]
            index += 2

            while index < len(lines):
                row_line = lines[index].rstrip("\r\n")
                row = self._split_markdown_table_row(row_line)
                if row is None:
                    break
                table_rows.append(row)
                index += 1

            result.append(save_table(self._format_markdown_table(table_rows)))
            if index < len(lines):
                result.append("\n")

        return "".join(result)

    def format_response(self, text: str, debug_mode: bool = False) -> str:
        """Convert mixed markdown-like text into Telegram-safe HTML."""
        if not debug_mode:
            text = strip_blockquotes(text)

        placeholders = []

        def _save_placeholder(content: str, tag: str) -> str:
            placeholders.append((tag, content))
            return f"TGFORMATPLACEHOLDER{len(placeholders) - 1}END"

        def save_fenced_code_block(match):
            content = match.group(2)
            if content is None:
                content = ""
            return _save_placeholder(content.strip(), "pre")

        def save_markdown_quote_lines(lines: list[str]) -> str:
            normalized_lines = []
            for raw_line in lines:
                line = re.sub(r"^\s*>\s?", "", raw_line)
                normalized_lines.append(line)
            return _save_placeholder("\n".join(normalized_lines).strip(), "pre")

        def replace_markdown_quote_blocks(content: str) -> str:
            result_lines = []
            quote_lines: list[str] = []
            quote_trailing_newline = ""

            def flush_quote_lines() -> None:
                nonlocal quote_lines, quote_trailing_newline
                if quote_lines:
                    result_lines.append(
                        f"{save_markdown_quote_lines(quote_lines)}{quote_trailing_newline}"
                    )
                    quote_lines = []
                    quote_trailing_newline = ""

            for line in content.splitlines(keepends=True):
                line_without_newline = line.rstrip("\r\n")
                newline_suffix = line[len(line_without_newline) :]
                if re.match(r"^\s*>", line_without_newline):
                    quote_lines.append(line_without_newline)
                    quote_trailing_newline = newline_suffix
                    continue

                flush_quote_lines()
                result_lines.append(f"{line_without_newline}{newline_suffix}")

            flush_quote_lines()
            return "".join(result_lines)

        def save_blockquote(match):
            content = match.group(1).strip()
            return _save_placeholder(content, "pre")

        def save_table(content: str) -> str:
            return _save_placeholder(content.strip(), "pre")

        def save_inline_code(match):
            return _save_placeholder(match.group(1), "code")

        text_with_fenced_placeholders = re.sub(
            r"```([^\n`]*)\n(.*?)```",
            save_fenced_code_block,
            text,
            flags=re.DOTALL,
        )

        text_with_markdown_quote_placeholders = replace_markdown_quote_blocks(
            text_with_fenced_placeholders
        )

        text_with_block_placeholders = re.sub(
            r"<\s*blockquote[^>]*>(.*?)<\s*/\s*blockquote\s*>",
            save_blockquote,
            text_with_markdown_quote_placeholders,
            flags=re.DOTALL | re.IGNORECASE,
        )

        text_with_table_placeholders = self._replace_markdown_tables(
            text_with_block_placeholders,
            save_table,
        )

        text_with_placeholders = re.sub(
            r"`([^`\n]+)`",
            save_inline_code,
            text_with_table_placeholders,
        )

        rendered_text = self._render_inline_markdown(text_with_placeholders)

        def restore_placeholder(match):
            idx = int(match.group(1))
            tag, original_content = placeholders[idx]
            escaped_content = html.escape(original_content)
            if tag == "code":
                return f"<code>{escaped_content}</code>"
            return f"<pre>{escaped_content}</pre>"

        return re.sub(
            r"TGFORMATPLACEHOLDER(\d+)END",
            restore_placeholder,
            rendered_text,
        )

    def split_message_into_segments(
        self, text: str, max_length: int = Config.TELEGRAM_MESSAGE_MAX_LENGTH
    ) -> List[str]:
        """Split Telegram HTML text into safe message segments."""
        segments: List[str] = []

        def _append_segment(content: str) -> None:
            if content and content.strip():
                segments.append(content.strip())

        def _find_safe_split_index(content: str, limit: int) -> int:
            in_tag = False
            last_whitespace = -1
            last_text_boundary = -1

            for idx, char in enumerate(content):
                if idx >= limit:
                    break
                if char == "<":
                    in_tag = True
                    continue
                if char == ">":
                    in_tag = False
                    continue
                if in_tag:
                    continue
                last_text_boundary = idx + 1
                if char.isspace():
                    last_whitespace = idx

            if last_whitespace > 0:
                return last_whitespace
            if last_text_boundary > 0:
                return last_text_boundary
            return min(limit, len(content))

        def _get_open_html_tags(content: str) -> List[tuple[str, str]]:
            tag_pattern = re.compile(r"<(/?)([a-zA-Z0-9-]+)([^<>]*?)(/?)>")
            open_tags: List[tuple[str, str]] = []

            for match in tag_pattern.finditer(content):
                is_closing = match.group(1) == "/"
                tag_name = match.group(2)
                is_self_closing = match.group(4) == "/"
                full_tag = match.group(0)

                if is_self_closing:
                    continue

                if is_closing:
                    for index in range(len(open_tags) - 1, -1, -1):
                        if open_tags[index][0] == tag_name:
                            del open_tags[index]
                            break
                    continue

                open_tags.append((tag_name, full_tag))

            return open_tags

        def _split_long_text(content: str, limit: int) -> List[str]:
            if len(content) <= limit:
                return [content]

            chunks: List[str] = []
            remaining = content.strip()

            while len(remaining) > limit:
                split_index = _find_safe_split_index(remaining, limit)
                chunk = remaining[:split_index].rstrip()

                while chunk:
                    open_tags = _get_open_html_tags(chunk)
                    closing_tags = "".join(
                        f"</{tag_name}>" for tag_name, _ in reversed(open_tags)
                    )
                    if len(chunk) + len(closing_tags) <= limit:
                        break

                    next_index = _find_safe_split_index(chunk, len(chunk) - 1)
                    if next_index >= len(chunk):
                        next_index = len(chunk) - 1
                    if next_index <= 0:
                        break
                    chunk = chunk[:next_index].rstrip()

                if not chunk:
                    chunk = remaining[:limit].rstrip()
                    open_tags = _get_open_html_tags(chunk)
                    closing_tags = "".join(
                        f"</{tag_name}>" for tag_name, _ in reversed(open_tags)
                    )
                else:
                    open_tags = _get_open_html_tags(chunk)
                    closing_tags = "".join(
                        f"</{tag_name}>" for tag_name, _ in reversed(open_tags)
                    )

                if chunk:
                    chunks.append(f"{chunk}{closing_tags}")

                reopened_tags = "".join(open_tag for _, open_tag in open_tags)
                remaining = f"{reopened_tags}{remaining[len(chunk):].lstrip()}"

            if remaining:
                chunks.append(remaining.strip())

            return chunks

        def _line_group_kind(content: str) -> str:
            if re.match(r"^([-*+]\s+|\d+\.\s+|\d+\)\s+|\[[ xX]\]\s+)", content):
                return "list"
            if content.startswith("&gt;") or content.startswith(">"):
                return "quote"
            return "text"

        def _split_regular_text(part: str) -> List[str]:
            grouped_lines: List[str] = []
            current_lines: List[str] = []
            current_kind: Optional[str] = None

            for raw_line in re.split(r"\n+", part):
                line = raw_line.strip()
                if not line:
                    if current_lines:
                        grouped_lines.append("\n".join(current_lines))
                        current_lines = []
                        current_kind = None
                    continue

                line_kind = _line_group_kind(line)
                if (
                    current_lines
                    and line_kind == current_kind
                    and line_kind in {"list", "quote"}
                ):
                    current_lines.append(line)
                    continue

                if current_lines:
                    grouped_lines.append("\n".join(current_lines))

                current_lines = [line]
                current_kind = line_kind

            if current_lines:
                grouped_lines.append("\n".join(current_lines))

            split_parts: List[str] = []
            for grouped in grouped_lines:
                split_parts.extend(_split_long_text(grouped, max_length))

            return split_parts

        protected_blocks = re.split(
            r"(<pre>[\s\S]*?</pre>|<blockquote>[\s\S]*?</blockquote>)",
            text,
        )

        for part in protected_blocks:
            if not part or not part.strip():
                continue

            if re.fullmatch(
                r"<pre>[\s\S]*?</pre>|<blockquote>[\s\S]*?</blockquote>", part
            ):
                _append_segment(part)
                continue

            for text_part in re.split(r"\n\s*\n", part):
                if not text_part or not text_part.strip():
                    continue
                for segment in _split_regular_text(text_part):
                    _append_segment(segment)

        if not segments and text.strip():
            return [text.strip()]

        return segments
