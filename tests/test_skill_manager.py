import pytest
import tempfile
import sys
import asyncio
from pathlib import Path
from unittest.mock import Mock, patch, AsyncMock, MagicMock

from tools.skill_manager import SkillManager


@pytest.fixture
def temp_skills_dir(tmp_path):
    """Create temporary skills directory for testing."""
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    return skills_dir


class TestSkillManager:
    """Test SkillManager functionality."""

    def test_initialization(self, temp_skills_dir):
        """Test skill manager initialization."""
        with patch("tools.skill_manager.Config") as mock_config_class:
            config_mock = mock_config_class.return_value
            config_mock.SKILLS_DIR = str(temp_skills_dir)
            config_mock.ENABLE_SKILLS = True

            manager = SkillManager()

            assert manager.skills_dir == temp_skills_dir
            assert isinstance(manager._skills, dict)
            assert manager._tools_cache is None

    def test_initialization_with_custom_dir(self, temp_skills_dir):
        """Test initialization with custom skills directory."""
        with patch("tools.skill_manager.Config") as mock_config_class:
            config_mock = mock_config_class.return_value
            config_mock.SKILLS_DIR = "default_skills"
            config_mock.ENABLE_SKILLS = True

            manager = SkillManager(skills_dir=str(temp_skills_dir))

            assert manager.skills_dir == temp_skills_dir

    def test_initialization_disabled(self, temp_skills_dir):
        """Test initialization when skills are disabled."""
        with patch("tools.skill_manager.Config") as mock_config_class:
            config_mock = mock_config_class.return_value
            config_mock.SKILLS_DIR = str(temp_skills_dir)
            config_mock.ENABLE_SKILLS = False

            manager = SkillManager()

            assert manager._skills == {}

    def test_load_skills_empty_directory(self, temp_skills_dir):
        """Test loading skills from empty directory."""
        with patch("tools.skill_manager.Config") as mock_config_class:
            config_mock = mock_config_class.return_value
            config_mock.SKILLS_DIR = str(temp_skills_dir)
            config_mock.ENABLE_SKILLS = True

            manager = SkillManager()

            assert len(manager._skills) == 0

    def test_load_skills_nonexistent_directory(self, tmp_path):
        """Test loading skills from nonexistent directory."""
        nonexistent_dir = tmp_path / "nonexistent"

        with patch("tools.skill_manager.Config") as mock_config_class:
            config_mock = mock_config_class.return_value
            config_mock.SKILLS_DIR = str(nonexistent_dir)
            config_mock.ENABLE_SKILLS = True

            manager = SkillManager()

            assert len(manager._skills) == 0

    def test_get_tools_empty(self, temp_skills_dir):
        """Test getting tools when no skills loaded."""
        with patch("tools.skill_manager.Config") as mock_config_class:
            config_mock = mock_config_class.return_value
            config_mock.SKILLS_DIR = str(temp_skills_dir)
            config_mock.ENABLE_SKILLS = True

            manager = SkillManager()

            tools = manager.get_tools()

            assert tools == []

    def test_get_tools_from_skills(self, temp_skills_dir):
        """Test getting tools from loaded skills."""
        with patch("tools.skill_manager.Config") as mock_config_class:
            config_mock = mock_config_class.return_value
            config_mock.SKILLS_DIR = str(temp_skills_dir)
            config_mock.ENABLE_SKILLS = True

            manager = SkillManager()

            mock_skill = Mock()
            mock_skill.name = "test_skill"
            mock_skill.description = "Test skill"
            mock_skill.parameters = {"type": "object"}
            manager._skills["test_skill"] = mock_skill

            tools = manager.get_tools()

            assert len(tools) == 1
            assert tools[0]["type"] == "function"
            assert tools[0]["function"]["name"] == "test_skill"
            assert tools[0]["function"]["description"] == "Test skill"

    def test_get_tools_uses_cache(self, temp_skills_dir):
        """Test that get_tools uses cached tools."""
        with patch("tools.skill_manager.Config") as mock_config_class:
            config_mock = mock_config_class.return_value
            config_mock.SKILLS_DIR = str(temp_skills_dir)
            config_mock.ENABLE_SKILLS = True

            manager = SkillManager()

            cached_tools = [{"type": "function", "function": {"name": "cached"}}]
            manager._tools_cache = cached_tools

            tools = manager.get_tools()

            assert tools == cached_tools

    @pytest.mark.asyncio
    async def test_execute_skill_not_found(self, temp_skills_dir):
        """Test executing non-existent skill."""
        with patch("tools.skill_manager.Config") as mock_config_class:
            config_mock = mock_config_class.return_value
            config_mock.SKILLS_DIR = str(temp_skills_dir)
            config_mock.ENABLE_SKILLS = True

            manager = SkillManager()

            result = await manager.execute_skill("nonexistent", {})

            assert "not found" in result

    @pytest.mark.asyncio
    async def test_execute_skill_success(self, temp_skills_dir):
        """Test successful skill execution."""
        with patch("tools.skill_manager.Config") as mock_config_class:
            config_mock = mock_config_class.return_value
            config_mock.SKILLS_DIR = str(temp_skills_dir)
            config_mock.ENABLE_SKILLS = True

            manager = SkillManager()

            mock_skill = Mock()
            mock_skill.execute = AsyncMock(return_value="Success!")
            manager._skills["test_skill"] = mock_skill

            result = await manager.execute_skill("test_skill", {"arg": "value"})

            assert result == "Success!"
            mock_skill.execute.assert_awaited_once_with(arg="value")

    @pytest.mark.asyncio
    async def test_execute_skill_error_handling(self, temp_skills_dir):
        """Test skill execution error handling."""
        with patch("tools.skill_manager.Config") as mock_config_class, patch(
            "tools.skill_manager.logger"
        ):
            config_mock = mock_config_class.return_value
            config_mock.SKILLS_DIR = str(temp_skills_dir)
            config_mock.ENABLE_SKILLS = True

            manager = SkillManager()

            mock_skill = Mock()
            mock_skill.execute = AsyncMock(side_effect=Exception("Skill error"))
            manager._skills["test_skill"] = mock_skill

            result = await manager.execute_skill("test_skill", {})

            assert "failed" in result

    def test_execute_skill_sync(self, temp_skills_dir):
        """Test synchronous skill execution wrapper."""
        with patch("tools.skill_manager.Config") as mock_config_class, patch(
            "tools.skill_manager.logger"
        ):
            config_mock = mock_config_class.return_value
            config_mock.SKILLS_DIR = str(temp_skills_dir)
            config_mock.ENABLE_SKILLS = True

            manager = SkillManager()

            mock_skill = Mock()
            mock_skill.execute = AsyncMock(return_value="Sync result")
            manager._skills["test_skill"] = mock_skill

            result = manager.execute_skill_sync("test_skill", {})

            assert result == "Sync result"

    def test_execute_skill_sync_error_handling(self, temp_skills_dir):
        """Test sync wrapper error handling."""
        with patch("tools.skill_manager.Config") as mock_config_class, patch(
            "tools.skill_manager.logger"
        ):
            config_mock = mock_config_class.return_value
            config_mock.SKILLS_DIR = str(temp_skills_dir)
            config_mock.ENABLE_SKILLS = True

            manager = SkillManager()

            mock_skill = Mock()
            mock_skill.execute = AsyncMock(side_effect=Exception("Sync error"))
            manager._skills["test_skill"] = mock_skill

            result = manager.execute_skill_sync("test_skill", {})

            assert "failed" in result


class TestSkillManagerIntegration:
    """Integration tests for SkillManagerManager."""

    def test_skill_loading_workflow(self, temp_skills_dir):
        """Test complete skill loading workflow."""
        with patch("tools.skill_manager.Config") as mock_config_class:
            config_mock = mock_config_class.return_value
            config_mock.SKILLS_DIR = str(temp_skills_dir)
            config_mock.ENABLE_SKILLS = True

            manager = SkillManager()

            mock_skill = Mock()
            mock_skill.name = "integration_skill"
            mock_skill.description = "Integration test skill"
            mock_skill.parameters = {
                "type": "object",
                "properties": {"param": {"type": "string"}},
            }
            manager._skills["integration_skill"] = mock_skill

            tools = manager.get_tools()

            assert len(tools) == 1
            assert "integration_skill" in manager._skills

    def test_multiple_skills(self, temp_skills_dir):
        """Test loading and managing multiple skills."""
        with patch("tools.skill_manager.Config") as mock_config_class:
            config_mock = mock_config_class.return_value
            config_mock.SKILLS_DIR = str(temp_skills_dir)
            config_mock.ENABLE_SKILLS = True

            manager = SkillManager()

            for i in range(3):
                mock_skill = Mock()
                mock_skill.name = f"skill_{i}"
                mock_skill.description = f"Skill {i}"
                mock_skill.parameters = {}
                manager._skills[f"skill_{i}"] = mock_skill

            tools = manager.get_tools()

            assert len(tools) == 3
            assert len(manager._skills) == 3
