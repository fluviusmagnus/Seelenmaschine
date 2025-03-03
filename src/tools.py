from config import Config
import requests
import json


def search_web(query: str) -> str:
    """调用JINA API搜索网络，返回自然语言形式结果"""

    url = "https://deepsearch.jina.ai/v1/chat/completions"
    headers = {
        "Content-Type": "application/json",
    }
    if Config.JINA_API_KEY:
        headers["Authorization"] = f"Bearer {Config.JINA_API_KEY}"
    data = {
        "model": "jina-deepsearch-v1",
        "messages": [
            {
                "role": "user",
                "content": "你是一个智能搜索引擎，你将根据我提供的信息搜索网络，并以自然语言形式返回结果。如有引用，请注明出处URL。",
            },
            {"role": "user", "content": query},
        ],
        "stream": False,
        "reasoning_effort": "low",
        "max_attempts": 2,
    }
    try:
        response = requests.post(url, headers=headers, data=json.dumps(data))
        answer = response.json()["choices"][0]["message"]["content"]
    except Exception as e:
        answer = "Error: Web search failed."
        raise Exception(f"Web search failed: {str(e)}")

    return answer


search_web_tool = {
    "type": "function",
    "function": {
        "name": "search_web",
        "description": "Search the web and return the result in natural language.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Keywords or question to search the web.",
                }
            },
            "required": ["query"],
        },
    },
}

tools_list = [search_web_tool]
