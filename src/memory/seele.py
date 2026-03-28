"""Seele profile loading, patching, and long-term memory updates."""

import json
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Union

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

    def _get_summary_timestamps(
        self, summary_id: int
    ) -> tuple[Optional[int], Optional[int]]:
        """Get first/last timestamps for a summary."""
        summary_row = self.db.get_summary_by_id(summary_id)
        first_timestamp = summary_row["first_timestamp"] if summary_row else None
        last_timestamp = summary_row["last_timestamp"] if summary_row else None
        return first_timestamp, last_timestamp

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
        self, messages: List[Message], error_message: str, summary_id: int
    ) -> str:
        """Generate a full seele.json object when patching fails."""
        return self._generate_with_llm_client(
            messages=messages,
            summary_id=summary_id,
            client_call=lambda client, messages_dict, current_seele_json, first_timestamp, last_timestamp: client.generate_complete_memory_json(
                messages_dict,
                current_seele_json,
                error_message,
                first_timestamp,
                last_timestamp,
            ),
        )

    async def generate_complete_memory_json_async(
        self, messages: List[Message], error_message: str, summary_id: int
    ) -> str:
        """Async version of generate_complete_memory_json."""
        return await self._generate_with_llm_client_async(
            messages=messages,
            summary_id=summary_id,
            client_call=lambda client, messages_dict, current_seele_json, first_timestamp, last_timestamp: client.generate_complete_memory_json_async(
                messages_dict,
                current_seele_json,
                error_message,
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
        generate_complete_json: Callable[[List[Message], str, int], Any],
        write_complete_json: Callable[[dict], None],
    ) -> bool:
        """Retry full seele.json generation after patch failure."""
        max_retries = 2

        for attempt in range(max_retries):
            try:
                logger.info(
                    f"Generating complete seele.json as fallback for summary {summary_id} (attempt {attempt + 1}/{max_retries})"
                )
                complete_json_str = generate_complete_json(
                    messages, error_message, summary_id
                )
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
        generate_complete_json: Callable[[List[Message], str, int], Any],
        write_complete_json: Callable[[dict], None],
    ) -> bool:
        """Async retry wrapper for full seele.json regeneration."""
        max_retries = 2

        for attempt in range(max_retries):
            try:
                logger.info(
                    f"Generating complete seele.json as fallback for summary {summary_id} (attempt {attempt + 1}/{max_retries})"
                )
                complete_json_str = await generate_complete_json(
                    messages, error_message, summary_id
                )
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



