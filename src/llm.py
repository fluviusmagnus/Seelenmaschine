from openai import OpenAI
from config import Config
from typing import List, Dict
import logging
import json
import asyncio
from mcp_client import MCPClient


class LLMClient:
    def __init__(self):
        self.client = OpenAI(
            api_key=Config.OPENAI_API_KEY, base_url=Config.OPENAI_API_BASE
        )
        self.mcp_client = None
        self._tools_cache = None

    def _get_event_loop(self):
        """获取或创建事件循环"""
        try:
            loop = asyncio.get_event_loop()
            if loop.is_closed():
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
            return loop
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            return loop

    def _get_tools(self) -> List[Dict]:
        """获取所有可用工具（MCP + 本地）"""
        if self._tools_cache is not None:
            return self._tools_cache

        all_tools = []

        # 尝试从 MCP 获取工具
        if Config.ENABLE_MCP:
            try:
                loop = self._get_event_loop()
                mcp_tools = loop.run_until_complete(self._fetch_mcp_tools())
                all_tools.extend(mcp_tools)
                logging.info(f"从MCP获取到 {len(mcp_tools)} 个工具")
            except Exception as e:
                logging.error(f"从MCP获取工具失败: {e}")

        # 如果没有从 MCP 获取到工具，使用传统的本地工具
        if not all_tools and Config.ENABLE_WEB_SEARCH:
            import tools

            all_tools = tools.tools_list
            logging.info(f"使用本地工具: {len(all_tools)} 个")

        self._tools_cache = all_tools
        return all_tools

    async def _fetch_mcp_tools(self) -> List[Dict]:
        """异步获取 MCP 工具"""
        mcp = MCPClient(Config.MCP_CONFIG_PATH)
        async with mcp:
            return await mcp.list_tools()

    def _call_tool(self, tool_name: str, arguments: Dict) -> str:
        """调用工具（MCP 或本地）"""
        # 先尝试 MCP
        if Config.ENABLE_MCP:
            try:
                loop = self._get_event_loop()
                result = loop.run_until_complete(
                    self._call_mcp_tool(tool_name, arguments)
                )
                return result
            except Exception as e:
                logging.error(f"MCP工具调用失败: {e}")

        # 回退到本地工具
        if Config.ENABLE_WEB_SEARCH:
            import tools

            if tool_name == "search_web":
                return tools.search_web(**arguments)

        return f"未知工具: {tool_name}"

    async def _call_mcp_tool(self, tool_name: str, arguments: Dict) -> str:
        """异步调用 MCP 工具"""
        mcp = MCPClient(Config.MCP_CONFIG_PATH)
        async with mcp:
            return await mcp.call_tool(tool_name, arguments)

    def generate_response(
        self,
        model: str,
        messages: List[Dict],
        use_tools: bool = True,
        reasoning_effort: str = "low",
    ) -> str:
        try:
            logging.debug(f"完整提示词: {messages}")

            # 获取所有可用工具
            available_tools = self._get_tools() if use_tools else []

            if available_tools:
                while True:
                    response = self.client.chat.completions.create(
                        model=model,
                        messages=messages,
                        tools=available_tools,
                        tool_choice="auto",
                        reasoning_effort=reasoning_effort,
                    )

                    message = response.choices[0].message

                    # 如果没有工具调用，直接返回消息
                    if not message.tool_calls:
                        if hasattr(message, "reasoning_content"):
                            logging.debug(f"检测到推理: {message.reasoning_content}")
                        if hasattr(message, "reasoning"):
                            logging.debug(f"检测到推理: {message.reasoning}")
                        logging.debug(f"生成的回复: {message.content}")
                        return message.content

                    # 处理工具调用
                    messages.append(message)  # 添加助手的响应

                    for tool_call in message.tool_calls:
                        function_name = tool_call.function.name
                        function_args = json.loads(tool_call.function.arguments)

                        logging.debug(f"检测到工具调用: {function_name}")
                        logging.debug(f"检测到工具参数: {function_args}")

                        # 使用统一的工具调用方法
                        result = self._call_tool(function_name, function_args)

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
                    reasoning_effort=reasoning_effort,
                )

            if hasattr(response.choices[0].message, "reasoning_content"):
                logging.debug(
                    f"检测到推理: {response.choices[0].message.reasoning_content}"
                )
            if hasattr(response.choices[0].message, "reasoning"):
                logging.debug(f"检测到推理: {response.choices[0].message.reasoning}")
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
