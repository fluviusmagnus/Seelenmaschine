import re


def strip_blockquotes(text: str) -> str:
    """Remove <blockquote>...</blockquote> blocks from text.

    Handles whitespace around blockquotes:
    - If at start/end of message: removes all surrounding empty lines
    - If in middle of message: maintains exactly 2 newlines between content

    Args:
        text: Input text containing blockquote tags.

    Returns:
        Text with blockquote blocks removed and proper whitespace handling.
    """
    if not text:
        return text

    # Pattern to match blockquote tags and content
    bq_pattern = re.compile(
        r"<\s*blockquote[^>]*>.*?<\s*/\s*blockquote\s*>", re.DOTALL | re.IGNORECASE
    )

    # Find all blockquotes
    matches = list(bq_pattern.finditer(text))

    if not matches:
        return text

    # Build result by collecting non-blockquote segments
    result_parts = []

    # Handle text before first blockquote
    first_bq_start = matches[0].start()
    before_first = text[:first_bq_start]

    if before_first and not before_first.isspace():
        # There's real content before first blockquote - not at start
        result_parts.append(before_first.rstrip())
    # If before_first is empty or whitespace, skip it (blockquote at start)

    # Handle text between blockquotes
    for i in range(len(matches) - 1):
        current_end = matches[i].end()
        next_start = matches[i + 1].start()
        between = text[current_end:next_start]

        if between.strip():
            # There's real content between blockquotes
            if result_parts:
                result_parts.append("\n\n")
            result_parts.append(between.strip())
        # If only whitespace, skip it

    # Handle text after last blockquote
    last_bq_end = matches[-1].end()
    after_last = text[last_bq_end:]

    if after_last and not after_last.isspace():
        # There's real content after last blockquote - not at end
        if result_parts:
            result_parts.append("\n\n")
        result_parts.append(after_last.lstrip())
    # If after_last is empty or whitespace, skip it (blockquote at end)

    result = "".join(result_parts)

    # Clean up excessive newlines (more than 2 consecutive)
    result = re.sub(r"\n{3,}", "\n\n", result)

    return result
