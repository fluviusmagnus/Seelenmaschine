import pytest
from utils.text import strip_blockquotes


def test_strip_blockquotes_simple():
    text = "Hello <blockquote>thought</blockquote> world"
    assert strip_blockquotes(text) == "Hello  world"


def test_strip_blockquotes_multiline():
    text = "Hello\n<blockquote>\nline1\nline2\n</blockquote>\nworld"
    assert strip_blockquotes(text) == "Hello\n\nworld"


def test_strip_blockquotes_multiple():
    text = "Start <blockquote>1</blockquote> middle <blockquote>2</blockquote> end"
    assert strip_blockquotes(text) == "Start  middle  end"


def test_strip_blockquotes_case_insensitive():
    text = "Hello <BLOCKQUOTE>thought</BLOCKQUOTE> world"
    assert strip_blockquotes(text) == "Hello  world"


def test_strip_blockquotes_with_attributes():
    text = 'Hello <blockquote class="thought">thought</blockquote> world'
    assert strip_blockquotes(text) == "Hello  world"


def test_strip_blockquotes_no_tags():
    text = "Just some normal text"
    assert strip_blockquotes(text) == "Just some normal text"


def test_strip_blockquotes_empty():
    assert strip_blockquotes("") == ""
    assert strip_blockquotes(None) is None
