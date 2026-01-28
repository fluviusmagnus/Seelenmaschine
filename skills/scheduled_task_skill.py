from typing import Dict, Any, Optional
import json

from skills.base_skill import BaseSkill
from utils.logger import get_logger
from utils.time import parse_time_expression, format_timestamp

logger = get_logger()


class ScheduledTaskSkill(BaseSkill):
    """Skill for managing scheduled tasks"""
    
    def __init__(self, scheduler):
        """Initialize with task scheduler instance
        
        Args:
            scheduler: TaskScheduler instance
        """
        self._scheduler = scheduler
    
    @property
    def name(self) -> str:
        return "scheduled_task"
    
    @property
    def description(self) -> str:
        return """Manage scheduled tasks (reminders, recurring messages).
        
Actions:
- add: Create a new task (once or interval)
- list: List all active tasks
- get: Get details of a specific task
- cancel: Cancel a task
- pause: Pause a task
- resume: Resume a paused task
"""
    
    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["add", "list", "get", "cancel", "pause", "resume"],
                    "description": "Action to perform"
                },
                "task_id": {
                    "type": "string",
                    "description": "Task ID (for get/cancel/pause/resume)"
                },
                "name": {
                    "type": "string",
                    "description": "Task name (for add)"
                },
                "trigger_type": {
                    "type": "string",
                    "enum": ["once", "interval"],
                    "description": "Type of trigger: 'once' for one-time, 'interval' for recurring"
                },
                "time": {
                    "type": "string",
                    "description": "Time for trigger (for 'once': ISO datetime or timestamp; for 'interval': duration like '1h', '30m', '1d')"
                },
                "message": {
                    "type": "string",
                    "description": "Message to send when task triggers"
                }
            },
            "required": ["action"]
        }
    
    async def execute(self, **kwargs) -> str:
        action = kwargs.get("action")
        
        if action == "add":
            return await self._add_task(kwargs)
        elif action == "list":
            return await self._list_tasks()
        elif action == "get":
            return await self._get_task(kwargs.get("task_id"))
        elif action == "cancel":
            return await self._cancel_task(kwargs.get("task_id"))
        elif action == "pause":
            return await self._pause_task(kwargs.get("task_id"))
        elif action == "resume":
            return await self._resume_task(kwargs.get("task_id"))
        else:
            return f"Unknown action: {action}"
    
    async def _add_task(self, kwargs: Dict[str, Any]) -> str:
        """Add a new scheduled task"""
        try:
            name = kwargs.get("name", "Unnamed Task")
            trigger_type = kwargs.get("trigger_type")
            time_expr = kwargs.get("time")
            message = kwargs.get("message", "")
            
            if not trigger_type:
                return "Error: trigger_type is required (once or interval)"
            
            if not time_expr:
                return "Error: time is required"
            
            if not message:
                return "Error: message is required"
            
            trigger_config = {}
            
            if trigger_type == "once":
                # Parse time for one-time task
                timestamp = parse_time_expression(time_expr)
                if timestamp is None:
                    return f"Error: Could not parse time expression '{time_expr}'"
                
                trigger_config = {"timestamp": timestamp}
                
            elif trigger_type == "interval":
                # Parse interval duration
                interval = self._parse_interval(time_expr)
                if interval is None:
                    return f"Error: Invalid interval '{time_expr}'. Use format like '1h', '30m', '1d'"
                
                trigger_config = {"interval": interval}
            
            else:
                return f"Error: Invalid trigger_type '{trigger_type}'"
            
            # Add task
            task_id = self._scheduler.add_task(
                name=name,
                trigger_type=trigger_type,
                trigger_config=trigger_config,
                message=message
            )
            
            # Format response
            if trigger_type == "once":
                time_str = format_timestamp(trigger_config["timestamp"])
                return f"✓ Task created (ID: {task_id})\nName: {name}\nType: One-time\nTrigger at: {time_str}\nMessage: {message}"
            else:
                return f"✓ Task created (ID: {task_id})\nName: {name}\nType: Recurring\nInterval: {time_expr}\nMessage: {message}"
                
        except Exception as e:
            logger.error(f"Error adding task: {e}")
            return f"Error adding task: {e}"
    
    async def _list_tasks(self) -> str:
        """List all active tasks"""
        try:
            tasks = self._scheduler.db.get_all_tasks(status="active")
            
            if not tasks:
                return "No active tasks found."
            
            result = f"Active tasks ({len(tasks)}):\n\n"
            
            for task in tasks:
                trigger_config = json.loads(task["trigger_config"])
                
                result += f"• {task['name']} (ID: {task['task_id'][:8]}...)\n"
                result += f"  Type: {task['trigger_type']}\n"
                
                if task['trigger_type'] == 'once':
                    time_str = format_timestamp(trigger_config.get('timestamp', 0))
                    result += f"  Trigger at: {time_str}\n"
                else:
                    interval = trigger_config.get('interval', 0)
                    result += f"  Interval: {self._format_interval(interval)}\n"
                    next_run = format_timestamp(task['next_run_at'])
                    result += f"  Next run: {next_run}\n"
                
                result += f"  Message: {task['message'][:50]}...\n\n"
            
            return result.strip()
            
        except Exception as e:
            logger.error(f"Error listing tasks: {e}")
            return f"Error listing tasks: {e}"
    
    async def _get_task(self, task_id: Optional[str]) -> str:
        """Get details of a specific task"""
        if not task_id:
            return "Error: task_id is required"
        
        try:
            task = self._scheduler.get_task(task_id)
            
            if not task:
                return f"Task not found: {task_id}"
            
            trigger_config = json.loads(task["trigger_config"])
            
            result = f"Task: {task['name']}\n"
            result += f"ID: {task['task_id']}\n"
            result += f"Type: {task['trigger_type']}\n"
            result += f"Status: {task['status']}\n"
            
            if task['trigger_type'] == 'once':
                time_str = format_timestamp(trigger_config.get('timestamp', 0))
                result += f"Trigger at: {time_str}\n"
            else:
                interval = trigger_config.get('interval', 0)
                result += f"Interval: {self._format_interval(interval)}\n"
                next_run = format_timestamp(task['next_run_at'])
                result += f"Next run: {next_run}\n"
            
            if task['last_run_at']:
                last_run = format_timestamp(task['last_run_at'])
                result += f"Last run: {last_run}\n"
            
            result += f"Message: {task['message']}"
            
            return result
            
        except Exception as e:
            logger.error(f"Error getting task: {e}")
            return f"Error getting task: {e}"
    
    async def _cancel_task(self, task_id: Optional[str]) -> str:
        """Cancel a task"""
        if not task_id:
            return "Error: task_id is required"
        
        try:
            task = self._scheduler.get_task(task_id)
            if not task:
                return f"Task not found: {task_id}"
            
            self._scheduler.db.update_task_status(task_id, "completed")
            return f"✓ Task cancelled: {task['name']}"
            
        except Exception as e:
            logger.error(f"Error cancelling task: {e}")
            return f"Error cancelling task: {e}"
    
    async def _pause_task(self, task_id: Optional[str]) -> str:
        """Pause a task"""
        if not task_id:
            return "Error: task_id is required"
        
        try:
            task = self._scheduler.get_task(task_id)
            if not task:
                return f"Task not found: {task_id}"
            
            if task['status'] != 'active':
                return f"Task is not active (current status: {task['status']})"
            
            self._scheduler.db.update_task_status(task_id, "paused")
            return f"✓ Task paused: {task['name']}"
            
        except Exception as e:
            logger.error(f"Error pausing task: {e}")
            return f"Error pausing task: {e}"
    
    async def _resume_task(self, task_id: Optional[str]) -> str:
        """Resume a paused task"""
        if not task_id:
            return "Error: task_id is required"
        
        try:
            task = self._scheduler.get_task(task_id)
            if not task:
                return f"Task not found: {task_id}"
            
            if task['status'] != 'paused':
                return f"Task is not paused (current status: {task['status']})"
            
            self._scheduler.db.update_task_status(task_id, "active")
            return f"✓ Task resumed: {task['name']}"
            
        except Exception as e:
            logger.error(f"Error resuming task: {e}")
            return f"Error resuming task: {e}"
    
    def _parse_interval(self, time_expr: str) -> Optional[int]:
        """Parse interval expression to seconds
        
        Args:
            time_expr: Expression like '1h', '30m', '2d'
            
        Returns:
            Interval in seconds, or None if invalid
        """
        time_expr = time_expr.strip().lower()
        
        try:
            if time_expr.endswith('s'):
                return int(time_expr[:-1])
            elif time_expr.endswith('m'):
                return int(time_expr[:-1]) * 60
            elif time_expr.endswith('h'):
                return int(time_expr[:-1]) * 3600
            elif time_expr.endswith('d'):
                return int(time_expr[:-1]) * 86400
            elif time_expr.endswith('w'):
                return int(time_expr[:-1]) * 604800
            else:
                # Try to parse as plain seconds
                return int(time_expr)
        except (ValueError, IndexError):
            return None
    
    def _format_interval(self, seconds: int) -> str:
        """Format interval in seconds to human-readable string"""
        if seconds % 604800 == 0:
            return f"{seconds // 604800}w"
        elif seconds % 86400 == 0:
            return f"{seconds // 86400}d"
        elif seconds % 3600 == 0:
            return f"{seconds // 3600}h"
        elif seconds % 60 == 0:
            return f"{seconds // 60}m"
        else:
            return f"{seconds}s"
