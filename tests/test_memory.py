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
    async def test_fallback_retry_reuses_previous_failed_output(self, memory_manager):
        """Retry should pass the raw failed generation output into the next attempt."""
        memory_manager.seele.validate_seele_structure = Mock(return_value=True)
        memory_manager.seele.clean_json_response = Mock(side_effect=lambda value: value)
        memory_manager.seele._write_complete_seele_json = Mock()

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
            write_complete_json=memory_manager.seele._write_complete_seele_json,
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
                    "_write_complete_seele_json",
                ) as mock_write:
                    result = await memory_manager.seele._apply_generated_patch_async(
                        1,
                        [],
                        None,
                    )

    assert result is True
    mock_compact.assert_awaited_once_with(oversized_memory)
    mock_write.assert_called_once_with(compacted_memory)


def test_compact_overflowing_memory_uses_fallback_for_invalid_llm_output(memory_manager):
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
            "emotions": {"long_term": "", "short_term": ""},
            "needs": {"long_term": "", "short_term": ""},
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
            "emotions": {"long_term": "", "short_term": ""},
            "needs": {"long_term": "", "short_term": ""},
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
        compacted = memory_manager.seele._compact_overflowing_memory(oversized_memory)

    assert len(compacted["user"]["personal_facts"]) == PERSONAL_FACTS_LIMIT
    assert compacted["user"]["personal_facts"] == oversized_memory["user"]["personal_facts"][:PERSONAL_FACTS_LIMIT]
    fake_client.close_async.assert_called_once()


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
            "emotions": {"long_term": "", "short_term": ""},
            "needs": {"long_term": "", "short_term": ""},
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
            "emotions": {"long_term": "", "short_term": ""},
            "needs": {"long_term": "", "short_term": ""},
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
    fake_client.generate_seele_compaction_async.assert_awaited_once()
    fake_client.close_async.assert_awaited_once()
