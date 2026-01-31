"""Targeted tests for LLM Client - Focusing on uncovered methods

This module tests methods not covered by existing tests to increase coverage.
"""

import sys
from pathlib import Path
from unittest.mock import Mock, patch, AsyncMock
import pytest
import json

# Add paths for imports
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


class TestLLMClientToolsManagement:
    """Test tool management methods"""
    
    def test_set_tool_executor(self):
        """Test set_tool_executor method"""
        from llm.client import LLMClient
        
        with patch('llm.client.Config.OPENAI_API_KEY', "test_key"):
            with patch('llm.client.Config.OPENAI_API_BASE', "https://api.openai.com/v1"):
                with patch('llm.client.Config.CHAT_MODEL', "gpt-4o"):
                    with patch('llm.client.Config.TOOL_MODEL', "gpt-4o"):
                        client = LLMClient()
                        
                        # Create a mock executor
                        mock_executor = Mock()
                        
                        # Set the executor
                        client.set_tool_executor(mock_executor)
                        
                        # Verify executor was set
                        assert client._tool_executor is mock_executor
    
    def test_set_tools(self):
        """Test set_tools method"""
        from llm.client import LLMClient
        
        with patch('llm.client.Config.OPENAI_API_KEY', "test_key"):
            with patch('llm.client.Config.OPENAI_API_BASE', "https://api.openai.com/v1"):
                with patch('llm.client.Config.CHAT_MODEL', "gpt-4o"):
                    with patch('llm.client.Config.TOOL_MODEL', "gpt-4o"):
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
        from llm.client import LLMClient
        
        with patch('llm.client.Config.OPENAI_API_KEY', "test_key"):
            with patch('llm.client.Config.OPENAI_API_BASE', "https://api.openai.com/v1"):
                with patch('llm.client.Config.CHAT_MODEL', "gpt-4o"):
                    with patch('llm.client.Config.TOOL_MODEL', "gpt-4o"):
                        client = LLMClient()
                        
                        # Get tools when not set
                        tools = client._get_tools()
                        
                        # Should return None
                        assert tools is None
    
    def test_get_tools_returns_tools_when_set(self):
        """Test _get_tools returns tools when set"""
        from llm.client import LLMClient
        
        with patch('llm.client.Config.OPENAI_API_KEY', "test_key"):
            with patch('llm.client.Config.OPENAI_API_BASE', "https://api.openai.com/v1"):
                with patch('llm.client.Config.CHAT_MODEL', "gpt-4o"):
                    with patch('llm.client.Config.TOOL_MODEL', "gpt-4o"):
                        client = LLMClient()
                        
                        # Set tools
                        mock_tools = [{"name": "test_tool"}]
                        client._tools_cache = mock_tools
                        
                        # Get tools
                        tools = client._get_tools()
                        
                        # Should return the tools
                        assert tools == mock_tools


class TestLLMClientBuildMessages:
    """Test message building methods"""
    
    @pytest.mark.skip(reason="Requires complex message structure mocking")
    def test_build_chat_messages_basic(self):
        """Test _build_chat_messages with basic input"""
        pass
    
    @pytest.mark.skip(reason="Requires complex message structure mocking")
    def test_build_chat_messages_with_retrieved(self):
        """Test _build_chat_messages with retrieved memories"""
        pass


class TestLLMClientClose:
    """Test close methods"""
    
    @pytest.mark.asyncio
    async def test_close_async(self):
        """Test close_async method"""
        from llm.client import LLMClient
        
        with patch('llm.client.Config.OPENAI_API_KEY', "test_key"):
            with patch('llm.client.Config.OPENAI_API_BASE', "https://api.openai.com/v1"):
                with patch('llm.client.Config.CHAT_MODEL', "gpt-4o"):
                    with patch('llm.client.Config.TOOL_MODEL', "gpt-4o"):
                        client = LLMClient()
                        
                        # Mock the async close
                        client._async_close = AsyncMock()
                        
                        # Close async
                        await client.close_async()
                        
                        # Verify close was called
                        client._async_close.assert_called_once()
    
    def test_close_sync(self):
        """Test close method (sync)"""
        from llm.client import LLMClient
        
        with patch('llm.client.Config.OPENAI_API_KEY', "test_key"):
            with patch('llm.client.Config.OPENAI_API_BASE', "https://api.openai.com/v1"):
                with patch('llm.client.Config.CHAT_MODEL', "gpt-4o"):
                    with patch('llm.client.Config.TOOL_MODEL', "gpt-4o"):
                        client = LLMClient()
                        
                        # Close sync
                        client.close()
                        
                        # Should complete without error
                        assert True


class TestLLMClientGenerationMethods:
    """Test generation methods (generate_summary, generate_memory_update)"""
    
    @pytest.mark.skip(reason="Requires async OpenAI mocking")
    def test_generate_summary(self):
        """Test generate_summary method"""
        from llm.client import LLMClient
        
        # This would test the generate_summary method
        # Requires mocking the async OpenAI client
        pass
    
    @pytest.mark.skip(reason="Requires async OpenAI mocking")
    def test_generate_memory_update(self):
        """Test generate_memory_update method"""
        from llm.client import LLMClient
        
        # This would test the generate_memory_update method
        # Requires mocking the async OpenAI client
        pass


# Run tests if executed directly
if __name__ == "__main__":
    pytest.main([__file__, "-v"])
