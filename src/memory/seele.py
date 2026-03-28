"""Seele profile loading, patching, and long-term memory updates."""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import jsonpatch

from memory.context import Message
from utils.logger import get_logger

logger = get_logger()


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

    def _get_summary_timestamps(self, summary_id: int) -> tuple[Optional[int], Optional[int]]:
        """Get first/last timestamps for a summary."""
        summary_row = self.db.get_summary_by_id(summary_id)
        first_timestamp = summary_row["first_timestamp"] if summary_row else None
        last_timestamp = summary_row["last_timestamp"] if summary_row else None
        return first_timestamp, last_timestamp

    def get_long_term_memory(self) -> Dict[str, Any]:
        """Load the current long-term memory profile."""
        from prompts import load_seele_json

        return load_seele_json()

    def generate_memory_update(self, messages: List[Message], summary_id: int) -> str:
        """Generate a JSON patch for long-term memory updates."""
        from llm.chat_client import LLMClient

        client = LLMClient()
        messages_dict = [msg.to_dict() for msg in messages]
        current_seele = self.get_long_term_memory()
        current_seele_json = json.dumps(current_seele, ensure_ascii=False, indent=2)
        first_timestamp, last_timestamp = self._get_summary_timestamps(summary_id)

        json_patch = client.generate_memory_update(
            messages_dict, current_seele_json, first_timestamp, last_timestamp
        )
        client.close()
        return json_patch

    async def generate_memory_update_async(
        self, messages: List[Message], summary_id: int
    ) -> str:
        """Async version of generate_memory_update."""
        from llm.chat_client import LLMClient

        client = LLMClient()
        messages_dict = [msg.to_dict() for msg in messages]
        first_timestamp, last_timestamp = self._get_summary_timestamps(summary_id)
        current_seele = self.get_long_term_memory()
        current_seele_json = json.dumps(current_seele, ensure_ascii=False, indent=2)

        json_patch = await client.generate_memory_update_async(
            messages_dict, current_seele_json, first_timestamp, last_timestamp
        )
        await client.close_async()
        return json_patch

    def generate_complete_memory_json(
        self, messages: List[Message], error_message: str, summary_id: int
    ) -> str:
        """Generate a full seele.json object when patching fails."""
        from llm.chat_client import LLMClient

        client = LLMClient()
        messages_dict = [msg.to_dict() for msg in messages]
        current_seele = self.get_long_term_memory()
        current_seele_json = json.dumps(current_seele, ensure_ascii=False, indent=2)
        first_timestamp, last_timestamp = self._get_summary_timestamps(summary_id)

        complete_json = client.generate_complete_memory_json(
            messages_dict,
            current_seele_json,
            error_message,
            first_timestamp,
            last_timestamp,
        )
        client.close()
        return complete_json

    async def generate_complete_memory_json_async(
        self, messages: List[Message], error_message: str, summary_id: int
    ) -> str:
        """Async version of generate_complete_memory_json."""
        from llm.chat_client import LLMClient

        client = LLMClient()
        messages_dict = [msg.to_dict() for msg in messages]
        current_seele = self.get_long_term_memory()
        current_seele_json = json.dumps(current_seele, ensure_ascii=False, indent=2)
        first_timestamp, last_timestamp = self._get_summary_timestamps(summary_id)

        complete_json = await client.generate_complete_memory_json_async(
            messages_dict,
            current_seele_json,
            error_message,
            first_timestamp,
            last_timestamp,
        )
        await client.close_async()
        return complete_json

    def update_long_term_memory(
        self, summary_id: int, json_patch: str, messages: Optional[List[Message]] = None
    ) -> bool:
        """Apply a generated JSON patch, with full-JSON fallback on failure."""
        try:
            patch_data = json.loads(json_patch.strip())

            from prompts import update_seele_json

            success = update_seele_json(patch_data)
            if success:
                patch_type = "array" if isinstance(patch_data, list) else "dict"
                logger.info(
                    f"Updated seele.json with {patch_type} patch from summary {summary_id}"
                )
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
        except json.JSONDecodeError as e:
            error_msg = f"Invalid JSON in patch from summary {summary_id}: {e}"
            logger.error(error_msg)
            if messages:
                logger.warning("Attempting fallback to complete JSON generation")
                return self.fallback_to_complete_json(summary_id, messages, error_msg)
            return False
        except Exception as e:
            error_msg = f"Failed to update long-term memory: {e}"
            logger.error(error_msg)
            if messages:
                logger.warning("Attempting fallback to complete JSON generation")
                return self.fallback_to_complete_json(summary_id, messages, error_msg)
            return False

    async def update_long_term_memory_async(
        self, summary_id: int, json_patch: str, messages: Optional[List[Message]] = None
    ) -> bool:
        """Async version of update_long_term_memory."""
        try:
            patch_data = json.loads(json_patch.strip())

            from prompts import update_seele_json

            success = update_seele_json(patch_data)
            if success:
                patch_type = "array" if isinstance(patch_data, list) else "dict"
                logger.info(
                    f"Updated seele.json with {patch_type} patch from summary {summary_id}"
                )
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
        except json.JSONDecodeError as e:
            error_msg = f"Invalid JSON in patch from summary {summary_id}: {e}"
            logger.error(error_msg)
            if messages:
                logger.warning("Attempting fallback to complete JSON generation")
                return await self.fallback_to_complete_json_async(
                    summary_id, messages, error_msg
                )
            return False
        except Exception as e:
            error_msg = f"Failed to update long-term memory: {e}"
            logger.error(error_msg)
            if messages:
                logger.warning("Attempting fallback to complete JSON generation")
                return await self.fallback_to_complete_json_async(
                    summary_id, messages, error_msg
                )
            return False

    def update_after_summary(self, summary_id: int, messages: List[Message]) -> bool:
        """Generate and apply a memory update after summary creation."""
        try:
            if not messages:
                return False

            json_patch = self.generate_memory_update(messages, summary_id)
            if not json_patch:
                return False

            return self.update_long_term_memory(summary_id, json_patch, messages)
        except Exception as e:
            logger.error(f"Failed to update long-term memory: {e}")
            return False

    async def update_after_summary_async(
        self, summary_id: int, messages: List[Message]
    ) -> bool:
        """Async version of update_after_summary."""
        try:
            if not messages:
                return False

            json_patch = await self.generate_memory_update_async(messages, summary_id)
            if not json_patch:
                return False

            return await self.update_long_term_memory_async(
                summary_id, json_patch, messages
            )
        except Exception as e:
            logger.error(f"Failed to update long-term memory: {e}")
            return False

    def fallback_to_complete_json(
        self, summary_id: int, messages: List[Message], error_message: str
    ) -> bool:
        """Fallback method: generate and apply complete seele.json when patch fails."""
        max_retries = 2

        for attempt in range(max_retries):
            try:
                logger.info(
                    f"Generating complete seele.json as fallback for summary {summary_id} (attempt {attempt + 1}/{max_retries})"
                )
                complete_json_str = self.generate_complete_memory_json(
                    messages, error_message, summary_id
                )
                if not complete_json_str:
                    logger.error("Failed to generate complete JSON - empty response")
                    continue

                complete_json_str = self.clean_json_response(complete_json_str)
                logger.debug(f"Generated JSON length: {len(complete_json_str)} chars")
                logger.debug(f"First 200 chars: {complete_json_str[:200]}")
                logger.debug(f"Last 200 chars: {complete_json_str[-200:]}")

                complete_data = json.loads(complete_json_str)
                if not self.validate_seele_structure(complete_data):
                    logger.warning("Generated JSON has invalid structure, retrying...")
                    error_message = (
                        "Previous attempt produced invalid structure. Ensure all required "
                        "fields are present: bot, user, memorable_events, commands_and_agreements"
                    )
                    continue

                self._write_complete_seele_json(complete_data)
                logger.info(
                    f"Successfully updated seele.json with complete JSON (fallback) for summary {summary_id}"
                )
                return True
            except json.JSONDecodeError as e:
                logger.error(
                    f"JSON parsing failed (attempt {attempt + 1}/{max_retries}): {e}"
                )
                logger.error(
                    f"Error at line {e.lineno}, column {e.colno}, position {e.pos}"
                )
                if attempt < max_retries - 1:
                    error_message = (
                        f"Previous JSON generation failed with parse error at line "
                        f"{e.lineno}: {str(e)}. Please ensure proper JSON syntax: all "
                        "strings must be properly quoted and escaped, no trailing commas, "
                        "proper brace/bracket matching."
                    )
                else:
                    logger.error("Max retries reached for complete JSON generation")
                    return False
            except Exception as e:
                logger.error(
                    f"Fallback to complete JSON failed (attempt {attempt + 1}/{max_retries}): {e}"
                )
                if attempt >= max_retries - 1:
                    return False

        return False

    async def fallback_to_complete_json_async(
        self, summary_id: int, messages: List[Message], error_message: str
    ) -> bool:
        """Async version of fallback_to_complete_json."""
        max_retries = 2

        for attempt in range(max_retries):
            try:
                logger.info(
                    f"Generating complete seele.json as fallback for summary {summary_id} (attempt {attempt + 1}/{max_retries})"
                )
                complete_json_str = await self.generate_complete_memory_json_async(
                    messages, error_message, summary_id
                )
                if not complete_json_str:
                    logger.error("Failed to generate complete JSON - empty response")
                    continue

                complete_json_str = self.clean_json_response(complete_json_str)
                logger.debug(f"Generated JSON length: {len(complete_json_str)} chars")
                logger.debug(f"First 200 chars: {complete_json_str[:200]}")
                logger.debug(f"Last 200 chars: {complete_json_str[-200:]}")

                complete_data = json.loads(complete_json_str)
                if not self.validate_seele_structure(complete_data):
                    logger.warning("Generated JSON has invalid structure, retrying...")
                    error_message = (
                        "Previous attempt produced invalid structure. Ensure all required "
                        "fields are present: bot, user, memorable_events, commands_and_agreements"
                    )
                    continue

                self._write_complete_seele_json(complete_data)
                logger.info(
                    f"Successfully updated seele.json with complete JSON (fallback) for summary {summary_id}"
                )
                return True
            except json.JSONDecodeError as e:
                logger.error(
                    f"JSON parsing failed (attempt {attempt + 1}/{max_retries}): {e}"
                )
                logger.error(
                    f"Error at line {e.lineno}, column {e.colno}, position {e.pos}"
                )
                if attempt < max_retries - 1:
                    error_message = (
                        f"Previous JSON generation failed with parse error at line "
                        f"{e.lineno}: {str(e)}. Please ensure proper JSON syntax: all "
                        "strings must be properly quoted and escaped, no trailing commas, "
                        "proper brace/bracket matching."
                    )
                else:
                    logger.error("Max retries reached for complete JSON generation")
                    return False
            except Exception as e:
                logger.error(
                    f"Fallback to complete JSON failed (attempt {attempt + 1}/{max_retries}): {e}"
                )
                if attempt >= max_retries - 1:
                    return False

        return False

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

        if not isinstance(data["memorable_events"], list):
            logger.warning("memorable_events is not an array")
            return False

        if len(data["memorable_events"]) > 20:
            logger.warning(
                f"memorable_events has {len(data['memorable_events'])} events (max 20), truncating..."
            )
            data["memorable_events"] = data["memorable_events"][-20:]

        return True

    def _write_complete_seele_json(self, complete_data: dict) -> None:
        """Write a full seele.json object and clear the prompt cache."""
        from core.config import Config
        import prompts

        config = Config()
        seele_path = config.SEELE_JSON_PATH
        seele_path.parent.mkdir(parents=True, exist_ok=True)
        with open(seele_path, "w", encoding="utf-8") as f:
            json.dump(complete_data, f, indent=2, ensure_ascii=False)

        prompts._seele_json_cache = {}



