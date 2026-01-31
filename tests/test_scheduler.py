"""Unit tests for task scheduler"""

import pytest
import json
from unittest.mock import Mock

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


def test_add_one_time_task(scheduler):
    """Test adding a one-time task"""
    current_time = get_current_timestamp()
    future_time = current_time + 3600  # 1 hour from now

    task_id = scheduler.add_task(
        name="Test Reminder",
        trigger_type="once",
        trigger_config={"timestamp": future_time},
        message="This is a test reminder",
    )

    assert task_id is not None
    assert len(task_id) > 0

    # Verify task was stored
    task = scheduler.get_task(task_id)
    assert task is not None
    assert task["name"] == "Test Reminder"
    assert task["trigger_type"] == "once"
    assert task["message"] == "This is a test reminder"
    assert task["next_run_at"] == future_time
    assert task["status"] == "active"


def test_add_interval_task(scheduler):
    """Test adding an interval task"""
    task_id = scheduler.add_task(
        name="Recurring Task",
        trigger_type="interval",
        trigger_config={"interval": 3600},  # Every hour
        message="Hourly reminder",
    )

    assert task_id is not None

    task = scheduler.get_task(task_id)
    assert task is not None
    assert task["name"] == "Recurring Task"
    assert task["trigger_type"] == "interval"
    assert task["trigger_config"]["interval"] == 3600


def test_get_due_tasks(scheduler, temp_db):
    """Test retrieving due tasks"""
    current_time = get_current_timestamp()

    # Add a past task (should be due)
    past_task_id = scheduler.add_task(
        name="Past Task",
        trigger_type="once",
        trigger_config={"timestamp": current_time - 100},
        message="Past",
    )

    # Add a future task (should not be due)
    scheduler.add_task(
        name="Future Task",
        trigger_type="once",
        trigger_config={"timestamp": current_time + 3600},
        message="Future",
    )

    # Get due tasks
    due_tasks = temp_db.get_due_tasks(current_time)

    assert len(due_tasks) == 1
    assert due_tasks[0]["task_id"] == past_task_id
    assert due_tasks[0]["name"] == "Past Task"


def test_update_task_after_execution(scheduler, temp_db):
    """Test updating task after execution"""
    current_time = get_current_timestamp()

    task_id = scheduler.add_task(
        name="Test Task",
        trigger_type="once",
        trigger_config={"timestamp": current_time},
        message="Test",
    )

    # Simulate execution
    temp_db.update_task_next_run(
        task_id=task_id,
        next_run_at=0,  # No next run for one-time task
        last_run_at=current_time,
    )

    # Verify update
    task = scheduler.get_task(task_id)
    assert task["last_run_at"] == current_time
    assert task["next_run_at"] == 0


def test_interval_task_reschedule(scheduler, temp_db):
    """Test that interval tasks are rescheduled after execution"""
    current_time = get_current_timestamp()
    interval = 3600

    task_id = scheduler.add_task(
        name="Interval Task",
        trigger_type="interval",
        trigger_config={"interval": interval},
        message="Test",
    )

    # Simulate execution
    new_next_run = current_time + interval
    temp_db.update_task_next_run(
        task_id=task_id, next_run_at=new_next_run, last_run_at=current_time
    )

    # Verify rescheduling
    updated_task = scheduler.get_task(task_id)
    assert updated_task["last_run_at"] == current_time
    assert updated_task["next_run_at"] == new_next_run


def test_task_status_management(scheduler, temp_db):
    """Test task status updates"""
    task_id = scheduler.add_task(
        name="Status Test",
        trigger_type="once",
        trigger_config={"timestamp": get_current_timestamp() + 3600},
        message="Test",
    )

    # Initial status should be active
    task = scheduler.get_task(task_id)
    assert task["status"] == "active"

    # Pause task
    temp_db.update_task_status(task_id, "paused")
    task = scheduler.get_task(task_id)
    assert task["status"] == "paused"

    # Complete task
    temp_db.update_task_status(task_id, "completed")
    task = scheduler.get_task(task_id)
    assert task["status"] == "completed"


def test_get_all_tasks(scheduler, temp_db):
    """Test retrieving all tasks"""
    # Add multiple tasks
    scheduler.add_task(
        name="Task 1",
        trigger_type="once",
        trigger_config={"timestamp": get_current_timestamp() + 100},
        message="Test 1",
    )

    task2_id = scheduler.add_task(
        name="Task 2",
        trigger_type="interval",
        trigger_config={"interval": 3600},
        message="Test 2",
    )

    # Pause one task
    temp_db.update_task_status(task2_id, "paused")

    # Get all active tasks
    active_tasks = temp_db.get_all_tasks(status="active")
    assert len(active_tasks) == 1
    assert active_tasks[0]["name"] == "Task 1"

    # Get all paused tasks
    paused_tasks = temp_db.get_all_tasks(status="paused")
    assert len(paused_tasks) == 1
    assert paused_tasks[0]["name"] == "Task 2"

    # Get all tasks
    all_tasks = temp_db.get_all_tasks()
    assert len(all_tasks) == 2


def test_message_callback(scheduler):
    """Test that message callback is invoked"""
    callback_mock = Mock()
    scheduler.set_message_callback(callback_mock)

    # Manually trigger callback (simulating task execution)
    test_message = "Test callback message"
    if scheduler._message_callback:
        scheduler._message_callback(test_message)

    callback_mock.assert_called_once_with(test_message)


def test_load_tasks_from_file(scheduler, tmp_path):
    """Test loading tasks from JSON file"""
    # Create a test config file
    config_file = tmp_path / "test_tasks.json"
    tasks_data = [
        {
            "name": "Morning Reminder",
            "trigger_type": "interval",
            "trigger_config": {"interval": 86400},
            "message": "Good morning!",
        },
        {
            "name": "One-time Event",
            "trigger_type": "once",
            "trigger_config": {"timestamp": get_current_timestamp() + 3600},
            "message": "Don't forget!",
        },
    ]

    with open(config_file, "w") as f:
        json.dump(tasks_data, f)

    # Load tasks
    scheduler.load_tasks_from_file(str(config_file))

    # Verify tasks were loaded
    all_tasks = scheduler.db.get_all_tasks()
    assert len(all_tasks) == 2

    task_names = {task["name"] for task in all_tasks}
    assert "Morning Reminder" in task_names
    assert "One-time Event" in task_names


def test_load_nonexistent_file(scheduler):
    """Test loading from nonexistent file doesn't crash"""
    # Should not raise exception
    scheduler.load_tasks_from_file("nonexistent_file.json")


@pytest.mark.asyncio
async def test_task_execution_flow(scheduler):
    """Test the full task execution flow"""
    messages_sent = []

    def callback(message):
        messages_sent.append(message)

    scheduler.set_message_callback(callback)

    # Add a task that's due now
    current_time = get_current_timestamp()
    task_id = scheduler.add_task(
        name="Immediate Task",
        trigger_type="once",
        trigger_config={"timestamp": current_time - 10},
        message="Execute now!",
    )

    # Manually check and run tasks (simulating scheduler loop)
    await scheduler._check_and_run_tasks()

    # Verify callback was called
    assert len(messages_sent) == 1
    assert messages_sent[0] == "Execute now!"

    # Verify task was marked as completed
    task = scheduler.get_task(task_id)
    assert task["last_run_at"] is not None
    assert task["status"] == "completed"  # One-time task should be marked as completed


def test_trigger_config_serialization(scheduler):
    """Test that trigger config is properly serialized/deserialized"""
    complex_config = {
        "interval": 3600,
        "metadata": {"created_by": "test", "priority": "high"},
        "tags": ["important", "daily"],
    }

    task_id = scheduler.add_task(
        name="Complex Config Task",
        trigger_type="interval",
        trigger_config=complex_config,
        message="Test",
    )

    # Retrieve and verify
    task = scheduler.get_task(task_id)
    retrieved_config = task["trigger_config"]

    assert retrieved_config == complex_config
    assert retrieved_config["metadata"]["created_by"] == "test"
    assert "important" in retrieved_config["tags"]
