import json
from pathlib import Path
from typing import Dict, List, Any, Optional
from fastmcp import Client
import asyncio

from config import Config
from utils.logger import get_logger

logger = get_logger()


class MCPClient:
    """MCP client wrapper using fastmcp.Client"""

    def __init__(
        self,
        config_path: Optional[Path] = None,
    ):
        self.config_path = config_path or Config.MCP_CONFIG_PATH
        self.client: Optional[Client] = None
        self._config = self._load_config()
        self._tools_cache: Optional[List[Dict[str, Any]]] = None

    def _get_default_roots(self) -> List[str]:
        """Get default roots configuration - using data directory"""
        data_dir = Config.DATA_DIR
        
        return [data_dir.as_uri()]

    def _load_config(self) -> Dict:
        """Load MCP server configuration"""
        if not self.config_path.exists():
            logger.warning(f"MCP config file not found: {self.config_path}")
            return {"mcpServers": {}}

        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                config = json.load(f)
                return config
        except Exception as e:
            logger.error(f"Failed to load MCP config: {e}")
            return {"mcpServers": {}}

    async def __aenter__(self):
        """Async context manager entry"""
        if not self._config.get("mcpServers"):
            logger.warning("No MCP servers configured")
            return self

        processed_config = self._process_config(self._config)
        roots = self._get_default_roots()

        self.client = Client(processed_config, roots=roots)
        
        await self.client.__aenter__()
        
        logger.info("MCP client connected")
        return self

    def _process_config(self, config: Dict) -> Dict:
        """Process config, convert bearerToken to Authorization header"""
        processed = {"mcpServers": {}}

        for name, server_config in config.get("mcpServers", {}).items():
            new_config = server_config.copy()

            if "bearerToken" in new_config:
                token = new_config.pop("bearerToken")
                if "headers" not in new_config:
                    new_config["headers"] = {}
                new_config["headers"]["Authorization"] = f"Bearer {token}"
                logger.debug(f"Added Authorization header for server {name}")

            processed["mcpServers"][name] = new_config

        return processed

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        if self.client:
            await self.client.__aexit__(exc_type, exc_val, exc_tb)
            logger.info("MCP client disconnected")

    async def list_tools(self) -> List[Dict]:
        """List all available tools, convert to OpenAI function calling format"""
        if not self.client:
            return []

        try:
            tools_response = await self.client.list_tools()

            if hasattr(tools_response, "result"):
                tools_response = tools_response.result
            elif isinstance(tools_response, dict) and "result" in tools_response:
                tools_response = tools_response["result"]

            if hasattr(tools_response, "tools"):
                tools_list = tools_response.tools
            elif isinstance(tools_response, dict) and "tools" in tools_response:
                tools_list = tools_response["tools"]
            elif isinstance(tools_response, list):
                tools_list = tools_response
            else:
                logger.error(f"Unknown tools list format: {type(tools_response)}")
                return []

            formatted_tools = []
            for tool in tools_list:
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
            
            self._tools_cache = formatted_tools
            return formatted_tools
            
        except Exception as e:
            logger.error(f"Failed to list tools: {e}", exc_info=True)
            return []

    def get_tools_sync(self) -> List[Dict]:
        """Get tools synchronously (wrapper for async)"""
        if self._tools_cache is not None:
            return self._tools_cache
        
        loop = asyncio.get_event_loop()
        try:
            return loop.run_until_complete(self.list_tools())
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            return loop.run_until_complete(self.list_tools())

    async def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> str:
        """Call tool and return result text"""

        if not self.client:
            error_msg = "Error: MCP client not connected"
            logger.error(error_msg)
            return error_msg

        try:
            result = await self.client.call_tool(tool_name, arguments)

            if result.content and len(result.content) > 0:
                first_content = result.content[0]
                if hasattr(first_content, "text"):
                    result_text = first_content.text
                    return result_text
                else:
                    result_text = str(first_content)
                    return result_text

            logger.warning(f"Tool call successful but no content: {tool_name}")
            return "Tool call successful but no content"
            
        except Exception as e:
            error_msg = f"Tool call failed: {str(e)}"
            logger.error(
                f"{error_msg} (tool={tool_name}, args={arguments})", exc_info=True
            )
            return error_msg

    def call_tool_sync(self, tool_name: str, arguments: Dict[str, Any]) -> str:
        """Call tool synchronously (wrapper for async)"""
        loop = asyncio.get_event_loop()
        try:
            return loop.run_until_complete(self.call_tool(tool_name, arguments))
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            return loop.run_until_complete(self.call_tool(tool_name, arguments))
