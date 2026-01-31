"""Tests for prompts/system.py

This module tests the system prompt building functionality,
including seele.json loading, time formatting, and prompt construction.
"""

import sys
from pathlib import Path
from unittest.mock import Mock, patch, mock_open
import json
from datetime import datetime
from zoneinfo import ZoneInfo
import pytest

# Add paths for imports
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


class TestLoadSeeleJson:
    """Test seele.json loading functionality"""
    
    def test_load_seele_json_from_disk(self):
        """Test loading seele.json from disk"""
        from prompts.system import _load_seele_json_from_disk
        
        mock_data = {"user": {"name": "Test"}, "bot": {"name": "Assistant"}}
        
        with patch('pathlib.Path.exists', return_value=True):
            with patch('builtins.open', mock_open(read_data=json.dumps(mock_data))):
                with patch('prompts.system.Config') as mock_config:
                    mock_config_instance = Mock()
                    mock_config_instance.SEELE_JSON_PATH = Path('/tmp/test_seele.json')
                    mock_config.return_value = mock_config_instance
                    
                    result = _load_seele_json_from_disk()
                    
                    assert result == mock_data
    
    def test_load_seele_json_uses_cache(self):
        """Test that load_seele_json uses cache after first load"""
        from prompts.system import load_seele_json, _seele_json_cache
        
        # Clear cache first
        import prompts.system
        prompts.system._seele_json_cache = {}
        
        mock_data = {"user": {"name": "Test"}}
        
        # First call should load from disk
        with patch('prompts.system._load_seele_json_from_disk', return_value=mock_data):
            result1 = load_seele_json()
            assert result1 == mock_data
        
        # Second call should use cache
        with patch('prompts.system._load_seele_json_from_disk', return_value={}):
            result2 = load_seele_json()
            assert result2 == mock_data  # Should still be the cached value


class TestGetCurrentTimeStr:
    """Test time formatting functionality"""
    
    def test_get_current_time_str_with_valid_timezone(self):
        """Test getting current time with valid timezone"""
        from prompts.system import get_current_time_str
        
        with patch('prompts.system.Config') as mock_config:
            mock_config_instance = Mock()
            mock_config_instance.TIMEZONE = ZoneInfo('UTC')
            mock_config.return_value = mock_config_instance
            
            result = get_current_time_str()
            
            # Should return formatted time string
            assert isinstance(result, str)
            assert len(result) > 0
            # Should contain year (2024, 2025, etc.)
            import datetime
            current_year = datetime.datetime.now().year
            assert str(current_year) in result
    
    def test_get_current_time_str_fallback_to_utc(self):
        """Test fallback to UTC when timezone is invalid"""
        from prompts.system import get_current_time_str
        
        with patch('prompts.system.Config') as mock_config:
            mock_config_instance = Mock()
            # Invalid timezone
            mock_config_instance.TIMEZONE = "Invalid/Timezone"
            mock_config.return_value = mock_config_instance
            
            result = get_current_time_str()
            
            # Should still return a formatted time string (fallback to UTC)
            assert isinstance(result, str)
            assert len(result) > 0


class TestBuildSystemPrompt:
    """Test system prompt building"""
    
    def test_get_cacheable_system_prompt_returns_string(self):
        """Test that get_cacheable_system_prompt returns a string"""
        from prompts.system import get_cacheable_system_prompt
        
        mock_seele_data = {
            "bot": {
                "name": "TestBot", 
                "personality": {
                    "mbti": "INTJ",
                    "traits": ["analytical", "logical"]
                }
            },
            "user": {"name": "TestUser"}
        }
        
        with patch('prompts.system.load_seele_json', return_value=mock_seele_data):
            with patch('prompts.system.get_current_time_str', return_value="2025-01-31 12:00:00 UTC"):
                result = get_cacheable_system_prompt(recent_summaries=["Summary 1", "Summary 2"])
                
                assert isinstance(result, str)
                assert len(result) > 0
                # Should contain bot name
                assert "TestBot" in result
                # Should contain user name
                assert "TestUser" in result
                # Should contain summaries
                assert "Summary 1" in result
                assert "Summary 2" in result


class TestJsonPatchConversion:
    """Test JSON Patch conversion utilities"""
    
    def test_dict_to_json_patch_with_nested_dict(self):
        """Test converting nested dict to JSON Patch operations"""
        from prompts.system import _dict_to_json_patch
        
        data = {
            "user": {
                "name": "John",
                "age": 30
            },
            "bot": {
                "name": "Assistant"
            }
        }
        
        operations = _dict_to_json_patch(data)
        
        # Should have 3 operations (name, age, bot.name)
        assert len(operations) >= 3
        # All operations should have 'op', 'path', and 'value'
        for op in operations:
            assert 'op' in op
            assert 'path' in op
            assert 'value' in op
    
    def test_dict_to_json_patch_with_lists(self):
        """Test converting dict with lists to JSON Patch operations"""
        from prompts.system import _dict_to_json_patch
        
        data = {
            "tags": ["tag1", "tag2", "tag3"]
        }
        
        operations = _dict_to_json_patch(data)
        
        # Should have 3 operations (one for each list item)
        assert len(operations) == 3
        # All should be 'add' operations to the list
        for op in operations:
            assert op['op'] == 'add'
            assert '/tags/-' in op['path']


# Run tests if executed directly
if __name__ == "__main__":
    pytest.main([__file__, "-v"])
