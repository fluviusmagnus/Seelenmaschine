"""Targeted tests for LLM Client - Focusing on uncovered methods

This module tests methods not covered by existing tests to increase coverage.
"""

from unittest.mock import AsyncMock, Mock, patch
import pytest


class TestLLMClientToolsManagement:
    """Test tool management methods"""
    
    def test_set_tool_executor(self):
        """Test set_tool_executor method"""
        from llm.chat_client import LLMClient
        
        with patch('llm.chat_client.Config.OPENAI_API_KEY', "test_key"):
            with patch('llm.chat_client.Config.OPENAI_API_BASE', "https://api.openai.com/v1"):
                with patch('llm.chat_client.Config.CHAT_MODEL', "gpt-4o"):
                    with patch('llm.chat_client.Config.TOOL_MODEL', "gpt-4o"):
                        client = LLMClient()
                        
                        # Create a mock executor
                        mock_executor = Mock()
                        
                        # Set the executor
                        client.set_tool_executor(mock_executor)
                        
                        # Verify executor was set
                        assert client._tool_executor is mock_executor
    
    def test_set_tools(self):
        """Test set_tools method"""
        from llm.chat_client import LLMClient
        
        with patch('llm.chat_client.Config.OPENAI_API_KEY', "test_key"):
            with patch('llm.chat_client.Config.OPENAI_API_BASE', "https://api.openai.com/v1"):
                with patch('llm.chat_client.Config.CHAT_MODEL', "gpt-4o"):
                    with patch('llm.chat_client.Config.TOOL_MODEL', "gpt-4o"):
                        client = LLMClient()
                        
                        # Create mock tools
                        mock_tools = [
                            {
                                "type": "function",
                                "function": {
                                    "name": "test_tool",
                                    "description": "A test tool",
                                    "parameters": {"type": "object", "properties": {}}
                                }
                            }
                        ]
                        
                        # Set tools
                        client.set_tools(mock_tools)
                        
                        # Verify tools were set
                        assert client._tools_cache == mock_tools
    
    def test_get_tools_returns_none_when_not_set(self):
        """Test _get_tools returns None when no tools set"""
        from llm.chat_client import LLMClient
        
        with patch('llm.chat_client.Config.OPENAI_API_KEY', "test_key"):
            with patch('llm.chat_client.Config.OPENAI_API_BASE', "https://api.openai.com/v1"):
                with patch('llm.chat_client.Config.CHAT_MODEL', "gpt-4o"):
                    with patch('llm.chat_client.Config.TOOL_MODEL', "gpt-4o"):
                        client = LLMClient()
                        
                        # Get tools when not set
                        tools = client._get_tools()
                        
                        # Should return None
                        assert tools is None
    
    def test_get_tools_returns_tools_when_set(self):
        """Test _get_tools returns tools when set"""
        from llm.chat_client import LLMClient
        
        with patch('llm.chat_client.Config.OPENAI_API_KEY', "test_key"):
            with patch('llm.chat_client.Config.OPENAI_API_BASE', "https://api.openai.com/v1"):
                with patch('llm.chat_client.Config.CHAT_MODEL', "gpt-4o"):
                    with patch('llm.chat_client.Config.TOOL_MODEL', "gpt-4o"):
                        client = LLMClient()
                        
                        # Set tools
                        mock_tools = [{"name": "test_tool"}]
                        client._tools_cache = mock_tools
                        
                        # Get tools
                        tools = client._get_tools()
                        
                        # Should return the tools
                        assert tools == mock_tools


class TestLLMClientClose:
    """Test close methods"""
    
    @pytest.mark.asyncio
    async def test_close_async(self):
        """Test close_async method"""
        from llm.chat_client import LLMClient
        
        with patch('llm.chat_client.Config.OPENAI_API_KEY', "test_key"):
            with patch('llm.chat_client.Config.OPENAI_API_BASE', "https://api.openai.com/v1"):
                with patch('llm.chat_client.Config.CHAT_MODEL', "gpt-4o"):
                    with patch('llm.chat_client.Config.TOOL_MODEL', "gpt-4o"):
                        client = LLMClient()
                        
                        # Mock the async close
                        client._async_close = AsyncMock()
                        
                        # Close async
                        await client.close_async()
                        
                        # Verify close was called
                        client._async_close.assert_called_once()
    
# Run tests if executed directly
if __name__ == "__main__":
    pytest.main([__file__, "-v"])
