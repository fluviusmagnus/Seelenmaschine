"""Telegram response formatting helpers."""

import html
import re
from typing import List, Optional

from core.config import Config
from utils.text import strip_blockquotes


class TelegramResponseFormatter:
    """Format assistant responses for Telegram HTML delivery."""

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

        def save_blockquote(match):
            content = match.group(1).strip()
            return _save_placeholder(content, "pre")

        def save_inline_code(match):
            return _save_placeholder(match.group(1), "code")

        text_with_fenced_placeholders = re.sub(
            r"```([^\n`]*)\n(.*?)```",
            save_fenced_code_block,
            text,
            flags=re.DOTALL,
        )

        text_with_block_placeholders = re.sub(
            r"<\s*blockquote[^>]*>(.*?)<\s*/\s*blockquote\s*>",
            save_blockquote,
            text_with_fenced_placeholders,
            flags=re.DOTALL | re.IGNORECASE,
        )

        text_with_placeholders = re.sub(
            r"`([^`\n]+)`",
            save_inline_code,
            text_with_block_placeholders,
        )

        escaped_text = html.escape(text_with_placeholders)
        escaped_text = re.sub(r"\*\*(.*?)\*\*", r"<b>\1</b>", escaped_text)
        escaped_text = re.sub(
            r"(?<!\*)\*(?!\*)(.*?)(?<!\*)\*(?!\*)", r"<i>\1</i>", escaped_text
        )
        escaped_text = re.sub(
            r"(?<!_)_(?!_)(.*?)(?<!_)_(?!_)", r"<i>\1</i>", escaped_text
        )
        escaped_text = re.sub(r"__(.*?)__", r"<u>\1</u>", escaped_text)
        escaped_text = re.sub(r"~~(.*?)~~", r"<s>\1</s>", escaped_text)
        escaped_text = re.sub(
            r"\|\|(.*?)\|\|", r"<tg-spoiler>\1</tg-spoiler>", escaped_text
        )
        escaped_text = re.sub(
            r"\[(.*?)\]\((.*?)\)", r'<a href="\2">\1</a>', escaped_text
        )

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
            escaped_text,
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
