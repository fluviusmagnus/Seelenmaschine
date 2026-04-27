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

    def test_format_markdown_quote_single_line(self):
        text = "> Single line quote"
        formatted = self.formatter.format_response(text, debug_mode=True)
        expected = "<pre>Single line quote</pre>"
        self.assertEqual(formatted, expected)

    def test_format_markdown_quote_multiline(self):
        text = "> Line 1\n> Line 2\n> Line 3"
        formatted = self.formatter.format_response(text, debug_mode=True)
        expected = "<pre>Line 1\nLine 2\nLine 3</pre>"
        self.assertEqual(formatted, expected)

    def test_format_markdown_quote_mixed_with_text(self):
        text = "Before\n\n> Line 1\n> Line 2\n\nAfter"
        formatted = self.formatter.format_response(text, debug_mode=True)
        expected = "Before\n\n<pre>Line 1\nLine 2</pre>\n\nAfter"
        self.assertEqual(formatted, expected)

    def test_format_markdown_quote_ignored_in_fenced_code(self):
        text = "```text\n> keep literal\n```"
        formatted = self.formatter.format_response(text, debug_mode=True)
        expected = "<pre>&gt; keep literal</pre>"
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

    def test_format_underscore_filename_not_italicized(self):
        text = "Files: eleutheria_screenshot.png / google_screenshot.png"
        formatted = self.formatter.format_response(text, debug_mode=True)
        expected = "Files: eleutheria_screenshot.png / google_screenshot.png"
        self.assertEqual(formatted, expected)

    def test_format_list_with_multiple_bold_filenames_stays_balanced(self):
        text = (
            "- **AGENTS.md** — 教训笔记本\n"
            "- **eleutheria_screenshot.png** / **google_screenshot.png** — 截图们\n"
            "- **prime_numbers.py** — 去年十月写的素数脚本"
        )

        formatted = self.formatter.format_response(text, debug_mode=True)
        expected = (
            "- <b>AGENTS.md</b> — 教训笔记本\n"
            "- <b>eleutheria_screenshot.png</b> / <b>google_screenshot.png</b> — 截图们\n"
            "- <b>prime_numbers.py</b> — 去年十月写的素数脚本"
        )
        self.assertEqual(formatted, expected)

    def test_format_link_label_can_contain_bold_without_crossing_tags(self):
        text = "Check [**Google** docs](https://google.com)."
        formatted = self.formatter.format_response(text, debug_mode=True)
        expected = 'Check <a href="https://google.com"><b>Google</b> docs</a>.'
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

    def test_format_markdown_table_as_preformatted_text(self):
        text = "| Name | Age |\n| --- | --- |\n| Alice | 24 |\n| Bob | 31 |"
        formatted = self.formatter.format_response(text, debug_mode=True)
        expected = "<pre>Name  | Age\n------+----\nAlice | 24\nBob   | 31</pre>"
        self.assertEqual(formatted, expected)

    def test_format_markdown_table_without_edge_pipes(self):
        text = "Name | City\n--- | ---\nAlice | Tokyo"
        formatted = self.formatter.format_response(text, debug_mode=True)
        expected = "<pre>Name  | City\n------+------\nAlice | Tokyo</pre>"
        self.assertEqual(formatted, expected)

    def test_format_markdown_table_mixed_with_text(self):
        text = "Before\n\n| A | B |\n| --- | --- |\n| 1 | 2 |\n\nAfter"
        formatted = self.formatter.format_response(text, debug_mode=True)
        expected = "Before\n\n<pre>A   | B\n----+----\n1   | 2</pre>\n\nAfter"
        self.assertEqual(formatted, expected)

    def test_format_markdown_table_ignored_in_fenced_code(self):
        text = "```text\n| A | B |\n| --- | --- |\n| 1 | 2 |\n```"
        formatted = self.formatter.format_response(text, debug_mode=True)
        expected = "<pre>| A | B |\n| --- | --- |\n| 1 | 2 |</pre>"
        self.assertEqual(formatted, expected)

    def test_format_markdown_table_escapes_special_chars(self):
        text = "| Key | Value |\n| --- | --- |\n| tag | <div> & stuff |"
        formatted = self.formatter.format_response(text, debug_mode=True)
        expected = (
            "<pre>Key | Value\n"
            "----+--------------\n"
            "tag | &lt;div&gt; &amp; stuff</pre>"
        )
        self.assertEqual(formatted, expected)

    def test_format_markdown_table_preserves_underscores_in_plain_cells(self):
        text = "| File | Value |\n| --- | --- |\n| foo_bar_baz.py | 1 |"
        formatted = self.formatter.format_response(text, debug_mode=True)

        self.assertIn("foo_bar_baz.py", formatted)

    def test_format_markdown_table_with_cjk_headers_and_two_dash_alignment(self):
        text = (
            "| 排名 | 模型 | 指数 |\n"
            "|:--:|------|:---:|\n"
            "| 1 | **GPT-5.5 (xhigh)** | 60 |\n"
            "| 2 | GPT-5.5 (high) | 59 |\n"
            "| 3 | Claude Opus 4.7 (max) | 57 |\n"
            "| 3 | Gemini 3.1 Pro Preview | 57 |\n"
            "| 3 | GPT-5.4 (xhigh) | 57 |\n"
            "| 3 | GPT-5.5 (medium) | 57 |\n"
            "| 7 | Kimi K2.6 | 54 |\n"
            "| 7 | MiMo-V2.5-Pro | 54 |\n"
            "| 7 | GPT-5.3 Codex (xhigh) | 54 |"
        )

        formatted = self.formatter.format_response(text, debug_mode=True)

        self.assertTrue(formatted.startswith("<pre>排名"))
        self.assertIn("GPT-5.5 (xhigh)", formatted)
        self.assertIn("-----+------------------------+-----", formatted)
        self.assertNotIn("**GPT-5.5 (xhigh)**", formatted)
        self.assertTrue(formatted.endswith("</pre>"))

    def test_no_blockquote(self):
        text = "Just normal text & stuff."
        formatted = self.formatter.format_response(text, debug_mode=True)
        expected = "Just normal text &amp; stuff."
        self.assertEqual(formatted, expected)


if __name__ == "__main__":
    unittest.main()
