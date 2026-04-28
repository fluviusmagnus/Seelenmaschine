from pathlib import Path

from texts import ApprovalTexts, EventTexts, TelegramTexts, ToolTexts


def test_telegram_user_error_text_includes_subject_and_details():
    text = TelegramTexts.user_error_text(
        scenario="scheduled_task",
        details="RuntimeError: boom",
        subject_label="Task",
        subject="Daily check",
    )

    assert "Sorry, an error occurred while processing a scheduled task." in text
    assert "Task: Daily check" in text
    assert "Details: RuntimeError: boom" in text


def test_approval_request_escapes_html_arguments():
    text = ApprovalTexts.request_approval(
        "shell<tool>",
        {"command": "echo <hello>"},
        "needs > approval",
    )

    assert "<code>shell&lt;tool&gt;</code>" in text
    assert "echo &lt;hello&gt;" in text
    assert "needs &gt; approval" in text


def test_scheduled_task_created_text_keeps_existing_shape():
    text = ToolTexts.ScheduledTask.task_created_once(
        task_id="task_001",
        name="Morning",
        trigger_at="2026-04-28 08:00:00",
        timezone_name="Europe/Berlin",
        message="Check the plan",
    )

    assert text.startswith("✓ Task created (Task ID: task_001)")
    assert "Type: One-time" in text
    assert "Timezone: Europe/Berlin" in text
    assert text.endswith("Message: Check the plan")


def test_file_event_and_scheduled_event_templates_are_centralized():
    file_text = EventTexts.received_file_event(
        file_type="document",
        original_name="report.pdf",
        saved_path="/tmp/report.pdf",
        mime_type="application/pdf",
        file_size=42,
        caption="for review",
    )
    scheduled_text = EventTexts.scheduled_task_event(
        task_message="Remind user to stretch",
        task_name="Stretch",
        task_id="task_123",
        trigger_time="2026-04-28 09:00:00",
    )

    assert "[File Event]" in file_text
    assert "Original filename: report.pdf" in file_text
    assert "Caption: for review" in file_text
    assert scheduled_text.startswith("[Scheduled Task]")
    assert "task_id: task_123" in scheduled_text


def test_sent_file_event_uses_path_name_and_platform():
    text = EventTexts.sent_file_event(
        sent_path=Path("/tmp/report.pdf"),
        delivery_method="document",
        saved_path="/tmp/report.pdf",
        platform_label="telegram",
        mime_type="application/pdf",
    )

    assert "[System Event] Assistant has sent a file via telegram." in text
    assert "Filename: report.pdf" in text
