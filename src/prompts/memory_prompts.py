"""Prompt builders for memory and summary generation."""

import json
from datetime import datetime
from typing import Any, Dict, Optional


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
        start_time = datetime.fromtimestamp(first_timestamp, timezone).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        end_time = datetime.fromtimestamp(last_timestamp, timezone).strftime(
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
  **CRITICAL LIMIT: Maximum 20 events. This is a hard limit.**
  **When adding new events would exceed this limit, you MUST remove less important or redundant events first.**
  **IMPORTANT UPDATE GUIDELINES for memorable_events:**
  - **Be selective**: Only keep events worth commemorating; ignore daily trivial matters.
  - **Merge & Synthesize**: Proactively merge events from the same day or related themes. If a new event is a continuation of an old one, update the old entry instead of adding a new one.
  - **Prioritize Significance**: If at the 20-event limit, you must make a trade-off. Delete the least significant events (even if they are recent) to make room for truly memorable milestones.
  - **Conciseness**: Keep event details brief but evocative.
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
   - **CRITICAL for /memorable_events: MAXIMUM 20 events allowed. (STRICT LIMIT: Merge, synthesize, or delete less significant events to stay under 20.)**
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

Example 5 - Managing memorable_events limit (max 20 events) - Merging/Removing to stay under limit:
[
  {{"op": "remove", "path": "/memorable_events/0"}},
  {{"op": "replace", "path": "/memorable_events/5/details", "value": "Updated details merging previous event with new insights"}},
  {{"op": "add", "path": "/memorable_events/-", "value": {{"time": "2026-01-28", "details": "Highly significant milestone achieved today"}}}}
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
        start_time = datetime.fromtimestamp(first_timestamp, timezone).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        end_time = datetime.fromtimestamp(last_timestamp, timezone).strftime(
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
  (NOTE: MAXIMUM 20 events in memorable_events array - STRICT LIMIT.)
  **IMPORTANT UPDATE GUIDELINES for memorable_events:**
  - **Be selective**: Only keep events worth commemorating; ignore daily trivial matters.
  - **Merge & Synthesize**: Proactively merge events from the same day or related themes. Update existing entries to incorporate new developments.
  - **Make Trade-offs**: If at the 20-event limit, prioritize the most significant milestones. Delete the least important ones to maintain the limit.
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
8. **CRITICAL: memorable_events array MUST NOT exceed 20 events (STRICT LIMIT).**
   - **Merge & Synthesize**: Proactively merge related events or those on the same day.
   - **Make Trade-offs**: If you need to add a significant new event but are at the limit, you MUST delete the least significant existing event to make room.
   - Prioritize events that represent major relationship milestones or identity-shaping experiences.

Complete seele.json (remember: pure JSON object only, starting with '{{' and ending with '}}'):"""
