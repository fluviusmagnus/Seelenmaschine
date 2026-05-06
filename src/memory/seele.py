"""Seele profile loading, patching, and long-term memory updates."""

import hashlib
import inspect
import json
import re
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

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
        "emotions": {
            "long_term": "",
            "short_term": [],
        },
        "needs": {
            "long_term": "",
            "short_term": [],
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
        "emotions": {
            "long_term": "",
            "short_term": [],
        },
        "needs": {
            "long_term": "",
            "short_term": [],
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
SHORT_TERM_MEMORY_LIMIT = 12
SHORT_TERM_MEMORY_KEEP_AFTER_COMPACTION = 4
SHORT_TERM_MEMORY_OWNERS = ("bot", "user")
SHORT_TERM_MEMORY_SECTIONS = ("emotions", "needs")
MAX_STRING_LENGTH_WARNING = 500
MAX_STRING_LENGTH_HARD = 300
STRING_COMPACTION_MAX_RETRIES = 3


@dataclass(frozen=True)
class PatchApplyResult:
    """Result of applying a seele.json patch."""

    success: bool
    data: Dict[str, Any]
    reason: str = ""


STRING_FIELD_PATHS = {
    "/bot/name",
    "/bot/gender",
    "/bot/birthday",
    "/bot/role",
    "/bot/appearance",
    "/bot/language_style/description",
    "/bot/personality/mbti",
    "/bot/personality/description",
    "/bot/personality/worldview_and_values",
    "/bot/emotions/long_term",
    "/bot/needs/long_term",
    "/bot/relationship_with_user",
    "/user/name",
    "/user/gender",
    "/user/birthday",
    "/user/location",
    "/user/personality/mbti",
    "/user/personality/description",
    "/user/personality/worldview_and_values",
    "/user/emotions/long_term",
    "/user/needs/long_term",
}

STRING_ARRAY_FIELD_PATHS = {
    "/bot/likes",
    "/bot/dislikes",
    "/bot/language_style/examples",
    "/bot/emotions/short_term",
    "/bot/needs/short_term",
    "/user/personal_facts",
    "/user/abilities",
    "/user/likes",
    "/user/dislikes",
    "/user/emotions/short_term",
    "/user/needs/short_term",
    "/commands_and_agreements",
}


def _merge_missing_template_fields(data: Any, template: Any) -> tuple[Any, bool]:
    """Fill missing current-schema fields without overwriting existing values."""
    if not isinstance(data, dict) or not isinstance(template, dict):
        return data, False

    changed = False
    for key, template_value in template.items():
        if key not in data:
            data[key] = json.loads(json.dumps(template_value))
            changed = True
            continue

        if isinstance(data[key], dict) and isinstance(template_value, dict):
            _, child_changed = _merge_missing_template_fields(data[key], template_value)
            changed = changed or child_changed

    return data, changed


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


def normalize_short_term_items(short_term: Any) -> tuple[List[str], bool]:
    """Normalize a short-term emotion/need value to a clean string list."""
    if short_term is None:
        return [], True

    if isinstance(short_term, str):
        normalized = " ".join(short_term.split()).strip()
        return ([normalized] if normalized else []), True

    if not isinstance(short_term, list):
        return [], True

    normalized_items: List[str] = []
    changed = False
    for item in short_term:
        if not isinstance(item, str):
            changed = True
            continue
        normalized = " ".join(item.split()).strip()
        if not normalized:
            changed = True
            continue
        if normalized != item:
            changed = True
        normalized_items.append(normalized)

    return normalized_items, changed


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


def _iter_short_term_fields(data: Dict[str, Any]):
    """Yield owner/section payloads that can contain short-term memory."""
    for owner_name in SHORT_TERM_MEMORY_OWNERS:
        owner = data.get(owner_name)
        if not isinstance(owner, dict):
            continue
        for section_name in SHORT_TERM_MEMORY_SECTIONS:
            section = owner.get(section_name)
            if isinstance(section, dict):
                yield owner_name, section_name, section


def _normalize_short_term_memory(data: Dict[str, Any]) -> bool:
    """Normalize all short-term emotion/need fields in-place."""
    changed = False
    for _, _, section in _iter_short_term_fields(data):
        normalized_items, field_changed = normalize_short_term_items(
            section.get("short_term", [])
        )
        if field_changed or section.get("short_term") != normalized_items:
            section["short_term"] = normalized_items
            changed = True
        if not isinstance(section.get("long_term"), str):
            section["long_term"] = ""
            changed = True
    return changed


def _short_term_limits_exceeded(data: Dict[str, Any]) -> bool:
    """Return whether any short-term emotion/need list exceeds the max size."""
    for _, _, section in _iter_short_term_fields(data):
        short_term = section.get("short_term", [])
        if isinstance(short_term, list) and len(short_term) > SHORT_TERM_MEMORY_LIMIT:
            return True
    return False


def _merge_short_term_overflow_into_long_term(
    long_term: str,
    overflow_items: List[str],
) -> str:
    """Build deterministic long-term text when fallback compacts short-term lists."""
    overflow_text = "; ".join(overflow_items)
    if not overflow_text:
        return long_term
    summary = f"Compacted short-term observations: {overflow_text}"
    if long_term.strip():
        return f"{long_term.strip()}\n{summary}"
    return summary


def fallback_compact_short_term_memory(data: Dict[str, Any]) -> None:
    """Compact overflowing short-term lists in-place with deterministic retention."""
    for _, _, section in _iter_short_term_fields(data):
        short_term = section.get("short_term", [])
        if not isinstance(short_term, list) or len(short_term) <= SHORT_TERM_MEMORY_LIMIT:
            continue
        keep_count = SHORT_TERM_MEMORY_KEEP_AFTER_COMPACTION
        overflow_items = short_term[:-keep_count]
        kept_items = short_term[-keep_count:]
        section["long_term"] = _merge_short_term_overflow_into_long_term(
            section.get("long_term", ""),
            overflow_items,
        )
        section["short_term"] = kept_items


def _collect_oversized_strings(
    data: Dict[str, Any], threshold: int
) -> List[tuple[str, str]]:
    """Return (json_pointer, value) pairs for leaf strings exceeding threshold."""
    oversized: List[tuple[str, str]] = []

    def _walk(value: Any, path: str) -> None:
        if isinstance(value, str):
            if len(value) > threshold:
                oversized.append((path, value))
        elif isinstance(value, dict):
            for key, child in value.items():
                _walk(child, f"{path}/{key}")
        elif isinstance(value, list):
            for idx, child in enumerate(value):
                _walk(child, f"{path}/{idx}")

    _walk(data, "")
    return oversized


def _validate_memorable_event_payload(path: str, value: Any) -> str:
    if not isinstance(value, dict):
        return f"{path} expects memorable event object, got {type(value).__name__}"
    for field in ("date", "importance", "details"):
        if field not in value:
            return f"{path} missing required event field: {field}"
    if _parse_event_date(value["date"]) is None:
        return f"{path}/date expects YYYY-MM-DD date"
    if (
        not isinstance(value["importance"], int)
        or value["importance"] not in MEMORABLE_EVENT_RETENTION_DAYS
    ):
        return f"{path}/importance expects integer 1-5"
    if not isinstance(value["details"], str) or not value["details"].strip():
        return f"{path}/details expects non-empty string"
    return ""


def validate_seele_structure_data(data: dict, logger: Any) -> bool:
    """Validate that the seele.json structure has all required fields."""
    required_fields = ["bot", "user", "memorable_events", "commands_and_agreements"]

    for field in required_fields:
        if field not in data:
            logger.warning(f"Missing required field: {field}")
            return False

    if not isinstance(data["memorable_events"], dict):
        logger.warning("memorable_events is not an object")
        return False

    for path in STRING_FIELD_PATHS:
        current: Any = data
        for part in path.strip("/").split("/"):
            if not isinstance(current, dict) or part not in current:
                logger.warning(f"Missing required string field: {path}")
                return False
            current = current[part]
        if not isinstance(current, str):
            logger.warning(f"{path} is not a string")
            return False

    for path in STRING_ARRAY_FIELD_PATHS:
        current = data
        for part in path.strip("/").split("/"):
            if not isinstance(current, dict) or part not in current:
                logger.warning(f"Missing required array field: {path}")
                return False
            current = current[part]
        if not isinstance(current, list):
            logger.warning(f"{path} is not an array")
            return False
        if any(not isinstance(item, str) or not item.strip() for item in current):
            logger.warning(f"{path} contains invalid items")
            return False

    for event_id, event in data["memorable_events"].items():
        if not isinstance(event_id, str) or not MEMORABLE_EVENT_ID_PATTERN.match(event_id):
            logger.warning(f"Invalid memorable event id: {event_id}")
            return False
        reason = _validate_memorable_event_payload(f"/memorable_events/{event_id}", event)
        if reason:
            logger.warning(reason)
            return False

    return True


def normalize_seele_data(data: Dict[str, Any], logger: Any) -> tuple[Dict[str, Any], bool]:
    """Normalize current seele data to the latest schema."""
    normalized_data = dict(data)
    normalized_data, schema_changed = _merge_missing_template_fields(
        normalized_data, CURRENT_SEELE_TEMPLATE_FALLBACK
    )

    user = normalized_data.get("user")
    if isinstance(user, dict) and not isinstance(user.get("location"), str):
        user["location"] = ""
        schema_changed = True

    if _normalize_short_term_memory(normalized_data):
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
                data = json.load(file_obj)
                normalized_data, _ = normalize_seele_data(data, logger)
                return normalized_data
        return {}

    try:
        with open(seele_path, "r", encoding="utf-8") as file_obj:
            data = json.load(file_obj)
            normalized_data, _ = normalize_seele_data(data, logger)
            return normalized_data
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


def _escape_json_pointer_token(token: str) -> str:
    return token.replace("~", "~0").replace("/", "~1")


def build_json_patch_diff(old: Any, new: Any, path: str = "") -> List[Dict[str, Any]]:
    """Build an RFC 6902 patch that transforms old into new."""
    if old == new:
        return []

    if isinstance(old, dict) and isinstance(new, dict):
        operations: List[Dict[str, Any]] = []
        for key in old.keys() - new.keys():
            operations.append(
                {"op": "remove", "path": f"{path}/{_escape_json_pointer_token(str(key))}"}
            )
        for key, new_value in new.items():
            child_path = f"{path}/{_escape_json_pointer_token(str(key))}"
            if key not in old:
                operations.append({"op": "add", "path": child_path, "value": new_value})
            else:
                operations.extend(build_json_patch_diff(old[key], new_value, child_path))
        return operations

    if isinstance(old, list) and isinstance(new, list):
        return [{"op": "replace", "path": path, "value": new}]

    op = "add" if path == "" else "replace"
    return [{"op": op, "path": path or "", "value": new}]


def _is_short_term_path(path: Any) -> bool:
    """Return whether a JSON Pointer path targets short-term emotion/need memory."""
    if not isinstance(path, str):
        return False
    parts = path.strip("/").split("/")
    return (
        len(parts) >= 4
        and parts[0] in SHORT_TERM_MEMORY_OWNERS
        and parts[1] in SHORT_TERM_MEMORY_SECTIONS
        and parts[2] == "short_term"
    )


def _validate_short_term_patch_operation(
    operation: Dict[str, Any], working_cache: Dict[str, Any]
) -> str:
    """Return a rejection reason for invalid short-term patch operations."""
    path = operation.get("path")
    op = operation.get("op", "")
    value = operation.get("value")

    if op == "add" and isinstance(path, str) and path.endswith("/-"):
        if not isinstance(value, str) or not value.strip():
            return f"{path} expects non-empty string append value"
        return ""
    if op != "replace" or not isinstance(path, str):
        return (
            f"{path} can only append to /- or replace the current last short_term item"
        )

    parts = path.strip("/").split("/")
    if len(parts) != 4 or not parts[3].isdigit():
        return f"{path} must target /<owner>/<section>/short_term/<index>"
    target_index = int(parts[3])
    owner = parts[0]
    section = parts[1]
    current_array = (
        working_cache.get(owner, {}).get(section, {}).get("short_term", [])
    )
    if not isinstance(current_array, list):
        return f"/{owner}/{section}/short_term is not an array"
    if target_index != len(current_array) - 1:
        return (
            f"{path} can only replace the last short_term item "
            f"(expected index {len(current_array) - 1})"
        )
    if not isinstance(value, str) or not value.strip():
        return f"{path} expects non-empty string value"
    return ""


def _validate_patch_operation(
    operation: Dict[str, Any], working_cache: Dict[str, Any]
) -> str:
    op = operation.get("op")
    path = operation.get("path")
    value = operation.get("value")
    if op not in {"add", "replace", "remove"}:
        return f"Unsupported JSON Patch op: {op}"
    if not isinstance(path, str) or not path.startswith("/"):
        return f"Invalid JSON Patch path: {path}"

    if _is_short_term_path(path):
        return _validate_short_term_patch_operation(operation, working_cache)

    if op == "remove":
        return ""

    if path in STRING_FIELD_PATHS:
        if not isinstance(value, str):
            return f"{path} expects string value, got {type(value).__name__}"
        return ""

    if path in STRING_ARRAY_FIELD_PATHS:
        if not isinstance(value, list) or any(
            not isinstance(item, str) or not item.strip() for item in value
        ):
            return f"{path} expects array of non-empty strings"
        return ""

    for array_path in STRING_ARRAY_FIELD_PATHS:
        if path == f"{array_path}/-":
            if not isinstance(value, str) or not value.strip():
                return f"{path} expects non-empty string append value"
            return ""

    parts = path.strip("/").split("/")
    if len(parts) >= 2 and parts[0] == "memorable_events":
        event_path = f"/memorable_events/{parts[1]}"
        if not MEMORABLE_EVENT_ID_PATTERN.match(parts[1]):
            return f"{event_path} has invalid event id"
        if len(parts) == 2:
            return _validate_memorable_event_payload(event_path, value)
        if len(parts) == 3:
            field = parts[2]
            if field == "date" and _parse_event_date(value) is None:
                return f"{event_path}/date expects YYYY-MM-DD date"
            if field == "importance" and (
                not isinstance(value, int)
                or value not in MEMORABLE_EVENT_RETENTION_DAYS
            ):
                return f"{event_path}/importance expects integer 1-5"
            if field == "details" and (not isinstance(value, str) or not value.strip()):
                return f"{event_path}/details expects non-empty string"
            if field not in {"date", "importance", "details"}:
                return f"{event_path}/{field} is not a valid event field"
            return ""

    return ""


def _validate_patch_operations(
    operations: List[Dict[str, Any]], working_cache: Dict[str, Any]
) -> str:
    if not isinstance(operations, list):
        return "JSON Patch must be an array of operations"
    for operation in operations:
        if not isinstance(operation, dict):
            return "JSON Patch operations must be objects"
        reason = _validate_patch_operation(operation, working_cache)
        if reason:
            return reason
    return ""


def apply_seele_json_patch(
    cache: Dict[str, Any],
    patch_operations: List[Dict[str, Any]],
    seele_path: Path,
    load_from_disk: Any,
    logger: Any,
) -> PatchApplyResult:
    """Apply a patch to cached seele.json and persist it."""
    working_cache = cache or load_from_disk()
    working_cache, normalized = normalize_seele_data(working_cache, logger)
    if normalized:
        logger.info("Normalized seele.json before applying JSON Patch")

    try:
        operations = patch_operations

        invalid_reason = _validate_patch_operations(operations, working_cache)
        if invalid_reason:
            logger.error(f"Rejected seele.json patch: {invalid_reason}")
            return PatchApplyResult(False, working_cache, invalid_reason)

        patch = jsonpatch.JsonPatch(operations)
        updated_cache = patch.apply(working_cache)
        updated_cache, _ = normalize_seele_data(updated_cache, logger)
        if not validate_seele_structure_data(updated_cache, logger):
            reason = "Patch result does not match seele.json schema"
            logger.error(reason)
            return PatchApplyResult(False, working_cache, reason)

        seele_path.parent.mkdir(parents=True, exist_ok=True)
        with open(seele_path, "w", encoding="utf-8") as file_obj:
            json.dump(updated_cache, file_obj, indent=2, ensure_ascii=False)

        logger.info(f"Applied {len(operations)} JSON Patch operation(s) to seele.json")
        return PatchApplyResult(True, updated_cache)
    except jsonpatch.JsonPatchException as error:
        reason = f"Invalid JSON Patch operation: {error}"
        logger.error(reason)
        return PatchApplyResult(False, working_cache, reason)
    except Exception as error:
        reason = f"Failed to update seele.json: {error}"
        logger.error(reason)
        return PatchApplyResult(False, working_cache, reason)


class Seele:
    """Generate and apply long-term memory updates for seele.json."""

    def __init__(self, db: Any):
        self.db = db
        self._last_patch_error = ""

    @staticmethod
    def _session_snapshot_path() -> Path:
        """Return the per-profile session-start seele snapshot path."""
        from core.config import Config

        config = Config()
        return config.SEELE_JSON_PATH.with_name("seele.session_snapshot.json")

    @staticmethod
    def _write_json_atomic(path: Path, data: Dict[str, Any]) -> None:
        """Write JSON atomically next to the target file."""
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as file_obj:
            temp_path = Path(file_obj.name)
            json.dump(data, file_obj, indent=2, ensure_ascii=False)

        temp_path.replace(path)

    def _write_seele_data_without_compaction(self, data: Dict[str, Any]) -> None:
        """Persist seele data exactly enough for rollback and refresh prompt cache."""
        from core.config import Config
        import prompts.runtime as prompts_runtime

        config = Config()
        normalized_data, _ = normalize_seele_data(data, logger)
        self._write_json_atomic(config.SEELE_JSON_PATH, normalized_data)
        prompts_runtime._seele_json_cache = normalized_data

    def capture_session_snapshot(self, session_id: int) -> None:
        """Capture the current seele.json as the active session reset baseline."""
        payload = {
            "session_id": int(session_id),
            "seele": self.get_long_term_memory(),
        }
        self._write_json_atomic(self._session_snapshot_path(), payload)
        logger.info(f"Captured seele session snapshot for session {session_id}")

    def ensure_session_snapshot_current(self, session_id: int) -> None:
        """Ensure the snapshot belongs to the active session, rebuilding stale ones."""
        snapshot_path = self._session_snapshot_path()
        try:
            if snapshot_path.exists():
                with open(snapshot_path, "r", encoding="utf-8") as file_obj:
                    payload = json.load(file_obj)
                seele_data = payload.get("seele")
                if (
                    int(payload.get("session_id")) == int(session_id)
                    and isinstance(seele_data, dict)
                    and self.validate_seele_structure(seele_data)
                ):
                    return
                logger.warning(
                    "seele session snapshot is stale or invalid for active session; rebuilding"
                )
        except Exception as error:
            logger.warning(f"Failed to read seele session snapshot; rebuilding: {error}")

        self.capture_session_snapshot(session_id)

    def restore_session_snapshot(self, session_id: int) -> None:
        """Restore seele.json to the active session's start snapshot."""
        snapshot_path = self._session_snapshot_path()
        if not snapshot_path.exists():
            raise RuntimeError(
                f"Cannot reset session: seele session snapshot is missing at {snapshot_path}"
            )

        try:
            with open(snapshot_path, "r", encoding="utf-8") as file_obj:
                payload = json.load(file_obj)
        except Exception as error:
            raise RuntimeError(
                f"Cannot reset session: failed to read seele session snapshot: {error}"
            ) from error

        try:
            snapshot_session_id = int(payload.get("session_id"))
        except (TypeError, ValueError) as error:
            raise RuntimeError(
                "Cannot reset session: seele session snapshot has an invalid session id"
            ) from error

        if snapshot_session_id != int(session_id):
            raise RuntimeError(
                "Cannot reset session: seele session snapshot belongs to a different session"
            )

        seele_data = payload.get("seele")
        if not isinstance(seele_data, dict):
            raise RuntimeError("Cannot reset session: seele session snapshot is invalid")
        if not self.validate_seele_structure(seele_data):
            raise RuntimeError(
                "Cannot reset session: seele session snapshot has invalid seele structure"
            )

        self._write_seele_data_without_compaction(seele_data)
        logger.info(f"Restored seele session snapshot for session {session_id}")

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
        ) or _short_term_limits_exceeded(data)

    @staticmethod
    def _apply_compaction_candidate(
        data: Dict[str, Any], candidate: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Apply compacted personal_facts and memorable_events onto existing seele data."""
        compacted = json.loads(json.dumps(data))
        compacted_user = compacted.setdefault("user", {})
        compacted_user["personal_facts"] = candidate["personal_facts"]
        compacted["memorable_events"] = candidate["memorable_events"]
        return compacted


    def _parse_compaction_response(self, compaction_response: str) -> Dict[str, Any]:
        """Parse a compacted-memory JSON response."""
        return json.loads(self.clean_json_response(compaction_response))

    def _validate_compaction_candidate(self, candidate: Dict[str, Any]) -> Optional[str]:
        """Validate LLM compaction output shape and limits; returns None if valid, error reason if invalid."""
        if not isinstance(candidate, dict):
            return "Result is not a JSON object"

        personal_facts = candidate.get("personal_facts")
        memorable_events = candidate.get("memorable_events")
        if not isinstance(personal_facts, list) or not isinstance(memorable_events, dict):
            return "Missing or invalid personal_facts (array) or memorable_events (object)"
        if len(personal_facts) > PERSONAL_FACTS_LIMIT:
            return (
                f"personal_facts has {len(personal_facts)} items, "
                f"limit is {PERSONAL_FACTS_LIMIT}"
            )
        if len(memorable_events) > MEMORABLE_EVENTS_LIMIT:
            return (
                f"memorable_events has {len(memorable_events)} items, "
                f"limit is {MEMORABLE_EVENTS_LIMIT}"
            )

        normalized_facts = _deduplicate_personal_facts(personal_facts)
        if len(normalized_facts) != len(personal_facts):
            return (
                "personal_facts contains duplicate entries "
                "(case-insensitive, whitespace-normalized)"
            )

        bad_facts = [f for f in personal_facts if not isinstance(f, str) or not f.strip()]
        if bad_facts:
            return "personal_facts contains empty or non-string entries"

        for event_id, event in memorable_events.items():
            if (
                not isinstance(event_id, str)
                or not MEMORABLE_EVENT_ID_PATTERN.match(event_id)
            ):
                return (
                    f"Invalid event ID '{event_id}': "
                    "must be lowercase letters, digits, and underscores only"
                )
            if _validate_memorable_event_payload(f"/memorable_events/{event_id}", event):
                return f"Invalid payload for event '{event_id}'"

        return None

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
        fallback_compact_short_term_memory(compacted)
        return compacted

    async def _compact_personal_facts_and_events_async(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """LLM-compact personal_facts and memorable_events sections."""
        from llm.chat_client import LLMClient

        client = LLMClient()
        current_seele_json = json.dumps(data, ensure_ascii=False, indent=2)
        try:
            previous_attempt = None
            previous_error = None
            for attempt in range(2):
                response = await client.generate_seele_compaction_async(
                    current_seele_json=current_seele_json,
                    personal_facts_limit=PERSONAL_FACTS_LIMIT,
                    memorable_events_limit=MEMORABLE_EVENTS_LIMIT,
                    previous_attempt=previous_attempt,
                    previous_error=previous_error,
                )
                candidate = self._parse_compaction_response(response)
                validation_error = self._validate_compaction_candidate(candidate)
                if validation_error is None:
                    break
                previous_attempt = response
                previous_error = validation_error
                if attempt == 1:
                    raise ValueError(previous_error)
            logger.info("Compacted personal_facts and memorable_events with LLM")
            return self._apply_compaction_candidate(data, candidate)
        except Exception as error:
            logger.warning(f"LLM seele compaction failed, using fallback compaction: {error}")
            return self._fallback_compact_seele_data(data)
        finally:
            await client.close_async()

    async def _compact_overflowing_memory_async(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Async version of overflowing long-term memory compaction with per-section triggers."""
        if not self._memory_limits_exceeded(data):
            return data

        result = json.loads(json.dumps(data))

        user = result.get("user", {}) if isinstance(result.get("user"), dict) else {}
        personal_facts = user.get("personal_facts", [])
        memorable_events = result.get("memorable_events", {})

        needs_pf_compaction = isinstance(personal_facts, list) and len(personal_facts) > PERSONAL_FACTS_LIMIT
        needs_me_compaction = isinstance(memorable_events, dict) and len(memorable_events) > MEMORABLE_EVENTS_LIMIT

        if needs_pf_compaction or needs_me_compaction:
            result = await self._compact_personal_facts_and_events_async(result)

        if _short_term_limits_exceeded(result):
            result = await self._compact_short_term_overflow_async(result)

        return result

    def _collect_overflow_fields(self, data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Collect all short-term fields that exceed the limit, with overflow items."""
        fields = []
        for owner_name in SHORT_TERM_MEMORY_OWNERS:
            owner = data.get(owner_name)
            if not isinstance(owner, dict):
                continue
            for section_name in SHORT_TERM_MEMORY_SECTIONS:
                section = owner.get(section_name)
                if not isinstance(section, dict):
                    continue
                short_term = section.get("short_term", [])
                if not isinstance(short_term, list) or len(short_term) <= SHORT_TERM_MEMORY_LIMIT:
                    continue
                overflow_items = short_term[:-SHORT_TERM_MEMORY_KEEP_AFTER_COMPACTION]
                fields.append({
                    "path": f"/{owner_name}/{section_name}",
                    "owner": owner_name,
                    "section": section_name,
                    "existing_long_term": section.get("long_term", ""),
                    "overflow_items": overflow_items,
                    "section_data": section,
                })
        return fields

    async def _compact_short_term_overflow_async(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Compact short-term emotions/needs overflow using a dedicated LLM prompt."""
        fields_to_compact = self._collect_overflow_fields(data)
        if not fields_to_compact:
            return data

        bot_name = data.get("bot", {}).get("name", "AI Assistant")
        user_name = data.get("user", {}).get("name", "User")

        fields_json = json.dumps([
            {
                "path": f["path"],
                "existing_long_term": f["existing_long_term"],
                "overflow_items": f["overflow_items"],
            }
            for f in fields_to_compact
        ], ensure_ascii=False, indent=2)

        from llm.chat_client import LLMClient

        client = LLMClient()
        try:
            previous_attempt = None
            previous_error = None
            required_paths = {f"{field['path']}/long_term" for field in fields_to_compact}
            for attempt in range(2):
                response = await client.generate_short_term_compaction_async(
                    fields_json=fields_json,
                    bot_name=bot_name,
                    user_name=user_name,
                    previous_attempt=previous_attempt,
                    previous_error=previous_error,
                )
                try:
                    new_long_terms = self._parse_short_term_compaction_response(
                        response, required_paths=required_paths
                    )
                    break
                except Exception as error:
                    previous_attempt = response
                    previous_error = str(error)
                    if attempt == 1:
                        raise

            patch_ops = []
            long_term_updates: dict = {}
            for field in fields_to_compact:
                path = field["path"]
                new_long_term = new_long_terms.get(f"{path}/long_term", "")
                if new_long_term:
                    long_term_updates[path] = new_long_term
                    patch_ops.append({
                        "op": "replace",
                        "path": f"{path}/long_term",
                        "value": new_long_term,
                    })
                kept_items = field["section_data"]["short_term"][
                    -SHORT_TERM_MEMORY_KEEP_AFTER_COMPACTION:
                ]
                patch_ops.append({
                    "op": "replace",
                    "path": f"{path}/short_term",
                    "value": kept_items,
                })

            from prompts.runtime import update_seele_json

            success = update_seele_json(patch_ops)

            for field in fields_to_compact:
                path = field["path"]
                if path in long_term_updates:
                    field["section_data"]["long_term"] = long_term_updates[path]
                field["section_data"]["short_term"] = field["section_data"]["short_term"][
                    -SHORT_TERM_MEMORY_KEEP_AFTER_COMPACTION:
                ]

            if not success:
                await self._write_complete_seele_json_async(data)

            logger.info("Compacted short-term emotions/needs with dedicated LLM prompt")
        except Exception as error:
            logger.warning(f"LLM short-term compaction failed, using fallback: {error}")
            fallback_compact_short_term_memory(data)
        finally:
            await client.close_async()

        return data

    def _parse_short_term_compaction_response(
        self, response: str, *, required_paths: Optional[set[str]] = None
    ) -> Dict[str, str]:
        """Parse the short-term compaction response into a path -> new long_term map."""
        cleaned = self.clean_json_response(response)
        parsed = json.loads(cleaned)
        if not isinstance(parsed, dict):
            raise ValueError("Short-term compaction response is not a JSON object")
        allowed_paths = {
            "/bot/emotions/long_term",
            "/bot/needs/long_term",
            "/user/emotions/long_term",
            "/user/needs/long_term",
        }
        if not required_paths:
            raise ValueError("required_paths must not be empty")
        for path, value in parsed.items():
            if path not in allowed_paths:
                raise ValueError(f"Unexpected short-term compaction path: {path}")
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{path} expects non-empty string")
            if len(value) > MAX_STRING_LENGTH_HARD:
                raise ValueError(
                    f"{path} exceeds {MAX_STRING_LENGTH_HARD} characters"
                )
        missing = required_paths - set(parsed)
        if missing:
            raise ValueError(
                f"Missing short-term compaction path(s): {', '.join(sorted(missing))}"
            )
        return parsed

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

    async def _apply_generated_patch_async(
        self,
        summary_id: int,
        patch_data: Any,
        messages: Optional[List[Message]],
    ) -> bool:
        """Apply generated patch data and trigger async fallback when needed."""
        from prompts.runtime import update_seele_json_result

        patch_result = update_seele_json_result(patch_data)
        self._last_patch_error = patch_result.reason
        if patch_result.success:
            current_memory = self.get_long_term_memory()
            compacted_data = await self._compact_overflowing_memory_async(current_memory)
            compacted_data = await self._compact_long_strings_async(compacted_data)
            if compacted_data != self.get_long_term_memory():
                await self._write_complete_seele_json_async(compacted_data)
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
        from prompts.runtime import load_seele_json

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
        logger.debug(
            "Generated JSON diagnostics: "
            f"length={len(complete_json_str)} chars, "
            f"head={complete_json_str[:200]!r}, "
            f"tail={complete_json_str[-200:]!r}"
        )

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

    async def generate_memory_update_async(
        self,
        messages: List[Message],
        summary_id: int,
        previous_attempt: Optional[str] = None,
        previous_error: Optional[str] = None,
    ) -> str:
        """Async version of generate_memory_update."""
        return await self._generate_with_llm_client_async(
            messages=messages,
            summary_id=summary_id,
            client_call=lambda client, messages_dict, current_seele_json, first_timestamp, last_timestamp: client.generate_memory_update_async(
                messages_dict,
                current_seele_json,
                first_timestamp,
                last_timestamp,
                previous_attempt,
                previous_error,
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

                write_result = write_complete_json(complete_data)
                if inspect.isawaitable(write_result):
                    await write_result
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

    async def update_long_term_memory_async(
        self, summary_id: int, json_patch: str, messages: Optional[List[Message]] = None
    ) -> bool:
        """Async version of update_long_term_memory."""
        try:
            patch_data = json.loads(self.clean_json_response(json_patch))
            apply_result = await self._apply_generated_patch_async(
                summary_id, patch_data, messages
            )
            success = bool(apply_result)
            reason = self._last_patch_error
            if success:
                return True
            if messages is None:
                return False

            retry_patch = await self.generate_memory_update_async(
                messages,
                summary_id,
                previous_attempt=json_patch,
                previous_error=reason or "JSON Patch application failed",
            )
            retry_data = json.loads(self.clean_json_response(retry_patch))
            retry_result = await self._apply_generated_patch_async(
                summary_id, retry_data, messages
            )
            retry_success = bool(retry_result)
            retry_reason = self._last_patch_error
            if retry_success:
                return True
            return await self.fallback_to_complete_json_async(
                summary_id,
                messages,
                retry_reason or "JSON Patch retry failed",
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

    async def fallback_to_complete_json_async(
        self, summary_id: int, messages: List[Message], error_message: str
    ) -> bool:
        """Async version of fallback_to_complete_json."""
        return await self._retry_complete_json_generation_async(
            summary_id=summary_id,
            messages=messages,
            error_message=error_message,
            generate_complete_json=self.generate_complete_memory_json_async,
            write_complete_json=self._write_complete_seele_json_async,
        )

    def clean_json_response(self, response: str) -> str:
        """Clean LLM response to extract valid JSON (object or array)."""
        if "```json" in response:
            response = response.split("```json")[1].split("```")[0]
        elif "```" in response:
            response = response.split("```")[1].split("```")[0]

        response = response.strip()

        obj_start = response.find("{")
        obj_end = response.rfind("}")
        arr_start = response.find("[")
        arr_end = response.rfind("]")

        if obj_start != -1 and (arr_start == -1 or obj_start < arr_start):
            if obj_end != -1 and obj_end > obj_start:
                response = response[obj_start : obj_end + 1]
        elif arr_start != -1 and arr_end != -1 and arr_end > arr_start:
            response = response[arr_start : arr_end + 1]

        return response

    def validate_seele_structure(self, data: dict) -> bool:
        """Validate that the seele.json structure has all required fields."""
        return validate_seele_structure_data(data, logger)

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

    async def _repair_persisted_seele_json_async(
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
                    repaired_json_str = await client.generate_seele_repair_async(
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

                    await self._write_complete_seele_json_async(repaired_data)
                    logger.info("Successfully repaired persisted seele.json with LLM")
                    return True
                except json.JSONDecodeError as error:
                    logger.error(f"Failed to parse repaired seele.json: {error}")
                    error_message = self._build_parse_retry_message(error)
                except Exception as error:
                    logger.error(f"LLM-based seele.json repair failed: {error}")
                    error_message = str(error)
        finally:
            await client.close_async()

        return False

    async def ensure_seele_schema_current_async(
        self, repair_context: str = "runtime bootstrap"
    ) -> bool:
        """Ensure persisted seele.json matches the current schema, using LLM for repairs."""
        from core.config import Config
        import prompts.runtime as prompts_runtime

        config = Config()
        template_data = self._load_template_data()

        if not config.SEELE_JSON_PATH.exists():
            logger.info("seele.json missing; initializing from current template")
            await self._write_complete_seele_json_async(template_data)
            return True

        raw_content = config.SEELE_JSON_PATH.read_text(encoding="utf-8")

        try:
            current_data = json.loads(raw_content)
        except json.JSONDecodeError as error:
            return await self._repair_persisted_seele_json_async(
                repair_context=repair_context,
                error_message=(
                    "The persisted seele.json is malformed JSON. "
                    f"Parse error at line {error.lineno}, column {error.colno}: {error.msg}"
                ),
                current_content=raw_content,
            )

        _, memorable_events_need_normalization = normalize_memorable_events(
            current_data.get("memorable_events", {}),
            logger=logger,
        )
        normalized_data, normalized_changed = normalize_seele_data(current_data, logger)
        issues = self._collect_schema_issues(normalized_data, template_data=template_data)
        if memorable_events_need_normalization:
            issues.append("memorable_events uses a legacy or non-canonical structure")
        if issues:
            return await self._repair_persisted_seele_json_async(
                repair_context=repair_context,
                error_message="\n".join(f"- {issue}" for issue in issues),
                current_content=json.dumps(normalized_data, ensure_ascii=False, indent=2),
            )

        pruned_events, changed = prune_expired_memorable_events(
            normalized_data.get("memorable_events", {}),
            logger=logger,
        )

        if not changed and not normalized_changed:
            return False

        normalized_data["memorable_events"] = pruned_events

        config.SEELE_JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(config.SEELE_JSON_PATH, "w", encoding="utf-8") as file_obj:
            json.dump(normalized_data, file_obj, indent=2, ensure_ascii=False)

        prompts_runtime._seele_json_cache = normalized_data
        logger.info("Normalized seele.json schema and pruned expired memorable events")
        return True

    async def _compact_long_strings_async(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Validate and compact any leaf strings exceeding the length limit."""
        oversized = _collect_oversized_strings(data, MAX_STRING_LENGTH_WARNING)
        if not oversized:
            return data

        logger.info(
            f"Found {len(oversized)} string(s) exceeding {MAX_STRING_LENGTH_WARNING} chars; "
            "triggering LLM compaction"
        )

        try:
            revised_data = await self._llm_compact_long_strings_full(data)
            if revised_data:
                from prompts.runtime import update_seele_json_result

                patch_ops = build_json_patch_diff(self.get_long_term_memory(), revised_data)
                patch_result = update_seele_json_result(patch_ops)
                if not patch_result.success:
                    await self._write_complete_seele_json_async(revised_data)

                data = self.get_long_term_memory()
        except Exception as error:
            logger.warning(f"Tier 1 long-string compaction failed: {error}")

        data = await self._compact_long_strings_tier2(data)

        return data

    async def _llm_compact_long_strings_full(
        self, data: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """Submit complete seele.json to LLM for holistic long-string compaction."""
        from llm.chat_client import LLMClient
        import prompts.runtime as prompts_runtime

        bot_name = data.get("bot", {}).get("name", "AI Assistant")
        current_json = json.dumps(data, ensure_ascii=False, indent=2)
        oversized = _collect_oversized_strings(data, MAX_STRING_LENGTH_WARNING)
        client = LLMClient()
        try:
            previous_attempt = None
            previous_error = None
            oversized_fields_json = json.dumps(
                [p for p, _ in oversized], ensure_ascii=False, indent=2
            )
            for attempt in range(2):
                prompt = prompts_runtime.get_long_string_compaction_prompt(
                    current_seele_json=current_json,
                    oversized_fields_json=oversized_fields_json,
                    bot_name=bot_name,
                    max_string_length=MAX_STRING_LENGTH_HARD,
                    previous_attempt=previous_attempt,
                    previous_error=previous_error,
                )
                response = await client.compact_long_strings_async(
                    prompt=prompt,
                    system_content=(
                        "You compact oversized strings in seele.json and preserve "
                        "personality-level insights."
                    ),
                )
                try:
                    cleaned = self.clean_json_response(response)
                    revised = json.loads(cleaned)
                    if not self.validate_seele_structure(revised):
                        raise ValueError("Revised seele.json has invalid structure")
                    oversized_after = _collect_oversized_strings(
                        revised, MAX_STRING_LENGTH_HARD
                    )
                    if oversized_after:
                        raise ValueError(
                            "Revised seele.json still has oversized strings: "
                            + ", ".join(path for path, _ in oversized_after)
                        )
                    return revised
                except Exception as error:
                    previous_attempt = response
                    previous_error = str(error)

            logger.warning(
                f"Tier 1 LLM long-string compaction exhausted retries: {previous_error}"
            )
            return None
        finally:
            await client.close_async()

    async def _compact_long_strings_tier2(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Tier 2: per-string LLM compaction for remaining oversized strings."""
        from llm.chat_client import LLMClient

        client = LLMClient()
        try:
            for attempt in range(STRING_COMPACTION_MAX_RETRIES):
                oversized = _collect_oversized_strings(data, MAX_STRING_LENGTH_HARD)
                if not oversized:
                    break

                for path, value in oversized:
                    try:
                        previous_attempt = None
                        previous_error = None
                        compressed = ""
                        for compress_attempt in range(STRING_COMPACTION_MAX_RETRIES):
                            compressed = await self._llm_compress_single_string(
                                value,
                                data,
                                path,
                                client,
                                previous_attempt=previous_attempt,
                                previous_error=previous_error,
                            )
                            if (
                                compressed
                                and len(compressed) <= MAX_STRING_LENGTH_HARD
                            ):
                                break
                            previous_attempt = compressed
                            previous_error = (
                                f"Compressed string is {len(compressed)} chars; "
                                f"must be {MAX_STRING_LENGTH_HARD} or fewer"
                            )
                            if compress_attempt == STRING_COMPACTION_MAX_RETRIES - 1:
                                logger.warning(
                                    f"Could not compress string at {path} below "
                                    f"{MAX_STRING_LENGTH_HARD} chars after "
                                    f"{STRING_COMPACTION_MAX_RETRIES} attempts "
                                    f"(current: {len(compressed)})"
                                )
                        if compressed and len(compressed) <= MAX_STRING_LENGTH_HARD:
                            from prompts.runtime import update_seele_json

                            update_seele_json(
                                [{"op": "replace", "path": path, "value": compressed}]
                            )
                    except Exception as error:
                        logger.warning(
                            f"Tier 2 long-string compaction failed for {path}: {error}"
                        )
                data = self.get_long_term_memory()
        finally:
            await client.close_async()

        return data

    async def _llm_compress_single_string(
        self,
        value: str,
        seele_data: Dict[str, Any],
        path: str,
        client,
        previous_attempt: Optional[str] = None,
        previous_error: Optional[str] = None,
    ) -> str:
        """LLM-compress a single oversized string with seele.json context."""
        import prompts.runtime as prompts_runtime

        bot_name = seele_data.get("bot", {}).get("name", "AI Assistant")
        current_json = json.dumps(seele_data, ensure_ascii=False, indent=2)
        prompt = prompts_runtime.get_single_string_compaction_prompt(
            value=value,
            current_seele_json=current_json,
            path=path,
            bot_name=bot_name,
            max_string_length=MAX_STRING_LENGTH_HARD,
            previous_attempt=previous_attempt,
            previous_error=previous_error,
        )

        response = await client.compress_single_string_async(
            prompt=prompt,
            system_content="You compress oversized strings while preserving meaning.",
        )
        return response.strip()

    async def _write_complete_seele_json_async(self, complete_data: dict) -> None:
        """Write a full seele.json object from async memory update flows."""
        from core.config import Config
        import prompts.runtime as prompts_runtime

        config = Config()
        complete_data, _ = normalize_seele_data(complete_data, logger)
        complete_data = await self._compact_overflowing_memory_async(complete_data)
        complete_data = await self._compact_long_strings_async(complete_data)
        seele_path = config.SEELE_JSON_PATH
        seele_path.parent.mkdir(parents=True, exist_ok=True)
        with open(seele_path, "w", encoding="utf-8") as f:
            json.dump(complete_data, f, indent=2, ensure_ascii=False)

        prompts_runtime._seele_json_cache = complete_data
