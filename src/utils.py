import re


def remove_cite_tags(text: str) -> str:
    """移除文本中的cite标签及其内容

    Args:
        text: 包含cite标签的文本

    Returns:
        移除cite标签及其内容后的文本
    """
    return re.sub(r"<cite>.*?</cite>\n*", "", text, flags=re.DOTALL)
