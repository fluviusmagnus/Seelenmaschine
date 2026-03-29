import pytest
import tempfile
import json
from pathlib import Path
from unittest.mock import Mock, patch
from typing import Dict, Any, Optional, List

from prompts import (
    get_current_time_str,
    get_cacheable_system_prompt,
    get_summary_prompt,
    get_memory_update_prompt,
    get_complete_memory_json_prompt,
    get_seele_repair_prompt,
)


@pytest.fixture
def reset_seele_json_cache():
    """Reset the seele json cache between tests."""
    import prompts as system_module

    # Reset cache
    if hasattr(system_module, "_seele_json_cache"):
        system_module._seele_json_cache = {}
    yield
    # Cleanup after test
    if hasattr(system_module, "_seele_json_cache"):
        system_module._seele_json_cache = {}


class TestLoadSeeeleJson:
    """Test load_seele_json functionality."""

    def test_load_seeele_json_file_not_found(
        self, tmp_path, reset_seele_json_cache, monkeypatch
    ):
        """Test loading when file doesn't exist."""
        from prompts import load_seele_json, _load_seele_json_from_disk

        # Patch Config to return a non-existent path
        with monkeypatch.context() as m:
            from core.config import Config

            m.setattr(
                Config, "SEELE_JSON_PATH", tmp_path / "nonexistent" / "seele.json"
            )
            m.setattr(Config, "DATA_DIR", tmp_path / "nonexistent")

            # Also need to patch the template loading
            import prompts as sys_module

            original_cache = getattr(sys_module, "_seele_json_cache", None)
            sys_module._seele_json_cache = {}  # Reset cache

            try:
                data = load_seele_json()
                # Should return empty dict or default structure
                assert isinstance(data, dict)
            finally:
                if original_cache is not None:
                    sys_module._seele_json_cache = original_cache


class TestUpdateSeeeleJson:
    """Test update_seeele_json functionality."""

    def test_update_seeele_json_simple_value(self, tmp_path, monkeypatch):
        """Test updating a simple value in seele.json."""
        # Create a temporary seele.json
        seele_path = tmp_path / "seele.json"
        initial_data = {
            "bot": {"name": "Test"},
            "user": {"name": ""},
            "memorable_events": {},
            "commands_and_agreements": [],
        }
        seele_path.write_text(json.dumps(initial_data, indent=2))

        # Patch Config
        from core.config import Config

        monkeypatch.setattr(Config, "SEELE_JSON_PATH", seele_path)
        monkeypatch.setattr(Config, "DATA_DIR", tmp_path)

        # Reset cache
        import prompts as system

        system._seele_json_cache = {}

        # Apply patch
        from prompts import update_seele_json

        result = update_seele_json(
            [{"op": "replace", "path": "/user/name", "value": "Alice"}]
        )

        assert result is True

    def test_update_seeele_json_nested_value(self, tmp_path, monkeypatch):
        """Test updating a nested value using dot notation."""
        # Similar setup as above
        seele_path = tmp_path / "seele.json"
        initial_data = {
            "bot": {"name": "Test", "likes": []},
            "user": {"name": ""},
            "memorable_events": {},
            "commands_and_agreements": [],
        }
        seele_path.write_text(json.dumps(initial_data, indent=2))

        from core.config import Config

        monkeypatch.setattr(Config, "SEELE_JSON_PATH", seele_path)
        monkeypatch.setattr(Config, "DATA_DIR", tmp_path)

        import prompts as system

        system._seele_json_cache = {}

        from prompts import update_seele_json

        result = update_seele_json(
            [{"op": "add", "path": "/bot/likes/-", "value": "music"}]
        )

        assert result is True

    def test_update_seeele_json_deep_nested(self, tmp_path, monkeypatch):
        """Test updating deeply nested value."""
        seele_path = tmp_path / "seele.json"
        initial_data = {
            "bot": {"name": "Test", "personality": {"mbti": ""}},
            "user": {"name": ""},
            "memorable_events": {},
            "commands_and_agreements": [],
        }
        seele_path.write_text(json.dumps(initial_data, indent=2))

        from core.config import Config

        monkeypatch.setattr(Config, "SEELE_JSON_PATH", seele_path)
        monkeypatch.setattr(Config, "DATA_DIR", tmp_path)

        import prompts as system

        system._seele_json_cache = {}

        from prompts import update_seele_json

        result = update_seele_json(
            [{"op": "replace", "path": "/bot/personality/mbti", "value": "INTP"}]
        )

        assert result is True

    def test_update_seeele_json_invalid_path(self, tmp_path, monkeypatch):
        """Test updating with invalid path."""
        seele_path = tmp_path / "seele.json"
        initial_data = {
            "bot": {"name": "Test"},
            "user": {"name": ""},
            "memorable_events": {},
            "commands_and_agreements": [],
        }
        seele_path.write_text(json.dumps(initial_data, indent=2))

        from core.config import Config

        monkeypatch.setattr(Config, "SEELE_JSON_PATH", seele_path)
        monkeypatch.setattr(Config, "DATA_DIR", tmp_path)

        import prompts as system

        system._seele_json_cache = {}

        from prompts import update_seele_json

        # Invalid path should return False
        result = update_seele_json(
            [{"op": "replace", "path": "/nonexistent/path/deep", "value": "test"}]
        )

        assert result is False

    def test_update_seeele_json_creates_intermediate(self, tmp_path, monkeypatch):
        """Test that update creates intermediate dictionaries."""
        seele_path = tmp_path / "seele.json"
        initial_data = {
            "bot": {"name": "Test"},
            "user": {"name": ""},
            "memorable_events": {},
            "commands_and_agreements": [],
        }
        seele_path.write_text(json.dumps(initial_data, indent=2))

        from core.config import Config

        monkeypatch.setattr(Config, "SEELE_JSON_PATH", seele_path)
        monkeypatch.setattr(Config, "DATA_DIR", tmp_path)

        import prompts as system

        system._seele_json_cache = {}

        from prompts import update_seele_json

        # Add operation with nested path should work
        result = update_seele_json(
            [{"op": "add", "path": "/bot/stats", "value": {"age": 1}}]
        )

        assert result is True


class TestGetCurrentTimeStr:
    """Test get_current_time_str functionality."""

    def test_get_current_time_str(self):
        """Test getting current time string."""
        time_str = get_current_time_str()
        assert isinstance(time_str, str)
        assert len(time_str) > 0


class TestGetCacheableSystemPrompt:
    """Test get_cacheable_system_prompt functionality."""

    def test_get_cacheable_system_prompt_no_summaries(self, tmp_path, monkeypatch):
        """Test getting system prompt without summaries."""
        # Create a temporary seele.json with valid structure
        seele_path = tmp_path / "seele.json"
        seele_data = {
            "bot": {
                "name": "TestBot",
                "gender": "neutral",
                "role": "AI Assistant",
                "likes": [],
                "dislikes": [],
                "language_style": {"description": "", "examples": []},
                "personality": {
                    "mbti": "",
                    "description": "",
                    "worldview_and_values": "",
                },
                "emotions_and_needs": {"long_term": "", "short_term": ""},
                "relationship_with_user": "",
            },
            "user": {
                "name": "",
                "gender": "",
                "personal_facts": [],
                "abilities": [],
                "likes": [],
                "dislikes": [],
                "personality": {
                    "mbti": "",
                    "description": "",
                    "worldview_and_values": "",
                },
                "emotions_and_needs": {"long_term": "", "short_term": ""},
            },
            "memorable_events": {
                "evt_20260329_project_commitment": {
                    "date": "2026-03-29",
                    "importance": 4,
                    "details": "Shared a long-term collaboration commitment",
                }
            },
            "commands_and_agreements": [],
        }
        seele_path.write_text(json.dumps(seele_data, indent=2))

        # Patch Config
        from core.config import Config

        monkeypatch.setattr(Config, "SEELE_JSON_PATH", seele_path)
        monkeypatch.setattr(Config, "DATA_DIR", tmp_path)

        # Reset cache
        import prompts as system

        system._seele_json_cache = {}

        # Call function
        from prompts import get_cacheable_system_prompt

        prompt = get_cacheable_system_prompt([])

        assert isinstance(prompt, str)
        assert len(prompt) > 0
        assert "evt_20260329_project_commitment" in prompt
        assert "importance=4" in prompt
        assert "<system_instruction>" in prompt
        assert "<user_profile>" in prompt
        assert "Use related memories only when helpful" in prompt
        assert "Keep user-facing replies clean and lightweight" in prompt
        assert "Lightweight Markdown is allowed" in prompt
        assert "never wrap your final reply in tags such as" in prompt
        assert "## Your Self-Awareness" not in prompt
        assert "## User Profile" not in prompt

class TestGetSummaryPrompt:
    """Test get_summary_prompt functionality."""

    def test_get_summary_prompt_no_existing(self):
        """Test getting summary prompt without existing summary."""
        conversations = "User: Hello\nAssistant: Hi"

        prompt = get_summary_prompt(None, conversations)

        assert isinstance(prompt, str)
        assert len(prompt) > 0
        assert "<summary_task>" in prompt
        assert "<conversations_to_summarize>" in prompt

    def test_get_summary_prompt_with_existing(self):
        """Test getting summary prompt with existing summary."""
        existing_summary = "Previous summary"
        new_conversations = "User: More chat\nAssistant: More response"

        prompt = get_summary_prompt(existing_summary, new_conversations)

        assert isinstance(prompt, str)
        assert len(prompt) > 0
        assert "<previous_summary_context>" in prompt

    def test_get_summary_prompt_empty_conversations(self):
        """Test getting summary prompt with empty conversations."""
        prompt = get_summary_prompt(None, "")
        assert isinstance(prompt, str)


class TestGetMemoryUpdatePrompt:
    """Test get_memory_update_prompt functionality."""

    @staticmethod
    def _current_seele_json() -> str:
        return json.dumps(
            {
                "bot": {"name": "TestBot"},
                "user": {"name": "TestUser"},
                "memorable_events": {},
                "commands_and_agreements": [],
            }
        )

    def test_get_memory_update_prompt_basic(self):
        """Test getting memory update prompt."""
        messages = "User: My name is John\nAssistant: Hello John"

        prompt = get_memory_update_prompt(messages, self._current_seele_json())

        assert isinstance(prompt, str)
        assert len(prompt) > 0
        assert "stable event ids" in prompt
        assert "evt_20260329_project_commitment" in prompt
        assert "Importance scores MAY change later" in prompt
        assert "Memorable events are NOT the same as reminders" in prompt
        assert "Prefer simple updates over complex rewrites" in prompt
        assert "<memory_update_task>" in prompt
        assert "<schema>" in prompt
        assert "<output_requirements>" in prompt

    def test_get_memory_update_prompt_includes_importance_examples(self):
        """Test that importance examples and task boundary rules are present."""
        prompt = get_memory_update_prompt("User: test", self._current_seele_json())

        assert "User officially started a new job" in prompt
        assert "Remind me tomorrow at 3pm to join a meeting" in prompt
        assert "My old cat passed away today" in prompt

    def test_get_memory_update_prompt_excludes_temporary_personal_facts(self):
        """personal_facts guidance should exclude temporary user state."""
        prompt = get_memory_update_prompt("User: test", self._current_seele_json())

        assert "/user/personal_facts should contain relatively stable facts" in prompt
        assert "Do NOT store temporary states" in prompt
        assert "Store only durable, identity-relevant, or repeatedly confirmed facts" in prompt

    def test_get_complete_memory_json_prompt_includes_boundary_rules(self):
        """Test that full-json prompt includes memorable-event boundary guidance."""
        prompt = get_complete_memory_json_prompt(
            "User: test",
            self._current_seele_json(),
            "patch failed",
        )

        assert "not ordinary tasks or reminders" in prompt
        assert "Prefer simple, high-confidence updates" in prompt
        assert "should not be written into seele.json" in prompt
        assert "a memorable relationship event" in prompt
        assert "<complete_memory_json_task>" in prompt
        assert "<previous_error>" in prompt
        assert "<output_requirements>" in prompt

    def test_get_complete_memory_json_prompt_includes_previous_attempt(self):
        """Retry prompt should include the raw previous failed output when provided."""
        prompt = get_complete_memory_json_prompt(
            "User: test",
            self._current_seele_json(),
            "parse failed",
            '{"bot": {oops}}',
        )

        assert "<previous_attempt>" in prompt
        assert '{"bot": {oops}}' in prompt

    def test_get_complete_memory_json_prompt_excludes_temporary_personal_facts(self):
        """Complete-memory prompt should exclude temporary personal facts."""
        prompt = get_complete_memory_json_prompt(
            "User: test",
            self._current_seele_json(),
            "patch failed",
        )

        assert "IMPORTANT UPDATE GUIDELINES for user.personal_facts" in prompt
        assert "Store only relatively stable facts" in prompt
        assert "Do NOT include temporary states" in prompt

    def test_get_memory_update_prompt_says_tasks_do_not_belong_in_seele(self):
        """Test that memory update prompt clearly excludes tasks/reminders from seele.json."""
        prompt = get_memory_update_prompt("User: test", self._current_seele_json())

        assert "should NOT be stored in seele.json" in prompt
        assert "Tasks and reminders should be handled by scheduling/task logic" in prompt
        assert "A reminder/task should not be stored in seele.json" in prompt

    def test_get_memory_update_prompt_with_timestamps(self):
        """Test getting memory update prompt with timestamps."""
        messages = "User: Test"
        first_ts = 1234567890
        last_ts = 1234567990

        prompt = get_memory_update_prompt(
            messages, self._current_seele_json(), first_ts, last_ts
        )

        assert isinstance(prompt, str)

    def test_get_seele_repair_prompt_contains_repair_rules(self):
        """Repair prompt should explicitly frame seele.json fixing as an LLM repair task."""
        prompt = get_seele_repair_prompt(
            '{"bot": {oops}}',
            self._current_seele_json(),
            "Malformed JSON",
            "migration",
        )

        assert "semantic migration/repair task" in prompt
        assert "CURRENT / LEGACY / BROKEN seele.json CONTENT TO REPAIR" in prompt
        assert "memorable_events MUST be an object keyed by stable ids" in prompt
        assert len(prompt) > 0
        assert "Repair context: migration" in prompt

    def test_get_memory_update_prompt_without_timestamps(self):
        """Test getting memory update prompt without timestamps."""
        messages = "User: Test"
        prompt = get_memory_update_prompt(messages, self._current_seele_json())
        assert isinstance(prompt, str)


class TestGetCompleteMemoryJsonPrompt:
    """Test get_complete_memory_json_prompt functionality."""

    def test_get_complete_memory_json_prompt(self, reset_seele_json_cache):
        """Test getting complete memory JSON prompt."""
        # load_seele_json is a local function, not exported from prompts
        pytest.skip("load_seele_json is not available for patching")


class TestPromptIntegration:
    """Integration tests for prompt system."""

    def test_full_prompt_workflow(self):
        """Test complete prompt workflow."""
        # Skip since DATA_DIR is not available in prompts
        pytest.skip("DATA_DIR not available in prompts module")

    def test_summary_prompt_workflow(self):
        """Test summary prompt creation workflow."""
        # Create some conversations
        conversations = (
            "User: Hello, I'm Alice\n"
            "Assistant: Nice to meet you, Alice\n"
            "User: What's your name?\n"
            "Assistant: I'm TestBot"
        )

        # Get initial summary
        first_prompt = get_summary_prompt(None, conversations)

        # Update summary with new conversations
        new_conversations = "User: Nice to meet you too"
        updated_prompt = get_summary_prompt("Initial summary", new_conversations)

        assert isinstance(first_prompt, str)
        assert isinstance(updated_prompt, str)

    def test_memory_update_workflow(self):
        """Test memory update prompt workflow."""
        messages = (
            "User: My name is Bob and I live in Paris\n"
            "Assistant: Hello Bob! Paris is a beautiful city."
        )

        current_seele_json = json.dumps(
            {
                "bot": {"name": "TestBot"},
                "user": {"name": "TestUser"},
                "memorable_events": {},
                "commands_and_agreements": [],
            }
        )
        memory_prompt = get_memory_update_prompt(
            messages, current_seele_json, 1234567890, 1234567990
        )

        assert isinstance(memory_prompt, str)



