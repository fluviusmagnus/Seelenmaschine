"""Tests for the prompts package entrypoints

This module tests the system prompt building functionality,
including seele.json loading, time formatting, and prompt construction.
"""

from pathlib import Path
from unittest.mock import Mock, patch, mock_open
import json
from zoneinfo import ZoneInfo
import pytest


class TestLoadSeeleJson:
    """Test seele.json loading functionality"""
    
    def test_load_seele_json_from_disk(self):
        """Test loading seele.json from disk"""
        from prompts.runtime import _load_seele_json_from_disk
        
        mock_data = {"user": {"name": "Test", "location": ""}, "bot": {"name": "Assistant"}}
        
        with patch('pathlib.Path.exists', return_value=True):
            with patch('builtins.open', mock_open(read_data=json.dumps(mock_data))):
                with patch('prompts.runtime.Config') as mock_config:
                    mock_config_instance = Mock()
                    mock_config_instance.SEELE_JSON_PATH = Path('/tmp/test_seele.json')
                    mock_config.return_value = mock_config_instance
                    
                    result = _load_seele_json_from_disk()
                    
                assert result["bot"]["name"] == mock_data["bot"]["name"]
                assert result["user"]["name"] == mock_data["user"]["name"]
                assert result["user"]["location"] == mock_data["user"]["location"]
                assert "emotions" in result["bot"]
                assert "personal_facts" in result["user"]
                assert result["memorable_events"] == {}
    
    def test_load_seele_json_uses_cache(self):
        """Test that load_seele_json uses cache after first load"""
        from prompts.runtime import load_seele_json
        
        # Clear cache first
        import prompts.runtime as prompts
        prompts._seele_json_cache = {}
        
        mock_data = {"user": {"name": "Test", "location": ""}}
        
        # First call should load from disk
        with patch('prompts.runtime._load_seele_json_from_disk', return_value=mock_data):
            result1 = load_seele_json()
            assert result1 == mock_data
        
        # Second call should use cache
        with patch('prompts.runtime._load_seele_json_from_disk', return_value={}):
            result2 = load_seele_json()
            assert result2 == mock_data  # Should still be the cached value


class TestGetCurrentTimeStr:
    """Test time formatting functionality"""
    
    def test_get_current_time_str_with_valid_timezone(self):
        """Test getting current time with valid timezone"""
        from prompts.runtime import get_current_time_str
        
        with patch('prompts.runtime.Config') as mock_config:
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
        from prompts.runtime import get_current_time_str
        
        with patch('prompts.runtime.Config') as mock_config:
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
        from prompts.runtime import get_cacheable_system_prompt
        
        mock_seele_data = {
            "bot": {
                "name": "TestBot", 
                "personality": {
                    "mbti": "INTJ",
                    "traits": ["analytical", "logical"]
                },
                "emotions": {"long_term": "", "short_term": ["focused", "curious"]},
                "needs": {"long_term": "", "short_term": ["clear constraints"]},
            },
            "user": {
                "name": "TestUser",
                "location": "Tokyo",
                "emotions": {"long_term": "", "short_term": ["tired"]},
                "needs": {"long_term": "", "short_term": ["rest"]},
            },
            "memorable_events": {
                "evt_20260329_project_commitment": {
                    "date": "2026-03-29",
                    "importance": 4,
                    "details": "A major relationship milestone",
                }
            },
        }
        
        with patch('prompts.runtime.load_seele_json', return_value=mock_seele_data):
            with patch('prompts.runtime.get_current_time_str', return_value="2025-01-31 12:00:00 UTC"):
                result = get_cacheable_system_prompt(recent_summaries=["Summary 1", "Summary 2"])
                
                assert isinstance(result, str)
                assert len(result) > 0
                # Should contain bot name
                assert "TestBot" in result
                # Should contain user name
                assert "TestUser" in result
                assert "Location: Tokyo" in result
                # Should contain summaries
                assert "Summary 1" in result
                assert "Summary 2" in result
                assert "Use related memories only when helpful" in result
                assert "Keep user-facing replies clean and lightweight" in result
                assert "Lightweight Markdown is allowed" in result
                assert "If the most recent tool call result appears truncated" in result
                assert "never wrap your final reply in tags such as" in result
                assert "evt_20260329_project_commitment" in result
                assert "importance=4" in result
                assert "<system_instruction>" in result
                assert "<self_awareness>" in result
                assert "<recent_summaries_for_current_conversation>" in result
                assert "- focused" in result
                assert "- curious" in result
                assert "- clear constraints" in result
                assert "- tired" in result
                assert "- rest" in result

class TestJsonPatchDiff:
    """Test complete-object JSON Patch diff utilities."""

    def test_build_json_patch_diff_with_nested_dict(self):
        """Test diffing nested dict values."""
        from memory.seele import build_json_patch_diff

        old = {"user": {"name": "Jane", "age": 29}, "bot": {"name": "Assistant"}}
        new = {"user": {"name": "John", "age": 30}, "bot": {"name": "Assistant"}}

        operations = build_json_patch_diff(old, new)

        assert operations == [
            {"op": "replace", "path": "/user/name", "value": "John"},
            {"op": "replace", "path": "/user/age", "value": 30},
        ]

    def test_build_json_patch_diff_replaces_lists(self):
        """Complete-object diffs should replace arrays as arrays."""
        from memory.seele import build_json_patch_diff

        operations = build_json_patch_diff(
            {"tags": ["tag1"]},
            {"tags": ["tag1", "tag2", "tag3"]},
        )

        assert operations == [
            {"op": "replace", "path": "/tags", "value": ["tag1", "tag2", "tag3"]}
        ]


# Run tests if executed directly
if __name__ == "__main__":
    pytest.main([__file__, "-v"])
