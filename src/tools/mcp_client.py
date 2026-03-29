import json
from pathlib import Path
from typing import Dict, List, Any, Optional
from fastmcp import Client
import asyncio
import re

from core.config import Config
from utils.logger import get_logger

logger = get_logger()


class MCPClient:
    """MCP client wrapper using fastmcp.Client"""

    _BASE64_SEQUENCE_PATTERN = re.compile(r"[A-Za-z0-9+/=]{512,}")

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

    def _extract_text_from_content_block(self, content_block: Any) -> str:
        """Extract text from an MCP content block."""
        block_type = self._get_content_block_attr(content_block, "type")
        mime_type = self._get_content_block_attr(content_block, "mimeType")
        if mime_type is None:
            mime_type = self._get_content_block_attr(content_block, "mime_type")

        text = self._get_content_block_attr(content_block, "text")
        if text is not None:
            return self._sanitize_text_block(
                str(text), block_type=block_type, mime_type=mime_type
            )

        if self._is_binary_like_content_block(content_block, block_type, mime_type):
            return self._summarize_non_text_content_block(
                content_block, block_type, mime_type
            )

        if isinstance(content_block, dict):
            serialized = json.dumps(content_block, ensure_ascii=False)
            return self._sanitize_text_block(
                serialized, block_type=block_type, mime_type=mime_type
            )

        return self._sanitize_text_block(
            str(content_block), block_type=block_type, mime_type=mime_type
        )

    def _get_content_block_attr(self, content_block: Any, key: str) -> Any:
        """Get attribute/key value from MCP content block objects or dicts."""
        if isinstance(content_block, dict):
            return content_block.get(key)
        return getattr(content_block, key, None)

    def _is_binary_like_content_block(
        self, content_block: Any, block_type: Any, mime_type: Any
    ) -> bool:
        """Detect MCP content blocks that should not be injected as raw text."""
        normalized_type = str(block_type or "").lower()
        normalized_mime = str(mime_type or "").lower()

        if normalized_type in {
            "image",
            "audio",
            "video",
            "resource",
            "blob",
            "binary",
            "file",
        }:
            return True

        if normalized_mime and not normalized_mime.startswith("text/"):
            if normalized_mime.startswith(("image/", "audio/", "video/")):
                return True
            if normalized_mime in {
                "application/octet-stream",
                "application/pdf",
                "application/zip",
                "application/json+binary",
            }:
                return True

        data = self._get_content_block_attr(content_block, "data")
        if data is None:
            data = self._get_content_block_attr(content_block, "blob")
        if data is None:
            data = self._get_content_block_attr(content_block, "bytes")

        if isinstance(data, (bytes, bytearray)):
            return True
        if isinstance(data, str) and self._BASE64_SEQUENCE_PATTERN.search(data):
            return True

        if isinstance(content_block, dict):
            for suspicious_key in ("data", "blob", "bytes", "base64"):
                value = content_block.get(suspicious_key)
                if isinstance(value, (bytes, bytearray)):
                    return True
                if isinstance(value, str) and self._BASE64_SEQUENCE_PATTERN.search(
                    value
                ):
                    return True

        return False

    def _sanitize_text_block(
        self,
        text: str,
        block_type: Optional[str] = None,
        mime_type: Optional[str] = None,
    ) -> str:
        """Prevent huge/base64-heavy tool payloads from entering the prompt."""
        if not text:
            return ""

        base64_match = self._find_base64_like_sequence(text)
        if base64_match is not None:
            return self._build_omitted_binary_message(
                block_type=block_type,
                mime_type=mime_type,
                details=f"base64_length≈{len(base64_match)}",
            )

        if len(text) <= Config.MCP_TEXT_BLOCK_MAX_CHARS:
            return text

        omitted_chars = len(text) - Config.MCP_TEXT_BLOCK_MAX_CHARS
        head = text[: Config.MCP_TEXT_BLOCK_TRUNCATE_HEAD_CHARS].rstrip()
        tail = text[-Config.MCP_TEXT_BLOCK_TRUNCATE_TAIL_CHARS :].lstrip()
        return (
            f"{head}\n\n"
            f"[tool output truncated, omitted {omitted_chars} characters]\n\n"
            f"{tail}"
        )

    def _find_base64_like_sequence(self, text: str) -> Optional[str]:
        """Return a suspicious base64-like sequence if one is found."""
        for match in self._BASE64_SEQUENCE_PATTERN.finditer(text):
            candidate = match.group(0)
            if self._looks_like_base64_payload(candidate):
                return candidate
        return None

    def _looks_like_base64_payload(self, candidate: str) -> bool:
        """Heuristic to avoid misclassifying long plain text as base64."""
        if len(candidate) < 512:
            return False

        if not any(ch in candidate for ch in "+/="):
            return False

        distinct_chars = len(set(candidate))
        if distinct_chars < 8:
            return False

        return True

    def _summarize_non_text_content_block(
        self, content_block: Any, block_type: Any, mime_type: Any
    ) -> str:
        """Return a short summary instead of raw binary/resource content."""
        details: List[str] = []

        uri = self._get_content_block_attr(content_block, "uri")
        if uri:
            details.append(f"uri={uri}")

        name = self._get_content_block_attr(content_block, "name")
        if name:
            details.append(f"name={name}")

        for key in ("data", "blob", "bytes", "base64"):
            value = self._get_content_block_attr(content_block, key)
            if value is None and isinstance(content_block, dict):
                value = content_block.get(key)

            if isinstance(value, (bytes, bytearray)):
                details.append(f"bytes={len(value)}")
                break
            if isinstance(value, str):
                details.append(f"data_length={len(value)}")
                break

        return self._build_omitted_binary_message(
            block_type=block_type,
            mime_type=mime_type,
            details=", ".join(details) if details else None,
        )

    def _build_omitted_binary_message(
        self,
        block_type: Optional[str] = None,
        mime_type: Optional[str] = None,
        details: Optional[str] = None,
    ) -> str:
        """Build a compact placeholder for omitted binary content."""
        info_parts = []
        if block_type:
            info_parts.append(f"type={block_type}")
        if mime_type:
            info_parts.append(f"mime={mime_type}")
        if details:
            info_parts.append(details)

        suffix = f" ({', '.join(info_parts)})" if info_parts else ""
        return f"[non-text MCP content omitted{suffix}]"

    async def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> str:
        """Call tool and return result text"""

        if not self.client:
            error_msg = "Error: MCP client not connected"
            logger.error(error_msg)
            return error_msg

        try:
            result = await self.client.call_tool(tool_name, arguments)

            if result.content and len(result.content) > 0:
                content_parts = [
                    self._extract_text_from_content_block(content_block)
                    for content_block in result.content
                ]
                return "\n".join(part for part in content_parts if part)

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

