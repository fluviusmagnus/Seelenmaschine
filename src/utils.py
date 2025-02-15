import re


def remove_blockquote_tags(text: str) -> str:
    """移除文本中的blockquote标签及其内容,并去除头尾的空白字符

    Args:
        text: 包含blockquote标签的文本

    Returns:
        清理过的文本
    """
    return re.sub(r"<blockquote>.*?</blockquote>\n*", "", text, flags=re.DOTALL).strip()
