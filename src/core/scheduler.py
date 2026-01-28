import asyncio
import uuid
from typing import Dict, Any, Optional, Callable
from dataclasses import dataclass

from core.database import DatabaseManager
from utils.time import get_current_timestamp
from utils.logger import get_logger

logger = get_logger()


@dataclass
class ScheduledTask:
    task_id: str
    name: str
    trigger_type: str
    trigger_config: Dict[str, Any]
    message: str
    created_at: int
    next_run_at: int
    last_run_at: Optional[int]
    status: str


class TaskScheduler:
    def __init__(self, db: DatabaseManager):
        self.db = db
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._message_callback: Optional[Callable] = None

    def set_message_callback(self, callback: Callable) -> None:
        """Set callback for sending messages (can be sync or async)"""
        self._message_callback = callback

    async def run_forever(self) -> None:
        """Run the scheduler loop forever (to be used as Application job)"""
        self._running = True
        logger.info("Task scheduler started")

        while self._running:
            try:
                await self._check_and_run_tasks()
                await asyncio.sleep(10)
            except asyncio.CancelledError:
                logger.info("Task scheduler cancelled")
                break
            except Exception as e:
                logger.error(f"Error in task scheduler loop: {e}")
                await asyncio.sleep(10)

        logger.info("Task scheduler stopped")

    def stop(self) -> None:
        """Stop the scheduler loop"""
        self._running = False
        if self._task and not self._task.done():
            try:
                self._task.cancel()
                logger.info("Task scheduler stop requested")
            except RuntimeError as e:
                # Event loop might already be closed
                logger.debug(f"Could not cancel scheduler task: {e}")

    async def _check_and_run_tasks(self) -> None:
        current_time = get_current_timestamp()

        due_tasks = self.db.get_due_tasks(current_time)

        for task_data in due_tasks:
            try:
                await self._execute_task(task_data)
            except Exception as e:
                logger.error(f"Failed to execute task {task_data['task_id']}: {e}")

    async def _execute_task(self, task_data: Dict[str, Any]) -> None:
        task_id = task_data["task_id"]
        trigger_type = task_data["trigger_type"]
        trigger_config = task_data["trigger_config"]
        message = task_data["message"]

        logger.info(f"Executing task: {task_id} - {task_data['name']}")

        if self._message_callback:
            # Support both sync and async callbacks
            if asyncio.iscoroutinefunction(self._message_callback):
                await self._message_callback(message)
            else:
                self._message_callback(message)
        else:
            logger.warning(f"No message callback set, task message: {message}")

        last_run_at = get_current_timestamp()
        next_run_at = None

        if trigger_type == "once":
            # Mark one-time task as completed and update last_run_at
            self.db.update_task_status_and_last_run(task_id, "completed", last_run_at)
            logger.info(f"One-time task {task_id} completed")

        elif trigger_type == "interval":
            interval = trigger_config.get("interval", 3600)
            next_run_at = last_run_at + interval
            self.db.update_task_next_run(
                task_id, next_run_at=next_run_at, last_run_at=last_run_at
            )
            logger.info(f"Interval task {task_id} rescheduled for {next_run_at}")

    def add_task(
        self, name: str, trigger_type: str, trigger_config: Dict[str, Any], message: str
    ) -> str:
        task_id = str(uuid.uuid4())
        created_at = get_current_timestamp()
        next_run_at = created_at

        if trigger_type == "once":
            timestamp = trigger_config.get("timestamp")
            if timestamp:
                next_run_at = timestamp
        elif trigger_type == "interval":
            interval = trigger_config.get("interval", 3600)
            next_run_at = created_at + interval

        self.db.insert_scheduled_task(
            task_id=task_id,
            name=name,
            trigger_type=trigger_type,
            trigger_config=trigger_config,
            message=message,
            created_at=created_at,
            next_run_at=next_run_at,
            status="active",
        )

        logger.info(f"Added task: {task_id} - {name}")
        return task_id

    def load_tasks_from_file(self, file_path: str) -> None:
        import json
        from pathlib import Path

        path = Path(file_path)
        if not path.exists():
            logger.warning(f"Task config file not found: {file_path}")
            return

        try:
            with open(path, "r", encoding="utf-8") as f:
                tasks_config = json.load(f)

            if isinstance(tasks_config, list):
                for task_config in tasks_config:
                    self.add_task(
                        name=task_config.get("name", ""),
                        trigger_type=task_config.get("trigger_type", "once"),
                        trigger_config=task_config.get("trigger_config", {}),
                        message=task_config.get("message", ""),
                    )

            logger.info(f"Loaded tasks from {file_path}")

        except Exception as e:
            logger.error(f"Failed to load tasks from {file_path}: {e}")

    def load_default_tasks(self) -> None:
        from config import Config

        config = Config()
        tasks_path = config.DATA_DIR / "scheduled_tasks.json"
        if tasks_path.exists():
            self.load_tasks_from_file(str(tasks_path))

    def get_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        return self.db.get_task(task_id)
