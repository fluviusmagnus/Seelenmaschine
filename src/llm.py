from openai import OpenAI
from config import Config
from typing import List, Dict
import logging
import tools
import json


class LLMClient:
    def __init__(self):
        self.client = OpenAI(
            api_key=Config.OPENAI_API_KEY, base_url=Config.OPENAI_API_BASE
        )

    def generate_response(
        self, model: str, messages: List[Dict], use_tools: bool = True
    ) -> str:
        try:
            logging.debug(f"完整提示词: {messages}")
            if use_tools and (Config.ENABLE_WEB_SEARCH or False):  # 列举所有工具
                while True:
                    response = self.client.chat.completions.create(
                        model=model,
                        messages=messages,
                        tools=tools.tools_list,
                        tool_choice="auto",
                    )

                    message = response.choices[0].message

                    # 如果没有工具调用，直接返回消息
                    if not message.tool_calls:
                        if hasattr(message, "reasoning_content"):
                            logging.debug(f"检测到推理: {message.reasoning_content}")
                        logging.debug(f"生成的回复: {message.content}")
                        return message.content

                    # 处理工具调用
                    messages.append(message)  # 添加助手的响应

                    for tool_call in message.tool_calls:
                        function_name = tool_call.function.name
                        function_args = json.loads(tool_call.function.arguments)

                        logging.debug(f"检测到工具调用: {function_name}")
                        logging.debug(f"检测到工具参数: {function_args}")

                        # 执行函数调用
                        if function_name == "search_web":
                            result = tools.search_web(**function_args)
                        else:
                            result = f"Unknown function: {function_name}"

                        logging.debug(f"工具返回结果: {result}")

                        # 添加工具执行结果
                        messages.append(
                            {
                                "tool_call_id": tool_call.id,
                                "role": "tool",
                                "name": function_name,
                                "content": result,
                            }
                        )
            else:
                response = self.client.chat.completions.create(
                    model=model,
                    messages=messages,
                    reasoning_effort=Config.REASONING_EFFORT,
                )

            if hasattr(response.choices[0].message, "reasoning_content"):
                logging.debug(
                    f"检测到推理: {response.choices[0].message.reasoning_content}"
                )
            logging.debug(f"生成的回复: {response.choices[0].message.content}")
            return response.choices[0].message.content

        except Exception as e:
            raise Exception(f"API请求失败 使用模型 {model}: {str(e)}")

    def get_embedding(self, text: str) -> List[float]:
        try:
            response = self.client.embeddings.create(
                input=text, model=Config.EMBEDDING_MODEL
            )
            return response.data[0].embedding
        except Exception as e:
            raise Exception(f"嵌入生成失败: {str(e)}")
