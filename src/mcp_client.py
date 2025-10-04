import json
import logging
from pathlib import Path
from typing import Dict, List, Any, Optional
from fastmcp import Client
import asyncio
from .config import Config


class MCPClient:
    """使用 fastmcp.Client 的 MCP 客户端封装"""

    def __init__(
        self,
        config_path: str = "mcp_servers.json",
        roots: Optional[List[Dict[str, str]]] = None,
    ):
        self.config_path = Path(config_path)
        self.client: Optional[Client] = None
        self._config = self._load_config()
        # 设置 roots 配置
        self.roots = roots or self._get_default_roots()

    def _get_default_roots(self) -> List[Dict[str, str]]:
        """获取默认的 roots 配置 - 使用数据目录"""
        data_dir = Config.DATA_DIR
        # 确保数据目录存在
        data_dir.mkdir(parents=True, exist_ok=True)

        # 转换为 file:// URI 格式
        # Windows 路径需要特殊处理
        data_uri = data_dir.as_uri()

        return [{"uri": data_uri, "name": "数据目录"}]

    def _load_config(self) -> Dict:
        """加载MCP服务器配置"""
        if not self.config_path.exists():
            logging.warning(f"MCP配置文件不存在: {self.config_path}")
            return {"mcpServers": {}}

        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                config = json.load(f)
                logging.info(
                    f"已加载 {len(config.get('mcpServers', {}))} 个MCP服务器配置"
                )
                return config
        except Exception as e:
            logging.error(f"加载MCP配置失败: {e}")
            return {"mcpServers": {}}

    async def __aenter__(self):
        """异步上下文管理器入口"""
        if not self._config.get("mcpServers"):
            logging.warning("没有配置MCP服务器")
            return self

        # 预处理配置：将 bearerToken 转换为 headers
        processed_config = self._process_config(self._config)

        # 创建客户端配置，包含 roots 支持
        client_config = {
            **processed_config,
            "capabilities": {"roots": {"listChanged": False}},  # 暂不支持动态变化
        }

        # 使用 fastmcp.Client 连接到所有配置的服务器
        self.client = Client(client_config)

        # 如果 client 支持设置 roots handler，设置它
        if hasattr(self.client, "set_roots_handler"):
            self.client.set_roots_handler(self._handle_roots_request)

        await self.client.__aenter__()
        logging.info(f"MCP客户端已连接，roots: {[r['name'] for r in self.roots]}")
        return self

    async def _handle_roots_request(self) -> Dict:
        """处理服务器的 roots/list 请求"""
        logging.debug(f"服务器请求 roots 列表，返回 {len(self.roots)} 个 roots")
        return {"roots": self.roots}

    def _process_config(self, config: Dict) -> Dict:
        """处理配置，将 bearerToken 转换为 Authorization header"""
        processed = {"mcpServers": {}}

        for name, server_config in config.get("mcpServers", {}).items():
            new_config = server_config.copy()

            # 如果有 bearerToken，将其转换为 Authorization header
            if "bearerToken" in new_config:
                token = new_config.pop("bearerToken")
                if "headers" not in new_config:
                    new_config["headers"] = {}
                new_config["headers"]["Authorization"] = f"Bearer {token}"
                logging.debug(f"为服务器 {name} 添加了 Authorization header")

            processed["mcpServers"][name] = new_config

        return processed

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """异步上下文管理器退出"""
        if self.client:
            await self.client.__aexit__(exc_type, exc_val, exc_tb)
            logging.info("MCP客户端已断开")

    async def list_tools(self) -> List[Dict]:
        """列出所有可用的工具，转换为 OpenAI function calling 格式"""
        if not self.client:
            return []

        try:
            # 获取所有工具
            tools_response = await self.client.list_tools()

            # 处理不同的响应格式
            # 首先检查是否有 result 字段（JSON-RPC 响应格式）
            if hasattr(tools_response, "result"):
                tools_response = tools_response.result
            elif isinstance(tools_response, dict) and "result" in tools_response:
                tools_response = tools_response["result"]

            # 然后提取工具列表
            if hasattr(tools_response, "tools"):
                # 标准对象格式
                tools_list = tools_response.tools
            elif isinstance(tools_response, dict) and "tools" in tools_response:
                # 字典格式
                tools_list = tools_response["tools"]
            elif isinstance(tools_response, list):
                # 直接列表格式
                tools_list = tools_response
            else:
                logging.error(f"未知的工具列表格式: {type(tools_response)}")
                return []

            # 转换为 OpenAI function calling 格式
            formatted_tools = []
            for tool in tools_list:
                # 处理工具对象或字典
                if isinstance(tool, dict):
                    tool_name = tool.get("name", "")
                    tool_description = tool.get("description", "")
                    tool_schema = tool.get("inputSchema", {})
                else:
                    tool_name = getattr(tool, "name", "")
                    tool_description = getattr(tool, "description", "")
                    tool_schema = getattr(tool, "inputSchema", {})

                formatted_tool = {
                    "type": "function",
                    "function": {
                        "name": tool_name,
                        "description": tool_description,
                        "parameters": tool_schema,
                    },
                }
                formatted_tools.append(formatted_tool)

            logging.info(f"获取到 {len(formatted_tools)} 个MCP工具")
            return formatted_tools
        except Exception as e:
            logging.error(f"列出工具失败: {e}", exc_info=True)
            return []

    async def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> str:
        """调用工具并返回结果文本"""
        logging.debug(f"MCPClient.call_tool 开始: {tool_name}, 参数: {arguments}")

        if not self.client:
            error_msg = "错误: MCP客户端未连接"
            logging.error(error_msg)
            return error_msg

        try:
            logging.debug(f"准备调用 fastmcp client.call_tool: {tool_name}")
            # 使用 fastmcp.Client 调用工具
            result = await self.client.call_tool(tool_name, arguments)
            logging.debug(f"fastmcp client.call_tool 返回成功: {tool_name}")

            # 提取文本内容
            if result.content and len(result.content) > 0:
                # fastmcp 返回的内容可能是 TextContent 或其他类型
                first_content = result.content[0]
                if hasattr(first_content, "text"):
                    result_text = first_content.text
                    logging.debug(f"工具调用成功，返回文本长度: {len(result_text)}")
                    return result_text
                else:
                    result_text = str(first_content)
                    logging.debug(f"工具调用成功，返回字符串长度: {len(result_text)}")
                    return result_text

            logging.warning(f"工具调用成功但无返回内容: {tool_name}")
            return "工具调用成功但无返回内容"
        except Exception as e:
            error_msg = f"工具调用失败: {str(e)}"
            logging.error(
                f"{error_msg} (tool={tool_name}, args={arguments})", exc_info=True
            )
            return error_msg


def create_mcp_client(
    config_path: str = "mcp_servers.json", roots: Optional[List[Dict[str, str]]] = None
) -> MCPClient:
    """创建 MCP 客户端实例的工厂函数

    Args:
        config_path: MCP服务器配置文件路径
        roots: 可选的 roots 列表，如果不提供则使用数据目录

    Returns:
        MCPClient 实例
    """
    return MCPClient(config_path, roots)
