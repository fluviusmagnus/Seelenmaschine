import json
from typing import Any, Dict, Optional

from texts import ToolTexts
from utils.logger import get_logger
from utils.time import (
    format_duration_seconds,
    format_timestamp,
    get_current_timestamp,
    parse_duration_to_seconds,
    parse_time_expression,
    parse_timezone,
)

logger = get_logger()


class ScheduledTaskTool:
    """Tool for managing scheduled tasks"""

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
        return ToolTexts.ScheduledTask.DESCRIPTION

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["add", "list", "get", "cancel", "pause", "resume"],
                    "description": ToolTexts.ScheduledTask.PARAMETER_DESCRIPTIONS["action"],
                },
                "task_id": {
                    "type": "string",
                    "description": ToolTexts.ScheduledTask.PARAMETER_DESCRIPTIONS["task_id"],
                },
                "name": {
                    "type": "string",
                    "description": ToolTexts.ScheduledTask.PARAMETER_DESCRIPTIONS["name"],
                },
                "trigger_type": {
                    "type": "string",
                    "enum": ["once", "interval"],
                    "description": ToolTexts.ScheduledTask.PARAMETER_DESCRIPTIONS["trigger_type"],
                },
                "time": {
                    "type": "string",
                    "description": ToolTexts.ScheduledTask.PARAMETER_DESCRIPTIONS["time"],
                },
                "start_time": {
                    "type": "string",
                    "description": ToolTexts.ScheduledTask.PARAMETER_DESCRIPTIONS["start_time"],
                },
                "end_time": {
                    "type": "string",
                    "description": ToolTexts.ScheduledTask.PARAMETER_DESCRIPTIONS["end_time"],
                },
                "timezone": {
                    "type": "string",
                    "description": ToolTexts.ScheduledTask.PARAMETER_DESCRIPTIONS["timezone"],
                },
                "message": {
                    "type": "string",
                    "description": ToolTexts.ScheduledTask.PARAMETER_DESCRIPTIONS["message"],
                },
            },
            "required": ["action"],
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
            return ToolTexts.unknown_action(action)

    async def _add_task(self, kwargs: Dict[str, Any]) -> str:
        """Add a new scheduled task"""
        try:
            name = kwargs.get("name", ToolTexts.ScheduledTask.UNNAMED_TASK)
            trigger_type = kwargs.get("trigger_type")
            time_expr = kwargs.get("time")
            start_time_expr = kwargs.get("start_time")
            end_time_expr = kwargs.get("end_time")
            timezone_name = kwargs.get("timezone")
            message = kwargs.get("message", "")

            if not trigger_type:
                return ToolTexts.error("trigger_type is required (once or interval)")

            if not time_expr:
                return ToolTexts.error("time is required")

            if not message:
                return ToolTexts.error("message is required")

            try:
                timezone = parse_timezone(timezone_name)
            except ValueError as e:
                return ToolTexts.error(str(e))

            trigger_config = {}

            if trigger_type == "once":
                if end_time_expr:
                    return ToolTexts.error("end_time is only supported for interval tasks")
                # Parse time for one-time task
                timestamp = parse_time_expression(time_expr, tz=timezone)
                if timestamp is None:
                    return ToolTexts.error(f"Could not parse time expression '{time_expr}'")

                trigger_config = {"timestamp": timestamp}
                if timezone_name:
                    trigger_config["timezone"] = timezone_name.strip()

            elif trigger_type == "interval":
                # Parse interval duration
                interval = self._parse_interval(time_expr)
                if interval is None:
                    return ToolTexts.error(
                        f"Invalid interval '{time_expr}'. Use format like '1h', '30m', '1d'"
                    )

                trigger_config = {"interval": interval}
                if start_time_expr:
                    start_timestamp = parse_time_expression(start_time_expr, tz=timezone)
                    if start_timestamp is None:
                        return ToolTexts.error(
                            f"Could not parse start_time expression '{start_time_expr}'"
                        )
                    trigger_config["start_timestamp"] = start_timestamp
                if end_time_expr:
                    end_timestamp = parse_time_expression(end_time_expr, tz=timezone)
                    if end_timestamp is None:
                        return ToolTexts.error(
                            f"Could not parse end_time expression '{end_time_expr}'"
                        )
                    trigger_config["end_timestamp"] = end_timestamp

                start_timestamp = trigger_config.get("start_timestamp")
                end_timestamp = trigger_config.get("end_timestamp")
                if (
                    start_timestamp is not None
                    and end_timestamp is not None
                    and end_timestamp < start_timestamp
                ):
                    return ToolTexts.error(
                        "end_time must be greater than or equal to start_time"
                    )

                current_timestamp_getter = getattr(
                    self._scheduler, "get_current_timestamp", None
                )
                if callable(current_timestamp_getter):
                    current_timestamp = current_timestamp_getter()
                    if not isinstance(current_timestamp, int):
                        current_timestamp = get_current_timestamp()
                else:
                    current_timestamp = get_current_timestamp()

                first_run_timestamp = start_timestamp or current_timestamp + interval
                if end_timestamp is not None and end_timestamp < first_run_timestamp:
                    return ToolTexts.error(
                        "end_time must be greater than or equal to the first scheduled run"
                    )

                if timezone_name:
                    trigger_config["timezone"] = timezone_name.strip()

            else:
                return ToolTexts.error(f"Invalid trigger_type '{trigger_type}'")

            # Add task
            task_id = self._scheduler.add_task(
                name=name,
                trigger_type=trigger_type,
                trigger_config=trigger_config,
                message=message,
            )

            # Format response
            if trigger_type == "once":
                time_str = format_timestamp(trigger_config["timestamp"], tz=timezone)
                return ToolTexts.ScheduledTask.task_created_once(
                    task_id=task_id,
                    name=name,
                    trigger_at=time_str,
                    timezone_name=timezone_name,
                    message=message,
                )
            else:
                first_run = None
                end_time = None
                if trigger_config.get("start_timestamp"):
                    first_run = format_timestamp(
                        trigger_config["start_timestamp"], tz=timezone
                    )
                if trigger_config.get("end_timestamp"):
                    end_time = format_timestamp(
                        trigger_config["end_timestamp"], tz=timezone
                    )
                return ToolTexts.ScheduledTask.task_created_interval(
                    task_id=task_id,
                    name=name,
                    interval=time_expr,
                    first_run=first_run,
                    end_time=end_time,
                    timezone_name=timezone_name,
                    message=message,
                )

        except Exception as e:
            logger.error(f"Error adding task: {e}")
            return f"Error adding task: {e}"

    async def _list_tasks(self) -> str:
        """List all active tasks"""
        try:
            tasks = self._scheduler.db.get_all_tasks(status="active")

            if not tasks:
                return ToolTexts.ScheduledTask.NO_ACTIVE_TASKS

            result = f"Active tasks ({len(tasks)}):\n\n"

            for task in tasks:
                trigger_config = task["trigger_config"]
                if isinstance(trigger_config, str):
                    trigger_config = json.loads(trigger_config)
                task_tz = self._get_task_timezone(trigger_config)

                result += f"• {task['name']}\n"
                result += f"  Task ID: {task['task_id']}\n"
                result += f"  Type: {task['trigger_type']}\n"

                if task["trigger_type"] == "once":
                    time_str = format_timestamp(
                        trigger_config.get("timestamp", 0), tz=task_tz
                    )
                    result += f"  Trigger at: {time_str}\n"
                else:
                    interval = trigger_config.get("interval", 0)
                    result += f"  Interval: {self._format_interval(interval)}\n"
                    if trigger_config.get("start_timestamp"):
                        first_run = format_timestamp(
                            trigger_config.get("start_timestamp", 0), tz=task_tz
                        )
                        result += f"  First run: {first_run}\n"
                    if trigger_config.get("end_timestamp"):
                        end_time = format_timestamp(
                            trigger_config.get("end_timestamp", 0), tz=task_tz
                        )
                        result += f"  End time: {end_time}\n"
                    if trigger_config.get("timezone"):
                        result += f"  Timezone: {trigger_config['timezone']}\n"
                    next_run = format_timestamp(task["next_run_at"], tz=task_tz)
                    result += f"  Next run: {next_run}\n"

                if task["trigger_type"] == "once" and trigger_config.get("timezone"):
                    result += f"  Timezone: {trigger_config['timezone']}\n"

                result += f"  Message: {task['message'][:50]}...\n\n"

            return result.strip()

        except Exception as e:
            logger.error(f"Error listing tasks: {e}")
            return f"Error listing tasks: {e}"

    async def _get_task(self, task_id: Optional[str]) -> str:
        """Get details of a specific task"""
        if not task_id:
            return ToolTexts.error("task_id is required")

        try:
            task = self._scheduler.get_task(task_id)

            if not task:
                return ToolTexts.ScheduledTask.task_not_found(task_id)

            trigger_config = task["trigger_config"]
            if isinstance(trigger_config, str):
                trigger_config = json.loads(trigger_config)
            task_tz = self._get_task_timezone(trigger_config)

            result = f"Name: {task['name']}\n"
            result += f"Task ID: {task['task_id']}\n"
            result += f"Type: {task['trigger_type']}\n"
            result += f"Status: {task['status']}\n"

            if task["trigger_type"] == "once":
                time_str = format_timestamp(trigger_config.get("timestamp", 0), tz=task_tz)
                result += f"Trigger at: {time_str}\n"
            else:
                interval = trigger_config.get("interval", 0)
                result += f"Interval: {self._format_interval(interval)}\n"
                if trigger_config.get("start_timestamp"):
                    first_run = format_timestamp(
                        trigger_config.get("start_timestamp", 0), tz=task_tz
                    )
                    result += f"First run: {first_run}\n"
                if trigger_config.get("end_timestamp"):
                    end_time = format_timestamp(
                        trigger_config.get("end_timestamp", 0), tz=task_tz
                    )
                    result += f"End time: {end_time}\n"
                if trigger_config.get("timezone"):
                    result += f"Timezone: {trigger_config['timezone']}\n"
                next_run = format_timestamp(task["next_run_at"], tz=task_tz)
                result += f"Next run: {next_run}\n"

            if task["trigger_type"] == "once" and trigger_config.get("timezone"):
                result += f"Timezone: {trigger_config['timezone']}\n"

            if task["last_run_at"]:
                last_run = format_timestamp(task["last_run_at"], tz=task_tz)
                result += f"Last run: {last_run}\n"

            result += f"Message: {task['message']}"

            return result

        except Exception as e:
            logger.error(f"Error getting task: {e}")
            return f"Error getting task: {e}"

    async def _cancel_task(self, task_id: Optional[str]) -> str:
        """Cancel a task"""
        if not task_id:
            return ToolTexts.error("task_id is required")

        try:
            task = self._scheduler.get_task(task_id)
            if not task:
                return ToolTexts.ScheduledTask.task_not_found(task_id)

            self._scheduler.db.update_task_status(task_id, "completed")
            return ToolTexts.ScheduledTask.task_action_success("cancelled", task["name"])

        except Exception as e:
            logger.error(f"Error cancelling task: {e}")
            return f"Error cancelling task: {e}"

    async def _pause_task(self, task_id: Optional[str]) -> str:
        """Pause a task"""
        if not task_id:
            return ToolTexts.error("task_id is required")

        try:
            task = self._scheduler.get_task(task_id)
            if not task:
                return ToolTexts.ScheduledTask.task_not_found(task_id)

            if task["status"] != "active":
                return ToolTexts.ScheduledTask.task_status_mismatch(
                    "active", task["status"]
                )

            self._scheduler.db.update_task_status(task_id, "paused")
            return ToolTexts.ScheduledTask.task_action_success("paused", task["name"])

        except Exception as e:
            logger.error(f"Error pausing task: {e}")
            return f"Error pausing task: {e}"

    async def _resume_task(self, task_id: Optional[str]) -> str:
        """Resume a paused task"""
        if not task_id:
            return ToolTexts.error("task_id is required")

        try:
            task = self._scheduler.get_task(task_id)
            if not task:
                return ToolTexts.ScheduledTask.task_not_found(task_id)

            if task["status"] != "paused":
                return ToolTexts.ScheduledTask.task_status_mismatch(
                    "paused", task["status"]
                )

            self._scheduler.db.update_task_status(task_id, "active")
            return ToolTexts.ScheduledTask.task_action_success("resumed", task["name"])

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
        return parse_duration_to_seconds(time_expr)

    def _format_interval(self, seconds: int) -> str:
        """Format interval in seconds to human-readable string"""
        return format_duration_seconds(seconds)

    def _get_task_timezone(self, trigger_config: Dict[str, Any]):
        timezone_name = trigger_config.get("timezone")
        if not timezone_name:
            return None

        try:
            return parse_timezone(timezone_name)
        except ValueError:
            logger.warning(f"Invalid task timezone stored in trigger_config: {timezone_name}")
            return None
