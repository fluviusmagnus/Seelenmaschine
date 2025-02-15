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
            if Config.DEBUG_MODE:
                logging.debug(f"完整提示词: {messages}")
            response = self.client.chat.completions.create(
                model=Config.CHAT_MODEL, messages=messages
            )
            if Config.DEBUG_MODE:
                if response.choices[0].message.reasoning_content:
                    logging.debug(
                        f"检测到推理: {response.choices[0].message.reasoning_content}"
                    )
                logging.debug(f"生成的回复: {response.choices[0].message.content}")
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
