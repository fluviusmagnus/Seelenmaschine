"""Test that one-time tasks don't repeat execution"""

import pytest
import asyncio
import time

from core.database import DatabaseManager
from core.scheduler import TaskScheduler
from utils.time import get_current_timestamp


@pytest.fixture
def temp_db(tmp_path):
    """Create a temporary database for testing"""
    db_path = tmp_path / "test.db"
    db = DatabaseManager(db_path)
    yield db
    # Cleanup
    if db_path.exists():
        db_path.unlink()


@pytest.fixture
def scheduler(temp_db):
    """Create a scheduler instance with temp database"""
    return TaskScheduler(temp_db)


@pytest.mark.asyncio
async def test_one_time_task_only_executes_once(scheduler):
    """Test that a one-time task only executes once even if checked multiple times"""
    messages_sent = []

    def callback(message):
        messages_sent.append(message)

    scheduler.set_message_callback(callback)

    # Add a task that's due now
    current_time = get_current_timestamp()
    task_id = scheduler.add_task(
        name="One-time Test",
        trigger_type="once",
        trigger_config={"timestamp": current_time - 10},
        message="Execute only once!",
    )

    # Execute task first time
    await scheduler._check_and_run_tasks()
    assert len(messages_sent) == 1
    assert messages_sent[0] == "Execute only once!"

    # Check task status
    task = scheduler.get_task(task_id)
    assert task["status"] == "completed"
    assert task["last_run_at"] is not None

    # Try to execute again immediately
    await scheduler._check_and_run_tasks()

    # Message should still only be sent once
    assert len(messages_sent) == 1

    # Try a third time after a small delay
    await asyncio.sleep(0.1)
    await scheduler._check_and_run_tasks()

    # Message should still only be sent once
    assert len(messages_sent) == 1

    # Verify task is still marked as completed
    task = scheduler.get_task(task_id)
    assert task["status"] == "completed"


@pytest.mark.asyncio
async def test_multiple_one_time_tasks_execute_independently(scheduler):
    """Test that multiple one-time tasks execute independently"""
    messages_sent = []

    def callback(message):
        messages_sent.append(message)

    scheduler.set_message_callback(callback)

    # Add two tasks that are due now
    current_time = get_current_timestamp()
    task1_id = scheduler.add_task(
        name="Task 1",
        trigger_type="once",
        trigger_config={"timestamp": current_time - 10},
        message="Task 1 message",
    )

    task2_id = scheduler.add_task(
        name="Task 2",
        trigger_type="once",
        trigger_config={"timestamp": current_time - 10},
        message="Task 2 message",
    )

    # Execute all due tasks
    await scheduler._check_and_run_tasks()
    assert len(messages_sent) == 2
    assert "Task 1 message" in messages_sent
    assert "Task 2 message" in messages_sent

    # Both tasks should be completed
    task1 = scheduler.get_task(task1_id)
    task2 = scheduler.get_task(task2_id)
    assert task1["status"] == "completed"
    assert task2["status"] == "completed"

    # Try to execute again - no new messages should be sent
    await scheduler._check_and_run_tasks()
    assert len(messages_sent) == 2


@pytest.mark.asyncio
async def test_interval_task_continues_executing(scheduler, temp_db):
    """Test that interval tasks continue to execute"""
    messages_sent = []

    def callback(message):
        messages_sent.append(message)

    scheduler.set_message_callback(callback)

    # Add an interval task
    current_time = get_current_timestamp()
    interval = 1  # 1 second interval for testing
    task_id = scheduler.add_task(
        name="Interval Test",
        trigger_type="interval",
        trigger_config={"interval": interval},
        message="Interval message",
    )

    # Manually set next_run_at to current time to make it due immediately
    temp_db.update_task_next_run(
        task_id=task_id, next_run_at=current_time, last_run_at=None
    )

    # Execute first time
    await scheduler._check_and_run_tasks()
    assert len(messages_sent) == 1

    # Task should still be active
    task = scheduler.get_task(task_id)
    assert task["status"] == "active"
    assert task["last_run_at"] is not None

    # Wait for interval to pass
    await asyncio.sleep(interval + 0.1)

    # Execute again
    await scheduler._check_and_run_tasks()
    assert len(messages_sent) == 2

    # Task should still be active
    task = scheduler.get_task(task_id)
    assert task["status"] == "active"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
