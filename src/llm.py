from openai import OpenAI
from config import Config
from typing import List, Dict
import logging


class LLMClient:
    def __init__(self):
        self.client = OpenAI(
            api_key=Config.OPENAI_API_KEY, base_url=Config.OPENAI_API_BASE
        )

    def generate_response(self, messages: List[Dict]) -> str:
        try:
            response = self.client.chat.completions.create(
                model=Config.CHAT_MODEL, messages=messages, temperature=0.7
            )
            if Config.DEBUG_MODE:
                logging.debug(f"完整提示词: {messages}")
            return response.choices[0].message.content
        except Exception as e:
            raise Exception(f"API请求失败: {str(e)}")

    def get_embedding(self, text: str) -> List[float]:
        try:
            response = self.client.embeddings.create(
                input=text, model=Config.EMBEDDING_MODEL
            )
            return response.data[0].embedding
        except Exception as e:
            raise Exception(f"嵌入生成失败: {str(e)}")
