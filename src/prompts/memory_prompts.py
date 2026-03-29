"""Prompt builders for memory and summary generation."""

import json
from typing import Any, Dict, Optional

from utils.time import format_timestamp_range


def build_summary_prompt(
    seele_data: Dict[str, Any],
    existing_summary: Optional[str],
    new_conversations: str,
) -> str:
    """Build summary generation prompt."""
    bot_name = seele_data.get("bot", {}).get("name", "AI Assistant")
    user_name = seele_data.get("user", {}).get("name", "User")

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

---

Summary:"""


def build_memory_update_prompt(
    messages: str,
    current_seele_json: str,
    timezone: Any,
    first_timestamp: Optional[int] = None,
    last_timestamp: Optional[int] = None,
) -> str:
    """Build memory update prompt that generates a JSON Patch."""
    seele_data = json.loads(current_seele_json)
    bot_name = seele_data.get("bot", {}).get("name", "AI Assistant")
    user_name = seele_data.get("user", {}).get("name", "User")

    time_info = ""
    if first_timestamp and last_timestamp:
        start_time, end_time = format_timestamp_range(
            first_timestamp,
            last_timestamp,
            tz=timezone,
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
- /memorable_events (object keyed by stable event ids)
  - Each key is a stable event id like "evt_20260329_project_commitment"
  - Each value is: {{"date": "YYYY-MM-DD", "importance": 1-5, "details": "string"}}
  - Use only lowercase ASCII letters, digits, and underscores in event ids
  - NEVER use numeric array indexes for memorable_events paths
  **IMPORTANCE SCORING POLICY:**
  - 1 = keep for 1 day; short-lived daily events with little lasting significance
  - 2 = keep for 1 week; mildly notable but still short-term events
  - 3 = keep for 1 month; meaningfully memorable events with medium-term value
  - 4 = keep for 6 months; important milestones, breakthroughs, or relationship shifts
  - 5 = keep permanently; identity-shaping, deeply meaningful, or enduring landmark events
  - Importance scores MAY change later when the meaning of an event becomes clearer
  - You should raise importance if a previously ordinary event later proves important
  - You should lower importance if an event turns out to be less lasting than first expected
  **HOW TO TELL MEMORABLE EVENTS APART FROM TODO ITEMS:**
  - Memorable events are primarily about the user's life, life changes, losses, gains, breakthroughs, routines that become meaningful, and the development or change of the relationship between user and {bot_name}
  - Memorable events are NOT the same as reminders, schedules, meetings, shopping lists, errands, or temporary tasks
  - If something is mainly a task to be completed, it should NOT be stored in seele.json as a memorable event
  - Tasks and reminders should be handled by scheduling/task logic, not by long-term memory storage in seele.json
  - Ask yourself: will this still matter as part of the user's life story or relationship development after days, weeks, or months?
  **IMPORTANCE EXAMPLES:**
  - 1 example: "User casually mentioned what they ate tonight" -> trivial daily detail, usually not worth storing at all; if stored, only very short retention
  - 2 example: "User is preparing for a presentation later this week" -> short-term notable situation, but not an enduring life milestone
  - 3 example: "User started a new project that is likely to matter for the next few weeks" -> medium-term meaningful development
  - 4 example: "User officially started a new job" or "user and {bot_name} established a new long-term collaboration pattern" -> important life or relationship milestone
  - 5 example: "User explicitly said they want to keep growing together with {bot_name} for a long time" -> enduring relationship-defining milestone
  **BOUNDARY EXAMPLES:**
  - "Remind me tomorrow at 3pm to join a meeting" -> NOT a memorable event; it is a task/reminder
  - "I am upset today" -> usually NOT a memorable event by itself; better for short_term emotions unless tied to a major life event
  - "My old cat passed away today" -> IS a memorable event; important life event, likely importance 4 or 5
  - "Today I told you I trust you with things I do not tell others" -> IS a memorable event; relationship deepening, likely importance 4 or 5
  **UPGRADE / DOWNGRADE EXAMPLES:**
  - Upgrade example: an event first stored as importance 2 because it looked like an ordinary project discussion may later become importance 4 or 5 if it turns out to be the start of a major long-term collaboration
  - Downgrade example: an event first stored as importance 4 may later be reduced to 2 or removed if it turns out to be only a short-lived phase with little lasting significance
  **IMPORTANT UPDATE GUIDELINES for memorable_events:**
  - **Be selective**: Only keep events worth commemorating; ignore daily trivial matters.
  - **Prefer updating existing ids** when refining the meaning, date certainty, importance, or details of an existing event.
  - **Create a new id only for a genuinely new memorable event.**
  - **Merge & Synthesize**: If multiple entries describe the same evolving event, keep one stable id and update it.
  - **Conciseness**: Keep event details brief but evocative.
  - **Prefer simple updates over complex rewrites**: when possible, either update one clearly matching existing event id or add one clearly new event id; avoid unnecessary large-scale restructuring
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
5a. For memorable_events, paths must use stable ids, e.g. "/memorable_events/evt_20260329_project_commitment/details"
6. Only update fields with meaningful changes from the conversation
7. Keep basic personality traits stable, only integrate new experiences
8. Be concise - don't change too much at once
9. **IMPORTANT: Consider using "remove" operations when:**
   - Information becomes outdated (e.g., old short_term emotions/needs)
   - User explicitly corrects or retracts previous information
   - Preferences or facts are no longer relevant
   - Duplicate or contradictory entries exist in arrays
   - Re-score event importance when the event's lasting significance changes over time
10. **LANGUAGE REQUIREMENT: All text values in the JSON patch MUST use the SAME LANGUAGE as the main language used in the conversations**
    - If conversations are primarily in Chinese, all "value" fields should be in Chinese
    - If conversations are primarily in English, all "value" fields should be in English
    - This applies to all text fields: descriptions, facts, events, etc.

Valid examples (this is how your entire response should look):

Example 1 - Adding new facts and events:
[
  {{"op": "add", "path": "/user/personal_facts/-", "value": "Enjoys programming in Python"}},
  {{"op": "add", "path": "/user/personal_facts/-", "value": "Has a cat named Whiskers"}},
  {{"op": "add", "path": "/memorable_events/evt_20260128_ai_project_ideas", "value": {{"date": "2026-01-28", "importance": 3, "details": "User shared their new AI project ideas"}}}}
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
  {{"op": "replace", "path": "/memorable_events/evt_20260128_ai_project_ideas/importance", "value": 4}}
]

Example 4 - Removing outdated memorable event by id:
[
  {{"op": "remove", "path": "/memorable_events/evt_20260103_brief_daily_note"}}
]

Example 5 - Updating event meaning over time:
[
  {{"op": "replace", "path": "/memorable_events/evt_20260128_ai_project_ideas/details", "value": "User shared AI project ideas that later became an ongoing long-term collaboration plan"}},
  {{"op": "replace", "path": "/memorable_events/evt_20260128_ai_project_ideas/importance", "value": 5}}
]

Example 6 - A reminder/task should not be stored in seele.json as a memorable event:
[]

Invalid examples (DO NOT output like these):
❌ ```json [{{"op": "add", ...}}]```
❌ Here is the JSON patch: [{{"op": "add", ...}}]
❌ {{"user": {{"name": "John"}}}} (this is not JSON Patch format)
❌ {{"op": "replace", "path": "/memorable_events/0/details", ...}} (never use numeric indexes for memorable_events)
❌ Any text before or after the JSON array

CURRENT seele.json:
{current_seele_json}

Conversations to analyze:
{messages}

JSON Patch array (remember: pure JSON array only, starting with '[' and ending with ']'):"""


def build_complete_memory_json_prompt(
    messages: str,
    current_seele_json: str,
    error_message: str,
    timezone: Any,
    first_timestamp: Optional[int] = None,
    last_timestamp: Optional[int] = None,
) -> str:
    """Build prompt for generating complete seele.json when JSON Patch fails."""
    seele_data = json.loads(current_seele_json)
    bot_name = seele_data.get("bot", {}).get("name", "AI Assistant")

    time_info = ""
    if first_timestamp and last_timestamp:
        start_time, end_time = format_timestamp_range(
            first_timestamp,
            last_timestamp,
            tz=timezone,
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
  "memorable_events": {{
    "evt_example_id": {{
      "date": "YYYY-MM-DD",
      "importance": 3,
      "details": "string"
    }}
  }},
  **IMPORTANT UPDATE GUIDELINES for memorable_events:**
  - **Be selective**: Only keep events worth commemorating; ignore daily trivial matters.
  - **Use stable event ids as object keys**; do not use arrays or numeric indexes.
  - **Importance scoring**: 1=1 day, 2=1 week, 3=1 month, 4=6 months, 5=permanent.
  - **Memorable events are mainly about the user's life and the development or change of the relationship with {bot_name}, not ordinary tasks or reminders.**
  - **Do not store todo items, reminders, meeting schedules, shopping lists, or temporary errands in seele.json unless they clearly mark an important life milestone.**
  - **Importance may change over time** if later context shows the event is more or less significant than originally thought.
  - **Importance examples**:
    - 1: a very minor short-lived daily detail, if worth storing at all
    - 2: a short-term notable situation that may matter for a few days
    - 3: a meaningful life development likely to matter for weeks
    - 4: an important life milestone or clear relationship shift
    - 5: a lasting relationship-defining or identity-shaping event
  - **Boundary examples**:
    - "Remind me tomorrow to call someone" is not a memorable event and should not be written into seele.json
    - "I trust you with things I tell no one else" is a memorable relationship event and likely deserves high importance
    - "My pet died today" is a memorable life event and likely deserves high importance
  - **Merge & Synthesize**: Keep one stable id for the same underlying event and update it over time.
  - **Prefer simple, high-confidence updates** rather than complicated large-scale rewrites of many events.
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
8. Preserve meaningful memorable events over time while still re-scoring or removing events that become outdated or less relevant.

Complete seele.json (remember: pure JSON object only, starting with '{{' and ending with '}}'):"""
