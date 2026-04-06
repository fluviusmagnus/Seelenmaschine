import pytest
from unittest.mock import Mock

from tools.scheduled_tasks import ScheduledTaskTool


@pytest.fixture
def mock_scheduler():
    """Create mock scheduler."""
    scheduler = Mock()
    scheduler.add_task = Mock(return_value="task_001")
    scheduler.db = Mock()
    scheduler.db.get_all_tasks = Mock(return_value=[])
    scheduler.get_task = Mock(return_value=None)
    return scheduler


@pytest.fixture
def scheduled_task_tool(mock_scheduler):
    """Create ScheduledTaskTool instance."""
    return ScheduledTaskTool(scheduler=mock_scheduler)


class TestScheduledTaskTool:
    """Test ScheduledTaskTool functionality."""

    def test_initialization(self, scheduled_task_tool, mock_scheduler):
        """Test tool initialization."""
        assert scheduled_task_tool._scheduler == mock_scheduler

    def test_name(self, scheduled_task_tool):
        """Test tool name."""
        assert scheduled_task_tool.name == "scheduled_task"

    def test_description(self, scheduled_task_tool):
        """Test tool description."""
        description = scheduled_task_tool.description
        assert "schedule" in description.lower()
        assert "task" in description.lower()

    def test_parameters(self, scheduled_task_tool):
        """Test tool parameters schema."""
        params = scheduled_task_tool.parameters
        assert params["type"] == "object"
        assert "action" in params["properties"]
        assert "action" in params["required"]

    def test_parse_interval_valid_formats(self, scheduled_task_tool):
        """Test parsing valid time interval formats."""
        # Test seconds
        assert scheduled_task_tool._parse_interval("30s") == 30
        assert scheduled_task_tool._parse_interval("60s") == 60

        # Test minutes
        assert scheduled_task_tool._parse_interval("5m") == 300
        assert scheduled_task_tool._parse_interval("10m") == 600

        # Test hours
        assert scheduled_task_tool._parse_interval("2h") == 7200
        assert scheduled_task_tool._parse_interval("24h") == 86400

        # Test days
        assert scheduled_task_tool._parse_interval("1d") == 86400
        assert scheduled_task_tool._parse_interval("7d") == 604800

    def test_parse_interval_invalid_formats(self, scheduled_task_tool):
        """Test parsing invalid time interval formats."""
        assert scheduled_task_tool._parse_interval("invalid") is None
        assert scheduled_task_tool._parse_interval("") is None

    def test_format_interval(self, scheduled_task_tool):
        """Test formatting interval to human readable string."""
        # Test seconds
        assert scheduled_task_tool._format_interval(30) == "30s"
        assert scheduled_task_tool._format_interval(59) == "59s"

        # Test minutes
        assert scheduled_task_tool._format_interval(60) == "1m"
        assert scheduled_task_tool._format_interval(300) == "5m"

        # Test hours
        assert scheduled_task_tool._format_interval(3600) == "1h"
        assert scheduled_task_tool._format_interval(7200) == "2h"

        # Test days
        assert scheduled_task_tool._format_interval(86400) == "1d"
        assert scheduled_task_tool._format_interval(604800) == "1w"

    @pytest.mark.asyncio
    async def test_add_task_interval(self, scheduled_task_tool, mock_scheduler):
        """Test adding interval-based task."""
        mock_scheduler.add_task.return_value = "task_001"

        result = await scheduled_task_tool.execute(
            action="add",
            name="Test Task",
            trigger_type="interval",
            time="5m",
            message="Test message",
        )

        assert "✓ Task created (Task ID: task_001)" in result
        assert "Name: Test Task" in result
        assert "Type: Recurring" in result
        assert "Interval: 5m" in result
        assert "Message: Test message" in result
        assert mock_scheduler.add_task.called

    @pytest.mark.asyncio
    async def test_add_task_interval_with_start_time_and_timezone(
        self, scheduled_task_tool, mock_scheduler
    ):
        """Test adding interval task with explicit first run and timezone."""
        mock_scheduler.add_task.return_value = "task_003"

        result = await scheduled_task_tool.execute(
            action="add",
            name="Daily Reminder",
            trigger_type="interval",
            time="1d",
            start_time="2026-04-07 08:00:00",
            timezone="Asia/Shanghai",
            message="Remind user to check the morning plan",
        )

        assert "✓ Task created (Task ID: task_003)" in result
        assert "Type: Recurring" in result
        assert "Interval: 1d" in result
        assert "First run:" in result
        assert "Timezone: Asia/Shanghai" in result
        mock_scheduler.add_task.assert_called_once()
        trigger_config = mock_scheduler.add_task.call_args.kwargs["trigger_config"]
        assert trigger_config["interval"] == 86400
        assert "start_timestamp" in trigger_config
        assert trigger_config["timezone"] == "Asia/Shanghai"

    @pytest.mark.asyncio
    async def test_add_task_interval_with_end_time(self, scheduled_task_tool, mock_scheduler):
        """Test adding interval task with explicit end time."""
        mock_scheduler.add_task.return_value = "task_005"
        mock_scheduler.get_current_timestamp.return_value = 1700000000

        result = await scheduled_task_tool.execute(
            action="add",
            name="Bounded Reminder",
            trigger_type="interval",
            time="1d",
            start_time="2026-04-07 08:00:00",
            end_time="2026-04-30 18:00:00",
            timezone="Europe/Berlin",
            message="Remind user to review progress",
        )

        assert "End time:" in result
        trigger_config = mock_scheduler.add_task.call_args.kwargs["trigger_config"]
        assert "end_timestamp" in trigger_config

    @pytest.mark.asyncio
    async def test_add_task_interval_rejects_end_before_start(
        self, scheduled_task_tool, mock_scheduler
    ):
        """Test validation when end_time is before start_time."""
        result = await scheduled_task_tool.execute(
            action="add",
            name="Invalid Window",
            trigger_type="interval",
            time="1d",
            start_time="2026-04-30 18:00:00",
            end_time="2026-04-07 08:00:00",
            timezone="Europe/Berlin",
            message="Test message",
        )

        assert "end_time must be greater than or equal to start_time" in result
        mock_scheduler.add_task.assert_not_called()

    @pytest.mark.asyncio
    async def test_add_task_once_rejects_end_time(self, scheduled_task_tool, mock_scheduler):
        """Test once task rejects end_time."""
        result = await scheduled_task_tool.execute(
            action="add",
            name="Once Task",
            trigger_type="once",
            time="2026-04-07 08:00:00",
            end_time="2026-04-08 08:00:00",
            message="One-time message",
        )

        assert "end_time is only supported for interval tasks" in result
        mock_scheduler.add_task.assert_not_called()

    @pytest.mark.asyncio
    async def test_add_task_once(self, scheduled_task_tool, mock_scheduler):
        """Test adding one-time task."""
        mock_scheduler.add_task.return_value = "task_002"

        result = await scheduled_task_tool.execute(
            action="add",
            name="One-time Task",
            trigger_type="once",
            time="2024-01-01 12:00:00",
            message="One-time message",
        )

        assert "✓ Task created (Task ID: task_002)" in result
        assert "Name: One-time Task" in result
        assert "Type: One-time" in result
        assert "Trigger at:" in result
        assert "Message: One-time message" in result
        assert mock_scheduler.add_task.called

    @pytest.mark.asyncio
    async def test_add_task_once_with_timezone(self, scheduled_task_tool, mock_scheduler):
        """Test adding one-time task with explicit timezone."""
        mock_scheduler.add_task.return_value = "task_004"

        result = await scheduled_task_tool.execute(
            action="add",
            name="Berlin Task",
            trigger_type="once",
            time="2026-04-07 08:00:00",
            timezone="Europe/Berlin",
            message="One-time message",
        )

        assert "✓ Task created (Task ID: task_004)" in result
        assert "Timezone: Europe/Berlin" in result
        trigger_config = mock_scheduler.add_task.call_args.kwargs["trigger_config"]
        assert trigger_config["timezone"] == "Europe/Berlin"
        assert "timestamp" in trigger_config

    @pytest.mark.asyncio
    async def test_add_task_invalid_timezone(self, scheduled_task_tool, mock_scheduler):
        """Test adding task with invalid timezone."""
        result = await scheduled_task_tool.execute(
            action="add",
            name="Bad TZ",
            trigger_type="once",
            time="2026-04-07 08:00:00",
            timezone="Mars/OlympusMons",
            message="Test message",
        )

        assert "Invalid timezone" in result
        mock_scheduler.add_task.assert_not_called()

    @pytest.mark.asyncio
    async def test_add_task_missing_time(self, scheduled_task_tool):
        """Test adding task without time parameter."""
        result = await scheduled_task_tool.execute(
            action="add",
            name="Test Task",
            trigger_type="interval",
            message="Test message",
        )

        assert "time is required" in result

    @pytest.mark.asyncio
    async def test_add_task_missing_message(self, scheduled_task_tool):
        """Test adding task without message parameter."""
        result = await scheduled_task_tool.execute(
            action="add",
            name="Test Task",
            trigger_type="interval",
            time="5m",
        )

        assert "message is required" in result

    @pytest.mark.asyncio
    async def test_list_tasks(self, scheduled_task_tool, mock_scheduler):
        """Test listing all tasks."""
        mock_scheduler.db.get_all_tasks.return_value = [
            {
                "task_id": "task_001",
                "name": "Task 1",
                "status": "active",
                "trigger_type": "interval",
                "next_run_at": 1234567890,
                "trigger_config": '{"interval": 300, "start_timestamp": 1234567000, "end_timestamp": 1234567999, "timezone": "UTC"}',
                "message": "Test message",
            }
        ]

        result = await scheduled_task_tool.execute(action="list")

        assert "Task ID: task_001" in result
        assert "Task 1" in result
        assert "Type: interval" in result
        assert "First run:" in result
        assert "End time:" in result
        assert "Timezone: UTC" in result
        assert mock_scheduler.db.get_all_tasks.called

    @pytest.mark.asyncio
    async def test_list_tasks_empty(self, scheduled_task_tool, mock_scheduler):
        """Test listing tasks when none exist."""
        mock_scheduler.db.get_all_tasks.return_value = []

        result = await scheduled_task_tool.execute(action="list")

        assert "No active tasks" in result

    @pytest.mark.asyncio
    async def test_get_task(self, scheduled_task_tool, mock_scheduler):
        """Test getting specific task."""
        mock_scheduler.get_task.return_value = {
            "task_id": "task_001",
            "name": "Task 1",
            "status": "active",
            "trigger_type": "interval",
            "next_run_at": 1234567890,
            "last_run_at": None,
            "trigger_config": '{"interval": 300}',
            "message": "Test message",
        }

        result = await scheduled_task_tool.execute(action="get", task_id="task_001")

        assert result.startswith("Name: Task 1\n")
        assert "Task ID: task_001" in result
        assert "Type: interval" in result
        assert "Status: active" in result
        assert mock_scheduler.get_task.called

    @pytest.mark.asyncio
    async def test_get_task_not_found(self, scheduled_task_tool, mock_scheduler):
        """Test getting non-existent task."""
        mock_scheduler.get_task.return_value = None

        result = await scheduled_task_tool.execute(action="get", task_id="nonexistent")

        assert "not found" in result

    @pytest.mark.asyncio
    async def test_cancel_task(self, scheduled_task_tool, mock_scheduler):
        """Test cancelling a task."""
        mock_scheduler.get_task.return_value = {
            "task_id": "task_001",
            "name": "Task 1",
            "status": "active",
        }

        result = await scheduled_task_tool.execute(action="cancel", task_id="task_001")

        assert "cancelled" in result.lower()
        mock_scheduler.db.update_task_status.assert_called_with("task_001", "completed")

    @pytest.mark.asyncio
    async def test_pause_task(self, scheduled_task_tool, mock_scheduler):
        """Test pausing a task."""
        mock_scheduler.get_task.return_value = {
            "task_id": "task_001",
            "name": "Task 1",
            "status": "active",
        }

        result = await scheduled_task_tool.execute(action="pause", task_id="task_001")

        assert "paused" in result.lower()
        mock_scheduler.db.update_task_status.assert_called_with("task_001", "paused")

    @pytest.mark.asyncio
    async def test_resume_task(self, scheduled_task_tool, mock_scheduler):
        """Test resuming a task."""
        mock_scheduler.get_task.return_value = {
            "task_id": "task_001",
            "name": "Task 1",
            "status": "paused",
        }

        result = await scheduled_task_tool.execute(action="resume", task_id="task_001")

        assert "resumed" in result.lower()
        mock_scheduler.db.update_task_status.assert_called_with("task_001", "active")

    @pytest.mark.asyncio
    async def test_execute_invalid_action(self, scheduled_task_tool):
        """Test executing with invalid action."""
        result = await scheduled_task_tool.execute(action="invalid_action")

        assert "Unknown action" in result

    @pytest.mark.asyncio
    async def test_execute_missing_action(self, scheduled_task_tool):
        """Test executing without action parameter."""
        result = await scheduled_task_tool.execute()

        assert "Unknown action" in result or "required" in result


class TestScheduledTaskToolIntegration:
    """Integration tests for ScheduledTaskTool."""

    @pytest.mark.asyncio
    async def test_full_task_lifecycle(self, scheduled_task_tool, mock_scheduler):
        """Test complete task lifecycle."""
        # Add task
        mock_scheduler.add_task.return_value = "task_001"
        add_result = await scheduled_task_tool.execute(
            action="add",
            name="Lifecycle Task",
            trigger_type="interval",
            time="1m",
            message="Test",
        )
        assert "task_001" in add_result

        # Get task
        mock_scheduler.get_task.return_value = {
            "task_id": "task_001",
            "name": "Lifecycle Task",
            "status": "active",
            "trigger_type": "interval",
            "next_run_at": 1234567890,
            "last_run_at": None,
            "trigger_config": '{"interval": 60}',
            "message": "Test",
        }
        get_result = await scheduled_task_tool.execute(action="get", task_id="task_001")
        assert "task_001" in get_result

        # Pause task
        get_result = await scheduled_task_tool.execute(
            action="pause", task_id="task_001"
        )
        assert "paused" in get_result.lower()

        # Update mock to show paused status for resume test
        mock_scheduler.get_task.return_value = {
            "task_id": "task_001",
            "name": "Lifecycle Task",
            "status": "paused",
            "trigger_type": "interval",
            "next_run_at": 1234567890,
            "last_run_at": None,
            "trigger_config": '{"interval": 60}',
            "message": "Test",
        }

        # Resume task
        get_result = await scheduled_task_tool.execute(
            action="resume", task_id="task_001"
        )
        assert "resumed" in get_result.lower()

        # Update mock to show active status for cancel test
        mock_scheduler.get_task.return_value = {
            "task_id": "task_001",
            "name": "Lifecycle Task",
            "status": "active",
            "trigger_type": "interval",
            "next_run_at": 1234567890,
            "last_run_at": None,
            "trigger_config": '{"interval": 60}',
            "message": "Test",
        }

        # Cancel task
        get_result = await scheduled_task_tool.execute(
            action="cancel", task_id="task_001"
        )
        assert "cancelled" in get_result.lower()

    @pytest.mark.asyncio
    async def test_multiple_tasks_management(self, scheduled_task_tool, mock_scheduler):
        """Test managing multiple tasks."""
        # Add multiple tasks
        for i in range(3):
            mock_scheduler.add_task.return_value = f"task_{i:03d}"
            await scheduled_task_tool.execute(
                action="add",
                name=f"Task {i}",
                trigger_type="interval",
                time=f"{i+1}m",
                message=f"Message {i}",
            )

        # List tasks
        mock_scheduler.db.get_all_tasks.return_value = [
            {
                "task_id": f"task_{i:03d}",
                "name": f"Task {i}",
                "status": "active",
                "trigger_type": "interval",
                "next_run_at": 1234567890 + i * 100,
                "trigger_config": f'{{"interval": {(i+1)*60}}}',
                "message": f"Message {i}",
            }
            for i in range(3)
        ]
        list_result = await scheduled_task_tool.execute(action="list")

        assert "task_000" in list_result
        assert "task_001" in list_result
        assert "task_002" in list_result
