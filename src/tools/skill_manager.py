import importlib
import inspect
import asyncio
from pathlib import Path
from typing import Dict, Any, List, Optional

from config import Config
from utils.logger import get_logger

logger = get_logger()


class SkillManager:
    """Manager for loading and executing skills"""
    
    def __init__(self, skills_dir: Optional[str] = None):
        config = Config()
        self.skills_dir = Path(skills_dir or config.SKILLS_DIR)
        self._skills: Dict[str, Any] = {}
        self._tools_cache: Optional[List[Dict[str, Any]]] = None
        
        if config.ENABLE_SKILLS:
            self._load_skills()
        else:
            logger.info("Skills system is disabled")

    def _load_skills(self) -> None:
        """Auto-discover and load skills from skills directory"""
        if not self.skills_dir.exists():
            logger.warning(f"Skills directory not found: {self.skills_dir}")
            return
        
        # Skills that require dependency injection and will be registered manually
        skip_skills = {"ScheduledTaskSkill"}
        
        for module_file in self.skills_dir.glob("*.py"):
            if module_file.name.startswith("_") or module_file.name == "base_skill.py":
                continue
            
            try:
                module_name = f"skills.{module_file.stem}"
                module = importlib.import_module(module_name)
                
                for name, obj in inspect.getmembers(module):
                    if inspect.isclass(obj) and name != "BaseSkill":
                        # Skip skills that need dependency injection
                        if name in skip_skills:
                            logger.debug(f"Skipping {name} (requires manual registration)")
                            continue
                        
                        try:
                            if hasattr(obj, "__bases__") and "BaseSkill" in [b.__name__ for b in obj.__mro__]:
                                skill = obj()
                                self._skills[skill.name] = skill
                                logger.info(f"Loaded skill: {skill.name}")
                        except Exception as e:
                            logger.warning(f"Failed to instantiate {name}: {e}")
                            
            except Exception as e:
                logger.error(f"Failed to load module {module_name}: {e}")
        
        logger.info(f"Loaded {len(self._skills)} skills")

    def get_tools(self) -> List[Dict[str, Any]]:
        """Get all skills as OpenAI function calling format tools"""
        if self._tools_cache is not None:
            return self._tools_cache
        
        tools = []
        for skill in self._skills.values():
            tool = {
                "type": "function",
                "function": {
                    "name": skill.name,
                    "description": skill.description,
                    "parameters": skill.parameters
                }
            }
            tools.append(tool)
        
        self._tools_cache = tools
        return tools

    async def execute_skill(self, skill_name: str, arguments: Dict[str, Any]) -> str:
        """Execute a skill asynchronously"""
        if skill_name not in self._skills:
            error_msg = f"Skill not found: {skill_name}"
            logger.error(error_msg)
            return error_msg
        
        try:
            skill = self._skills[skill_name]
            result = await skill.execute(**arguments)
            logger.info(f"Executed skill: {skill_name}")
            return str(result)
        except Exception as e:
            error_msg = f"Skill execution failed: {str(e)}"
            logger.error(f"{error_msg} (skill={skill_name}, args={arguments})", exc_info=True)
            return error_msg

    def execute_skill_sync(self, skill_name: str, arguments: Dict[str, Any]) -> str:
        """Execute a skill synchronously (wrapper for async)"""
        loop = asyncio.get_event_loop()
        try:
            return loop.run_until_complete(self.execute_skill(skill_name, arguments))
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            return loop.run_until_complete(self.execute_skill(skill_name, arguments))
