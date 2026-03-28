import unittest

from adapter.telegram.formatter import TelegramResponseFormatter
from core.config import Config


class TestFormatting(unittest.TestCase):
    def setUp(self):
        self._original_debug_mode = Config.DEBUG_MODE
        Config.DEBUG_MODE = True
        self.formatter = TelegramResponseFormatter()

    def tearDown(self):
        Config.DEBUG_MODE = self._original_debug_mode

    def test_format_blockquote_simple(self):
        text = "Here is a quote: <blockquote>This is quoted text.</blockquote>"
        formatted = self.formatter.format_response(text, debug_mode=True)
        # Expect HTML format
        expected = "Here is a quote: <pre>This is quoted text.</pre>"
        self.assertEqual(formatted, expected)

    def test_format_blockquote_multiline(self):
        text = "<blockquote>Line 1\nLine 2</blockquote>"
        formatted = self.formatter.format_response(text, debug_mode=True)
        expected = "<pre>Line 1\nLine 2</pre>"
        self.assertEqual(formatted, expected)

    def test_format_blockquote_with_special_chars(self):
        # Characters that needs HTML escaping outside block
        text = "<blockquote>Special chars: -_.!</blockquote> & more"
        formatted = self.formatter.format_response(text, debug_mode=True)
        # Content inside pre is escaped, text outside is escaped
        expected = "<pre>Special chars: -_.!</pre> &amp; more"
        self.assertEqual(formatted, expected)

    def test_format_bold(self):
        text = "This is **bold** text."
        formatted = self.formatter.format_response(text, debug_mode=True)
        expected = "This is <b>bold</b> text."
        self.assertEqual(formatted, expected)

    def test_format_italic(self):
        text = "This is *italic* and _italic_ text."
        formatted = self.formatter.format_response(text, debug_mode=True)
        expected = "This is <i>italic</i> and <i>italic</i> text."
        self.assertEqual(formatted, expected)

    def test_format_inline_code(self):
        text = "Use `print()` for output."
        formatted = self.formatter.format_response(text, debug_mode=True)
        expected = "Use <code>print()</code> for output."
        self.assertEqual(formatted, expected)

    def test_format_inline_code_preserves_underscores(self):
        text = "Use `snake_case_value` literally."
        formatted = self.formatter.format_response(text, debug_mode=True)
        expected = "Use <code>snake_case_value</code> literally."
        self.assertEqual(formatted, expected)

    def test_format_fenced_code_block(self):
        text = "Here is code:\n\n```python\nprint('hi')\n```\n\nDone."
        formatted = self.formatter.format_response(text, debug_mode=True)
        expected = "Here is code:\n\n<pre>print(&#x27;hi&#x27;)</pre>\n\nDone."
        self.assertEqual(formatted, expected)

    def test_format_link(self):
        text = "Check [Google](https://google.com)."
        formatted = self.formatter.format_response(text, debug_mode=True)
        expected = 'Check <a href="https://google.com">Google</a>.'
        self.assertEqual(formatted, expected)

    def test_format_strikethrough(self):
        text = "This is ~~bad~~ good."
        formatted = self.formatter.format_response(text, debug_mode=True)
        expected = "This is <s>bad</s> good."
        self.assertEqual(formatted, expected)

    def test_format_underline(self):
        text = "This is __underlined__."
        formatted = self.formatter.format_response(text, debug_mode=True)
        expected = "This is <u>underlined</u>."
        self.assertEqual(formatted, expected)

    def test_format_spoiler(self):
        text = "This is ||secret||."
        formatted = self.formatter.format_response(text, debug_mode=True)
        expected = "This is <tg-spoiler>secret</tg-spoiler>."
        self.assertEqual(formatted, expected)

    def test_no_blockquote(self):
        text = "Just normal text & stuff."
        formatted = self.formatter.format_response(text, debug_mode=True)
        expected = "Just normal text &amp; stuff."
        self.assertEqual(formatted, expected)


if __name__ == "__main__":
    unittest.main()
