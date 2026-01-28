from abc import ABC, abstractmethod
from typing import Dict, Any


class BaseSkill(ABC):
    """Base class for all skills"""
    
    @property
    @abstractmethod
    def name(self) -> str:
        """Name of the skill"""
        pass
    
    @property
    @abstractmethod
    def description(self) -> str:
        """Description of what the skill does"""
        pass
    
    @property
    @abstractmethod
    def parameters(self) -> Dict[str, Any]:
        """JSON Schema for the skill's parameters"""
        pass
    
    @abstractmethod
    async def execute(self, **kwargs) -> str:
        """Execute the skill with given parameters
        
        Returns:
            str: Result of the skill execution
        """
        pass
