from prompts.chat_prompt import ChatMessageBuilder


class _FakeLLMClient:
    def _get_cacheable_system_prompt(self, recent_summaries=None):
        return "system prompt"

    def _get_current_time_str(self):
        return "2026-03-30 00:00:00"


def test_build_chat_messages_instructs_clean_final_reply_for_current_user_message():
    builder = ChatMessageBuilder(_FakeLLMClient())

    messages = builder.build_chat_messages(
        current_context=[
            {"role": "user", "content": "Earlier message"},
            {"role": "user", "content": "现在回复我"},
        ],
        retrieved_summaries=[],
        retrieved_conversations=[],
    )

    assert messages[-1]["role"] == "user"
    assert "Now continue the current conversation" in messages[-1]["content"]
    assert "现在回复我" in messages[-1]["content"]


def test_build_chat_messages_instructs_clean_final_reply_for_custom_user_message():
    builder = ChatMessageBuilder(_FakeLLMClient())

    messages = builder.build_chat_messages(
        current_context=[],
        retrieved_summaries=[],
        retrieved_conversations=[],
        custom_user_message="请总结一下",
    )

    assert messages[-1]["role"] == "user"
    assert "Please respond to the following system message" in messages[-1]["content"]
    assert "请总结一下" in messages[-1]["content"]