import json

import pytest
from unittest.mock import AsyncMock, Mock, patch

from memory.manager import MemoryManager
from core.database import DatabaseManager
from memory.vector_retriever import RetrievedSummary, RetrievedConversation
from llm.embedding import EmbeddingClient
from llm.reranker import RerankerClient


@pytest.fixture
def mock_db():
    """Create mock DatabaseManager."""
    db = Mock(DatabaseManager)
    db.get_active_session.return_value = None
    db.create_session.return_value = 1
    return db


@pytest.fixture
def mock_embedding_client():
    """Create mock EmbeddingClient."""
    client = Mock(EmbeddingClient)
    client.get_embedding_async = AsyncMock(return_value=[0.1] * 1536)
    return client


@pytest.fixture
def mock_reranker_client():
    """Create mock RerankerClient."""
    client = Mock(RerankerClient)
    client.is_enabled.return_value = False
    return client


@pytest.fixture
def memory_manager(mock_db, mock_embedding_client, mock_reranker_client):
    """Create MemoryManager with mock dependencies."""
    return MemoryManager(
        db=mock_db,
        embedding_client=mock_embedding_client,
        reranker_client=mock_reranker_client,
    )


def make_seele_data():
    """Return a complete minimal seele.json payload for update tests."""
    return {
        "bot": {
            "name": "TestBot",
            "gender": "",
            "birthday": "",
            "role": "",
            "appearance": "",
            "likes": [],
            "dislikes": [],
            "language_style": {"description": "", "examples": []},
            "personality": {"mbti": "", "description": "", "worldview_and_values": ""},
            "emotions": {"long_term": "", "short_term": []},
            "needs": {"long_term": "", "short_term": []},
            "relationship_with_user": "",
        },
        "user": {
            "name": "TestUser",
            "gender": "",
            "birthday": "",
            "location": "",
            "personal_facts": [],
            "abilities": [],
            "likes": [],
            "dislikes": [],
            "personality": {"mbti": "", "description": "", "worldview_and_values": ""},
            "emotions": {"long_term": "", "short_term": []},
            "needs": {"long_term": "", "short_term": []},
        },
        "memorable_events": {},
        "commands_and_agreements": [],
    }


class TestMemoryManager:
    """Test MemoryManager functionality."""

    def test_initialization(self, memory_manager):
        """Test memory manager initializes correctly."""
        assert memory_manager.db is not None
        assert memory_manager.embedding_client is not None
        assert memory_manager.reranker_client is not None
        assert memory_manager.context_window is not None
        assert memory_manager.retriever is not None

    def test_ensure_active_session_creates_session(self, memory_manager, mock_db):
        """Test that ensure_active_session creates a session if none exists."""
        mock_db.get_active_session.return_value = None
        memory_manager._ensure_active_session()
        assert mock_db.create_session.called

    def test_get_current_session_id(self, memory_manager, mock_db):
        """Test getting current session ID."""
        mock_db.get_active_session.return_value = {"session_id": 5}
        session_id = memory_manager.get_current_session_id()
        assert session_id == 5

    def test_get_current_session_id_no_session(self, memory_manager, mock_db):
        """Test getting session ID raises error when no active session."""
        mock_db.get_active_session.return_value = None
        with pytest.raises(RuntimeError):
            memory_manager.get_current_session_id()

    @pytest.mark.asyncio
    async def test_new_session(self, memory_manager, mock_db):
        """Test creating a new session."""
        mock_db.get_active_session.return_value = {"session_id": 1}
        new_id = await memory_manager.new_session_async()
        assert mock_db.close_session.called
        assert mock_db.create_session.called
        assert new_id == 1

    @pytest.mark.asyncio
    async def test_new_session_with_remaining_messages(self, memory_manager, mock_db):
        """Test creating new session summarizes remaining messages."""
        mock_db.get_active_session.return_value = {"session_id": 1}
        mock_db.insert_summary.return_value = 10

        # Add some messages to context window
        memory_manager.context_window.add_message("user", "Hello", timestamp=100)
        memory_manager.context_window.add_message("assistant", "Hi there", timestamp=130)
        memory_manager.context_window.add_message("user", "How are you?", timestamp=160)

        with patch.object(
            memory_manager,
            "_generate_summary_async",
            new=AsyncMock(return_value="Final summary"),
        ) as mock_summary:
            with patch.object(
                memory_manager,
                "_update_long_term_memory_async",
                new=AsyncMock(return_value=True),
            ) as mock_update_ltm:
                await memory_manager.new_session_async()

                # Verify summary was created for remaining messages
                assert mock_summary.await_count
                assert mock_db.insert_summary.called
                assert mock_db.insert_summary.call_args.kwargs["first_timestamp"] == 100
                assert mock_db.insert_summary.call_args.kwargs["last_timestamp"] == 160

                # Verify long-term memory was updated with the remaining messages
                assert mock_update_ltm.await_count
                update_call_args = mock_update_ltm.await_args.args
                assert update_call_args[0] == 10  # summary_id
                assert len(update_call_args[1]) == 3  # 3 remaining messages

    @pytest.mark.asyncio
    async def test_new_session_ignores_scheduled_task_messages_in_summary(self, memory_manager, mock_db):
        """Scheduled-task trigger messages should not pollute final summary input."""
        mock_db.get_active_session.return_value = {"session_id": 1}
        mock_db.insert_summary.return_value = 10
        mock_db.insert_conversation.return_value = 20

        memory_manager.context_window.add_message("user", "Hello", timestamp=100)
        await memory_manager.add_context_message_async(
            "[Scheduled Task Trigger]\n提醒喝水",
            role="system",
            message_type="scheduled_task",
            include_in_turn_count=False,
            include_in_summary=False,
            embedding=None,
        )
        memory_manager.context_window.add_message("assistant", "Hi there", timestamp=130)

        with patch.object(
            memory_manager,
            "_generate_summary_async",
            new=AsyncMock(return_value="Final summary"),
        ) as mock_summary:
            with patch.object(
                memory_manager,
                "_update_long_term_memory_async",
                new=AsyncMock(return_value=True),
            ):
                await memory_manager.new_session_async()

        summarized_messages = mock_summary.await_args.args[0]
        assert [message.text for message in summarized_messages] == ["Hello", "Hi there"]
        assert mock_db.close_session.called
        assert mock_db.create_session.called

    @pytest.mark.asyncio
    async def test_new_session_no_existing(self, memory_manager, mock_db):
        """Test creating new session when none exists."""
        mock_db.get_active_session.return_value = None
        await memory_manager.new_session_async()
        assert not mock_db.close_session.called
        assert mock_db.create_session.called

    def test_reset_session(self, memory_manager, mock_db):
        """Test resetting current session."""
        mock_db.get_active_session.return_value = {"session_id": 1}
        with patch.object(memory_manager.seele, "restore_session_snapshot") as mock_restore:
            with patch.object(memory_manager.seele, "capture_session_snapshot") as mock_capture:
                memory_manager.reset_session()
        assert mock_db.delete_session.called
        assert mock_db.create_session.called
        mock_restore.assert_called_once_with(1)
        mock_capture.assert_called_once()

    @pytest.mark.asyncio
    async def test_add_user_message(self, memory_manager, mock_db):
        """Test adding user message."""
        mock_db.get_active_session.return_value = {"session_id": 1}
        mock_db.insert_conversation.return_value = 10

        conv_id, embedding = await memory_manager.add_user_message_async("Hello")

        assert conv_id == 10
        assert len(embedding) == 1536
        assert mock_db.insert_conversation.called
        assert memory_manager.context_window.get_total_message_count() == 1

    @pytest.mark.asyncio
    async def test_add_assistant_message(self, memory_manager, mock_db, monkeypatch):
        """Test adding assistant message."""
        # Mock Config values using monkeypatch
        from core.config import Config

        monkeypatch.setattr(Config, "CONTEXT_WINDOW_TRIGGER_SUMMARY", 100)

        mock_db.get_active_session.return_value = {"session_id": 1}
        mock_db.insert_conversation.return_value = 11

        conv_id, summary_id = await memory_manager.add_assistant_message_async(
            "Response"
        )

        assert conv_id == 11
        assert mock_db.insert_conversation.called

    @pytest.mark.asyncio
    async def test_add_assistant_message_triggers_summary(
        self, memory_manager, mock_db, monkeypatch
    ):
        """Test that adding assistant message triggers summary when threshold reached."""
        # Mock Config values
        from core.config import Config

        monkeypatch.setattr(Config, "CONTEXT_WINDOW_TRIGGER_SUMMARY", 24)
        monkeypatch.setattr(Config, "CONTEXT_WINDOW_KEEP_MIN", 12)

        mock_db.get_active_session.return_value = {"session_id": 1}
        mock_db.insert_conversation.return_value = 11
        mock_db.insert_summary.return_value = 1

        # Add exactly 24 messages to trigger summary
        for i in range(24):
            memory_manager.context_window.add_message(
                "user" if i % 2 == 0 else "assistant",
                f"Message {i}",
                timestamp=1000 + i * 100,
            )

        # add_assistant_message 本身不再自动触发 summary，需显式执行 summary check
        with patch.object(
            memory_manager,
            "_generate_summary_async",
            new=AsyncMock(return_value="Test summary"),
        ):
            with patch.object(
                memory_manager,
                "_generate_memory_update_async",
                new=AsyncMock(return_value='{"user": {"name": "Test"}}'),
            ) as mock_memory_update:
                with patch.object(
                    memory_manager,
                    "update_long_term_memory_async",
                    new=AsyncMock(return_value=True),
                ):
                    conv_id, summary_id = await memory_manager.add_assistant_message_async(
                        "Response"
                    )
                    summary_id, summarized_messages = (
                        await memory_manager._check_and_create_summary_async()
                    )
                    if summary_id is not None and summarized_messages is not None:
                        await memory_manager._update_long_term_memory_async(
                            summary_id, summarized_messages
                        )

                    assert summary_id is not None
                    assert mock_db.insert_summary.called
                    assert mock_db.insert_summary.call_args.kwargs["first_timestamp"] == 1000
                    assert mock_db.insert_summary.call_args.kwargs["last_timestamp"] == 2100

                    # Verify that _generate_memory_update was called with the correct messages
                    # It should be called with the 12 messages that were summarized (the earliest ones)
                    assert mock_memory_update.await_count
                    called_messages = mock_memory_update.await_args.args[0]

                    # The first 12 messages should have been used for the summary and memory update
                    assert len(called_messages) == 12
                    assert called_messages[0].text == "Message 0"
                    assert called_messages[11].text == "Message 11"

    @pytest.mark.asyncio
    async def test_process_user_input(self, memory_manager):
        """Test processing user input retrieves related memories."""
        summaries = [
            RetrievedSummary(
                summary_id=1,
                session_id=1,
                summary="Summary 1",
                first_timestamp=100,
                last_timestamp=200,
                score=0.5,
            )
        ]
        conversations = [
            RetrievedConversation(
                conversation_id=1,
                session_id=1,
                timestamp=150,
                role="user",
                text="Test",
                score=0.5,
            )
        ]

        with patch.object(
            memory_manager.retriever,
            "retrieve_related_memories_async",
            new=AsyncMock(return_value=(summaries, conversations)),
        ):
            with patch.object(
                memory_manager.retriever,
                "format_summaries_for_prompt",
                return_value=["Formatted Summary 1"],
            ):
                with patch.object(
                    memory_manager.retriever,
                    "format_conversations_for_prompt",
                    return_value=["Formatted Conv 1"],
                ):
                    formatted_summaries, formatted_convs = (
                        await memory_manager.process_user_input_async("Hello")
                    )

                    assert len(formatted_summaries) == 1
                    assert len(formatted_convs) == 1

    def test_get_context_messages(self, memory_manager):
        """Test getting context messages."""
        memory_manager.context_window.add_message("user", "Hello")
        memory_manager.context_window.add_message("assistant", "Hi")

        context = memory_manager.get_context_messages()
        assert len(context) == 2
        assert context[0]["role"] == "user"
        assert context[0]["content"] == "Hello"  # Changed from "text" to "content"

    def test_get_recent_summaries(self, memory_manager, monkeypatch):
        """Test getting recent summaries."""
        from core.config import Config

        monkeypatch.setattr(Config, "RECENT_SUMMARIES_MAX", 3)

        memory_manager.context_window.add_summary("Summary 1", summary_id=1)
        memory_manager.context_window.add_summary("Summary 2", summary_id=2)

        summaries = memory_manager.get_recent_summaries()
        assert len(summaries) == 2
        assert summaries[0] == "Summary 1"

    @pytest.mark.asyncio
    async def test_update_long_term_memory_invalid_json(self, memory_manager):
        """Test update_long_term_memory returns False for invalid JSON."""
        result = await memory_manager.update_long_term_memory_async(1, "not json")
        assert result is False

    @pytest.mark.asyncio
    async def test_update_long_term_memory_retries_patch_with_previous_patch_and_reason(
        self, memory_manager
    ):
        """A rejected patch should be retried with the rejected patch and reason."""
        messages = []
        bad_patch = json.dumps(
            [{"op": "replace", "path": "/user/likes", "value": "likes hiking"}]
        )
        fixed_patch = json.dumps(
            [{"op": "add", "path": "/user/likes/-", "value": "hiking"}]
        )

        with patch.object(
            memory_manager.seele,
            "_apply_generated_patch_async",
            new=AsyncMock(side_effect=[False, True]),
        ) as mock_apply:
            memory_manager.seele._last_patch_error = "/user/likes expects array"
            with patch.object(
                memory_manager.seele,
                "generate_memory_update_async",
                new=AsyncMock(return_value=fixed_patch),
            ) as mock_retry:
                result = await memory_manager.update_long_term_memory_async(
                    1, bad_patch, messages
                )

        assert result is True
        mock_retry.assert_awaited_once_with(
            messages,
            1,
            previous_attempt=bad_patch,
            previous_error="/user/likes expects array",
        )
        assert mock_apply.await_args_list[1].args[1] == json.loads(fixed_patch)

    @pytest.mark.asyncio
    async def test_fallback_retry_reuses_previous_failed_output(self, memory_manager):
        """Retry should pass the raw failed generation output into the next attempt."""
        memory_manager.seele.validate_seele_structure = Mock(return_value=True)
        memory_manager.seele.clean_json_response = Mock(side_effect=lambda value: value)
        write_complete_json = AsyncMock()

        messages = []
        generate_complete_json = AsyncMock(
            side_effect=[
                '{"bot": {oops}}',
                '{"bot": {}, "user": {}, "memorable_events": {}, "commands_and_agreements": []}',
            ]
        )

        result = await memory_manager.seele._retry_complete_json_generation_async(
            summary_id=1,
            messages=messages,
            error_message="patch failed",
            generate_complete_json=generate_complete_json,
            write_complete_json=write_complete_json,
        )

        assert result is True
        assert generate_complete_json.await_args_list[0].args == (
            messages,
            "patch failed",
            1,
            None,
        )
        assert generate_complete_json.await_args_list[1].args == (
            messages,
            memory_manager.seele._build_parse_retry_message(
                json.JSONDecodeError(
                    "Expecting property name enclosed in double quotes",
                    '{"bot": {oops}}',
                    9,
                )
            ),
            1,
            '{"bot": {oops}}',
        )


def test_build_event_id_uses_short_slug_and_hash():
    """Memorable event ids should be concise and include a stable short hash."""
    from memory.seele import _build_event_id

    event_id = _build_event_id(
        "2026-03-30",
        "Project commitment with Seele for a very long collaboration plan",
        set(),
    )

    assert event_id.startswith("evt_20260330_project_commitme_")
    assert len(event_id.split("_")) >= 4


def test_build_event_id_falls_back_to_event_slug_for_non_ascii_details():
    """When details have no ASCII slug content, ids should still be compact and valid."""
    from memory.seele import _build_event_id

    event_id = _build_event_id("2026-03-30", "！！！今天！！！", set())

    assert event_id.startswith("evt_20260330_event_")


def test_apply_seele_json_patch_rejects_array_field_replaced_with_string_with_reason(tmp_path):
    """Schema validation should reject patch operations that make array fields strings."""
    from memory.seele import apply_seele_json_patch

    data = make_seele_data()

    result = apply_seele_json_patch(
        cache=data,
        patch_operations=[
            {"op": "replace", "path": "/user/likes", "value": "likes hiking"}
        ],
        seele_path=tmp_path / "seele.json",
        load_from_disk=lambda: data,
        logger=Mock(),
    )

    assert result.success is False
    assert result.data == data
    assert "/user/likes" in result.reason
    assert "array" in result.reason


def test_apply_seele_json_patch_accepts_array_append_string(tmp_path):
    """Appending a string to a string-array field should remain valid."""
    from memory.seele import apply_seele_json_patch

    data = make_seele_data()

    result = apply_seele_json_patch(
        cache=data,
        patch_operations=[{"op": "add", "path": "/user/likes/-", "value": "hiking"}],
        seele_path=tmp_path / "seele.json",
        load_from_disk=lambda: data,
        logger=Mock(),
    )

    assert result.success is True
    assert result.data["user"]["likes"] == ["hiking"]


def test_apply_seele_json_patch_rejects_invalid_memorable_event_with_reason(tmp_path):
    """Memorable event patch values should be schema-checked before writing."""
    from memory.seele import apply_seele_json_patch

    data = make_seele_data()

    result = apply_seele_json_patch(
        cache=data,
        patch_operations=[
            {
                "op": "add",
                "path": "/memorable_events/evt_20260506_bad",
                "value": {"date": "2026-05-06", "importance": 9, "details": "Bad"},
            }
        ],
        seele_path=tmp_path / "seele.json",
        load_from_disk=lambda: data,
        logger=Mock(),
    )

    assert result.success is False
    assert "importance" in result.reason


def test_build_json_patch_diff_replaces_arrays_instead_of_appending():
    """Complete JSON diffs should replace arrays instead of appending duplicate values."""
    from memory.seele import build_json_patch_diff

    old = {"bot": {"likes": ["old"]}, "memorable_events": {}}
    new = {"bot": {"likes": ["new"]}, "memorable_events": {}}

    patch = build_json_patch_diff(old, new)

    assert patch == [{"op": "replace", "path": "/bot/likes", "value": ["new"]}]


def test_build_json_patch_diff_adds_new_nested_object_at_parent_path():
    """Complete JSON diffs should add a new nested object at the missing parent path."""
    from memory.seele import build_json_patch_diff

    event = {"date": "2026-05-06", "importance": 3, "details": "New event"}
    old = {"memorable_events": {}}
    new = {"memorable_events": {"evt_20260506_new": event}}

    patch = build_json_patch_diff(old, new)

    assert patch == [
        {"op": "add", "path": "/memorable_events/evt_20260506_new", "value": event}
    ]


def test_validate_compaction_candidate_rejects_invalid_event_payload(memory_manager):
    """Seele compaction candidates must preserve memorable event schema."""
    candidate = {
        "personal_facts": ["Stable fact"],
        "memorable_events": {
            "evt_20260506_bad": {
                "date": "2026-05-06",
                "importance": 9,
                "details": "Bad importance",
            }
        },
    }

    assert memory_manager.seele._validate_compaction_candidate(candidate) is not None


@pytest.mark.asyncio
async def test_seele_compaction_retries_invalid_candidate_with_previous_output_and_reason(
    memory_manager,
):
    """Invalid seele compaction output should be retried before deterministic fallback."""
    data = make_seele_data()
    data["user"]["personal_facts"] = [f"Fact {i}" for i in range(21)]
    invalid_response = json.dumps(
        {
            "personal_facts": data["user"]["personal_facts"][:20],
            "memorable_events": {
                "evt_20260506_bad": {
                    "date": "2026-05-06",
                    "importance": 9,
                    "details": "Bad",
                }
            },
        }
    )
    valid_response = json.dumps(
        {
            "personal_facts": data["user"]["personal_facts"][:20],
            "memorable_events": {},
        }
    )
    fake_client = Mock()
    fake_client.generate_seele_compaction_async = AsyncMock(
        side_effect=[invalid_response, valid_response]
    )
    fake_client.close_async = AsyncMock()

    with patch("llm.chat_client.LLMClient", return_value=fake_client):
        result = await memory_manager.seele._compact_personal_facts_and_events_async(data)

    assert len(result["user"]["personal_facts"]) == 20
    retry_kwargs = fake_client.generate_seele_compaction_async.await_args_list[1].kwargs
    assert retry_kwargs["previous_attempt"] == invalid_response
    assert retry_kwargs["previous_error"] is not None
    assert len(retry_kwargs["previous_error"]) > 0
    assert "payload" in retry_kwargs["previous_error"] or "event" in retry_kwargs["previous_error"]


def test_parse_short_term_compaction_rejects_unknown_path(memory_manager):
    """Short-term compaction output must only target known long_term paths."""
    response = json.dumps({"/user/likes/long_term": "invalid path"})

    with pytest.raises(ValueError, match="Unexpected short-term compaction path"):
        memory_manager.seele._parse_short_term_compaction_response(
            response, required_paths={"/bot/emotions/long_term"}
        )


def test_parse_short_term_compaction_rejects_overlong_value(memory_manager):
    """Short-term compaction long_term values must obey the hard length limit."""
    from memory.seele import MAX_STRING_LENGTH_HARD

    response = json.dumps({"/bot/emotions/long_term": "X" * (MAX_STRING_LENGTH_HARD + 1)})

    with pytest.raises(ValueError, match="exceeds"):
        memory_manager.seele._parse_short_term_compaction_response(
            response, required_paths={"/bot/emotions/long_term"}
        )


def test_build_event_id_adds_suffix_on_collision():
    """Colliding ids should receive numeric suffixes after the short hash form."""
    from memory.seele import _build_event_id

    used_ids: set[str] = set()
    first_id = _build_event_id("2026-03-30", "same detail", used_ids)
    second_id = _build_event_id("2026-03-30", "same detail", used_ids)

    assert second_id == f"{first_id}_2"


def test_fallback_compact_personal_facts_deduplicates_and_limits():
    """Fallback personal-fact compaction should deduplicate and truncate deterministically."""
    from memory.seele import fallback_compact_personal_facts

    facts = [" Loves Python ", "loves python", "Has a cat"] + [
        f"Fact {i}" for i in range(30)
    ]

    compacted = fallback_compact_personal_facts(facts, limit=3)

    assert compacted == ["Loves Python", "Has a cat", "Fact 0"]


def test_fallback_compact_memorable_events_prioritizes_importance_then_date():
    """Fallback memorable-event compaction should keep strongest events first."""
    from memory.seele import fallback_compact_memorable_events

    events = {
        "evt_low": {"date": "2026-01-01", "importance": 1, "details": "low"},
        "evt_mid_old": {"date": "2026-01-01", "importance": 3, "details": "mid old"},
        "evt_high": {"date": "2026-01-02", "importance": 5, "details": "high"},
        "evt_mid_new": {"date": "2026-02-01", "importance": 3, "details": "mid new"},
    }

    compacted = fallback_compact_memorable_events(events, limit=2)

    assert set(compacted.keys()) == {"evt_high", "evt_mid_old"}


def test_normalize_seele_data_migrates_short_term_strings_to_lists():
    """Legacy short-term emotion/need strings should migrate to string lists."""
    from memory.seele import normalize_seele_data
    from utils.logger import get_logger

    data = {
        "bot": {
            "emotions": {"long_term": "", "short_term": "Feeling focused"},
            "needs": {"long_term": "", "short_term": ""},
        },
        "user": {
            "location": "",
            "emotions": {"long_term": "", "short_term": [" tired ", "", 123]},
            "needs": {"long_term": "", "short_term": "Needs quiet"},
        },
        "memorable_events": {},
    }

    normalized, changed = normalize_seele_data(data, get_logger())

    assert changed is True
    assert normalized["bot"]["emotions"]["short_term"] == ["Feeling focused"]
    assert normalized["bot"]["needs"]["short_term"] == []
    assert normalized["user"]["emotions"]["short_term"] == ["tired"]
    assert normalized["user"]["needs"]["short_term"] == ["Needs quiet"]


def test_validate_seele_structure_rejects_non_list_short_term(memory_manager):
    """Current schema requires short-term emotion/need fields to be lists."""
    data = {
        "bot": {
            "name": "TestBot",
            "gender": "",
            "birthday": "",
            "role": "",
            "appearance": "",
            "likes": [],
            "dislikes": [],
            "language_style": {"description": "", "examples": []},
            "personality": {"mbti": "", "description": "", "worldview_and_values": ""},
            "emotions": {"long_term": "", "short_term": "legacy string"},
            "needs": {"long_term": "", "short_term": []},
            "relationship_with_user": "",
        },
        "user": {
            "name": "TestUser",
            "gender": "",
            "birthday": "",
            "location": "",
            "personal_facts": [],
            "abilities": [],
            "likes": [],
            "dislikes": [],
            "personality": {"mbti": "", "description": "", "worldview_and_values": ""},
            "emotions": {"long_term": "", "short_term": []},
            "needs": {"long_term": "", "short_term": []},
        },
        "memorable_events": {},
        "commands_and_agreements": [],
    }

    assert memory_manager.seele.validate_seele_structure(data) is False


@pytest.mark.asyncio
async def test_apply_generated_patch_compacts_when_memory_exceeds_limit(memory_manager):
    """Successful patch application should trigger follow-up compaction when needed."""
    from memory.seele import PERSONAL_FACTS_LIMIT

    oversized_memory = {
        "bot": {"name": "TestBot"},
        "user": {
            "name": "TestUser",
            "location": "",
            "personal_facts": [f"Fact {i}" for i in range(PERSONAL_FACTS_LIMIT + 2)],
        },
        "memorable_events": {},
        "commands_and_agreements": [],
    }
    compacted_memory = {
        **oversized_memory,
        "user": {
            **oversized_memory["user"],
            "personal_facts": oversized_memory["user"]["personal_facts"][:PERSONAL_FACTS_LIMIT],
        },
    }

    with patch("prompts.runtime.update_seele_json", return_value=True):
        with patch.object(memory_manager.seele, "get_long_term_memory", return_value=oversized_memory):
            with patch.object(
                memory_manager.seele,
                "_compact_overflowing_memory_async",
                new=AsyncMock(return_value=compacted_memory),
            ) as mock_compact:
                with patch.object(
                    memory_manager.seele,
                    "_write_complete_seele_json_async",
                    new=AsyncMock(),
                ) as mock_write:
                    result = await memory_manager.seele._apply_generated_patch_async(
                        1,
                        [],
                        None,
                    )

    assert result is True
    mock_compact.assert_awaited_once_with(oversized_memory)
    mock_write.assert_awaited_once_with(compacted_memory)


@pytest.mark.asyncio
async def test_short_term_overflow_triggers_compaction_after_patch(memory_manager):
    """Successful patches should compact when any short-term list exceeds 12 items."""
    from memory.seele import SHORT_TERM_MEMORY_KEEP_AFTER_COMPACTION, SHORT_TERM_MEMORY_LIMIT

    oversized_memory = {
        "bot": {
            "emotions": {
                "long_term": "",
                "short_term": [f"Bot emotion {i}" for i in range(SHORT_TERM_MEMORY_LIMIT + 1)],
            },
            "needs": {"long_term": "", "short_term": []},
        },
        "user": {
            "personal_facts": [],
            "emotions": {"long_term": "", "short_term": []},
            "needs": {"long_term": "", "short_term": []},
        },
        "memorable_events": {},
        "commands_and_agreements": [],
    }
    compacted_memory = {
        **oversized_memory,
        "bot": {
            **oversized_memory["bot"],
            "emotions": {
                "long_term": "Older short-term emotions were summarized.",
                "short_term": oversized_memory["bot"]["emotions"]["short_term"][-SHORT_TERM_MEMORY_KEEP_AFTER_COMPACTION:],
            },
        },
    }

    with patch("prompts.runtime.update_seele_json", return_value=True):
        with patch.object(memory_manager.seele, "get_long_term_memory", return_value=oversized_memory):
            with patch.object(
                memory_manager.seele,
                "_compact_overflowing_memory_async",
                new=AsyncMock(return_value=compacted_memory),
            ) as mock_compact:
                with patch.object(
                    memory_manager.seele,
                    "_write_complete_seele_json_async",
                    new=AsyncMock(),
                ) as mock_write:
                    result = await memory_manager.seele._apply_generated_patch_async(1, [], None)

    assert result is True
    mock_compact.assert_awaited_once_with(oversized_memory)
    mock_write.assert_awaited_once_with(compacted_memory)


@pytest.mark.asyncio
async def test_compact_overflowing_memory_uses_fallback_for_invalid_llm_output(memory_manager):
    """Invalid compaction output should fall back to deterministic truncation."""
    from memory.seele import PERSONAL_FACTS_LIMIT

    oversized_memory = {
        "bot": {
            "name": "TestBot",
            "gender": "",
            "birthday": "",
            "role": "",
            "appearance": "",
            "likes": [],
            "dislikes": [],
            "language_style": {"description": "", "examples": []},
            "personality": {"mbti": "", "description": "", "worldview_and_values": ""},
            "emotions": {"long_term": "", "short_term": []},
            "needs": {"long_term": "", "short_term": []},
            "relationship_with_user": "",
        },
        "user": {
            "name": "TestUser",
            "gender": "",
            "birthday": "",
            "location": "",
            "personal_facts": [f"Fact {i}" for i in range(PERSONAL_FACTS_LIMIT + 5)],
            "abilities": [],
            "likes": [],
            "dislikes": [],
            "personality": {"mbti": "", "description": "", "worldview_and_values": ""},
            "emotions": {"long_term": "", "short_term": []},
            "needs": {"long_term": "", "short_term": []},
        },
        "memorable_events": {},
        "commands_and_agreements": [],
    }

    fake_client = Mock()
    fake_client.generate_seele_compaction_async = AsyncMock(
        return_value='{"personal_facts": [""], "memorable_events": {}}'
    )
    fake_client.close_async = AsyncMock()

    with patch("llm.chat_client.LLMClient", return_value=fake_client):
        compacted = await memory_manager.seele._compact_overflowing_memory_async(oversized_memory)

    assert len(compacted["user"]["personal_facts"]) == PERSONAL_FACTS_LIMIT
    assert compacted["user"]["personal_facts"] == oversized_memory["user"]["personal_facts"][:PERSONAL_FACTS_LIMIT]
    fake_client.close_async.assert_awaited_once()


@pytest.mark.asyncio
async def test_compact_overflowing_memory_accepts_short_term_llm_compaction(memory_manager):
    """Valid LLM compaction may merge old short-term items into long-term fields."""
    from memory.seele import SHORT_TERM_MEMORY_LIMIT, SHORT_TERM_MEMORY_KEEP_AFTER_COMPACTION

    short_terms = [f"Pressure note {i}" for i in range(SHORT_TERM_MEMORY_LIMIT + 1)]
    oversized_memory = {
        "bot": {
            "name": "TestBot",
            "gender": "",
            "birthday": "",
            "role": "",
            "appearance": "",
            "likes": [],
            "dislikes": [],
            "language_style": {"description": "", "examples": []},
            "personality": {"mbti": "", "description": "", "worldview_and_values": ""},
            "emotions": {"long_term": "Generally steady.", "short_term": short_terms},
            "needs": {"long_term": "", "short_term": []},
            "relationship_with_user": "",
        },
        "user": {
            "name": "TestUser",
            "gender": "",
            "birthday": "",
            "location": "",
            "personal_facts": [],
            "abilities": [],
            "likes": [],
            "dislikes": [],
            "personality": {"mbti": "", "description": "", "worldview_and_values": ""},
            "emotions": {"long_term": "", "short_term": []},
            "needs": {"long_term": "", "short_term": []},
        },
        "memorable_events": {},
        "commands_and_agreements": [],
    }
    candidate = {
        "personal_facts": [],
        "memorable_events": {},
        "bot": {
            "emotions": {
                "long_term": "Generally steady, with recent pressure now integrated.",
                "short_term": short_terms[-SHORT_TERM_MEMORY_KEEP_AFTER_COMPACTION:],
            },
            "needs": {"long_term": "", "short_term": []},
        },
        "user": {
            "emotions": {"long_term": "", "short_term": []},
            "needs": {"long_term": "", "short_term": []},
        },
    }

    short_term_compaction_response = json.dumps({
        "/bot/emotions/long_term": candidate["bot"]["emotions"]["long_term"],
    })
    fake_client = Mock()
    fake_client.generate_seele_compaction_async = AsyncMock(
        return_value=json.dumps(candidate)
    )
    fake_client.generate_short_term_compaction_async = AsyncMock(
        return_value=short_term_compaction_response
    )
    fake_client.close_async = AsyncMock()

    with patch("llm.chat_client.LLMClient", return_value=fake_client):
        compacted = await memory_manager.seele._compact_overflowing_memory_async(oversized_memory)

    assert compacted["bot"]["emotions"]["long_term"] == candidate["bot"]["emotions"]["long_term"]
    assert compacted["bot"]["emotions"]["short_term"] == short_terms[-SHORT_TERM_MEMORY_KEEP_AFTER_COMPACTION:]
    assert fake_client.close_async.call_count >= 1


@pytest.mark.asyncio
async def test_short_term_fallback_compaction_keeps_latest_four(memory_manager):
    """Fallback compaction should keep latest 4 short-term items after overflow."""
    from memory.seele import SHORT_TERM_MEMORY_KEEP_AFTER_COMPACTION, SHORT_TERM_MEMORY_LIMIT

    short_terms = [f"Need note {i}" for i in range(SHORT_TERM_MEMORY_LIMIT + 2)]
    oversized_memory = {
        "bot": {
            "name": "TestBot",
            "gender": "",
            "birthday": "",
            "role": "",
            "appearance": "",
            "likes": [],
            "dislikes": [],
            "language_style": {"description": "", "examples": []},
            "personality": {"mbti": "", "description": "", "worldview_and_values": ""},
            "emotions": {"long_term": "", "short_term": []},
            "needs": {"long_term": "Existing need.", "short_term": short_terms},
            "relationship_with_user": "",
        },
        "user": {
            "name": "TestUser",
            "gender": "",
            "birthday": "",
            "location": "",
            "personal_facts": [],
            "abilities": [],
            "likes": [],
            "dislikes": [],
            "personality": {"mbti": "", "description": "", "worldview_and_values": ""},
            "emotions": {"long_term": "", "short_term": []},
            "needs": {"long_term": "", "short_term": []},
        },
        "memorable_events": {},
        "commands_and_agreements": [],
    }

    fake_client = Mock()
    fake_client.generate_seele_compaction_async = AsyncMock(return_value="{}")
    fake_client.generate_short_term_compaction_async = AsyncMock(
        side_effect=RuntimeError("LLM unavailable")
    )
    fake_client.close_async = AsyncMock()

    with patch("llm.chat_client.LLMClient", return_value=fake_client):
        compacted = await memory_manager.seele._compact_overflowing_memory_async(oversized_memory)

    assert compacted["bot"]["needs"]["short_term"] == short_terms[-SHORT_TERM_MEMORY_KEEP_AFTER_COMPACTION:]
    assert "Existing need." in compacted["bot"]["needs"]["long_term"]
    assert "Need note 0" in compacted["bot"]["needs"]["long_term"]
    assert "Need note 9" in compacted["bot"]["needs"]["long_term"]
    fake_client.close_async.assert_awaited_once()


@pytest.mark.asyncio
async def test_write_complete_seele_json_async_compacts_with_async_fallback(
    memory_manager, tmp_path, monkeypatch
):
    """Async full writes should compact oversized memory without sync bridge calls."""
    from core.config import Config
    from memory.seele import PERSONAL_FACTS_LIMIT
    import prompts.runtime as prompts_runtime

    seele_path = tmp_path / "seele.json"
    monkeypatch.setattr(Config, "SEELE_JSON_PATH", seele_path)
    prompts_runtime._seele_json_cache = {}

    oversized_memory = {
        "bot": {
            "name": "TestBot",
            "gender": "",
            "birthday": "",
            "role": "",
            "appearance": "",
            "likes": [],
            "dislikes": [],
            "language_style": {"description": "", "examples": []},
            "personality": {"mbti": "", "description": "", "worldview_and_values": ""},
            "emotions": {"long_term": "", "short_term": []},
            "needs": {"long_term": "", "short_term": []},
            "relationship_with_user": "",
        },
        "user": {
            "name": "TestUser",
            "gender": "",
            "birthday": "",
            "location": "",
            "personal_facts": [f"Fact {i}" for i in range(PERSONAL_FACTS_LIMIT + 3)],
            "abilities": [],
            "likes": [],
            "dislikes": [],
            "personality": {"mbti": "", "description": "", "worldview_and_values": ""},
            "emotions": {"long_term": "", "short_term": []},
            "needs": {"long_term": "", "short_term": []},
        },
        "memorable_events": {},
        "commands_and_agreements": [],
    }
    fake_client = Mock()
    fake_client.generate_seele_compaction_async = AsyncMock(
        return_value='{"personal_facts": [""], "memorable_events": {}}'
    )
    fake_client.close_async = AsyncMock()

    with patch("llm.chat_client.LLMClient", return_value=fake_client):
        await memory_manager.seele._write_complete_seele_json_async(oversized_memory)

    saved = json.loads(seele_path.read_text(encoding="utf-8"))
    assert saved["user"]["personal_facts"] == oversized_memory["user"]["personal_facts"][:PERSONAL_FACTS_LIMIT]
    assert prompts_runtime._seele_json_cache == saved
    assert fake_client.generate_seele_compaction_async.await_count == 2
    fake_client.close_async.assert_awaited_once()


def test_collect_oversized_strings_finds_leaf_strings_exceeding_threshold():
    """Should return (path, value) for all leaf strings exceeding the threshold."""
    from memory.seele import _collect_oversized_strings

    data = {
        "bot": {
            "name": "TestBot",
            "personality": {"description": "A" * 501, "worldview_and_values": "short"},
            "emotions": {"long_term": "B" * 600, "short_term": ["ok"]},
            "needs": {"long_term": "brief", "short_term": ["X" * 501]},
        },
        "user": {
            "name": "TestUser",
            "emotions": {"long_term": "fine", "short_term": []},
            "needs": {"long_term": "", "short_term": []},
        },
        "memorable_events": {},
        "commands_and_agreements": [],
    }

    oversized = _collect_oversized_strings(data, 500)

    paths = {p for p, _ in oversized}
    assert "/bot/personality/description" in paths
    assert "/bot/emotions/long_term" in paths
    assert "/bot/needs/short_term/0" in paths
    assert all(len(v) > 500 for _, v in oversized)


def test_collect_oversized_strings_returns_empty_when_none_exceed_threshold():
    """Should return empty list when all strings are within limit."""
    from memory.seele import _collect_oversized_strings

    data = {"bot": {"name": "short"}, "user": {"name": "also_short"}}

    oversized = _collect_oversized_strings(data, 500)
    assert oversized == []


@pytest.mark.asyncio
async def test_collect_overflow_fields_detects_exceeding_short_term_lists(memory_manager):
    """Should identify which short_term lists exceed the limit."""
    from memory.seele import SHORT_TERM_MEMORY_LIMIT

    data = {
        "bot": {
            "emotions": {"long_term": "", "short_term": [f"e{i}" for i in range(SHORT_TERM_MEMORY_LIMIT + 3)]},
            "needs": {"long_term": "", "short_term": ["n1", "n2"]},
        },
        "user": {
            "emotions": {"long_term": "", "short_term": []},
            "needs": {"long_term": "", "short_term": [f"u{i}" for i in range(SHORT_TERM_MEMORY_LIMIT + 1)]},
        },
    }

    fields = memory_manager.seele._collect_overflow_fields(data)

    assert len(fields) == 2
    field_paths = {f["path"] for f in fields}
    assert "/bot/emotions" in field_paths
    assert "/user/needs" in field_paths


@pytest.mark.asyncio
async def test_compact_short_term_overflow_truncates_and_calls_llm(memory_manager):
    """Short-term compaction should truncate lists and call dedicated LLM prompt."""
    from memory.seele import SHORT_TERM_MEMORY_LIMIT, SHORT_TERM_MEMORY_KEEP_AFTER_COMPACTION

    short_terms = [f"Emotion {i}" for i in range(SHORT_TERM_MEMORY_LIMIT + 2)]
    data = {
        "bot": {
            "name": "TestBot",
            "gender": "",
            "birthday": "",
            "role": "",
            "appearance": "",
            "likes": [],
            "dislikes": [],
            "language_style": {"description": "", "examples": []},
            "personality": {"mbti": "", "description": "", "worldview_and_values": ""},
            "emotions": {"long_term": "Previously calm.", "short_term": short_terms},
            "needs": {"long_term": "", "short_term": []},
            "relationship_with_user": "",
        },
        "user": {
            "name": "TestUser",
            "gender": "",
            "birthday": "",
            "location": "",
            "personal_facts": [],
            "abilities": [],
            "likes": [],
            "dislikes": [],
            "personality": {"mbti": "", "description": "", "worldview_and_values": ""},
            "emotions": {"long_term": "", "short_term": []},
            "needs": {"long_term": "", "short_term": []},
        },
        "memorable_events": {},
        "commands_and_agreements": [],
    }

    new_long_term = "Synthesized calm with recent emotional depth."
    fake_llm_response = json.dumps({"/bot/emotions/long_term": new_long_term})

    fake_client = Mock()
    fake_client.generate_short_term_compaction_async = AsyncMock(return_value=fake_llm_response)
    fake_client.close_async = AsyncMock()

    with patch("llm.chat_client.LLMClient", return_value=fake_client):
        with patch("prompts.runtime.update_seele_json", return_value=True):
            result = await memory_manager.seele._compact_short_term_overflow_async(data)

    assert result["bot"]["emotions"]["short_term"] == short_terms[-SHORT_TERM_MEMORY_KEEP_AFTER_COMPACTION:]
    fake_client.generate_short_term_compaction_async.assert_awaited_once()
    fake_client.close_async.assert_awaited_once()


@pytest.mark.asyncio
async def test_compact_short_term_overflow_falls_back_on_llm_failure(memory_manager):
    """When LLM fails, short-term compaction should use deterministic fallback."""
    from memory.seele import SHORT_TERM_MEMORY_KEEP_AFTER_COMPACTION, SHORT_TERM_MEMORY_LIMIT

    short_terms = [f"Need {i}" for i in range(SHORT_TERM_MEMORY_LIMIT + 3)]
    data = {
        "bot": {
            "name": "TestBot",
            "gender": "",
            "birthday": "",
            "role": "",
            "appearance": "",
            "likes": [],
            "dislikes": [],
            "language_style": {"description": "", "examples": []},
            "personality": {"mbti": "", "description": "", "worldview_and_values": ""},
            "emotions": {"long_term": "", "short_term": []},
            "needs": {"long_term": "Existing need.", "short_term": short_terms},
            "relationship_with_user": "",
        },
        "user": {
            "name": "TestUser",
            "gender": "",
            "birthday": "",
            "location": "",
            "personal_facts": [],
            "abilities": [],
            "likes": [],
            "dislikes": [],
            "personality": {"mbti": "", "description": "", "worldview_and_values": ""},
            "emotions": {"long_term": "", "short_term": []},
            "needs": {"long_term": "", "short_term": []},
        },
        "memorable_events": {},
        "commands_and_agreements": [],
    }

    fake_client = Mock()
    fake_client.generate_short_term_compaction_async = AsyncMock(side_effect=Exception("LLM down"))
    fake_client.close_async = AsyncMock()

    with patch("llm.chat_client.LLMClient", return_value=fake_client):
        result = await memory_manager.seele._compact_short_term_overflow_async(data)

    assert "Existing need." in result["bot"]["needs"]["long_term"]
    assert len(result["bot"]["needs"]["short_term"]) == SHORT_TERM_MEMORY_KEEP_AFTER_COMPACTION
    fake_client.close_async.assert_awaited_once()


@pytest.mark.asyncio
async def test_compact_short_term_overflow_retries_with_previous_output_and_reason(memory_manager):
    """Invalid short-term compaction output should be retried with output and reason."""
    from memory.seele import SHORT_TERM_MEMORY_LIMIT

    short_terms = [f"Emotion {i}" for i in range(SHORT_TERM_MEMORY_LIMIT + 1)]
    data = make_seele_data()
    data["bot"]["emotions"]["short_term"] = short_terms

    invalid_response = json.dumps({"/bot/emotions/long_term": "X" * 301})
    valid_response = json.dumps({"/bot/emotions/long_term": "Summarized emotion."})
    fake_client = Mock()
    fake_client.generate_short_term_compaction_async = AsyncMock(
        side_effect=[invalid_response, valid_response]
    )
    fake_client.close_async = AsyncMock()

    with patch("llm.chat_client.LLMClient", return_value=fake_client):
        with patch("prompts.runtime.update_seele_json", return_value=True):
            await memory_manager.seele._compact_short_term_overflow_async(data)

    assert fake_client.generate_short_term_compaction_async.await_args_list[1].kwargs[
        "previous_attempt"
    ] == invalid_response
    assert "exceeds" in fake_client.generate_short_term_compaction_async.await_args_list[1].kwargs[
        "previous_error"
    ]


@pytest.mark.asyncio
async def test_compact_overflowing_memory_triggers_short_term_only_when_needed(memory_manager):
    """Per-section: only short_term overflow should trigger only short_term compaction."""
    from memory.seele import SHORT_TERM_MEMORY_LIMIT

    data = {
        "bot": {
            "name": "TestBot",
            "gender": "",
            "birthday": "",
            "role": "",
            "appearance": "",
            "likes": [],
            "dislikes": [],
            "language_style": {"description": "", "examples": []},
            "personality": {"mbti": "", "description": "", "worldview_and_values": ""},
            "emotions": {"long_term": "", "short_term": [f"e{i}" for i in range(SHORT_TERM_MEMORY_LIMIT + 1)]},
            "needs": {"long_term": "", "short_term": []},
            "relationship_with_user": "",
        },
        "user": {
            "name": "TestUser",
            "gender": "",
            "birthday": "",
            "location": "",
            "personal_facts": ["Just one fact"],
            "abilities": [],
            "likes": [],
            "dislikes": [],
            "personality": {"mbti": "", "description": "", "worldview_and_values": ""},
            "emotions": {"long_term": "", "short_term": []},
            "needs": {"long_term": "", "short_term": []},
        },
        "memorable_events": {},
        "commands_and_agreements": [],
    }

    with patch.object(memory_manager.seele, "_compact_personal_facts_and_events_async") as mock_pf:
        with patch.object(memory_manager.seele, "_compact_short_term_overflow_async") as mock_st:
            with patch.object(memory_manager.seele, "_compact_long_strings_async") as mock_ls:
                mock_pf.return_value = data
                mock_st.return_value = data
                mock_ls.return_value = data
                await memory_manager.seele._compact_overflowing_memory_async(data)

    mock_pf.assert_not_awaited()
    mock_st.assert_awaited_once()


@pytest.mark.asyncio
async def test_compact_overflowing_memory_runs_personal_facts_compaction_only_for_pf_overflow(memory_manager):
    """When only personal_facts exceeds limit, only that compaction runs."""
    from memory.seele import PERSONAL_FACTS_LIMIT

    data = {
        "bot": {
            "name": "TestBot",
            "gender": "",
            "birthday": "",
            "role": "",
            "appearance": "",
            "likes": [],
            "dislikes": [],
            "language_style": {"description": "", "examples": []},
            "personality": {"mbti": "", "description": "", "worldview_and_values": ""},
            "emotions": {"long_term": "", "short_term": []},
            "needs": {"long_term": "", "short_term": []},
            "relationship_with_user": "",
        },
        "user": {
            "name": "TestUser",
            "gender": "",
            "birthday": "",
            "location": "",
            "personal_facts": [f"Fact {i}" for i in range(PERSONAL_FACTS_LIMIT + 3)],
            "abilities": [],
            "likes": [],
            "dislikes": [],
            "personality": {"mbti": "", "description": "", "worldview_and_values": ""},
            "emotions": {"long_term": "", "short_term": []},
            "needs": {"long_term": "", "short_term": []},
        },
        "memorable_events": {},
        "commands_and_agreements": [],
    }

    with patch.object(memory_manager.seele, "_compact_personal_facts_and_events_async") as mock_pf:
        with patch.object(memory_manager.seele, "_compact_short_term_overflow_async") as mock_st:
            with patch.object(memory_manager.seele, "_compact_long_strings_async") as mock_ls:
                mock_pf.return_value = data
                mock_st.return_value = data
                mock_ls.return_value = data
                await memory_manager.seele._compact_overflowing_memory_async(data)

    mock_pf.assert_awaited_once()
    mock_st.assert_not_awaited()


@pytest.mark.asyncio
async def test_compact_long_strings_tier1_triggers_on_oversized(memory_manager):
    """Tier 1 should submit full seele.json and apply revisions when strings exceed 300 chars."""
    from memory.seele import MAX_STRING_LENGTH_HARD

    data = {
        "bot": {
            "name": "TestBot",
            "gender": "",
            "birthday": "",
            "role": "",
            "appearance": "",
            "likes": [],
            "dislikes": [],
            "language_style": {"description": "X" * 501, "examples": []},
            "personality": {"mbti": "", "description": "", "worldview_and_values": ""},
            "emotions": {"long_term": "", "short_term": []},
            "needs": {"long_term": "", "short_term": []},
            "relationship_with_user": "",
        },
        "user": {
            "name": "TestUser",
            "gender": "",
            "birthday": "",
            "location": "",
            "personal_facts": [],
            "abilities": [],
            "likes": [],
            "dislikes": [],
            "personality": {"mbti": "", "description": "", "worldview_and_values": ""},
            "emotions": {"long_term": "", "short_term": []},
            "needs": {"long_term": "", "short_term": []},
        },
        "memorable_events": {},
        "commands_and_agreements": [],
    }

    revised = json.loads(json.dumps(data))
    revised["bot"]["language_style"]["description"] = "A" * (MAX_STRING_LENGTH_HARD - 10)

    fake_response = json.dumps(revised)

    fake_client = Mock()
    fake_client.compact_long_strings_async = AsyncMock(return_value=fake_response)
    fake_client.close_async = AsyncMock()

    with patch("llm.chat_client.LLMClient", return_value=fake_client):
        with patch("prompts.runtime.update_seele_json", return_value=True):
            with patch.object(memory_manager.seele, "get_long_term_memory", return_value=data):
                result = await memory_manager.seele._compact_long_strings_async(data)

    assert result is not None


@pytest.mark.asyncio
async def test_compact_long_strings_uses_runtime_prompt_builder(memory_manager):
    """Long-string compaction prompts should be owned by prompts.runtime."""
    from memory.seele import MAX_STRING_LENGTH_HARD

    data = {
        "bot": {
            "name": "TestBot",
            "gender": "",
            "birthday": "",
            "role": "",
            "appearance": "",
            "likes": [],
            "dislikes": [],
            "language_style": {"description": "X" * 501, "examples": []},
            "personality": {"mbti": "", "description": "", "worldview_and_values": ""},
            "emotions": {"long_term": "", "short_term": []},
            "needs": {"long_term": "", "short_term": []},
            "relationship_with_user": "",
        },
        "user": {
            "name": "TestUser",
            "gender": "",
            "birthday": "",
            "location": "",
            "personal_facts": [],
            "abilities": [],
            "likes": [],
            "dislikes": [],
            "personality": {"mbti": "", "description": "", "worldview_and_values": ""},
            "emotions": {"long_term": "", "short_term": []},
            "needs": {"long_term": "", "short_term": []},
        },
        "memorable_events": {},
        "commands_and_agreements": [],
    }
    revised = json.loads(json.dumps(data))
    revised["bot"]["language_style"]["description"] = "A" * (MAX_STRING_LENGTH_HARD - 1)

    fake_client = Mock()
    fake_client.compact_long_strings_async = AsyncMock(return_value=json.dumps(revised))
    fake_client.close_async = AsyncMock()

    with patch("llm.chat_client.LLMClient", return_value=fake_client):
        with patch("prompts.runtime.get_long_string_compaction_prompt", return_value="central prompt") as mock_prompt:
            await memory_manager.seele._llm_compact_long_strings_full(data)

    mock_prompt.assert_called_once()
    assert fake_client.compact_long_strings_async.call_args.kwargs["prompt"] == "central prompt"


@pytest.mark.asyncio
async def test_long_string_full_compaction_retries_with_previous_output_and_reason(
    memory_manager,
):
    """Invalid full long-string compaction output should be retried with context."""
    from memory.seele import MAX_STRING_LENGTH_HARD

    data = make_seele_data()
    data["bot"]["language_style"]["description"] = "X" * 501
    revised = json.loads(json.dumps(data))
    revised["bot"]["language_style"]["description"] = "A" * (
        MAX_STRING_LENGTH_HARD - 1
    )
    invalid_response = '{"bot":'
    valid_response = json.dumps(revised)

    fake_client = Mock()
    fake_client.compact_long_strings_async = AsyncMock(
        side_effect=[invalid_response, valid_response]
    )
    fake_client.close_async = AsyncMock()

    with patch("llm.chat_client.LLMClient", return_value=fake_client):
        with patch(
            "prompts.runtime.get_long_string_compaction_prompt",
            side_effect=["first prompt", "retry prompt"],
        ) as mock_prompt:
            result = await memory_manager.seele._llm_compact_long_strings_full(data)

    assert result == revised
    retry_kwargs = mock_prompt.call_args_list[1].kwargs
    assert retry_kwargs["previous_attempt"] == invalid_response
    assert retry_kwargs["previous_error"]


@pytest.mark.asyncio
async def test_single_string_compaction_retries_with_previous_output_and_reason(
    memory_manager,
):
    """Oversized single-string compaction output should inform the next attempt."""
    from memory.seele import MAX_STRING_LENGTH_HARD

    data = make_seele_data()
    data["bot"]["language_style"]["description"] = "X" * 501
    oversized_output = "Y" * (MAX_STRING_LENGTH_HARD + 1)
    valid_output = "short"

    with patch.object(
        memory_manager.seele,
        "_llm_compress_single_string",
        new=AsyncMock(side_effect=[oversized_output, valid_output]),
    ) as mock_compress:
        with patch("prompts.runtime.update_seele_json", return_value=True):
            with patch.object(
                memory_manager.seele,
                "get_long_term_memory",
                return_value=make_seele_data(),
            ):
                fake_client = Mock()
                fake_client.close_async = AsyncMock()
                with patch("llm.chat_client.LLMClient", return_value=fake_client):
                    await memory_manager.seele._compact_long_strings_tier2(data)

    retry_kwargs = mock_compress.await_args_list[1].kwargs
    assert retry_kwargs["previous_attempt"] == oversized_output
    assert "must be" in retry_kwargs["previous_error"]
