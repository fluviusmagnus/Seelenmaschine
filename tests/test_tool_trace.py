import json
from pathlib import Path

import pytest

from tools.tool_trace import ToolTraceQueryTool, ToolTraceStore


def test_tool_trace_store_query_defaults_to_current_session_reverse_order(tmp_path):
    store = ToolTraceStore(tmp_path)

    store.append_trace(
        session_id=1,
        tool_name="read_file",
        arguments={"file_path": "a.txt"},
        result="result-a",
        status="success",
        duration_ms=10,
        approval_required=False,
        approved_by_user=False,
    )
    store.append_trace(
        session_id=2,
        tool_name="read_file",
        arguments={"file_path": "b.txt"},
        result="result-b",
        status="success",
        duration_ms=11,
        approval_required=False,
        approved_by_user=False,
    )
    store.append_trace(
        session_id=1,
        tool_name="write_file",
        arguments={"file_path": "c.txt"},
        result="result-c",
        status="success",
        duration_ms=12,
        approval_required=False,
        approved_by_user=False,
    )

    result = store.query_records(current_session_id=1)

    assert "Found 2 tool trace(s)." in result
    assert "Tool: write_file" in result
    assert "Tool: read_file" in result
    assert result.index("Tool: write_file") < result.index("Tool: read_file")
    assert "result-b" not in result


def test_tool_trace_store_can_return_full_result_by_trace_id(tmp_path):
    store = ToolTraceStore(tmp_path)
    trace_id = store.append_trace(
        session_id=1,
        tool_name="read_file",
        arguments={"file_path": "src/llm/client.py"},
        result="x" * 900,
        status="success",
        duration_ms=33,
        approval_required=False,
        approved_by_user=False,
    )

    result = store.query_records(
        current_session_id=1,
        trace_id=trace_id,
        include_full_result=True,
    )

    assert f"trace_id={trace_id}" in result
    assert "Result preview:" in result
    assert "Result full:" in result
    assert "Has full result: yes" in result


def test_tool_trace_store_prunes_old_records_on_session_end(tmp_path):
    store = ToolTraceStore(tmp_path, max_records=100)

    for idx in range(105):
        store.append_trace(
            session_id=1,
            tool_name="tool",
            arguments={"index": idx},
            result=f"result-{idx}",
            status="success",
            duration_ms=1,
            approval_required=False,
            approved_by_user=False,
        )

    store.prune_to_max_records()

    lines = (tmp_path / "tool_traces.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 100
    first_record = json.loads(lines[0])
    last_record = json.loads(lines[-1])
    assert first_record["arguments_full"] == '{"index": 5}'
    assert last_record["arguments_full"] == '{"index": 104}'


@pytest.mark.asyncio
async def test_tool_trace_query_tool_defaults_and_full_result_toggle(tmp_path):
    store = ToolTraceStore(tmp_path)
    store.append_trace(
        session_id=7,
        tool_name="grep_search",
        arguments={"query": "foo"},
        result="line1\nline2\nline3",
        status="success",
        duration_ms=20,
        approval_required=False,
        approved_by_user=False,
    )

    tool = ToolTraceQueryTool(store, lambda: 7)

    preview_only = await tool.execute()
    assert "Found 1 tool trace(s)." in preview_only
    assert "Result preview:" in preview_only
    assert "Result full:" not in preview_only

    with_full = await tool.execute(include_full_result=True)
    assert "Result full:" in with_full
