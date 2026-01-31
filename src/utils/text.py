import re


def strip_blockquotes(text: str) -> str:
    """Remove <blockquote>...</blockquote> blocks from text.

    Args:
        text: Input text containing blockquote tags.

    Returns:
        Text with blockquote blocks removed.
    """
    if not text:
        return text

    # Regex to match <blockquote>...</blockquote> tags and anything in between
    # flags=re.DOTALL | re.IGNORECASE to handle multiline content and case-insensitive tags
    pattern = r"<\s*blockquote[^>]*>.*?<\s*/\s*blockquote\s*>"
    return re.sub(pattern, "", text, flags=re.DOTALL | re.IGNORECASE).strip()
