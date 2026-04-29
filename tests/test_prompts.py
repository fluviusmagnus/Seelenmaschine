import pytest
import json

from prompts.runtime import (
    get_current_time_str,
    get_cacheable_system_prompt,
    get_summary_prompt,
    get_memory_update_prompt,
    get_complete_memory_json_prompt,
    get_seele_compaction_prompt,
    get_seele_repair_prompt,
)


@pytest.fixture
def reset_seele_json_cache():
    """Reset the seele json cache between tests."""
    import prompts.runtime as system_module

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
        from prompts.runtime import load_seele_json

        # Patch Config to return a non-existent path
        with monkeypatch.context() as m:
            from core.config import Config

            m.setattr(
                Config, "SEELE_JSON_PATH", tmp_path / "nonexistent" / "seele.json"
            )
            m.setattr(Config, "DATA_DIR", tmp_path / "nonexistent")

            # Also need to patch the template loading
            import prompts.runtime as sys_module

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
            "user": {"name": "", "location": ""},
            "memorable_events": {},
            "commands_and_agreements": [],
        }
        seele_path.write_text(json.dumps(initial_data, indent=2))

        # Patch Config
        from core.config import Config

        monkeypatch.setattr(Config, "SEELE_JSON_PATH", seele_path)
        monkeypatch.setattr(Config, "DATA_DIR", tmp_path)

        # Reset cache
        import prompts.runtime as system

        system._seele_json_cache = {}

        # Apply patch
        from prompts.runtime import update_seele_json

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
            "user": {"name": "", "location": ""},
            "memorable_events": {},
            "commands_and_agreements": [],
        }
        seele_path.write_text(json.dumps(initial_data, indent=2))

        from core.config import Config

        monkeypatch.setattr(Config, "SEELE_JSON_PATH", seele_path)
        monkeypatch.setattr(Config, "DATA_DIR", tmp_path)

        import prompts.runtime as system

        system._seele_json_cache = {}

        from prompts.runtime import update_seele_json

        result = update_seele_json(
            [{"op": "add", "path": "/bot/likes/-", "value": "music"}]
        )

        assert result is True

    def test_update_seeele_json_deep_nested(self, tmp_path, monkeypatch):
        """Test updating deeply nested value."""
        seele_path = tmp_path / "seele.json"
        initial_data = {
            "bot": {"name": "Test", "personality": {"mbti": ""}},
            "user": {"name": "", "location": ""},
            "memorable_events": {},
            "commands_and_agreements": [],
        }
        seele_path.write_text(json.dumps(initial_data, indent=2))

        from core.config import Config

        monkeypatch.setattr(Config, "SEELE_JSON_PATH", seele_path)
        monkeypatch.setattr(Config, "DATA_DIR", tmp_path)

        import prompts.runtime as system

        system._seele_json_cache = {}

        from prompts.runtime import update_seele_json

        result = update_seele_json(
            [{"op": "replace", "path": "/bot/personality/mbti", "value": "INTP"}]
        )

        assert result is True

    def test_update_seeele_json_invalid_path(self, tmp_path, monkeypatch):
        """Test updating with invalid path."""
        seele_path = tmp_path / "seele.json"
        initial_data = {
            "bot": {"name": "Test"},
            "user": {"name": "", "location": ""},
            "memorable_events": {},
            "commands_and_agreements": [],
        }
        seele_path.write_text(json.dumps(initial_data, indent=2))

        from core.config import Config

        monkeypatch.setattr(Config, "SEELE_JSON_PATH", seele_path)
        monkeypatch.setattr(Config, "DATA_DIR", tmp_path)

        import prompts.runtime as system

        system._seele_json_cache = {}

        from prompts.runtime import update_seele_json

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
            "user": {"name": "", "location": ""},
            "memorable_events": {},
            "commands_and_agreements": [],
        }
        seele_path.write_text(json.dumps(initial_data, indent=2))

        from core.config import Config

        monkeypatch.setattr(Config, "SEELE_JSON_PATH", seele_path)
        monkeypatch.setattr(Config, "DATA_DIR", tmp_path)

        import prompts.runtime as system

        system._seele_json_cache = {}

        from prompts.runtime import update_seele_json

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

    @staticmethod
    def _build_seele_data(commands_and_agreements=None):
        return {
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
                "emotions": {"long_term": "", "short_term": []},
                "needs": {"long_term": "", "short_term": []},
                "relationship_with_user": "",
            },
            "user": {
                "name": "",
                "gender": "",
                "location": "Berlin",
                "personal_facts": [],
                "abilities": [],
                "likes": [],
                "dislikes": [],
                "personality": {
                    "mbti": "",
                    "description": "",
                    "worldview_and_values": "",
                },
                "emotions": {"long_term": "", "short_term": []},
                "needs": {"long_term": "", "short_term": []},
            },
            "memorable_events": {
                "evt_20260329_project_commitment": {
                    "date": "2026-03-29",
                    "importance": 4,
                    "details": "Shared a long-term collaboration commitment",
                }
            },
            "commands_and_agreements": commands_and_agreements or [],
        }

    def test_get_cacheable_system_prompt_no_summaries(self, tmp_path, monkeypatch):
        """Test getting system prompt without summaries."""
        # Create a temporary seele.json with valid structure
        seele_path = tmp_path / "seele.json"
        seele_data = self._build_seele_data()
        seele_path.write_text(json.dumps(seele_data, indent=2))

        # Patch Config
        from core.config import Config

        monkeypatch.setattr(Config, "SEELE_JSON_PATH", seele_path)
        monkeypatch.setattr(Config, "DATA_DIR", tmp_path)

        # Reset cache
        import prompts.runtime as system

        system._seele_json_cache = {}

        # Call function
        from prompts.runtime import get_cacheable_system_prompt

        prompt = get_cacheable_system_prompt([])

        assert isinstance(prompt, str)
        assert len(prompt) > 0
        assert "evt_20260329_project_commitment" in prompt
        assert "importance=4" in prompt
        assert "<system_instruction>" in prompt
        assert "<user_profile>" in prompt
        assert "Location: Berlin" in prompt
        assert "- Not specified" in prompt
        assert "Use related memories only when helpful" in prompt
        assert "Keep user-facing replies clean and lightweight" in prompt
        assert "Lightweight Markdown is allowed" in prompt
        assert "If the most recent tool call result appears truncated" in prompt
        assert "never wrap your final reply in tags such as" in prompt
        assert "## Your Self-Awareness" not in prompt
        assert "## User Profile" not in prompt

    def test_build_cacheable_system_prompt_includes_shell_environment_near_workspace(
        self, tmp_path
    ):
        """Shell environment facts should be included with workspace guidance."""
        from prompts.system_prompt import build_cacheable_system_prompt

        shell_environment_info = {
            "os_name": "Windows",
            "platform": "win32",
            "shell": "cmd.exe via cmd /D /S /C",
            "path_style": "Windows drive-letter paths with backslashes",
            "command_guidance": (
                "Generate commands for this shell and path style. Do not mix Bash, "
                "PowerShell, and cmd.exe syntax."
            ),
        }

        prompt = build_cacheable_system_prompt(
            seele_data=self._build_seele_data(),
            workspace_dir=tmp_path,
            shell_environment_info=shell_environment_info,
        )

        assert f"Your default workspace is `{tmp_path.resolve()}`" in prompt
        assert "Shell environment: OS is Windows (win32)" in prompt
        assert "`execute_shell_command` runs commands in cmd.exe via cmd /D /S /C" in prompt
        assert "path style is Windows drive-letter paths with backslashes" in prompt
        assert "Do not mix Bash, PowerShell, and cmd.exe syntax" in prompt
        assert prompt.index("Your default workspace") < prompt.index("Shell environment")

    def test_build_cacheable_system_prompt_allows_missing_shell_environment(
        self, tmp_path
    ):
        """Direct prompt construction should still work without shell facts."""
        from prompts.system_prompt import build_cacheable_system_prompt

        prompt = build_cacheable_system_prompt(
            seele_data=self._build_seele_data(),
            workspace_dir=tmp_path,
        )

        assert f"Your default workspace is `{tmp_path.resolve()}`" in prompt
        assert "Shell environment:" not in prompt

    def test_get_cacheable_system_prompt_includes_workspace_agents_md_after_commands(
        self, tmp_path, monkeypatch
    ):
        """Workspace AGENTS.md should be included after commands_and_agreements."""
        seele_path = tmp_path / "seele.json"
        seele_data = self._build_seele_data(commands_and_agreements=["Call me by my name"])
        seele_path.write_text(json.dumps(seele_data, indent=2), encoding="utf-8")

        agents_md_path = tmp_path / "AGENTS.md"
        agents_md_path.write_text("# Workspace Rules\n\n- Keep changes small", encoding="utf-8")

        from core.config import Config
        import prompts.runtime as system

        monkeypatch.setattr(Config, "SEELE_JSON_PATH", seele_path)
        monkeypatch.setattr(Config, "DATA_DIR", tmp_path)
        monkeypatch.setattr(Config, "WORKSPACE_DIR", tmp_path)
        system._seele_json_cache = {}

        prompt = get_cacheable_system_prompt([])

        assert "<commands_and_agreements>" in prompt
        assert "- Call me by my name" in prompt
        assert "<agents_md>" in prompt
        assert "# Workspace Rules" in prompt
        assert "- Keep changes small" in prompt
        assert prompt.index("</commands_and_agreements>") < prompt.index("<agents_md>")

    def test_get_cacheable_system_prompt_ignores_missing_workspace_agents_md(
        self, tmp_path, monkeypatch
    ):
        """Missing workspace AGENTS.md should be ignored."""
        seele_path = tmp_path / "seele.json"
        seele_data = self._build_seele_data(commands_and_agreements=["Be concise"])
        seele_path.write_text(json.dumps(seele_data, indent=2), encoding="utf-8")

        from core.config import Config
        import prompts.runtime as system

        monkeypatch.setattr(Config, "SEELE_JSON_PATH", seele_path)
        monkeypatch.setattr(Config, "DATA_DIR", tmp_path)
        monkeypatch.setattr(Config, "WORKSPACE_DIR", tmp_path)
        system._seele_json_cache = {}

        prompt = get_cacheable_system_prompt([])

        assert "<commands_and_agreements>" in prompt
        assert "- Be concise" in prompt
        assert "<agents_md>" not in prompt

    def test_get_cacheable_system_prompt_reloads_agents_md_on_next_call(
        self, tmp_path, monkeypatch
    ):
        """Updating workspace AGENTS.md should affect the next prompt build immediately."""
        seele_path = tmp_path / "seele.json"
        seele_data = self._build_seele_data(commands_and_agreements=["Follow workspace rules"])
        seele_path.write_text(json.dumps(seele_data, indent=2), encoding="utf-8")

        agents_md_path = tmp_path / "AGENTS.md"
        agents_md_path.write_text("# Version 1\n\n- old rule", encoding="utf-8")

        from core.config import Config
        import prompts.runtime as system

        monkeypatch.setattr(Config, "SEELE_JSON_PATH", seele_path)
        monkeypatch.setattr(Config, "DATA_DIR", tmp_path)
        monkeypatch.setattr(Config, "WORKSPACE_DIR", tmp_path)
        system._seele_json_cache = {}

        first_prompt = get_cacheable_system_prompt([])

        agents_md_path.write_text("# Version 2\n\n- new rule", encoding="utf-8")

        second_prompt = get_cacheable_system_prompt([])

        assert "# Version 1" in first_prompt
        assert "- old rule" in first_prompt
        assert "# Version 2" not in first_prompt

        assert "# Version 2" in second_prompt
        assert "- new rule" in second_prompt
        assert "# Version 1" not in second_prompt
        assert "- old rule" not in second_prompt

    def test_get_cacheable_system_prompt_removes_agents_md_on_next_call_after_delete(
        self, tmp_path, monkeypatch
    ):
        """Deleting workspace AGENTS.md should remove the block on the next prompt build."""
        seele_path = tmp_path / "seele.json"
        seele_data = self._build_seele_data(commands_and_agreements=["Follow workspace rules"])
        seele_path.write_text(json.dumps(seele_data, indent=2), encoding="utf-8")

        agents_md_path = tmp_path / "AGENTS.md"
        agents_md_path.write_text("# Temporary Rules\n\n- transient", encoding="utf-8")

        from core.config import Config
        import prompts.runtime as system

        monkeypatch.setattr(Config, "SEELE_JSON_PATH", seele_path)
        monkeypatch.setattr(Config, "DATA_DIR", tmp_path)
        monkeypatch.setattr(Config, "WORKSPACE_DIR", tmp_path)
        system._seele_json_cache = {}

        prompt_with_agents = get_cacheable_system_prompt([])

        agents_md_path.unlink()

        prompt_without_agents = get_cacheable_system_prompt([])

        assert "<agents_md>" in prompt_with_agents
        assert "# Temporary Rules" in prompt_with_agents

        assert "<agents_md>" not in prompt_without_agents
        assert "# Temporary Rules" not in prompt_without_agents

    def test_get_cacheable_system_prompt_formats_language_style_examples_as_list(
        self, tmp_path, monkeypatch
    ):
        """Language style examples should render as bullet list items, not comma-joined text."""
        seele_path = tmp_path / "seele.json"
        seele_data = {
            "bot": {
                "name": "TestBot",
                "gender": "neutral",
                "role": "AI Assistant",
                "likes": [],
                "dislikes": [],
                "language_style": {
                    "description": "warm and concise",
                    "examples": ["Hello there.", "Let me handle that."],
                },
                "personality": {
                    "mbti": "",
                    "description": "",
                    "worldview_and_values": "",
                },
                "emotions": {"long_term": "", "short_term": []},
                "needs": {"long_term": "", "short_term": []},
                "relationship_with_user": "",
            },
            "user": {
                "name": "",
                "gender": "",
                "location": "Berlin",
                "personal_facts": [],
                "abilities": [],
                "likes": [],
                "dislikes": [],
                "personality": {
                    "mbti": "",
                    "description": "",
                    "worldview_and_values": "",
                },
                "emotions": {"long_term": "", "short_term": []},
                "needs": {"long_term": "", "short_term": []},
            },
            "memorable_events": {},
            "commands_and_agreements": [],
        }
        seele_path.write_text(json.dumps(seele_data, indent=2), encoding="utf-8")

        from core.config import Config
        import prompts.runtime as system

        monkeypatch.setattr(Config, "SEELE_JSON_PATH", seele_path)
        monkeypatch.setattr(Config, "DATA_DIR", tmp_path)
        system._seele_json_cache = {}

        prompt = get_cacheable_system_prompt([])

        assert "**Language Style:**" in prompt
        assert "- Examples:\n- Hello there.\n- Let me handle that." in prompt
        assert "Hello there., Let me handle that." not in prompt

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
                "user": {"name": "TestUser", "location": ""},
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
        assert "/user/location" in prompt

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
        assert "prefer storing it as stable knowledge/facts/personality/relationship understanding" in prompt

    def test_get_memory_update_prompt_prioritizes_non_event_long_term_updates(self):
        """Long-term useful information should be framed as facts/knowledge before events."""
        prompt = get_memory_update_prompt("User: test", self._current_seele_json())

        assert "If the main value is durable understanding" in prompt
        assert "Keep the number of memorable_events small" in prompt
        assert "Prefer non-event storage first" in prompt

    def test_get_memory_update_prompt_warns_to_be_extremely_cautious_with_importance_five(self):
        """Importance 5 should be explicitly described as rare and high-bar."""
        prompt = get_memory_update_prompt("User: test", self._current_seele_json())

        assert "5 should be used extremely sparingly" in prompt
        assert "When uncertain between 4 and 5, prefer 4" in prompt

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
        assert '"location": "string"' in prompt

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
        assert "prefer storing it as knowledge/facts/personality/relationship understanding" in prompt

    def test_get_complete_memory_json_prompt_prioritizes_non_event_long_term_updates(self):
        """Fallback full-json prompt should also prefer stable understanding over event inflation."""
        prompt = get_complete_memory_json_prompt(
            "User: test",
            self._current_seele_json(),
            "patch failed",
        )

        assert "Default to non-event storage" in prompt
        assert "Keep the set small" in prompt
        assert "prefer that over adding an event" in prompt

    def test_get_complete_memory_json_prompt_warns_about_importance_five(self):
        """Fallback full-json prompt should set a very high bar for importance 5."""
        prompt = get_complete_memory_json_prompt(
            "User: test",
            self._current_seele_json(),
            "patch failed",
        )

        assert "Use importance 5 extremely sparingly" in prompt
        assert "prefer 4 over 5" in prompt

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

    def test_get_seele_compaction_prompt_contains_limits_and_rules(self):
        """Compaction prompt should encode retention limits and curation rules."""
        prompt = get_seele_compaction_prompt(
            self._current_seele_json(),
            20,
            20,
        )

        assert "<seele_compaction_task>" in prompt
        assert "Keep at most 20 personal_facts" in prompt
        assert "Keep at most 20 memorable_events" in prompt
        assert "Re-evaluate each event's lasting significance" in prompt
        assert "short_term emotion/need list exceeds 12 items" in prompt
        assert "keep only the latest 4 short-term items" in prompt
        assert '"personal_facts": ["..."]' in prompt
        assert '"memorable_events": {' in prompt
        assert '"short_term": ["..."]' in prompt

    def test_memory_update_prompt_requires_short_term_append_only_arrays(self):
        """Memory update prompt should constrain short-term emotion/need patches."""
        prompt = get_memory_update_prompt("User: test", self._current_seele_json())

        assert "short_term: array of strings" in prompt
        assert 'Use only {"op": "add"' in prompt
        assert '/short_term/-' in prompt
        assert "Do NOT replace an entire short_term list" in prompt
        assert "exceeds 12 items" in prompt
        assert "latest 4 items" in prompt

    def test_get_memory_update_prompt_without_timestamps(self):
        """Test getting memory update prompt without timestamps."""
        messages = "User: Test"
        prompt = get_memory_update_prompt(messages, self._current_seele_json())
        assert isinstance(prompt, str)


class TestGetCompleteMemoryJsonPrompt:
    """Test get_complete_memory_json_prompt functionality."""

    def test_get_complete_memory_json_prompt(self, reset_seele_json_cache):
        """Test getting complete memory JSON prompt."""
        messages = "User: My name is Alice\nAssistant: Nice to meet you, Alice"
        current_seele_json = json.dumps(
            {
                "bot": {"name": "TestBot"},
                "user": {"name": "", "location": ""},
                "memorable_events": {},
                "commands_and_agreements": [],
            }
        )

        prompt = get_complete_memory_json_prompt(
            messages,
            current_seele_json,
            "JSON Patch application failed",
        )

        assert isinstance(prompt, str)
        assert "<complete_memory_json_task>" in prompt
        assert "JSON Patch application failed" in prompt
        assert "Alice" in prompt
        assert "TestBot" in prompt


class TestPromptIntegration:
    """Integration tests for prompt system."""

    def test_full_prompt_workflow(self, tmp_path, monkeypatch, reset_seele_json_cache):
        """Test complete prompt workflow."""
        from core.config import Config
        import prompts.runtime as system

        seele_path = tmp_path / "seele.json"
        seele_path.write_text(
            json.dumps(
                {
                    "bot": {
                        "name": "TestBot",
                        "gender": "neutral",
                        "role": "AI assistant",
                        "likes": [],
                        "dislikes": [],
                        "language_style": {"description": "", "examples": []},
                        "personality": {
                            "mbti": "",
                            "description": "",
                            "worldview_and_values": "",
                        },
                        "emotions": {"long_term": "", "short_term": []},
                        "needs": {"long_term": "", "short_term": []},
                        "relationship_with_user": "",
                    },
                    "user": {
                        "name": "TestUser",
                        "gender": "",
                        "location": "Berlin",
                        "personal_facts": [],
                        "abilities": [],
                        "likes": [],
                        "dislikes": [],
                        "personality": {
                            "mbti": "",
                            "description": "",
                            "worldview_and_values": "",
                        },
                        "emotions": {"long_term": "", "short_term": []},
                        "needs": {"long_term": "", "short_term": []},
                    },
                    "memorable_events": {},
                    "commands_and_agreements": ["Prefer concise replies"],
                }
            ),
            encoding="utf-8",
        )
        monkeypatch.setattr(Config, "SEELE_JSON_PATH", seele_path)
        monkeypatch.setattr(Config, "DATA_DIR", tmp_path)
        monkeypatch.setattr(Config, "WORKSPACE_DIR", tmp_path)
        system._seele_json_cache = {}

        cacheable_prompt = get_cacheable_system_prompt([])
        summary_prompt = get_summary_prompt(None, "User: Hello\nAssistant: Hi")
        memory_prompt = get_memory_update_prompt(
            "User: I live in Berlin", seele_path.read_text(encoding="utf-8")
        )
        complete_json_prompt = get_complete_memory_json_prompt(
            "User: I live in Berlin",
            seele_path.read_text(encoding="utf-8"),
            "Patch failed",
        )

        assert "TestBot" in cacheable_prompt
        assert "Prefer concise replies" in cacheable_prompt
        assert "<summary_task>" in summary_prompt
        assert "<memory_update_task>" in memory_prompt
        assert "<complete_memory_json_task>" in complete_json_prompt

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
                "user": {"name": "TestUser", "location": ""},
                "memorable_events": {},
                "commands_and_agreements": [],
            }
        )
        memory_prompt = get_memory_update_prompt(
            messages, current_seele_json, 1234567890, 1234567990
        )

        assert isinstance(memory_prompt, str)
