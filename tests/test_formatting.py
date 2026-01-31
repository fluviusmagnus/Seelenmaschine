import unittest
from tg_bot.handlers import MessageHandler


class TestFormatting(unittest.TestCase):
    def setUp(self):
        # We only need to test the static method logic, but it's an instance method.
        # We can mock the dependencies since we won't be using them.
        import collections

        Config = collections.namedtuple(
            "Config", ["ENABLE_MCP", "TELEGRAM_USER_ID", "TELEGRAM_USE_MARKDOWN"]
        )

        # Mocking __init__ effectively by creating a dummy class or just instantiating and mocking
        # But MessageHandler does a lot in __init__.
        # Let's just monkeypatch the __init__ to do nothing for this test.
        original_init = MessageHandler.__init__
        MessageHandler.__init__ = lambda self: None
        try:
            self.handler = MessageHandler()
        finally:
            MessageHandler.__init__ = original_init

    def test_format_blockquote_simple(self):
        text = "Here is a quote: <blockquote>This is quoted text.</blockquote>"
        formatted = self.handler._format_response_for_telegram(text)
        # Expect HTML format
        expected = "Here is a quote: <pre>This is quoted text.</pre>"
        self.assertEqual(formatted, expected)

    def test_format_blockquote_multiline(self):
        text = "<blockquote>Line 1\nLine 2</blockquote>"
        formatted = self.handler._format_response_for_telegram(text)
        expected = "<pre>Line 1\nLine 2</pre>"
        self.assertEqual(formatted, expected)

    def test_format_blockquote_with_special_chars(self):
        # Characters that needs HTML escaping outside block
        text = "<blockquote>Special chars: -_.!</blockquote> & more"
        formatted = self.handler._format_response_for_telegram(text)
        # Content inside pre is escaped, text outside is escaped
        expected = "<pre>Special chars: -_.!</pre> &amp; more"
        self.assertEqual(formatted, expected)

    def test_format_bold(self):
        text = "This is **bold** text."
        formatted = self.handler._format_response_for_telegram(text)
        expected = "This is <b>bold</b> text."
        self.assertEqual(formatted, expected)

    def test_format_italic(self):
        text = "This is *italic* and _italic_ text."
        formatted = self.handler._format_response_for_telegram(text)
        expected = "This is <i>italic</i> and <i>italic</i> text."
        self.assertEqual(formatted, expected)

    def test_format_inline_code(self):
        text = "Use `print()` for output."
        formatted = self.handler._format_response_for_telegram(text)
        expected = "Use <code>print()</code> for output."
        self.assertEqual(formatted, expected)

    def test_format_link(self):
        text = "Check [Google](https://google.com)."
        formatted = self.handler._format_response_for_telegram(text)
        expected = 'Check <a href="https://google.com">Google</a>.'
        self.assertEqual(formatted, expected)

    def test_format_strikethrough(self):
        text = "This is ~~bad~~ good."
        formatted = self.handler._format_response_for_telegram(text)
        expected = "This is <s>bad</s> good."
        self.assertEqual(formatted, expected)

    def test_format_underline(self):
        text = "This is __underlined__."
        formatted = self.handler._format_response_for_telegram(text)
        expected = "This is <u>underlined</u>."
        self.assertEqual(formatted, expected)

    def test_format_spoiler(self):
        text = "This is ||secret||."
        formatted = self.handler._format_response_for_telegram(text)
        expected = "This is <tg-spoiler>secret</tg-spoiler>."
        self.assertEqual(formatted, expected)

    def test_no_blockquote(self):
        text = "Just normal text & stuff."
        formatted = self.handler._format_response_for_telegram(text)
        expected = "Just normal text &amp; stuff."
        self.assertEqual(formatted, expected)


if __name__ == "__main__":
    unittest.main()
