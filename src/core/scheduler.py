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
        self._instance_id = str(uuid.uuid4())[:8]
        logger.debug(f"TaskScheduler {self._instance_id} initialized")

    def set_message_callback(self, callback: Callable) -> None:
        """Set callback for sending messages (can be sync or async)"""
        self._message_callback = callback
        logger.debug(f"TaskScheduler {self._instance_id}: message callback set")

    async def run_forever(self) -> None:
        """Run the scheduler loop forever (to be used as Application job)"""
        if self._running:
            logger.warning(
                f"TaskScheduler {self._instance_id} is already running, skipping start"
            )
            return

        self._running = True
        logger.info(f"Task scheduler {self._instance_id} started")

        while self._running:
            try:
                await self._check_and_run_tasks()
                await asyncio.sleep(10)
            except asyncio.CancelledError:
                logger.info(f"Task scheduler {self._instance_id} cancelled")
                break
            except Exception as e:
                logger.error(f"Error in task scheduler {self._instance_id} loop: {e}")
                await asyncio.sleep(10)

        logger.info(f"Task scheduler {self._instance_id} stopped")

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

        # Atomically claim tasks so no other scheduler instance picks them up
        due_tasks = self.db.claim_due_tasks(current_time)
        if due_tasks:
            logger.info(
                f"TaskScheduler {self._instance_id}: Claimed {len(due_tasks)} due tasks"
            )

        for task_data in due_tasks:
            try:
                await self._execute_task(task_data)
            except Exception as e:
                logger.error(
                    f"TaskScheduler {self._instance_id}: Failed to execute task {task_data['task_id']}: {e}"
                )
                # Reset status to active if it failed, so it can be retried later
                self.db.update_task_status(task_data["task_id"], "active")

    async def _execute_task(self, task_data: Dict[str, Any]) -> None:
        task_id = task_data["task_id"]
        trigger_type = task_data["trigger_type"]
        trigger_config = task_data["trigger_config"]
        message = task_data["message"]

        logger.info(
            f"TaskScheduler {self._instance_id} executing task: {task_id} - {task_data['name']}"
        )

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

    def get_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        return self.db.get_task(task_id)
