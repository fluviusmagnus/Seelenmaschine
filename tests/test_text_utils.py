from utils.text import strip_blockquotes


def test_strip_blockquotes_simple_inline():
    """Blockquote in middle of text - should preserve spacing."""
    text = "Hello <blockquote>thought</blockquote> world"
    assert strip_blockquotes(text) == "Hello\n\nworld"


def test_strip_blockquotes_multiline_middle():
    """Blockquote in middle with newlines - should preserve 2 newlines."""
    text = "Hello\n\n<blockquote>\nline1\nline2\n</blockquote>\n\nworld"
    assert strip_blockquotes(text) == "Hello\n\nworld"


def test_strip_blockquotes_at_start():
    """Blockquote at start - should remove all surrounding empty lines."""
    text = "<blockquote>thought</blockquote>\n\nHello world"
    assert strip_blockquotes(text) == "Hello world"


def test_strip_blockquotes_at_start_with_leading_whitespace():
    """Blockquote at start with leading newlines - should remove all."""
    text = "\n\n<blockquote>thought</blockquote>\n\nHello world"
    assert strip_blockquotes(text) == "Hello world"


def test_strip_blockquotes_at_end():
    """Blockquote at end - should remove all surrounding empty lines."""
    text = "Hello world\n\n<blockquote>thought</blockquote>"
    assert strip_blockquotes(text) == "Hello world"


def test_strip_blockquotes_at_end_with_trailing_whitespace():
    """Blockquote at end with trailing newlines - should remove all."""
    text = "Hello world\n\n<blockquote>thought</blockquote>\n\n"
    assert strip_blockquotes(text) == "Hello world"


def test_strip_blockquotes_only_blockquote():
    """Only blockquote in text - should return empty."""
    text = "<blockquote>thought</blockquote>"
    assert strip_blockquotes(text) == ""


def test_strip_blockquotes_only_blockquote_with_whitespace():
    """Only blockquote surrounded by whitespace - should return empty."""
    text = "\n\n<blockquote>thought</blockquote>\n\n"
    assert strip_blockquotes(text) == ""


def test_strip_blockquotes_multiple():
    """Multiple blockquotes - should handle each position correctly."""
    text = "Start <blockquote>1</blockquote> middle <blockquote>2</blockquote> end"
    assert strip_blockquotes(text) == "Start\n\nmiddle\n\nend"


def test_strip_blockquotes_multiple_with_newlines():
    """Multiple blockquotes with newlines."""
    text = "Start\n<blockquote>1</blockquote>\nmiddle\n<blockquote>2</blockquote>\nend"
    assert strip_blockquotes(text) == "Start\n\nmiddle\n\nend"


def test_strip_blockquotes_multiple_at_start_end():
    """Multiple blockquotes with some at start/end."""
    text = "<blockquote>1</blockquote>\n\ncontent\n\n<blockquote>2</blockquote>"
    assert strip_blockquotes(text) == "content"


def test_strip_blockquotes_case_insensitive():
    """Blockquote tags should be case insensitive."""
    text = "Hello <BLOCKQUOTE>thought</BLOCKQUOTE> world"
    assert strip_blockquotes(text) == "Hello\n\nworld"


def test_strip_blockquotes_with_attributes():
    """Blockquote with attributes should be handled."""
    text = 'Hello <blockquote class="thought">thought</blockquote> world'
    assert strip_blockquotes(text) == "Hello\n\nworld"


def test_strip_blockquotes_no_tags():
    """Text without blockquotes should be unchanged."""
    text = "Just some normal text"
    assert strip_blockquotes(text) == "Just some normal text"


def test_strip_blockquotes_empty():
    """Empty and None inputs."""
    assert strip_blockquotes("") == ""
    assert strip_blockquotes(None) is None


def test_strip_blockquotes_with_extra_newlines():
    """Should clean up excessive newlines to exactly 2."""
    text = "Hello\n\n\n\n<blockquote>thought</blockquote>\n\n\n\nworld"
    assert strip_blockquotes(text) == "Hello\n\nworld"
