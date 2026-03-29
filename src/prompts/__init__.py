from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from core.config import Config
from memory.seele import (
    apply_seele_json_patch,
    dict_to_json_patch as _seele_dict_to_json_patch,
    load_seele_json_from_disk as _seele_load_seele_json_from_disk,
)
from prompts.memory_prompts import (
    build_complete_memory_json_prompt,
    build_memory_update_prompt,
    build_seele_repair_prompt,
    build_summary_prompt,
)
from prompts.system_prompt import (
    build_cacheable_system_prompt,
    get_current_time_str as _build_current_time_str,
)
from utils.logger import get_logger

logger = get_logger()

_seele_json_cache: Dict[str, Any] = {}


def _load_seele_json_from_disk() -> Dict[str, Any]:
    """Load seele.json from disk."""
    config = Config()
    return _seele_load_seele_json_from_disk(
        seele_path=config.SEELE_JSON_PATH,
        template_path=Path.cwd() / "template" / "seele.json",
        logger=logger,
    )


def load_seele_json() -> Dict[str, Any]:
    """Load cached seele.json data."""
    global _seele_json_cache
    if not _seele_json_cache:
        _seele_json_cache = _load_seele_json_from_disk()
    return _seele_json_cache


def update_seele_json(
    patch_operations: Union[List[Dict[str, Any]], Dict[str, Any]],
) -> bool:
    """Update seele.json with a JSON Patch."""
    global _seele_json_cache
    config = Config()
    success, updated_cache = apply_seele_json_patch(
        cache=_seele_json_cache,
        patch_operations=patch_operations,
        seele_path=config.SEELE_JSON_PATH,
        load_from_disk=_load_seele_json_from_disk,
        logger=logger,
    )
    if success:
        _seele_json_cache = updated_cache
    return success


def _dict_to_json_patch(
    data: Dict[str, Any], base_path: str = ""
) -> List[Dict[str, Any]]:
    """Convert a nested dict to JSON Patch operations."""
    return _seele_dict_to_json_patch(data, base_path=base_path)


def get_current_time_str() -> str:
    """Get current time string with timezone."""
    config = Config()
    return _build_current_time_str(config.TIMEZONE, logger)


def get_cacheable_system_prompt(recent_summaries: Optional[List[str]] = None) -> str:
    """Build the cacheable system prompt."""
    config = Config()
    return build_cacheable_system_prompt(
        seele_data=load_seele_json(),
        workspace_dir=config.WORKSPACE_DIR,
        recent_summaries=recent_summaries,
    )


def get_summary_prompt(existing_summary: str | None, new_conversations: str) -> str:
    """Build the summary generation prompt."""
    return build_summary_prompt(
        seele_data=load_seele_json(),
        existing_summary=existing_summary,
        new_conversations=new_conversations,
    )


def get_memory_update_prompt(
    messages: str,
    current_seele_json: str,
    first_timestamp: int | None = None,
    last_timestamp: int | None = None,
) -> str:
    """Build the memory update prompt."""
    config = Config()
    return build_memory_update_prompt(
        messages=messages,
        current_seele_json=current_seele_json,
        timezone=config.TIMEZONE,
        first_timestamp=first_timestamp,
        last_timestamp=last_timestamp,
    )


def get_complete_memory_json_prompt(
    messages: str,
    current_seele_json: str,
    error_message: str,
    previous_attempt: str | None = None,
    first_timestamp: int | None = None,
    last_timestamp: int | None = None,
) -> str:
    """Build the full seele.json regeneration prompt."""
    config = Config()
    return build_complete_memory_json_prompt(
        messages=messages,
        current_seele_json=current_seele_json,
        error_message=error_message,
        timezone=config.TIMEZONE,
        previous_attempt=previous_attempt,
        first_timestamp=first_timestamp,
        last_timestamp=last_timestamp,
    )


def get_seele_repair_prompt(
    current_content: str,
    schema_template: str,
    error_message: str,
    repair_context: str,
    previous_attempt: str | None = None,
) -> str:
    """Build the LLM prompt for repairing/migrating persisted seele.json."""
    return build_seele_repair_prompt(
        current_content=current_content,
        schema_template=schema_template,
        error_message=error_message,
        repair_context=repair_context,
        previous_attempt=previous_attempt,
    )


__all__ = [
    "get_cacheable_system_prompt",
    "get_current_time_str",
    "get_summary_prompt",
    "get_memory_update_prompt",
    "get_complete_memory_json_prompt",
    "get_seele_repair_prompt",
    "load_seele_json",
    "update_seele_json",
]

