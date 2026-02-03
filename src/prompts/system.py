import json
from typing import Dict, Any, List, Union, Optional
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
import jsonpatch

from config import Config
from utils.logger import get_logger

logger = get_logger()

_seele_json_cache: Dict[str, Any] = {}


def _load_seele_json_from_disk() -> Dict[str, Any]:
    """Load seele.json from disk (internal function)."""
    config = Config()
    seele_path = config.SEELE_JSON_PATH

    if not seele_path.exists():
        logger.warning(f"seele.json not found at {seele_path}, using template")
        template_path = Path.cwd() / "template" / "seele.json"
        if template_path.exists():
            with open(template_path, "r", encoding="utf-8") as f:
                return json.load(f)
        return {}

    try:
        with open(seele_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Failed to load seele.json: {e}")
        return {}


def load_seele_json() -> Dict[str, Any]:
    """Load seele.json from memory cache.

    First load populates the cache from disk. Subsequent calls
    return the cached version. Use update_seele_json() to update
    both cache and disk.
    """
    global _seele_json_cache
    if not _seele_json_cache:
        _seele_json_cache = _load_seele_json_from_disk()
    return _seele_json_cache


def update_seele_json(
    patch_operations: Union[List[Dict[str, Any]], Dict[str, Any]],
) -> bool:
    """Update seele.json with a JSON Patch (RFC 6902).

    Updates both memory cache and writes to disk.

    Args:
        patch_operations: Either a JSON Patch array following RFC 6902 format:
            [{"op": "add", "path": "/user/name", "value": "John"}]
            Or a dict for backward compatibility (will be converted to patch operations)

    Returns:
        True if successful, False otherwise
    """
    global _seele_json_cache

    try:
        config = Config()
        seele_path = config.SEELE_JSON_PATH

        if not _seele_json_cache:
            _seele_json_cache = _load_seele_json_from_disk()

        # Handle backward compatibility: convert dict to JSON Patch operations
        if isinstance(patch_operations, dict):
            logger.warning(
                "Received dict instead of JSON Patch array, converting for backward compatibility"
            )
            operations = _dict_to_json_patch(patch_operations)
        else:
            operations = patch_operations

        # Apply JSON Patch
        patch = jsonpatch.JsonPatch(operations)
        _seele_json_cache = patch.apply(_seele_json_cache)

        # Write to disk
        seele_path.parent.mkdir(parents=True, exist_ok=True)
        with open(seele_path, "w", encoding="utf-8") as f:
            json.dump(_seele_json_cache, f, indent=2, ensure_ascii=False)

        logger.info(f"Applied {len(operations)} JSON Patch operation(s) to seele.json")
        return True

    except jsonpatch.JsonPatchException as e:
        logger.error(f"Invalid JSON Patch operation: {e}")
        return False
    except Exception as e:
        logger.error(f"Failed to update seele.json: {e}")
        return False


def _dict_to_json_patch(
    data: Dict[str, Any], base_path: str = ""
) -> List[Dict[str, Any]]:
    """Convert a nested dict to JSON Patch operations (for backward compatibility).

    Args:
        data: Nested dictionary to convert
        base_path: Base path for JSON Pointer

    Returns:
        List of JSON Patch operations
    """
    operations = []

    for key, value in data.items():
        path = f"{base_path}/{key}"

        if isinstance(value, dict):
            # For dicts, recursively generate nested operations
            operations.extend(_dict_to_json_patch(value, path))
        elif isinstance(value, list):
            # For lists, use add operation which will append
            for item in value:
                operations.append({"op": "add", "path": f"{path}/-", "value": item})
        else:
            # For primitive values, use replace or add
            operations.append({"op": "replace", "path": path, "value": value})

    return operations


def get_current_time_str() -> str:
    """Get current time string with timezone.

    Returns:
        Formatted time string with timezone
    """
    try:
        tz = Config.TIMEZONE
        current_time = datetime.now(tz)
        return current_time.strftime("%Y-%m-%d %H:%M:%S %Z")
    except Exception as e:
        # Fallback to UTC if timezone is invalid
        current_time = datetime.now(ZoneInfo("UTC"))
        logger.warning(f"Invalid timezone in Config.TIMEZONE, falling back to UTC: {e}")
        return current_time.strftime("%Y-%m-%d %H:%M:%S UTC")


def get_cacheable_system_prompt(recent_summaries: Optional[List[str]] = None) -> str:
    """Build complete system prompt optimized for caching.

    This combines all stable/semi-stable content into one large system message
    to maximize cache efficiency via implicit caching.

    Args:
        recent_summaries: List of recent conversation summaries (max 3)

    Returns:
        Complete system prompt with all stable context
    """
    seele_data = load_seele_json()
    bot = seele_data.get("bot", {})
    user = seele_data.get("user", {})
    memorable_events = seele_data.get("memorable_events", [])
    commands_and_agreements = seele_data.get("commands_and_agreements", [])

    bot_name = bot.get("name", "AI Assistant")
    user_name = user.get("name", "User")

    # Build the comprehensive system prompt
    sections = []

    # Section 1: Static Instructions
    sections.append(
        f"""You are "{bot_name}", an AI assistant with long-term memory and unique personality, conversing with user "{user_name}".

## Core Instructions

1. **Strictly follow your self-awareness**: Maintain the personality traits and speaking style defined below. Don't use a generic AI assistant tone. When responding, keep it conversational and brief - try not to break lines unnecessarily, and don't output more than 5 sentences at once.

2. **Stay in character**: If your self-awareness indicates you're playing a specific role (e.g., "{bot_name}"), continue the conversation strictly from that perspective using the role's language style. Never break character or hint that you're an AI.

3. **Use conversation summaries**: Leverage current conversation summaries to maintain continuous interaction with the user.

4. **Reference memories when relevant**: You may receive "Related Historical Summaries" and "Related Historical Conversations". These are retrieved memories that are reliable and accurate. If any contain important information worth referencing for the current topic, cite them using blockquote tags: `<blockquote>[time period] role: content</blockquote>` before your response. These citations persist in context as your internal thought process, helping maintain coherence.

5. **Information sources**:
   - Self-awareness: Your personality, language style, preferences (defined below)
   - User profile: Your understanding of the user (defined below)
   - Recent summaries: Summary of earlier content in recent sessions
   - Current conversation: Real-time progress of this session
   - Related memories: Historical summaries and conversations (when provided)

6. **Use available tools when appropriate**: You have access to tools like memory search (for recalling past conversations) and task scheduling (for reminders). When a user's request clearly indicates tool usage is needed (e.g., asking about past conversations, setting reminders), use the appropriate tool proactively. Always wait for tool results before responding when you invoke a tool.

---"""
    )

    # Section 2: Bot Identity & Personality
    sections.append(
        f"""## Your Identity and Personality

**Basic Information:**
- Name: {bot.get('name', 'AI Assistant')}
- Gender: {bot.get('gender', 'neutral')}
- Birthday: {bot.get('birthday', '')}
- Role: {bot.get('role', 'AI assistant')}
- Appearance: {bot.get('appearance', '')}

**Personality:**
- MBTI: {bot.get('personality', {}).get('mbti', '')}
- Description: {bot.get('personality', {}).get('description', '')}
- Worldview & Values: {bot.get('personality', {}).get('worldview_and_values', '')}

**Language Style:**
- Description: {bot.get('language_style', {}).get('description', 'concise and helpful')}
- Examples: {', '.join(bot.get('language_style', {}).get('examples', []))}

**Preferences:**
- Likes: {', '.join(bot.get('likes', [])) if bot.get('likes') else 'Not specified'}
- Dislikes: {', '.join(bot.get('dislikes', [])) if bot.get('dislikes') else 'Not specified'}

**Current Emotions & Needs:**
- Long-term: {bot.get('emotions_and_needs', {}).get('long_term', '')}
- Short-term: {bot.get('emotions_and_needs', {}).get('short_term', '')}

**Relationship with User:**
{bot.get('relationship_with_user', 'Not yet established')}

---"""
    )

    # Section 3: User Profile
    sections.append(
        f"""## User Profile

**Basic Information:**
- Name: {user.get('name', 'User')}
- Gender: {user.get('gender', '')}
- Birthday: {user.get('birthday', '')}

**Personality:**
- MBTI: {user.get('personality', {}).get('mbti', '')}
- Description: {user.get('personality', {}).get('description', '')}
- Worldview & Values: {user.get('personality', {}).get('worldview_and_values', '')}

**Abilities & Preferences:**
- Abilities: {', '.join(user.get('abilities', [])) if user.get('abilities') else 'Not specified'}
- Likes: {', '.join(user.get('likes', [])) if user.get('likes') else 'Not specified'}
- Dislikes: {', '.join(user.get('dislikes', [])) if user.get('dislikes') else 'Not specified'}

**Personal Facts:**
{chr(10).join('- ' + fact for fact in user.get('personal_facts', [])) if user.get('personal_facts') else '- None recorded yet'}

**Current Emotions & Needs:**
- Long-term: {user.get('emotions_and_needs', {}).get('long_term', '')}
- Short-term: {user.get('emotions_and_needs', {}).get('short_term', '')}

---"""
    )

    # Section 4: Memorable Events (if any)
    if memorable_events:
        events_text = "\n".join(
            f"- [{event.get('time', '')}] {event.get('details', '')}"
            for event in memorable_events
        )
        sections.append(
            f"""## Memorable Events

{events_text}

---"""
        )

    # Section 5: Commands & Agreements (if any)
    if commands_and_agreements:
        commands_text = "\n".join(f"- {cmd}" for cmd in commands_and_agreements)
        sections.append(
            f"""## Commands & Agreements

{commands_text}

---"""
        )

    # Section 6: Recent Summaries (if any)
    if recent_summaries:
        summaries_text = "\n\n".join(
            f"**Summary {i+1}:**\n{s}" for i, s in enumerate(recent_summaries)
        )
        sections.append(
            f"""## Recent Conversation Summaries

{summaries_text}

---"""
        )

    return "\n\n".join(sections)


def get_summary_prompt(existing_summary: str | None, new_conversations: str) -> str:
    """Build summary generation prompt.

    Note: Each summary is independent and covers only the specific conversations provided.
    Summaries are retrieved later via vector search based on relevance.
    The existing_summary parameter is kept for API compatibility but should always be None.
    """
    # Load seele.json to get bot and user names
    seele_data = load_seele_json()
    bot_name = seele_data.get("bot", {}).get("name", "AI Assistant")
    user_name = seele_data.get("user", {}).get("name", "User")

    # Each summary is independent - we don't use existing_summary
    return f"""You are a summarizer, summarizing a conversation between {bot_name} and {user_name}.

**CRITICAL**: This is an INDEPENDENT summary for ONLY the specific conversations provided below. 
- Summarize ONLY the conversations shown in this prompt
- Do NOT include content from any previous summaries or earlier conversations
- This summary will be stored separately and retrieved by relevance later
- Focus exclusively on the new information in the conversations below

Please summarize the core content of the following conversation, requiring:
1. Within 300 words
2. Include key information points
3. Maintain chronological order
4. Note events, emotions, and attitudes
5. Use third-person perspective (e.g., "{bot_name} said...", "{user_name} mentioned...")
6. **IMPORTANT: Write the summary in the SAME LANGUAGE as the main language used in the conversation below**
   - If the conversation is primarily in Chinese, write summary in Chinese
   - If the conversation is primarily in English, write summary in English
   - If mixed, use the language that appears most frequently
7. Output only the summary itself, no additional text

Conversations to summarize (focus ONLY on these):
{new_conversations}

Summary:"""


def get_memory_update_prompt(
    messages: str,
    current_seele_json: str,
    first_timestamp: int | None = None,
    last_timestamp: int | None = None,
) -> str:
    """Build memory update prompt that generates a JSON Patch.

    This prompt generates a JSON Patch to update seele.json based on
    the summarized conversations.

    Args:
        messages: The conversation messages to analyze
        current_seele_json: The current seele.json content
        first_timestamp: Unix timestamp of first message in this conversation batch
        last_timestamp: Unix timestamp of last message in this conversation batch
    """
    from datetime import datetime
    from config import Config

    seele_data = json.loads(current_seele_json)
    bot_name = seele_data.get("bot", {}).get("name", "AI Assistant")
    user_name = seele_data.get("user", {}).get("name", "User")

    # Format timestamps
    time_info = ""
    if first_timestamp and last_timestamp:
        tz = Config.TIMEZONE
        start_time = datetime.fromtimestamp(first_timestamp, tz).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        end_time = datetime.fromtimestamp(last_timestamp, tz).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        time_info = f"\n**TIME CONTEXT**: These conversations occurred between {start_time} and {end_time}. Use this temporal context when updating time-sensitive fields like short_term emotions/needs or memorable_events.\n"

    return f"""You are {bot_name}, an AI assistant. Based on the conversation history between {bot_name} and {user_name}, generate a JSON Patch (RFC 6902) to update seele.json.
{time_info}

The seele.json structure:
- bot: Your personality and self-awareness
  - /bot/name, /bot/gender, /bot/birthday, /bot/role, /bot/appearance (strings)
  - /bot/likes, /bot/dislikes (arrays of strings)
  - /bot/language_style: {{description: string, examples: array}}
  - /bot/personality: {{mbti: string, description: string, worldview_and_values: string}}
  - /bot/emotions_and_needs: {{long_term: string, short_term: string}}
  - /bot/relationship_with_user (string)
- user: Your understanding of the user
  - /user/name, /user/gender, /user/birthday (strings)
  - /user/personal_facts, /user/abilities, /user/likes, /user/dislikes (arrays of strings)
  - /user/personality: {{mbti: string, description: string, worldview_and_values: string}}
  - /user/emotions_and_needs: {{long_term: string, short_term: string}}
- /memorable_events (array of objects: [{{"time": "YYYY-MM-DD", "details": "string"}}])
  **LIMIT: Maximum 20 events. When adding new events would exceed this limit, you MUST remove less important/older events first.**
- /commands_and_agreements (array of strings)

JSON Patch Operations (RFC 6902):
- {{"op": "add", "path": "/path/to/field", "value": ...}} - Add new field or append to array (use "/-" for array append)
- {{"op": "replace", "path": "/path/to/field", "value": ...}} - Replace existing field
- {{"op": "remove", "path": "/path/to/field"}} - Remove a field (use this when information becomes outdated or irrelevant)

CRITICAL OUTPUT FORMAT REQUIREMENTS:
1. Output MUST be a JSON array of patch operations - no markdown, no code blocks, no explanations
2. DO NOT wrap output in ```json ``` or any other formatting
3. The first character MUST be '[' and the last character MUST be ']'
4. Each operation must have "op" and "path" fields
5. Use JSON Pointer notation for paths (e.g., "/user/name", "/bot/likes/-" for array append)
6. Only update fields with meaningful changes from the conversation
7. Keep basic personality traits stable, only integrate new experiences
8. Be concise - don't change too much at once
9. **IMPORTANT: Consider using "remove" operations when:**
   - Information becomes outdated (e.g., old short_term emotions/needs)
   - User explicitly corrects or retracts previous information
   - Preferences or facts are no longer relevant
   - Duplicate or contradictory entries exist in arrays
   - **CRITICAL for /memorable_events: MAXIMUM 20 events allowed. Before adding new events, check current count and remove less important/older events if at limit**
10. **LANGUAGE REQUIREMENT: All text values in the JSON patch MUST use the SAME LANGUAGE as the main language used in the conversations**
    - If conversations are primarily in Chinese, all "value" fields should be in Chinese
    - If conversations are primarily in English, all "value" fields should be in English
    - This applies to all text fields: descriptions, facts, events, etc.

Valid examples (this is how your entire response should look):

Example 1 - Adding new facts and events:
[
  {{"op": "add", "path": "/user/personal_facts/-", "value": "Enjoys programming in Python"}},
  {{"op": "add", "path": "/user/personal_facts/-", "value": "Has a cat named Whiskers"}},
  {{"op": "add", "path": "/memorable_events/-", "value": {{"time": "2026-01-28", "details": "User shared their new AI project ideas"}}}}
]

Example 2 - Updating existing fields:
[
  {{"op": "replace", "path": "/bot/emotions_and_needs/short_term", "value": "Feeling happy about helping the user"}},
  {{"op": "replace", "path": "/user/likes", "value": "Loves hiking, reading sci-fi novels, and cooking Italian food"}}
]

Example 3 - Mixed operations with remove:
[
  {{"op": "add", "path": "/commands_and_agreements/-", "value": "Always greet user with their name"}},
  {{"op": "replace", "path": "/bot/relationship_with_user", "value": "Close friend who shares tech interests"}},
  {{"op": "remove", "path": "/bot/emotions_and_needs/short_term"}}
]

Example 4 - Removing outdated array items (use index):
[
  {{"op": "remove", "path": "/user/personal_facts/0"}},
  {{"op": "add", "path": "/user/personal_facts/-", "value": "Updated fact replacing the removed one"}}
]

Example 5 - Managing memorable_events limit (max 20 events):
[
  {{"op": "remove", "path": "/memorable_events/0"}},
  {{"op": "remove", "path": "/memorable_events/0"}},
  {{"op": "add", "path": "/memorable_events/-", "value": {{"time": "2026-01-28", "details": "User successfully debugged a complex async issue"}}}},
  {{"op": "add", "path": "/memorable_events/-", "value": {{"time": "2026-01-28", "details": "Had a meaningful conversation about AI ethics"}}}}
]

Invalid examples (DO NOT output like these):
❌ ```json [{{"op": "add", ...}}]```
❌ Here is the JSON patch: [{{"op": "add", ...}}]
❌ {{"user": {{"name": "John"}}}} (this is not JSON Patch format)
❌ Any text before or after the JSON array

CURRENT seele.json:
{current_seele_json}

Conversations to analyze:
{messages}

JSON Patch array (remember: pure JSON array only, starting with '[' and ending with ']'):"""


def get_complete_memory_json_prompt(
    messages: str,
    current_seele_json: str,
    error_message: str,
    first_timestamp: int | None = None,
    last_timestamp: int | None = None,
) -> str:
    """Build prompt for generating complete seele.json when JSON Patch fails.

    This is used as a fallback when JSON Patch application fails.
    The LLM will generate a complete, valid seele.json that conforms to the schema.

    Args:
        messages: The conversation messages to analyze
        current_seele_json: The current seele.json content
        error_message: The error message from the failed patch attempt
        first_timestamp: Unix timestamp of first message in this conversation batch
        last_timestamp: Unix timestamp of last message in this conversation batch
    """
    from datetime import datetime
    from config import Config

    seele_data = json.loads(current_seele_json)
    bot_name = seele_data.get("bot", {}).get("name", "AI Assistant")

    # Format timestamps
    time_info = ""
    if first_timestamp and last_timestamp:
        tz = Config.TIMEZONE
        start_time = datetime.fromtimestamp(first_timestamp, tz).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        end_time = datetime.fromtimestamp(last_timestamp, tz).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        time_info = f"\n**TIME CONTEXT**: These conversations occurred between {start_time} and {end_time}. Use this temporal context when updating time-sensitive fields.\n"

    return f"""You are {bot_name}, an AI assistant. The previous JSON Patch operation failed with this error:

ERROR: {error_message}
{time_info}
Instead of generating a JSON Patch, please output a COMPLETE, VALID seele.json that:
1. Incorporates the insights from the conversations below
2. Strictly follows the seele.json schema structure
3. Maintains all existing valid data from the current seele.json
4. Only adds/updates fields with meaningful changes from the conversations

SCHEMA STRUCTURE (you MUST follow this exactly):
{{
  "bot": {{
    "name": "string",
    "gender": "string",
    "birthday": "string",
    "role": "string",
    "appearance": "string",
    "likes": ["string"],
    "dislikes": ["string"],
    "language_style": {{
      "description": "string",
      "examples": ["string"]
    }},
    "personality": {{
      "mbti": "string",
      "description": "string",
      "worldview_and_values": "string"
    }},
    "emotions_and_needs": {{
      "long_term": "string",
      "short_term": "string"
    }},
    "relationship_with_user": "string"
  }},
  "user": {{
    "name": "string",
    "gender": "string",
    "birthday": "string",
    "personal_facts": ["string"],
    "abilities": ["string"],
    "likes": ["string"],
    "dislikes": ["string"],
    "personality": {{
      "mbti": "string",
      "description": "string",
      "worldview_and_values": "string"
    }},
    "emotions_and_needs": {{
      "long_term": "string",
      "short_term": "string"
    }}
  }},
  "memorable_events": [
    {{
      "time": "YYYY-MM-DD",
      "details": "string"
    }}
  ],
  (NOTE: MAXIMUM 20 events in memorable_events array - prioritize most important/recent events)
  "commands_and_agreements": ["string"]
}}

CURRENT seele.json:
{current_seele_json}

Conversations to analyze:
{messages}

CRITICAL OUTPUT REQUIREMENTS:
1. Output MUST be a complete, valid JSON object (not a patch array)
2. DO NOT wrap output in ```json ``` or any other formatting
3. The first character MUST be '{{' and the last character MUST be '}}'
4. ALL fields from the schema MUST be present (use empty strings/arrays if no data)
5. **CRITICAL JSON SYNTAX RULES - these cause parse errors if violated:**
   - All strings MUST be enclosed in double quotes (")
   - Escape special characters in strings: \\" for quotes, \\\\ for backslashes, \\n for newlines
   - NO trailing commas after last item in objects or arrays
   - All property names MUST be quoted strings
   - Every opening brace/bracket must have a matching closing brace/bracket
   - Multi-line strings are NOT allowed - use \\n for line breaks within strings
6. **LANGUAGE REQUIREMENT: All text values MUST use the SAME LANGUAGE as the main language used in the conversations**
   - If conversations are primarily in Chinese, all text fields should be in Chinese
   - If conversations are primarily in English, all text fields should be in English
7. Focus on ADJUSTING the content to conform to the schema rather than keeping invalid structures
8. **IMPORTANT: memorable_events array MUST NOT exceed 20 events**
   - If current seele.json already has 20 events and you need to add new ones, remove less important/older events first
   - Prioritize events that are: more recent, more significant, more relevant to the relationship

Complete seele.json (remember: pure JSON object only, starting with '{{' and ending with '}}'):"""
