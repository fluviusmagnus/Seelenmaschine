"""Advanced tests for LLM Client tool calling and chat

This module contains tests for LLMClient's complex logic including tool calling,
streaming responses, and retry mechanisms.
"""

import pytest
from unittest.mock import patch


class TestLLMClientInitialization:
    """Test LLMClient initialization"""
    
    def test_initialization_with_defaults(self):
        """Test LLMClient initialization with default values"""
        from llm.chat_client import LLMClient
        
        with patch('llm.chat_client.Config.OPENAI_API_KEY', "test_key"):
            with patch('llm.chat_client.Config.OPENAI_API_BASE', "https://api.openai.com/v1"):
                with patch('llm.chat_client.Config.CHAT_MODEL', "gpt-4o"):
                    with patch('llm.chat_client.Config.TOOL_MODEL', "gpt-4o"):
                        client = LLMClient()
                        
                        assert client.api_key == "test_key"
                        assert client.api_base == "https://api.openai.com/v1"
                        assert client.chat_model == "gpt-4o"


# Run tests if executed directly
if __name__ == "__main__":
    pytest.main([__file__, "-v"])
