from openai import OpenAI
from config import Config
from typing import List, Dict, Optional
import logging
import json
import asyncio
from mcp_client import MCPClient


class LLMClient:
    def __init__(self):
        self.client = OpenAI(
            api_key=Config.OPENAI_API_KEY, base_url=Config.OPENAI_API_BASE
        )
        self.mcp_client: Optional[MCPClient] = None
        self._tools_cache = None
        self._event_loop = None

    def _get_event_loop(self):
        """获取或创建事件循环（复用同一个事件循环）"""
        if self._event_loop is None or self._event_loop.is_closed():
            try:
                loop = asyncio.get_event_loop()
                if loop.is_closed():
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                self._event_loop = loop
            except RuntimeError:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                self._event_loop = loop
        return self._event_loop

    async def _ensure_mcp_connected(self):
        """确保 MCP 客户端已连接（延迟初始化 + 连接复用）"""
        if self.mcp_client is None:
            logging.info("初始化 MCP 客户端连接...")
            self.mcp_client = MCPClient(Config.MCP_CONFIG_PATH)
            await self.mcp_client.__aenter__()
            logging.info("MCP 客户端连接已建立")

    def _get_tools(self) -> List[Dict]:
        """获取所有可用工具（MCP + 本地）"""
        if self._tools_cache is not None:
            logging.debug(f"使用缓存的工具列表，共 {len(self._tools_cache)} 个工具")
            return self._tools_cache

        all_tools = []

        # 尝试从 MCP 获取工具
        if Config.ENABLE_MCP:
            try:
                # 使用复用的连接获取工具列表
                loop = self._get_event_loop()
                mcp_tools = loop.run_until_complete(self._fetch_mcp_tools())
                all_tools.extend(mcp_tools)
            except Exception as e:
                logging.error(f"从MCP获取工具失败: {e}", exc_info=True)

        # 如果没有从 MCP 获取到工具，使用传统的本地工具
        if not all_tools and Config.ENABLE_WEB_SEARCH:
            import tools

            all_tools = tools.tools_list

        self._tools_cache = all_tools

        return all_tools

    async def _fetch_mcp_tools(self) -> List[Dict]:
        """使用复用的连接获取 MCP 工具列表"""
        await self._ensure_mcp_connected()
        return await self.mcp_client.list_tools()

    def _call_tool(self, tool_name: str, arguments: Dict) -> str:
        """调用工具（MCP 或本地）"""

        # 先尝试 MCP
        if Config.ENABLE_MCP:
            try:
                logging.debug(f"尝试使用MCP调用工具: {tool_name}")
                # 使用复用的连接调用工具
                loop = self._get_event_loop()
                result = loop.run_until_complete(
                    self._call_mcp_tool(tool_name, arguments)
                )
                return result
            except Exception as e:
                logging.error(f"MCP工具调用失败: {e}", exc_info=True)

        # 回退到本地工具
        if Config.ENABLE_WEB_SEARCH:
            import tools

            if tool_name == "search_web":
                logging.debug(f"使用本地工具: search_web")
                return tools.search_web(**arguments)

        error_msg = f"未知工具: {tool_name}"
        logging.error(error_msg)
        return error_msg

    async def _call_mcp_tool(self, tool_name: str, arguments: Dict) -> str:
        """使用复用的连接调用 MCP 工具"""

        # 确保连接已建立
        await self._ensure_mcp_connected()
        result = await self.mcp_client.call_tool(tool_name, arguments)
        return result

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
            logging.debug(f"available_tools 数量: {len(available_tools)}")

            if available_tools:
                while True:
                    logging.debug(
                        f"准备调用OpenAI API，消息数量: {len(messages)}, 工具数量: {len(available_tools)}"
                    )
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

    def cleanup(self):
        """清理 MCP 客户端连接（显式调用）"""
        if self.mcp_client:
            try:
                loop = self._get_event_loop()
                loop.run_until_complete(self.mcp_client.__aexit__(None, None, None))
                self.mcp_client = None
            except Exception as e:
                logging.error(f"关闭 MCP 客户端连接失败: {e}")

    def __del__(self):
        """析构函数 - 尝试清理资源"""
        try:
            self.cleanup()
        except Exception:
            pass  # 忽略析构时的错误
