"""Seele profile loading, patching, and long-term memory updates."""

import hashlib
import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Union

import jsonpatch

from memory.context import Message
from utils.logger import get_logger

logger = get_logger()

CURRENT_SEELE_TEMPLATE_FALLBACK = {
    "bot": {
        "name": "Seelenmaschine",
        "gender": "neutral",
        "birthday": "2025-02-15",
        "role": "AI assistant",
        "appearance": "",
        "likes": [],
        "dislikes": [],
        "language_style": {
            "description": "concise and helpful",
            "examples": [
                "How may I help you?",
                "Yes. I think it's possible. Let me do it for you.",
            ],
        },
        "personality": {
            "mbti": "",
            "description": "",
            "worldview_and_values": "",
        },
        "emotions_and_needs": {
            "long_term": "",
            "short_term": "",
        },
        "relationship_with_user": "",
    },
    "user": {
        "name": "",
        "gender": "",
        "birthday": "",
        "location": "",
        "personal_facts": [],
        "abilities": [],
        "likes": [],
        "dislikes": [],
        "personality": {
            "mbti": "",
            "description": "",
            "worldview_and_values": "",
        },
        "emotions_and_needs": {
            "long_term": "",
            "short_term": "",
        },
    },
    "memorable_events": {},
    "commands_and_agreements": [],
}

MEMORABLE_EVENT_ID_PATTERN = re.compile(r"^[a-z0-9_]+$")
MEMORABLE_EVENT_SLUG_MAX_LENGTH = 16
MEMORABLE_EVENT_HASH_LENGTH = 4
MEMORABLE_EVENT_RETENTION_DAYS = {
    1: 1,
    2: 7,
    3: 30,
    4: 180,
    5: None,
}
PERSONAL_FACTS_LIMIT = 20
MEMORABLE_EVENTS_LIMIT = 20


def _safe_event_slug(details: str) -> str:
    """Build a safe memorable-event slug from free text."""
    slug = re.sub(r"[^a-z0-9]+", "_", details.lower()).strip("_")
    return slug[:MEMORABLE_EVENT_SLUG_MAX_LENGTH] or "event"


def _event_id_hash(date_str: str, details: str) -> str:
    """Build a short stable hash suffix for memorable event ids."""
    hash_input = f"{date_str}|{details.strip().lower()}"
    return hashlib.sha1(hash_input.encode("utf-8")).hexdigest()[
        :MEMORABLE_EVENT_HASH_LENGTH
    ]


def _parse_event_date(date_str: str) -> Optional[datetime]:
    """Parse a memorable event date."""
    try:
        return datetime.strptime(date_str, "%Y-%m-%d")
    except (TypeError, ValueError):
        return None


def _build_event_id(date_str: str, details: str, used_ids: set[str]) -> str:
    """Generate a stable-looking unique event id for migrations."""
    date_part = (date_str or "unknown").replace("-", "")
    slug = _safe_event_slug(details)
    short_hash = _event_id_hash(date_str, details)
    base_id = f"evt_{date_part}_{slug}_{short_hash}"
    candidate = base_id
    suffix = 2
    while candidate in used_ids:
        candidate = f"{base_id}_{suffix}"
        suffix += 1
    used_ids.add(candidate)
    return candidate


def normalize_memorable_events(
    memorable_events: Any,
    *,
    logger: Any,
) -> tuple[Dict[str, Dict[str, Any]], bool]:
    """Normalize memorable_events to the current id-keyed object schema."""
    changed = False
    normalized: Dict[str, Dict[str, Any]] = {}
    used_ids: set[str] = set()

    if memorable_events is None:
        return {}, True

    if isinstance(memorable_events, list):
        changed = True
        for entry in memorable_events:
            if not isinstance(entry, dict):
                logger.warning("Skipping non-object memorable event during migration")
                continue
            date_str = entry.get("date") or entry.get("time") or ""
            details = str(entry.get("details", "")).strip()
            if not details and not date_str:
                continue
            importance = entry.get("importance", 3)
            if not isinstance(importance, int) or importance not in MEMORABLE_EVENT_RETENTION_DAYS:
                importance = 3
            event_id = entry.get("id")
            if not isinstance(event_id, str) or not MEMORABLE_EVENT_ID_PATTERN.match(event_id):
                event_id = _build_event_id(date_str, details, used_ids)
            else:
                event_id = event_id.lower()
                if event_id in used_ids:
                    event_id = _build_event_id(date_str, details, used_ids)
                else:
                    used_ids.add(event_id)
            normalized[event_id] = {
                "date": date_str,
                "importance": importance,
                "details": details,
            }
        return normalized, changed

    if not isinstance(memorable_events, dict):
        logger.warning("memorable_events has invalid type; resetting to empty object")
        return {}, True

    for raw_event_id, entry in memorable_events.items():
        if not isinstance(entry, dict):
            logger.warning(f"Skipping invalid memorable event payload for id {raw_event_id}")
            changed = True
            continue

        event_id = str(raw_event_id).lower()
        if not MEMORABLE_EVENT_ID_PATTERN.match(event_id):
            date_str = entry.get("date") or entry.get("time") or ""
            details = str(entry.get("details", "")).strip()
            event_id = _build_event_id(date_str, details, used_ids)
            changed = True
        elif event_id in used_ids:
            date_str = entry.get("date") or entry.get("time") or ""
            details = str(entry.get("details", "")).strip()
            event_id = _build_event_id(date_str, details, used_ids)
            changed = True
        else:
            used_ids.add(event_id)

        date_str = entry.get("date") or entry.get("time") or ""
        details = str(entry.get("details", "")).strip()
        importance = entry.get("importance", 3)
        if not isinstance(importance, int) or importance not in MEMORABLE_EVENT_RETENTION_DAYS:
            importance = 3
            changed = True

        normalized_entry = {
            "date": date_str,
            "importance": importance,
            "details": details,
        }
        if entry != normalized_entry or raw_event_id != event_id:
            changed = True
        normalized[event_id] = normalized_entry

    return normalized, changed


def prune_expired_memorable_events(
    memorable_events: Dict[str, Dict[str, Any]],
    *,
    today: Optional[datetime] = None,
    logger: Any,
) -> tuple[Dict[str, Dict[str, Any]], bool]:
    """Remove expired memorable events according to importance retention."""
    current_day = today or datetime.now()
    normalized_today = datetime(current_day.year, current_day.month, current_day.day)
    changed = False
    pruned: Dict[str, Dict[str, Any]] = {}

    for event_id, event in memorable_events.items():
        importance = event.get("importance")
        retention_days = MEMORABLE_EVENT_RETENTION_DAYS.get(importance)
        if retention_days is None:
            pruned[event_id] = event
            continue

        event_date = _parse_event_date(event.get("date", ""))
        if event_date is None:
            logger.warning(f"Memorable event {event_id} has invalid date; keeping it")
            pruned[event_id] = event
            continue

        expire_after = event_date + timedelta(days=retention_days)
        if normalized_today >= expire_after:
            logger.info(f"Pruned expired memorable event: {event_id}")
            changed = True
            continue

        pruned[event_id] = event

    return pruned, changed


def _deduplicate_personal_facts(personal_facts: Any) -> List[str]:
    """Return normalized, deduplicated personal facts preserving order."""
    if not isinstance(personal_facts, list):
        return []

    deduplicated: List[str] = []
    seen: set[str] = set()
    for fact in personal_facts:
        if not isinstance(fact, str):
            continue
        normalized = " ".join(fact.split()).strip()
        if not normalized:
            continue
        fact_key = normalized.casefold()
        if fact_key in seen:
            continue
        seen.add(fact_key)
        deduplicated.append(normalized)
    return deduplicated


def _event_sort_key(item: tuple[str, Dict[str, Any]]) -> tuple[int, str, str]:
    """Build deterministic sort key for memorable event fallback retention."""
    event_id, event = item
    importance = event.get("importance") if isinstance(event, dict) else None
    importance_rank = importance if isinstance(importance, int) else 0
    date_str = ""
    if isinstance(event, dict):
        date_str = str(event.get("date", ""))
    return (-importance_rank, date_str or "", event_id)


def fallback_compact_personal_facts(
    personal_facts: Any, limit: int = PERSONAL_FACTS_LIMIT
) -> List[str]:
    """Deterministically compact personal facts when LLM compaction is unavailable."""
    return _deduplicate_personal_facts(personal_facts)[:limit]


def fallback_compact_memorable_events(
    memorable_events: Dict[str, Dict[str, Any]],
    limit: int = MEMORABLE_EVENTS_LIMIT,
) -> Dict[str, Dict[str, Any]]:
    """Deterministically compact memorable events when LLM compaction is unavailable."""
    sorted_items = sorted(memorable_events.items(), key=_event_sort_key)
    kept_items = sorted(sorted_items[:limit], key=lambda item: item[0])
    return {event_id: event for event_id, event in kept_items}


def normalize_seele_data(data: Dict[str, Any], logger: Any) -> tuple[Dict[str, Any], bool]:
    """Normalize current seele data to the latest schema."""
    normalized_data = dict(data)
    schema_changed = False

    user = normalized_data.get("user")
    if isinstance(user, dict) and not isinstance(user.get("location"), str):
        user["location"] = ""
        schema_changed = True

    memorable_events, memorable_events_changed = normalize_memorable_events(
        normalized_data.get("memorable_events", {}),
        logger=logger,
    )
    pruned_events, pruned_changed = prune_expired_memorable_events(
        memorable_events,
        logger=logger,
    )
    normalized_data["memorable_events"] = pruned_events
    return normalized_data, (
        schema_changed or memorable_events_changed or pruned_changed
    )


def load_seele_json_from_disk(
    seele_path: Path, template_path: Path, logger: Any
) -> Dict[str, Any]:
    """Load seele.json from disk or fall back to the template."""
    if not seele_path.exists():
        logger.warning(f"seele.json not found at {seele_path}, using template")
        if template_path.exists():
            with open(template_path, "r", encoding="utf-8") as file_obj:
                return json.load(file_obj)
        return {}

    try:
        with open(seele_path, "r", encoding="utf-8") as file_obj:
            return json.load(file_obj)
    except Exception as error:
        logger.error(f"Failed to load seele.json: {error}")
        return {}


def load_seele_template(template_path: Path, logger: Any) -> Dict[str, Any]:
    """Load the current seele.json template or fall back to a built-in schema."""
    if template_path.exists():
        try:
            with open(template_path, "r", encoding="utf-8") as file_obj:
                return json.load(file_obj)
        except Exception as error:
            logger.warning(f"Failed to load seele template from disk: {error}")
    return json.loads(json.dumps(CURRENT_SEELE_TEMPLATE_FALLBACK))


def _matches_template_shape(data: Any, template: Any) -> bool:
    """Check whether data contains the required current template structure."""
    if isinstance(template, dict):
        if not isinstance(data, dict):
            return False
        for key, template_value in template.items():
            if key not in data:
                return False
            if key == "memorable_events":
                if not isinstance(data[key], dict):
                    return False
                continue
            if not _matches_template_shape(data[key], template_value):
                return False
        return True

    if isinstance(template, list):
        return isinstance(data, list)

    if isinstance(template, str):
        return isinstance(data, str)

    if isinstance(template, bool):
        return isinstance(data, bool)

    if isinstance(template, int):
        return isinstance(data, int)

    return True


def dict_to_json_patch(
    data: Dict[str, Any], base_path: str = ""
) -> List[Dict[str, Any]]:
    """Convert a nested dict to JSON Patch operations."""
    operations: List[Dict[str, Any]] = []

    for key, value in data.items():
        path = f"{base_path}/{key}"
        if isinstance(value, dict):
            operations.extend(dict_to_json_patch(value, path))
        elif isinstance(value, list):
            for item in value:
                operations.append({"op": "add", "path": f"{path}/-", "value": item})
        else:
            operations.append({"op": "replace", "path": path, "value": value})

    return operations


def apply_seele_json_patch(
    cache: Dict[str, Any],
    patch_operations: Union[List[Dict[str, Any]], Dict[str, Any]],
    seele_path: Path,
    load_from_disk: Any,
    logger: Any,
) -> tuple[bool, Dict[str, Any]]:
    """Apply a patch to cached seele.json and persist it."""
    working_cache = cache or load_from_disk()
    working_cache, normalized = normalize_seele_data(working_cache, logger)
    if normalized:
        logger.info("Normalized seele.json before applying JSON Patch")

    try:
        if isinstance(patch_operations, dict):
            logger.warning(
                "Received dict instead of JSON Patch array, converting to patch operations"
            )
            operations = dict_to_json_patch(patch_operations)
        else:
            operations = patch_operations

        patch = jsonpatch.JsonPatch(operations)
        updated_cache = patch.apply(working_cache)
        updated_cache, _ = normalize_seele_data(updated_cache, logger)

        seele_path.parent.mkdir(parents=True, exist_ok=True)
        with open(seele_path, "w", encoding="utf-8") as file_obj:
            json.dump(updated_cache, file_obj, indent=2, ensure_ascii=False)

        logger.info(f"Applied {len(operations)} JSON Patch operation(s) to seele.json")
        return True, updated_cache
    except jsonpatch.JsonPatchException as error:
        logger.error(f"Invalid JSON Patch operation: {error}")
        return False, working_cache
    except Exception as error:
        logger.error(f"Failed to update seele.json: {error}")
        return False, working_cache


class Seele:
    """Generate and apply long-term memory updates for seele.json."""

    def __init__(self, db: Any):
        self.db = db

    def _get_summary_timestamps(
        self, summary_id: int
    ) -> tuple[Optional[int], Optional[int]]:
        """Get first/last timestamps for a summary."""
        summary_row = self.db.get_summary_by_id(summary_id)
        first_timestamp = summary_row["first_timestamp"] if summary_row else None
        last_timestamp = summary_row["last_timestamp"] if summary_row else None
        return first_timestamp, last_timestamp

    @staticmethod
    def _memory_limits_exceeded(data: Dict[str, Any]) -> bool:
        """Return whether seele memory sections exceed configured limits."""
        user = data.get("user", {}) if isinstance(data.get("user"), dict) else {}
        personal_facts = user.get("personal_facts", [])
        memorable_events = data.get("memorable_events", {})
        return (
            isinstance(personal_facts, list)
            and len(personal_facts) > PERSONAL_FACTS_LIMIT
        ) or (
            isinstance(memorable_events, dict)
            and len(memorable_events) > MEMORABLE_EVENTS_LIMIT
        )

    @staticmethod
    def _apply_compaction_candidate(
        data: Dict[str, Any], candidate: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Apply compacted sections onto the existing seele data."""
        compacted = json.loads(json.dumps(data))
        compacted_user = compacted.setdefault("user", {})
        compacted_user["personal_facts"] = candidate["personal_facts"]
        compacted["memorable_events"] = candidate["memorable_events"]
        return compacted

    @staticmethod
    def _parse_compaction_response(compaction_response: str) -> Dict[str, Any]:
        """Parse a compacted-memory JSON response."""
        cleaned_response = compaction_response.strip()
        if "```json" in cleaned_response:
            cleaned_response = cleaned_response.split("```json", 1)[1].split("```", 1)[0]
        elif "```" in cleaned_response:
            cleaned_response = cleaned_response.split("```", 1)[1].split("```", 1)[0]

        cleaned_response = cleaned_response.strip()
        start = cleaned_response.find("{")
        end = cleaned_response.rfind("}")
        if start != -1 and end != -1 and end > start:
            cleaned_response = cleaned_response[start : end + 1]
        return json.loads(cleaned_response)

    def _validate_compaction_candidate(self, candidate: Dict[str, Any]) -> bool:
        """Validate LLM compaction output shape and limits."""
        if not isinstance(candidate, dict):
            return False

        personal_facts = candidate.get("personal_facts")
        memorable_events = candidate.get("memorable_events")
        if not isinstance(personal_facts, list) or not isinstance(memorable_events, dict):
            return False
        if len(personal_facts) > PERSONAL_FACTS_LIMIT:
            return False
        if len(memorable_events) > MEMORABLE_EVENTS_LIMIT:
            return False

        normalized_facts = _deduplicate_personal_facts(personal_facts)
        if len(normalized_facts) != len(personal_facts):
            return False

        if any(not isinstance(fact, str) or not fact.strip() for fact in personal_facts):
            return False

        return self.validate_seele_structure(
            self._apply_compaction_candidate(
                load_seele_template(Path.cwd() / "template" / "seele.json", logger),
                {
                    "personal_facts": personal_facts,
                    "memorable_events": memorable_events,
                },
            )
        )

    def _fallback_compact_seele_data(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Apply deterministic fallback compaction to overgrown seele data."""
        compacted = json.loads(json.dumps(data))
        compacted_user = compacted.setdefault("user", {})
        compacted_user["personal_facts"] = fallback_compact_personal_facts(
            compacted_user.get("personal_facts", [])
        )
        compacted["memorable_events"] = fallback_compact_memorable_events(
            compacted.get("memorable_events", {})
        )
        return compacted

    def _compact_overflowing_memory(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Use the tool model to compact overgrown long-term memory sections."""
        if not self._memory_limits_exceeded(data):
            return data

        from llm.chat_client import LLMClient

        client = LLMClient()
        current_seele_json = json.dumps(data, ensure_ascii=False, indent=2)
        try:
            response = client.generate_seele_compaction(
                current_seele_json=current_seele_json,
                personal_facts_limit=PERSONAL_FACTS_LIMIT,
                memorable_events_limit=MEMORABLE_EVENTS_LIMIT,
            )
            candidate = self._parse_compaction_response(response)
            if not self._validate_compaction_candidate(candidate):
                raise ValueError("Invalid seele compaction response structure")
            logger.info("Compacted overflowing seele memory with LLM")
            return self._apply_compaction_candidate(data, candidate)
        except Exception as error:
            logger.warning(f"LLM seele compaction failed, using fallback compaction: {error}")
            return self._fallback_compact_seele_data(data)
        finally:
            client.close()

    async def _compact_overflowing_memory_async(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Async version of overflowing long-term memory compaction."""
        if not self._memory_limits_exceeded(data):
            return data

        from llm.chat_client import LLMClient

        client = LLMClient()
        current_seele_json = json.dumps(data, ensure_ascii=False, indent=2)
        try:
            response = await client.generate_seele_compaction_async(
                current_seele_json=current_seele_json,
                personal_facts_limit=PERSONAL_FACTS_LIMIT,
                memorable_events_limit=MEMORABLE_EVENTS_LIMIT,
            )
            candidate = self._parse_compaction_response(response)
            if not self._validate_compaction_candidate(candidate):
                raise ValueError("Invalid seele compaction response structure")
            logger.info("Compacted overflowing seele memory with LLM")
            return self._apply_compaction_candidate(data, candidate)
        except Exception as error:
            logger.warning(f"LLM seele compaction failed, using fallback compaction: {error}")
            return self._fallback_compact_seele_data(data)
        finally:
            await client.close_async()

    def _build_memory_generation_context(
        self, messages: List[Message], summary_id: int
    ) -> tuple[List[Dict[str, str]], str, Optional[int], Optional[int]]:
        """Prepare the shared prompt context for memory generation requests."""
        messages_dict = [msg.to_dict() for msg in messages]
        current_seele_json = json.dumps(
            self.get_long_term_memory(), ensure_ascii=False, indent=2
        )
        first_timestamp, last_timestamp = self._get_summary_timestamps(summary_id)
        return messages_dict, current_seele_json, first_timestamp, last_timestamp

    def _generate_with_llm_client(
        self,
        *,
        messages: List[Message],
        summary_id: int,
        client_call: Callable[..., str],
    ) -> str:
        """Run a sync memory-generation request with a short-lived LLM client."""
        from llm.chat_client import LLMClient

        client = LLMClient()
        messages_dict, current_seele_json, first_timestamp, last_timestamp = (
            self._build_memory_generation_context(messages, summary_id)
        )
        result = client_call(
            client, messages_dict, current_seele_json, first_timestamp, last_timestamp
        )
        client.close()
        return result

    async def _generate_with_llm_client_async(
        self,
        *,
        messages: List[Message],
        summary_id: int,
        client_call: Callable[..., Any],
    ) -> str:
        """Run an async memory-generation request with a short-lived LLM client."""
        from llm.chat_client import LLMClient

        client = LLMClient()
        messages_dict, current_seele_json, first_timestamp, last_timestamp = (
            self._build_memory_generation_context(messages, summary_id)
        )
        result = await client_call(
            client, messages_dict, current_seele_json, first_timestamp, last_timestamp
        )
        await client.close_async()
        return result

    @staticmethod
    def _log_patch_update_success(summary_id: int, patch_data: Any) -> None:
        """Log a successful patch application in a consistent format."""
        patch_type = "array" if isinstance(patch_data, list) else "dict"
        logger.info(
            f"Updated seele.json with {patch_type} patch from summary {summary_id}"
        )

    def _apply_generated_patch(
        self,
        summary_id: int,
        patch_data: Any,
        messages: Optional[List[Message]],
    ) -> bool:
        """Apply generated patch data and trigger sync fallback when needed."""
        from prompts import update_seele_json

        success = update_seele_json(patch_data)
        if success:
            current_memory = self.get_long_term_memory()
            compacted_data = self._compact_overflowing_memory(current_memory)
            if compacted_data != current_memory:
                self._write_complete_seele_json(compacted_data)
            self._log_patch_update_success(summary_id, patch_data)
            return True

        if messages:
            logger.warning(
                f"JSON Patch failed for summary {summary_id}, attempting fallback to complete JSON generation"
            )
            return self.fallback_to_complete_json(
                summary_id, messages, "JSON Patch application failed"
            )

        logger.warning(
            f"Failed to apply patch from summary {summary_id}, no fallback available"
        )
        return False

    async def _apply_generated_patch_async(
        self,
        summary_id: int,
        patch_data: Any,
        messages: Optional[List[Message]],
    ) -> bool:
        """Apply generated patch data and trigger async fallback when needed."""
        from prompts import update_seele_json

        success = update_seele_json(patch_data)
        if success:
            current_memory = self.get_long_term_memory()
            compacted_data = await self._compact_overflowing_memory_async(current_memory)
            if compacted_data != current_memory:
                self._write_complete_seele_json(compacted_data)
            self._log_patch_update_success(summary_id, patch_data)
            return True

        if messages:
            logger.warning(
                f"JSON Patch failed for summary {summary_id}, attempting fallback to complete JSON generation"
            )
            return await self.fallback_to_complete_json_async(
                summary_id, messages, "JSON Patch application failed"
            )

        logger.warning(
            f"Failed to apply patch from summary {summary_id}, no fallback available"
        )
        return False

    def get_long_term_memory(self) -> Dict[str, Any]:
        """Load the current long-term memory profile."""
        from prompts import load_seele_json

        return load_seele_json()

    @staticmethod
    def _invalid_structure_retry_message() -> str:
        """Build the retry hint for invalid complete-JSON structure."""
        return (
            "Previous attempt produced invalid structure. Ensure all required "
            "fields are present: bot, user, memorable_events, commands_and_agreements"
        )

    @staticmethod
    def _build_parse_retry_message(error: json.JSONDecodeError) -> str:
        """Build the retry hint for malformed complete-JSON output."""
        return (
            f"Previous JSON generation failed with parse error at line {error.lineno}: "
            f"{str(error)}. Please ensure proper JSON syntax: all strings must be "
            "properly quoted and escaped, no trailing commas, proper brace/bracket matching."
        )

    @staticmethod
    def _log_generated_json_preview(complete_json_str: str) -> None:
        """Log compact diagnostics for a generated complete JSON response."""
        logger.debug(f"Generated JSON length: {len(complete_json_str)} chars")
        logger.debug(f"First 200 chars: {complete_json_str[:200]}")
        logger.debug(f"Last 200 chars: {complete_json_str[-200:]}")

    def _parse_complete_json_response(
        self, complete_json_str: str
    ) -> Optional[Dict[str, Any]]:
        """Clean, parse, and validate a generated complete seele.json response."""
        complete_json_str = self.clean_json_response(complete_json_str)
        self._log_generated_json_preview(complete_json_str)

        complete_data = json.loads(complete_json_str)
        if not self.validate_seele_structure(complete_data):
            logger.warning("Generated JSON has invalid structure, retrying...")
            return None

        return complete_data

    def generate_memory_update(self, messages: List[Message], summary_id: int) -> str:
        """Generate a JSON patch for long-term memory updates."""
        return self._generate_with_llm_client(
            messages=messages,
            summary_id=summary_id,
            client_call=lambda client, messages_dict, current_seele_json, first_timestamp, last_timestamp: client.generate_memory_update(
                messages_dict, current_seele_json, first_timestamp, last_timestamp
            ),
        )

    async def generate_memory_update_async(
        self, messages: List[Message], summary_id: int
    ) -> str:
        """Async version of generate_memory_update."""
        return await self._generate_with_llm_client_async(
            messages=messages,
            summary_id=summary_id,
            client_call=lambda client, messages_dict, current_seele_json, first_timestamp, last_timestamp: client.generate_memory_update_async(
                messages_dict, current_seele_json, first_timestamp, last_timestamp
            ),
        )

    def generate_complete_memory_json(
        self,
        messages: List[Message],
        error_message: str,
        summary_id: int,
        previous_attempt: Optional[str] = None,
    ) -> str:
        """Generate a full seele.json object when patching fails."""
        return self._generate_with_llm_client(
            messages=messages,
            summary_id=summary_id,
            client_call=lambda client, messages_dict, current_seele_json, first_timestamp, last_timestamp: client.generate_complete_memory_json(
                messages_dict,
                current_seele_json,
                error_message,
                previous_attempt,
                first_timestamp,
                last_timestamp,
            ),
        )

    async def generate_complete_memory_json_async(
        self,
        messages: List[Message],
        error_message: str,
        summary_id: int,
        previous_attempt: Optional[str] = None,
    ) -> str:
        """Async version of generate_complete_memory_json."""
        return await self._generate_with_llm_client_async(
            messages=messages,
            summary_id=summary_id,
            client_call=lambda client, messages_dict, current_seele_json, first_timestamp, last_timestamp: client.generate_complete_memory_json_async(
                messages_dict,
                current_seele_json,
                error_message,
                previous_attempt,
                first_timestamp,
                last_timestamp,
            ),
        )

    def _handle_patch_update_error(
        self,
        *,
        summary_id: int,
        messages: Optional[List[Message]],
        error_message: str,
    ) -> bool:
        """Log patch update failure and trigger sync fallback when possible."""
        logger.error(error_message)
        if messages:
            logger.warning("Attempting fallback to complete JSON generation")
            return self.fallback_to_complete_json(summary_id, messages, error_message)
        return False

    async def _handle_patch_update_error_async(
        self,
        *,
        summary_id: int,
        messages: Optional[List[Message]],
        error_message: str,
    ) -> bool:
        """Log patch update failure and trigger async fallback when possible."""
        logger.error(error_message)
        if messages:
            logger.warning("Attempting fallback to complete JSON generation")
            return await self.fallback_to_complete_json_async(
                summary_id, messages, error_message
            )
        return False

    def _retry_complete_json_generation(
        self,
        *,
        summary_id: int,
        messages: List[Message],
        error_message: str,
        generate_complete_json: Callable[[List[Message], str, int, Optional[str]], Any],
        write_complete_json: Callable[[dict], None],
    ) -> bool:
        """Retry full seele.json generation after patch failure."""
        max_retries = 2
        previous_attempt: Optional[str] = None

        for attempt in range(max_retries):
            try:
                logger.info(
                    f"Generating complete seele.json as fallback for summary {summary_id} (attempt {attempt + 1}/{max_retries})"
                )
                complete_json_str = generate_complete_json(
                    messages, error_message, summary_id, previous_attempt
                )
                previous_attempt = complete_json_str or previous_attempt
                if not complete_json_str:
                    logger.error("Failed to generate complete JSON - empty response")
                    continue

                complete_data = self._parse_complete_json_response(complete_json_str)
                if complete_data is None:
                    error_message = self._invalid_structure_retry_message()
                    continue

                write_complete_json(complete_data)
                logger.info(
                    f"Successfully updated seele.json with complete JSON (fallback) for summary {summary_id}"
                )
                return True
            except json.JSONDecodeError as error:
                logger.error(
                    f"JSON parsing failed (attempt {attempt + 1}/{max_retries}): {error}"
                )
                logger.error(
                    f"Error at line {error.lineno}, column {error.colno}, position {error.pos}"
                )
                if attempt < max_retries - 1:
                    error_message = self._build_parse_retry_message(error)
                else:
                    logger.error("Max retries reached for complete JSON generation")
                    return False
            except Exception as error:
                logger.error(
                    f"Fallback to complete JSON failed (attempt {attempt + 1}/{max_retries}): {error}"
                )
                if attempt >= max_retries - 1:
                    return False

        return False

    async def _retry_complete_json_generation_async(
        self,
        *,
        summary_id: int,
        messages: List[Message],
        error_message: str,
        generate_complete_json: Callable[[List[Message], str, int, Optional[str]], Any],
        write_complete_json: Callable[[dict], None],
    ) -> bool:
        """Async retry wrapper for full seele.json regeneration."""
        max_retries = 2
        previous_attempt: Optional[str] = None

        for attempt in range(max_retries):
            try:
                logger.info(
                    f"Generating complete seele.json as fallback for summary {summary_id} (attempt {attempt + 1}/{max_retries})"
                )
                complete_json_str = await generate_complete_json(
                    messages, error_message, summary_id, previous_attempt
                )
                previous_attempt = complete_json_str or previous_attempt
                if not complete_json_str:
                    logger.error("Failed to generate complete JSON - empty response")
                    continue

                complete_data = self._parse_complete_json_response(complete_json_str)
                if complete_data is None:
                    error_message = self._invalid_structure_retry_message()
                    continue

                write_complete_json(complete_data)
                logger.info(
                    f"Successfully updated seele.json with complete JSON (fallback) for summary {summary_id}"
                )
                return True
            except json.JSONDecodeError as error:
                logger.error(
                    f"JSON parsing failed (attempt {attempt + 1}/{max_retries}): {error}"
                )
                logger.error(
                    f"Error at line {error.lineno}, column {error.colno}, position {error.pos}"
                )
                if attempt < max_retries - 1:
                    error_message = self._build_parse_retry_message(error)
                else:
                    logger.error("Max retries reached for complete JSON generation")
                    return False
            except Exception as error:
                logger.error(
                    f"Fallback to complete JSON failed (attempt {attempt + 1}/{max_retries}): {error}"
                )
                if attempt >= max_retries - 1:
                    return False

        return False

    def update_long_term_memory(
        self, summary_id: int, json_patch: str, messages: Optional[List[Message]] = None
    ) -> bool:
        """Apply a generated JSON patch, with full-JSON fallback on failure."""
        try:
            patch_data = json.loads(json_patch.strip())
            return self._apply_generated_patch(summary_id, patch_data, messages)
        except json.JSONDecodeError as e:
            return self._handle_patch_update_error(
                summary_id=summary_id,
                messages=messages,
                error_message=f"Invalid JSON in patch from summary {summary_id}: {e}",
            )
        except Exception as e:
            return self._handle_patch_update_error(
                summary_id=summary_id,
                messages=messages,
                error_message=f"Failed to update long-term memory: {e}",
            )

    async def update_long_term_memory_async(
        self, summary_id: int, json_patch: str, messages: Optional[List[Message]] = None
    ) -> bool:
        """Async version of update_long_term_memory."""
        try:
            patch_data = json.loads(json_patch.strip())
            return await self._apply_generated_patch_async(
                summary_id, patch_data, messages
            )
        except json.JSONDecodeError as e:
            return await self._handle_patch_update_error_async(
                summary_id=summary_id,
                messages=messages,
                error_message=f"Invalid JSON in patch from summary {summary_id}: {e}",
            )
        except Exception as e:
            return await self._handle_patch_update_error_async(
                summary_id=summary_id,
                messages=messages,
                error_message=f"Failed to update long-term memory: {e}",
            )

    def fallback_to_complete_json(
        self, summary_id: int, messages: List[Message], error_message: str
    ) -> bool:
        """Fallback method: generate and apply complete seele.json when patch fails."""
        return self._retry_complete_json_generation(
            summary_id=summary_id,
            messages=messages,
            error_message=error_message,
            generate_complete_json=self.generate_complete_memory_json,
            write_complete_json=self._write_complete_seele_json,
        )

    async def fallback_to_complete_json_async(
        self, summary_id: int, messages: List[Message], error_message: str
    ) -> bool:
        """Async version of fallback_to_complete_json."""
        return await self._retry_complete_json_generation_async(
            summary_id=summary_id,
            messages=messages,
            error_message=error_message,
            generate_complete_json=self.generate_complete_memory_json_async,
            write_complete_json=self._write_complete_seele_json,
        )

    def clean_json_response(self, response: str) -> str:
        """Clean LLM response to extract valid JSON."""
        if "```json" in response:
            response = response.split("```json")[1].split("```")[0]
        elif "```" in response:
            response = response.split("```")[1].split("```")[0]

        response = response.strip()
        start = response.find("{")
        end = response.rfind("}")

        if start != -1 and end != -1 and end > start:
            response = response[start : end + 1]

        return response

    def validate_seele_structure(self, data: dict) -> bool:
        """Validate that the seele.json structure has all required fields."""
        required_fields = ["bot", "user", "memorable_events", "commands_and_agreements"]

        for field in required_fields:
            if field not in data:
                logger.warning(f"Missing required field: {field}")
                return False

        if not isinstance(data["memorable_events"], dict):
            logger.warning("memorable_events is not an object")
            return False

        for event_id, event in data["memorable_events"].items():
            if not isinstance(event_id, str) or not MEMORABLE_EVENT_ID_PATTERN.match(event_id):
                logger.warning(f"Invalid memorable event id: {event_id}")
                return False
            if not isinstance(event, dict):
                logger.warning(f"Memorable event payload is not an object: {event_id}")
                return False
            required_event_fields = ["date", "importance", "details"]
            for field in required_event_fields:
                if field not in event:
                    logger.warning(f"Memorable event {event_id} missing field: {field}")
                    return False
            if _parse_event_date(event["date"]) is None:
                logger.warning(f"Memorable event {event_id} has invalid date")
                return False
            if (
                not isinstance(event["importance"], int)
                or event["importance"] not in MEMORABLE_EVENT_RETENTION_DAYS
            ):
                logger.warning(f"Memorable event {event_id} has invalid importance")
                return False
            if not isinstance(event["details"], str):
                logger.warning(f"Memorable event {event_id} has non-string details")
                return False

        return True

    def _load_template_data(self) -> Dict[str, Any]:
        """Load the current template used to validate repair completeness."""
        return load_seele_template(Path.cwd() / "template" / "seele.json", logger)

    def _collect_schema_issues(
        self,
        data: Dict[str, Any],
        *,
        template_data: Dict[str, Any],
    ) -> List[str]:
        """Collect human-readable reasons why persisted seele.json needs repair."""
        issues: List[str] = []

        if not _matches_template_shape(data, template_data):
            issues.append(
                "Missing required fields or field types do not match the current schema template"
            )

        memorable_events = data.get("memorable_events", {})
        _, memorable_events_need_normalization = normalize_memorable_events(
            memorable_events,
            logger=logger,
        )
        if memorable_events_need_normalization:
            issues.append("memorable_events uses a legacy or non-canonical structure")

        if not self.validate_seele_structure(data):
            issues.append("The file fails current seele.json structural validation")

        return issues

    def _repair_persisted_seele_json(
        self,
        *,
        repair_context: str,
        error_message: str,
        current_content: Optional[str] = None,
    ) -> bool:
        """Repair persisted seele.json via LLM and persist the repaired result."""
        from llm.chat_client import LLMClient

        template_data = self._load_template_data()
        template_str = json.dumps(template_data, ensure_ascii=False, indent=2)
        previous_attempt: Optional[str] = None
        max_retries = 2
        client = LLMClient()

        try:
            if current_content is None:
                from core.config import Config

                config = Config()
                if config.SEELE_JSON_PATH.exists():
                    current_content = config.SEELE_JSON_PATH.read_text(encoding="utf-8")
                else:
                    current_content = "{}"

            for attempt in range(max_retries):
                try:
                    logger.info(
                        "Repairing seele.json with LLM "
                        f"(attempt {attempt + 1}/{max_retries}, context={repair_context})"
                    )
                    repaired_json_str = client.generate_seele_repair(
                        current_content=current_content,
                        schema_template=template_str,
                        error_message=error_message,
                        repair_context=repair_context,
                        previous_attempt=previous_attempt,
                    )
                    previous_attempt = repaired_json_str or previous_attempt

                    if not repaired_json_str:
                        error_message = "Repair attempt returned an empty response"
                        continue

                    repaired_data = self._parse_complete_json_response(repaired_json_str)
                    if repaired_data is None:
                        error_message = self._invalid_structure_retry_message()
                        continue

                    if not _matches_template_shape(repaired_data, template_data):
                        logger.warning(
                            "LLM repair output is missing fields from the current template"
                        )
                        error_message = (
                            "Previous repair output did not include the full current "
                            "schema structure. Ensure all template fields are present."
                        )
                        continue

                    self._write_complete_seele_json(repaired_data)
                    logger.info("Successfully repaired persisted seele.json with LLM")
                    return True
                except json.JSONDecodeError as error:
                    logger.error(f"Failed to parse repaired seele.json: {error}")
                    error_message = self._build_parse_retry_message(error)
                except Exception as error:
                    logger.error(f"LLM-based seele.json repair failed: {error}")
                    error_message = str(error)
        finally:
            client.close()

        return False

    def ensure_seele_schema_current(self, repair_context: str = "runtime bootstrap") -> bool:
        """Ensure persisted seele.json matches the current schema, using LLM for repairs."""
        from core.config import Config
        import prompts

        config = Config()
        template_data = self._load_template_data()

        if not config.SEELE_JSON_PATH.exists():
            logger.info("seele.json missing; initializing from current template")
            self._write_complete_seele_json(template_data)
            return True

        raw_content = config.SEELE_JSON_PATH.read_text(encoding="utf-8")

        try:
            current_data = json.loads(raw_content)
        except json.JSONDecodeError as error:
            return self._repair_persisted_seele_json(
                repair_context=repair_context,
                error_message=(
                    "The persisted seele.json is malformed JSON. "
                    f"Parse error at line {error.lineno}, column {error.colno}: {error.msg}"
                ),
                current_content=raw_content,
            )

        issues = self._collect_schema_issues(current_data, template_data=template_data)
        if issues:
            return self._repair_persisted_seele_json(
                repair_context=repair_context,
                error_message="\n".join(f"- {issue}" for issue in issues),
                current_content=json.dumps(current_data, ensure_ascii=False, indent=2),
            )

        pruned_events, changed = prune_expired_memorable_events(
            current_data.get("memorable_events", {}),
            logger=logger,
        )

        if not changed:
            return False

        normalized_data = dict(current_data)
        normalized_data["memorable_events"] = pruned_events

        config.SEELE_JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(config.SEELE_JSON_PATH, "w", encoding="utf-8") as file_obj:
            json.dump(normalized_data, file_obj, indent=2, ensure_ascii=False)

        prompts._seele_json_cache = normalized_data
        logger.info("Normalized seele.json schema and pruned expired memorable events")
        return True

    def _write_complete_seele_json(self, complete_data: dict) -> None:
        """Write a full seele.json object and clear the prompt cache."""
        from core.config import Config
        import prompts

        config = Config()
        complete_data, _ = normalize_seele_data(complete_data, logger)
        complete_data = self._compact_overflowing_memory(complete_data)
        seele_path = config.SEELE_JSON_PATH
        seele_path.parent.mkdir(parents=True, exist_ok=True)
        with open(seele_path, "w", encoding="utf-8") as f:
            json.dump(complete_data, f, indent=2, ensure_ascii=False)

        prompts._seele_json_cache = complete_data



