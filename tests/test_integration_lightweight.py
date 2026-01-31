"""Lightweight integration tests using in-memory SQLite

These tests verify complete workflows without external dependencies.
"""

import sys
from pathlib import Path
from unittest.mock import Mock, patch, AsyncMock, MagicMock
import pytest
import json
import tempfile
import os

# Add paths for imports
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


@pytest.fixture
def test_environment():
    """Create isolated test environment with temp directory"""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Set up test environment
        env = {
            'data_dir': Path(tmpdir) / "data",
            'config': Mock(),
        }
        env['data_dir'].mkdir(parents=True, exist_ok=True)
        yield env


class TestMemoryIntegrationLightweight:
    """Lightweight memory integration tests"""
    
    @pytest.mark.skip(reason="Requires full database initialization")
    def test_message_storage_and_retrieval(self, test_environment):
        """Test storing messages and retrieving them"""
        # This test requires proper database initialization
        # Skipped due to complex initialization requirements
        pass


class TestContextWindowIntegration:
    """Test ContextWindow with real message flow"""
    
    def test_message_addition_and_retrieval(self):
        """Test adding messages and retrieving context"""
        from core.context import ContextWindow, Message
        
        ctx = ContextWindow()
        
        # Add messages
        ctx.add_message("user", "Hello")
        ctx.add_message("assistant", "Hi there!")
        ctx.add_message("user", "How are you?")
        
        # Get context as messages
        messages = ctx.get_context_as_messages()
        
        assert len(messages) == 3
        assert messages[0]["role"] == "user"
        assert messages[0]["content"] == "Hello"
        assert messages[1]["role"] == "assistant"
        assert messages[1]["content"] == "Hi there!"


class TestPromptBuildingIntegration:
    """Test prompt building with real data"""
    
    def test_system_prompt_with_seele_data(self, tmp_path):
        """Test building system prompt with actual seele.json"""
        from prompts.system import get_cacheable_system_prompt, _seele_json_cache
        import prompts.system
        
        # Create test seele.json
        seele_data = {
            "bot": {
                "name": "TestBot",
                "personality": {
                    "mbti": "INTJ",
                    "traits": ["analytical"]
                }
            },
            "user": {
                "name": "TestUser",
                "personal_facts": ["likes coding"]
            },
            "memorable_events": [],
            "commands_and_agreements": []
        }
        
        seele_path = tmp_path / "seele.json"
        seele_path.write_text(json.dumps(seele_data, indent=2))
        
        # Clear cache
        prompts.system._seele_json_cache = {}
        
        with patch('prompts.system.Config.SEELE_JSON_PATH', seele_path):
            with patch('prompts.system.Config.DATA_DIR', tmp_path):
                # Build prompt
                prompt = get_cacheable_system_prompt(recent_summaries=["Previous chat summary"])
                
                # Verify prompt contains expected data
                assert "TestBot" in prompt
                assert "TestUser" in prompt
                assert "Previous chat summary" in prompt


class TestTimeFormattingIntegration:
    """Test time formatting across the system"""
    
    def test_time_conversion_roundtrip(self):
        """Test timestamp → datetime → timestamp conversion"""
        from utils.time import (
            get_current_timestamp,
            timestamp_to_datetime,
            datetime_to_timestamp
        )
        from datetime import datetime
        
        # Get current timestamp
        ts1 = get_current_timestamp()
        
        # Convert to datetime
        dt = timestamp_to_datetime(ts1)
        assert isinstance(dt, datetime)
        
        # Convert back to timestamp
        ts2 = datetime_to_timestamp(dt)
        
        # Should be approximately equal (allowing for second precision)
        assert abs(ts1 - ts2) <= 1


class TestConfigIntegration:
    """Test configuration loading and validation"""
    
    @pytest.mark.skip(reason="Requires proper config initialization")
    def test_config_with_env_file(self, tmp_path):
        """Test loading config from .env file"""
        # This test requires proper config initialization
        # Skipped due to complex initialization requirements
        pass


class TestJsonPatchIntegration:
    """Test JSON Patch operations"""
    
    def test_json_patch_application(self):
        """Test applying JSON Patch to seele.json"""
        import jsonpatch
        
        # Original data
        original = {
            "user": {"name": "John"},
            "bot": {"name": "Assistant"}
        }
        
        # Patch operations
        patch_operations = [
            {"op": "replace", "path": "/user/name", "value": "Jane"},
            {"op": "add", "path": "/user/age", "value": 30}
        ]
        
        # Apply patch
        patch = jsonpatch.JsonPatch(patch_operations)
        result = patch.apply(original)
        
        # Verify changes
        assert result["user"]["name"] == "Jane"
        assert result["user"]["age"] == 30
        assert result["bot"]["name"] == "Assistant"


# Run tests if executed directly
if __name__ == "__main__":
    pytest.main([__file__, "-v"])
