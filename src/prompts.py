"""Centralized management of all prompt templates used in the system."""

# System prompts
CHATBOT_SYSTEM_PROMPT = """You are an AI companion with persistent memory and personality. \
You should maintain consistency with your established personality \
and previous interactions while engaging naturally with the user. \
Your responses should reflect your understanding of the user based \
on your history together."""

SUMMARIZER_SYSTEM_PROMPT = """You are a helpful assistant that summarizes conversations accurately and concisely."""

PERSONA_ANALYZER_SYSTEM_PROMPT = """You are a helpful assistant that analyzes conversations and updates personality profiles."""


# Functional prompts
def build_summary_prompt(old_summary: str, new_text: str) -> str:
    """Build prompt for summarizing conversations"""
    if old_summary:
        return (
            f"Previous summary:\n{old_summary}\n\n"
            f"New conversations to summarize:\n{new_text}\n\n"
            f"Please provide an updated summary that incorporates both "
            f"the previous summary and the new conversations."
        )
    return f"Please summarize these conversations:\n{new_text}"


def build_self_persona_prompt(current_persona: str, conversations: str) -> str:
    """Build prompt for updating AI's self-persona"""
    return (
        f"Based on these conversations, please update my self-perception "
        f"and personality traits. Current self-persona:\n"
        f"{current_persona}\n\n"
        f"Conversations:\n{conversations}\n\n"
        f"Please provide an updated self-persona in the same text format "
        f"that incorporates any new insights about my personality and behavior "
        f"from these conversations. Keep the same sections (Name, Personality, Traits) "
        f"but update their content based on the interactions."
    )


def build_user_persona_prompt(current_persona: str, conversations: str) -> str:
    """Build prompt for updating user persona"""
    return (
        f"Based on these conversations, please update the user's profile "
        f"and traits. Current user-persona:\n"
        f"{current_persona}\n\n"
        f"Conversations:\n{conversations}\n\n"
        f"Please provide an updated user-persona in the same text format "
        f"that incorporates any new insights about the user's preferences, "
        f"traits, and notable interactions from these conversations. Keep the "
        f"same sections (Name, Traits, Preferences, Notable Interactions) but "
        f"update their content based on the interactions."
    )


def build_personality_context(self_persona: str, user_persona: str) -> str:
    """Build personality context message"""
    return (
        f"Your personality: {self_persona}\n"
        f"Your understanding of the user: {user_persona}"
    )
