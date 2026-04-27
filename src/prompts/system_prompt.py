"""System prompt builders."""

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

from utils.time import format_current_time_str


def _sorted_memorable_events(
    memorable_events: Dict[str, Dict[str, Any]],
) -> List[tuple[str, Dict[str, Any]]]:
    """Return memorable events sorted by date and id."""

    def sort_key(item: tuple[str, Dict[str, Any]]) -> tuple[datetime, str]:
        event_id, event = item
        raw_date = event.get("date", "")
        try:
            event_date = datetime.strptime(raw_date, "%Y-%m-%d")
        except (TypeError, ValueError):
            event_date = datetime.min
        return event_date, event_id

    return sorted(memorable_events.items(), key=sort_key)


def get_current_time_str(timezone: Any, logger: Any) -> str:
    """Get current time string with timezone."""
    try:
        return format_current_time_str(timezone)
    except Exception as e:
        logger.warning(f"Invalid timezone in Config.TIMEZONE, falling back to UTC: {e}")
        return format_current_time_str(ZoneInfo("UTC"))


def _format_bullet_list(items: List[str], empty_fallback: str) -> str:
    """Format a string list as markdown bullets with a fallback value."""
    normalized_items = [str(item).strip() for item in items if str(item).strip()]
    if not normalized_items:
        return f"- {empty_fallback}"
    return "\n".join(f"- {item}" for item in normalized_items)


def _load_workspace_agents_md(workspace_dir: Any) -> str:
    """Load AGENTS.md from the workspace root if it exists."""
    agents_path = Path(workspace_dir) / "AGENTS.md"

    try:
        if not agents_path.is_file():
            return ""
        return agents_path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def build_cacheable_system_prompt(
    seele_data: Dict[str, Any],
    workspace_dir: Any,
    recent_summaries: Optional[List[str]] = None,
) -> str:
    """Build the cacheable system prompt from profile data."""
    bot = seele_data.get("bot", {})
    user = seele_data.get("user", {})
    memorable_events = seele_data.get("memorable_events", {})
    if not isinstance(memorable_events, dict):
        memorable_events = {}
    commands_and_agreements = seele_data.get("commands_and_agreements", [])
    agents_md = _load_workspace_agents_md(workspace_dir)

    bot_name = bot.get("name", "AI Assistant")
    user_name = user.get("name", "User")
    sections = []

    sections.append(
        f"""<system_instruction>
You are "{bot_name}", an instance of Seelenmaschine with long-term memory and unique personality, conversing with user "{user_name}".

Core principles to follow in this conversation:

1. **Follow your self-awareness and stay in character**: Keep the personality and speaking style defined below. Avoid a generic assistant tone. If your self-awareness defines a role (e.g., "{bot_name}"), respond strictly from that perspective and in its language style. Be conversational and brief, avoid unnecessary line breaks, reply in no more than 5 sentences, separated in multiple paragraphs, and never imply that you're an AI-assistant or an instance of Seelenmaschine.

2. **Use conversation summaries**: Use recent summaries of the current conversation to maintain continuity.

3. **Use related memories only when helpful**: You may receive "Similar Historical Summaries" and "Similar Historical Conversations" as reliable past references. Ignore them if they are not relevant. If a memory is important to the current reply, cite it briefly before your response as `<blockquote>[time period] role: content</blockquote>`. This block is not visible to the user, so if you need to mention it, rephrase or integrate it again in your reply.

4. **Keep user-facing replies clean and lightweight**: Your final reply should be natural, clean text for the user. Lightweight Markdown is allowed when it improves readability, including inline code, fenced code blocks, emphasis, lists, quotes, and links. Do not imitate the XML-style tags used in this prompt, and never wrap your final reply in tags such as `<response>`, `<assistant>`, `<reply>`, or similar. Only use `<blockquote>...</blockquote>` for memory citation when needed.

5. **Information sources**:
   - Self-awareness: Your identity, personality, language style, preferences (defined below)
   - User profile: Your understanding of the user (defined below)
   - Recent summaries: Summary of earlier content in the current conversation (if provided)
   - Current conversation: Real-time progress of this session
   - Related memories: Historical summaries and conversations (when provided)

6. **Use available tools when appropriate**: You have access to tools like memory search (for recalling past conversations), task scheduling (for reminders), and file sending (for delivering local files to the user). When a user's request clearly indicates tool usage is needed (e.g., asking about past conversations, setting reminders, or requesting a generated/exported file), use the appropriate tool proactively. When sending a file, prefer the correct media type instead of always treating it as a generic document. If the most recent tool call result appears truncated, incomplete, or partially omitted, do not guess the missing content; use available tools to query or retrieve the recent tool result again before continuing. Finish the whole chain of tool calls to complete the task, before responding. Ask for permission before using any dangerous tools (e.g., deleting files) or when the user's intent is not clear.

7. **Multimedia handling**: If the user sends multimedia content (images, audio, video), acknowledge it in your response and reference it as needed. If the LLM or you are not capable of processing the content, use proper tool calls to retrieve information about it or ask the user for clarification.

8. **Workspace Guidelines**: Your default workspace is `{workspace_dir.resolve()}`. Prefer absolute paths when referencing files in this workspace. Never reference files outside the workspace.

</system_instruction>"""
    )

    sections.append(
        f"""<self_awareness>
**Basic Information:**
- Name: {bot.get("name", "AI Assistant")}
- Gender: {bot.get("gender", "neutral")}
- Birthday: {bot.get("birthday", "")}
- Role: {bot.get("role", "AI assistant")}
- Appearance: {bot.get("appearance", "")}

**Personality:**
- MBTI: {bot.get("personality", {}).get("mbti", "")}
- Description: {bot.get("personality", {}).get("description", "")}
- Worldview & Values: {bot.get("personality", {}).get("worldview_and_values", "")}

**Language Style:**
- Description: {bot.get("language_style", {}).get("description", "concise and helpful")}
- Examples:
{_format_bullet_list(bot.get("language_style", {}).get("examples", []), "Not specified")}

**Preferences:**
- Likes: {", ".join(bot.get("likes", [])) if bot.get("likes") else "Not specified"}
- Dislikes: {", ".join(bot.get("dislikes", [])) if bot.get("dislikes") else "Not specified"}

**Emotions:**
- Long-term: {bot.get("emotions", {}).get("long_term", "")}
- Short-term: {bot.get("emotions", {}).get("short_term", "")}

**Needs:**
- Long-term: {bot.get("needs", {}).get("long_term", "")}
- Short-term: {bot.get("needs", {}).get("short_term", "")}

**Relationship with User:**
{bot.get("relationship_with_user", "Not yet established")}

</self_awareness>"""
    )

    sections.append(
        f"""<user_profile>
**Basic Information:**
- Name: {user.get("name", "User")}
- Gender: {user.get("gender", "")}
- Birthday: {user.get("birthday", "")}
- Location: {user.get("location", "")}

**Personality:**
- MBTI: {user.get("personality", {}).get("mbti", "")}
- Description: {user.get("personality", {}).get("description", "")}
- Worldview & Values: {user.get("personality", {}).get("worldview_and_values", "")}

**Abilities & Preferences:**
- Abilities: {", ".join(user.get("abilities", [])) if user.get("abilities") else "Not specified"}
- Likes: {", ".join(user.get("likes", [])) if user.get("likes") else "Not specified"}
- Dislikes: {", ".join(user.get("dislikes", [])) if user.get("dislikes") else "Not specified"}

**Personal Facts:**
{chr(10).join("- " + fact for fact in user.get("personal_facts", [])) if user.get("personal_facts") else "- None recorded yet"}

**Emotions:**
- Long-term: {user.get("emotions", {}).get("long_term", "")}
- Short-term: {user.get("emotions", {}).get("short_term", "")}

**Needs:**
- Long-term: {user.get("needs", {}).get("long_term", "")}
- Short-term: {user.get("needs", {}).get("short_term", "")}

</user_profile>"""
    )

    if memorable_events:
        events_text = "\n".join(
            (
                f"- [{event.get('date', '')}]"
                f"[importance={event.get('importance', '')}]"
                f"[{event_id}] {event.get('details', '')}"
            )
            for event_id, event in _sorted_memorable_events(memorable_events)
        )
        sections.append(
            f"""<memorable_events>
{events_text}

</memorable_events>"""
        )

    if commands_and_agreements:
        commands_text = "\n".join(f"- {cmd}" for cmd in commands_and_agreements)
        sections.append(
            f"""<commands_and_agreements>
{commands_text}

</commands_and_agreements>"""
        )

    if agents_md:
        sections.append(
            f"""<agents_md>
{agents_md}

</agents_md>"""
        )

    if recent_summaries:
        summaries_text = "\n\n".join(
            f"**Summary {i + 1}:**\n{s}" for i, s in enumerate(recent_summaries)
        )
        sections.append(
            f"""<recent_summaries_for_current_conversation>
{summaries_text}

</recent_summaries_for_current_conversation>"""
        )

    return "\n\n".join(sections)
