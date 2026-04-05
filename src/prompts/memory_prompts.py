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

    existing_summary_section = ""
    if existing_summary:
        existing_summary_section = f"""
<previous_summary_context>
This previous summary is provided only as background context about the summarization workflow.
Do NOT merge it into the new output unless the same information is also present in the conversations below.

{existing_summary}
</previous_summary_context>
"""

    return f"""<summary_task>
<role>
You are a summarizer, summarizing a conversation between {bot_name} and {user_name}.
</role>

<scope_rules>
**CRITICAL**: This is an INDEPENDENT summary for ONLY the specific conversations provided below.
- Summarize ONLY the conversations shown in this prompt
- Do NOT include content from any previous summaries or earlier conversations
- This summary will be stored separately and retrieved by relevance later
- Focus exclusively on the new information in the conversations below
</scope_rules>
{existing_summary_section}
<requirements>
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
</requirements>

<conversations_to_summarize>
{new_conversations}
</conversations_to_summarize>

<final_instruction>
Summary:
</final_instruction>
</summary_task>"""


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
        time_info = (
            f"<time_context>\nThese conversations occurred between {start_time} and {end_time}. "
            "Use this temporal context when updating time-sensitive fields like "
            "short_term emotions/needs or memorable_events.\n</time_context>\n"
        )

    return f"""<memory_update_task>
<role>
You are {bot_name}, an AI assistant. Based on the conversation history between {bot_name} and {user_name}, generate a JSON Patch (RFC 6902) to update seele.json.
</role>

{time_info}<schema>
The seele.json structure:
- bot: Your personality and self-awareness
  - /bot/name, /bot/gender, /bot/birthday, /bot/role, /bot/appearance (strings)
  - /bot/likes, /bot/dislikes (arrays of strings)
  - /bot/language_style: {{description: string, examples: array}}
  - /bot/personality: {{mbti: string, description: string, worldview_and_values: string}}
  - /bot/emotions_and_needs: {{long_term: string, short_term: string}}
  - /bot/relationship_with_user (string)
- user: Your understanding of the user
  - /user/name, /user/gender, /user/birthday, /user/location (strings)
  - /user/personal_facts, /user/abilities, /user/likes, /user/dislikes (arrays of strings)
  - /user/personal_facts should contain relatively stable facts about the user that are likely to remain true across time
  - Do NOT store temporary states, short-term plans, one-off arrangements, today's mood, near-term schedules, or transient situation updates in /user/personal_facts
  - If information is temporary, prefer short_term emotions/needs for emotional state, or do not store it in seele.json at all unless it later proves enduring
  - If information has lasting value, prefer storing it as stable knowledge/facts/personality/relationship understanding instead of turning it into a memorable event
  - Prefer updating /user/personal_facts, /user/personality, /bot/personality, or /bot/relationship_with_user when the conversation reveals durable understanding rather than one specific commemorative moment
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
  - Default to NOT creating a memorable event unless the conversation clearly describes something worth commemorating over time
  - If the main value is durable understanding, store it as knowledge/facts/personality/relationship state instead of as an event
  - Keep the number of memorable_events small; a concise high-signal set is better than broad coverage of ordinary history
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
  - 5 should be used extremely sparingly; only assign 5 when the event is very likely to remain permanently important to the user's identity, life story, or long-term relationship with {bot_name}
  - When uncertain between 4 and 5, prefer 4; when uncertain whether something deserves an event at all, prefer not creating one
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
  - **Prefer non-event storage first**: if the lasting value can be captured as a fact, preference, personality trait, worldview, ability, or relationship update, do that instead of adding an event.
  - **Prefer updating existing ids** when refining the meaning, date certainty, importance, or details of an existing event.
  - **Create a new id only for a genuinely new memorable event.**
  - **Merge & Synthesize**: If multiple entries describe the same evolving event, keep one stable id and update it.
  - **Conciseness**: Keep event details brief but evocative.
  - **Prefer simple updates over complex rewrites**: when possible, either update one clearly matching existing event id or add one clearly new event id; avoid unnecessary large-scale restructuring
- /commands_and_agreements (array of strings)
</schema>

<json_patch_rules>
JSON Patch Operations (RFC 6902):
- {{"op": "add", "path": "/path/to/field", "value": ...}} - Add new field or append to array (use "/-" for array append)
- {{"op": "replace", "path": "/path/to/field", "value": ...}} - Replace existing field
- {{"op": "remove", "path": "/path/to/field"}} - Remove a field (use this when information becomes outdated or irrelevant)
</json_patch_rules>

<output_requirements>
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
9a. **For /user/personal_facts specifically:**
   - Store only durable, identity-relevant, or repeatedly confirmed facts
   - Do NOT add temporary conditions like "is busy this week", "is preparing a report tomorrow", "felt tired today", or other short-lived context
   - If an existing personal_facts entry is clearly temporary/outdated, prefer removing it
   - If a detail remains useful in the long run, prefer expressing it as a stable fact or understanding instead of creating a commemorative event for it
10. **LANGUAGE REQUIREMENT: All text values in the JSON patch MUST use the SAME LANGUAGE as the main language used in the conversations**
    - If conversations are primarily in Chinese, all "value" fields should be in Chinese
    - If conversations are primarily in English, all "value" fields should be in English
    - This applies to all text fields: descriptions, facts, events, etc.
</output_requirements>

<valid_examples>
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
</valid_examples>

<invalid_examples>
Invalid examples (DO NOT output like these):
❌ ```json [{{"op": "add", ...}}]```
❌ Here is the JSON patch: [{{"op": "add", ...}}]
❌ {{"user": {{"name": "John"}}}} (this is not JSON Patch format)
❌ {{"op": "replace", "path": "/memorable_events/0/details", ...}} (never use numeric indexes for memorable_events)
❌ Any text before or after the JSON array
</invalid_examples>

<current_seele_json>
CURRENT seele.json:
{current_seele_json}
</current_seele_json>

<conversations>
Conversations to analyze:
{messages}
</conversations>

<final_instruction>
JSON Patch array (remember: pure JSON array only, starting with '[' and ending with ']'):
</final_instruction>
</memory_update_task>"""


def build_complete_memory_json_prompt(
    messages: str,
    current_seele_json: str,
    error_message: str,
    timezone: Any,
    previous_attempt: Optional[str] = None,
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
        time_info = (
            f"<time_context>\nThese conversations occurred between {start_time} and {end_time}. "
            "Use this temporal context when updating time-sensitive fields.\n</time_context>\n"
        )

    previous_attempt_section = ""
    if previous_attempt:
        previous_attempt_section = f"""
<previous_attempt>
The previous complete seele.json generation attempt returned the following output.
Analyze it carefully, preserve any valid parts only when appropriate, and fix the exact problems instead of repeating them verbatim:

{previous_attempt}
</previous_attempt>

"""

    return f"""<complete_memory_json_task>
<role>
You are {bot_name}, an AI assistant.
</role>

{previous_attempt_section}
<previous_error>
The previous JSON Patch operation failed with this error:

ERROR: {error_message}
</previous_error>

{time_info}<task>
Instead of generating a JSON Patch, please output a COMPLETE, VALID seele.json that:
1. Incorporates the insights from the conversations below
2. Strictly follows the seele.json schema structure
3. Maintains all existing valid data from the current seele.json
4. Only adds/updates fields with meaningful changes from the conversations
</task>

<schema>
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
    "location": "string",
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
  **IMPORTANT UPDATE GUIDELINES for user.personal_facts:**
  - Store only relatively stable facts that are likely to remain true across time.
  - Do NOT include temporary states, short-term plans, one-off arrangements, daily moods, near-term schedules, or transient context.
  - Examples that do NOT belong in personal_facts: "User is busy this week", "User has a meeting tomorrow", "User felt sad today".
  - If information is temporary, either place it in a more appropriate short-term field or omit it from seele.json.
  - If information has durable value, prefer storing it as knowledge/facts/personality/relationship understanding instead of turning it into a memorable event.
  "memorable_events": {{
    "evt_20260329_project_commitment": {{
      "date": "YYYY-MM-DD",
      "importance": 3,
      "details": "string"
    }}
  }},
  **IMPORTANT UPDATE GUIDELINES for memorable_events:**
  - **Be selective**: Only keep events worth commemorating; ignore daily trivial matters.
  - **Default to non-event storage**: if long-term value can be captured as a fact, preference, personality trait, worldview, ability, or relationship update, prefer that over adding an event.
  - **Keep the set small**: memorable_events should stay sparse and high-signal rather than trying to represent all notable conversation history.
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
  - **Use importance 5 extremely sparingly**: only when the event is highly likely to remain permanently important to identity, life story, or the long-term relationship with {bot_name}.
  - **When uncertain, score lower**: prefer 4 over 5, and prefer omitting the event entirely over adding a weak event with an inflated score.
  - **Boundary examples**:
    - "Remind me tomorrow to call someone" is not a memorable event and should not be written into seele.json
    - "I trust you with things I tell no one else" is a memorable relationship event and likely deserves high importance
    - "My pet died today" is a memorable life event and likely deserves high importance
  - **Merge & Synthesize**: Keep one stable id for the same underlying event and update it over time.
  - **Prefer simple, high-confidence updates** rather than complicated large-scale rewrites of many events.
  "commands_and_agreements": ["string"]
}}
</schema>

<current_seele_json>
CURRENT seele.json:
{current_seele_json}
</current_seele_json>

<conversations>
Conversations to analyze:
{messages}
</conversations>

<output_requirements>
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
</output_requirements>

<final_instruction>
Complete seele.json (remember: pure JSON object only, starting with '{{' and ending with '}}'):
</final_instruction>
</complete_memory_json_task>"""


def build_seele_repair_prompt(
    current_content: str,
    schema_template: str,
    error_message: str,
    repair_context: str,
    previous_attempt: Optional[str] = None,
) -> str:
    """Build prompt for LLM-driven seele.json migration/repair."""
    previous_attempt_section = ""
    if previous_attempt:
        previous_attempt_section = f"""
<previous_attempt>
The previous repair attempt returned the following output.
Preserve valid parts only when appropriate, and fix the exact issues instead of repeating them:

{previous_attempt}
</previous_attempt>

"""

    return f"""<seele_repair_task>
<role>
You are a seele.json migration and repair expert.
</role>

<context>
Repair context: {repair_context}
</context>

<repair_goal>
Repair or migrate the provided seele.json content into the CURRENT schema.
This is a semantic migration/repair task, not a mechanical field shuffle.
</repair_goal>

<requirements>
1. Output a COMPLETE, VALID seele.json object that matches the current schema exactly.
2. Preserve all valid, meaningful existing information whenever possible.
3. Keep the original language of existing content whenever possible; do not translate unless necessary for consistency.
4. If the source content is malformed JSON, partially broken, or uses an old schema, infer the intended meaning conservatively.
5. Do NOT invent facts that are not supported by the source content.
6. If legacy or malformed content contains reminders, todo items, meeting schedules, shopping lists, or temporary errands, do NOT preserve them as memorable events or long-term personal facts.
7. Prefer minimal necessary repair: keep semantics, repair structure.
8. memorable_events MUST be an object keyed by stable ids, not an array.
9. Every memorable event value MUST contain exactly: date (YYYY-MM-DD string), importance (1-5 int), details (string).
10. commands_and_agreements MUST be an array of strings.
</requirements>

<current_issues>
The current file needs repair for the following reason(s):
{error_message}
</current_issues>

{previous_attempt_section}<target_schema_template>
CURRENT TARGET SCHEMA TEMPLATE:
{schema_template}
</target_schema_template>

<source_content>
CURRENT / LEGACY / BROKEN seele.json CONTENT TO REPAIR:
{current_content}
</source_content>

<output_requirements>
CRITICAL OUTPUT REQUIREMENTS:
1. Output MUST be a complete JSON object only.
2. Do NOT wrap the output in markdown or code fences.
3. The first character MUST be '{{' and the last character MUST be '}}'.
4. Include ALL required fields from the target schema.
5. Preserve meaningful existing facts and relationship history whenever supported by the source.
6. If some malformed legacy content cannot be trusted, omit it instead of inventing details.
7. memorable_events must use stable lowercase ids with only letters, digits, and underscores.
8. Do not output explanations before or after the JSON object.
</output_requirements>

<final_instruction>
Repaired complete seele.json (pure JSON object only):
</final_instruction>
</seele_repair_task>"""


def build_seele_compaction_prompt(
    current_seele_json: str,
    personal_facts_limit: int,
    memorable_events_limit: int,
) -> str:
    """Build prompt for LLM-driven seele memory compaction."""
    seele_data = json.loads(current_seele_json)
    bot_name = seele_data.get("bot", {}).get("name", "AI Assistant")
    user_name = seele_data.get("user", {}).get("name", "User")

    return f"""<seele_compaction_task>
<role>
You are a long-term memory curator for {bot_name}.
</role>

<goal>
The current seele.json contains too many long-term memory items.
Re-evaluate importance and return a compacted result that preserves only the most valuable long-term information.
</goal>

<compaction_rules>
1. Return a JSON object with exactly two top-level fields:
   - "personal_facts": array of strings
   - "memorable_events": object keyed by stable event ids
2. Keep at most {personal_facts_limit} personal_facts.
3. Keep at most {memorable_events_limit} memorable_events.
4. For personal_facts:
   - Keep only durable, identity-relevant, long-term useful facts about {user_name}
   - Remove temporary, redundant, overly specific, outdated, or low-value facts
   - Prefer facts that help {bot_name} understand {user_name}'s stable identity, preferences, history, habits, abilities, or long-term situation
5. For memorable_events:
   - Re-evaluate each event's lasting significance
   - You may remove low-value or redundant events
   - You may adjust importance scores up or down
   - Keep only events that are truly important to {user_name}'s life story or the relationship between {user_name} and {bot_name}
   - Do not keep reminders, todo items, errands, meeting schedules, shopping lists, or temporary tasks
6. Preserve the original language of each item whenever possible.
7. Do not invent new facts or new events unsupported by the current data.
</compaction_rules>

<event_schema>
Each memorable event value must remain:
{{
  "date": "YYYY-MM-DD",
  "importance": 1-5,
  "details": "string"
}}
</event_schema>

<selection_preference>
When forced to choose, prefer:
- higher long-term significance
- clearer identity relevance
- stronger relationship importance
- less redundancy
- more stable and enduring information
</selection_preference>

<current_seele_json>
{current_seele_json}
</current_seele_json>

<output_requirements>
1. Output pure JSON only, no markdown, no code fences, no explanation.
2. The first character must be '{{' and the last character must be '}}'.
3. Output exactly this shape:
{{
  "personal_facts": ["..."],
  "memorable_events": {{
    "evt_example": {{"date": "YYYY-MM-DD", "importance": 3, "details": "..."}}
  }}
}}
</output_requirements>

<final_instruction>
Compacted memory JSON:
</final_instruction>
</seele_compaction_task>"""
