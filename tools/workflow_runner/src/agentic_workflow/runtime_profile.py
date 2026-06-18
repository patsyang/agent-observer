from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class RuntimeProfileError(ValueError):
    pass


@dataclass(frozen=True)
class RuntimeProfile:
    path: Path
    profile_id: str
    invocation_args: tuple[str, ...]
    invocation_stdin: str | None
    prompt_write_file: bool
    prompt_file_name: str
    final_message_source: str
    final_message_json_path: tuple[str, ...]
    final_message_fallback: str | None
    success_exit_codes: tuple[int, ...]
    success_json_conditions: tuple[dict[str, object], ...]


ALLOWED_TEMPLATE_NAMES = {
    "cwd",
    "repo_root",
    "project_root",
    "run_dir",
    "node_dir",
    "artifacts_dir",
    "prompt_file",
    "final_message_path",
    "node_id",
    "workflow",
    "prompt",
}
FINAL_MESSAGE_SOURCES = {"stdout_json", "stdout_text", "stdout_jsonl_text", "final_message_file"}
TEMPLATE_PATTERN = re.compile(r"{{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*}}")


def load_runtime_profile(path: Path) -> RuntimeProfile:
    if not path.exists():
        raise RuntimeProfileError(f"runtime profile not found: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise RuntimeProfileError(f"runtime profile is not valid JSON: {path}") from error
    if not isinstance(payload, dict):
        raise RuntimeProfileError(f"runtime profile must be an object: {path}")
    if payload.get("schema_version") != 1:
        raise RuntimeProfileError(f"runtime profile schema_version must be 1: {path}")
    invocation = _object(payload.get("invocation"), path, "invocation")
    args = invocation.get("args")
    if not isinstance(args, list) or not all(isinstance(item, str) for item in args):
        raise RuntimeProfileError(f"invocation.args must be a string array: {path}")
    _reject_prompt_in_args(args)
    prompt = _object(payload.get("prompt"), path, "prompt")
    final_message = _object(payload.get("final_message"), path, "final_message")
    success = _object(payload.get("success"), path, "success")
    source = _required_string(final_message, "source", path)
    if source not in FINAL_MESSAGE_SOURCES:
        raise RuntimeProfileError(f"unsupported final_message.source `{source}` in {path}")
    return RuntimeProfile(
        path=path,
        profile_id=_required_string(payload, "id", path),
        invocation_args=tuple(args),
        invocation_stdin=_optional_string(invocation.get("stdin")),
        prompt_write_file=bool(prompt.get("write_file")),
        prompt_file_name=_required_string(prompt, "file_name", path),
        final_message_source=source,
        final_message_json_path=tuple(_string_list(final_message.get("json_path"), "json_path", path)),
        final_message_fallback=_optional_string(final_message.get("fallback")),
        success_exit_codes=tuple(_success_exit_codes(success, path)),
        success_json_conditions=tuple(_json_conditions(success.get("json_conditions"), path)),
    )


def render_template(template: str, values: dict[str, str]) -> str:
    def replace(match: re.Match[str]) -> str:
        name = match.group(1)
        if name not in ALLOWED_TEMPLATE_NAMES:
            raise RuntimeProfileError(f"unknown runtime profile template variable: {name}")
        if name not in values:
            raise RuntimeProfileError(f"missing runtime profile template value: {name}")
        return values[name]

    return TEMPLATE_PATTERN.sub(replace, template)


def json_path_value(payload: object, path: tuple[str, ...]) -> object:
    current = payload
    for item in path:
        if not isinstance(current, dict) or item not in current:
            raise RuntimeProfileError("json path not found: " + ".".join(path))
        current = current[item]
    return current


def conditions_pass(payload: object, conditions: tuple[dict[str, object], ...]) -> bool:
    for condition in conditions:
        path = tuple(str(item) for item in condition.get("path", []))
        expected = condition.get("equals")
        try:
            actual = json_path_value(payload, path)
        except RuntimeProfileError:
            return False
        if actual != expected:
            return False
    return True


def parse_stdout_json(stdout: str) -> object:
    text = stdout.strip()
    if not text:
        raise RuntimeProfileError("stdout is empty")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    for line in reversed(stdout.splitlines()):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            return json.loads(stripped)
        except json.JSONDecodeError:
            continue
    raise RuntimeProfileError("stdout does not contain a JSON object")


def last_non_empty_line(text: str) -> str:
    for line in reversed(text.splitlines()):
        stripped = line.strip()
        if stripped:
            return stripped
    return ""


def stdout_jsonl_text(stdout: str) -> str:
    texts: list[str] = []
    for line in stdout.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        try:
            payload = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            texts.extend(_jsonl_event_texts(payload))
    return texts[-1] if texts else ""


def resolve_executable(command: list[str]) -> list[str]:
    if not command:
        raise RuntimeProfileError("runtime command must not be empty")
    executable = command[0]
    candidate = Path(executable)
    if candidate.is_absolute() or candidate.parent != Path("."):
        if not candidate.exists():
            raise RuntimeProfileError(f"runtime executable not found: {executable}")
        return [str(candidate), *command[1:]]
    resolved = shutil.which(executable)
    if resolved is None:
        raise RuntimeProfileError(f"runtime executable not found on PATH: {executable}")
    return [resolved, *command[1:]]


def _object(value: object, path: Path, field: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise RuntimeProfileError(f"{field} must be an object in {path}")
    return value


def _required_string(payload: dict[str, object], field: str, path: Path) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value.strip():
        raise RuntimeProfileError(f"{field} must be a non-empty string in {path}")
    return value.strip()


def _optional_string(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _string_list(value: object, field: str, path: Path) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise RuntimeProfileError(f"{field} must be a string array in {path}")
    return value


def _json_conditions(value: object, path: Path) -> list[dict[str, object]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise RuntimeProfileError(f"success.json_conditions must be an array in {path}")
    result = []
    for item in value:
        if not isinstance(item, dict):
            raise RuntimeProfileError(f"success.json_conditions item must be an object in {path}")
        condition_path = item.get("path")
        if not isinstance(condition_path, list) or not all(
            isinstance(part, str) for part in condition_path
        ):
            raise RuntimeProfileError(f"success.json_conditions path must be a string array in {path}")
        if "equals" not in item:
            raise RuntimeProfileError(f"success.json_conditions equals is required in {path}")
        result.append(dict(item))
    return result


def _reject_prompt_in_args(args: list[str]) -> None:
    for item in args:
        for match in TEMPLATE_PATTERN.finditer(item):
            if match.group(1) == "prompt":
                raise RuntimeProfileError("{{prompt}} is not allowed in invocation.args")


def _success_exit_codes(success: dict[str, object], path: Path) -> list[int]:
    exit_codes = success.get("exit_codes")
    if exit_codes is not None:
        if not isinstance(exit_codes, list) or not exit_codes:
            raise RuntimeProfileError(f"success.exit_codes must be a non-empty integer array in {path}")
        return [int(item) for item in exit_codes]
    return [int(success.get("exit_code", 0))]


def _jsonl_event_texts(payload: dict[str, object]) -> list[str]:
    texts: list[str] = []
    event_allows_text = _event_allows_text(payload)
    for container in _jsonl_event_containers(payload):
        if not _container_allows_assistant_text(container, event_allows_text=event_allows_text):
            continue
        part = container.get("part")
        if isinstance(part, dict) and _part_allows_text(part):
            texts.extend(_text_values(part.get("text")))
            texts.extend(_text_values(part.get("content")))
        message = container.get("message")
        if isinstance(message, dict) and _container_allows_assistant_text(
            message,
            event_allows_text=event_allows_text,
        ):
            texts.extend(_text_values(message.get("content")))
            parts = message.get("parts")
            if isinstance(parts, list):
                for item in parts:
                    if isinstance(item, str):
                        texts.extend(_text_values(item))
                    elif isinstance(item, dict) and _part_allows_text(item):
                        texts.extend(_text_values(item.get("text")))
                        texts.extend(_text_values(item.get("content")))
        if _container_has_assistant_role(container):
            texts.extend(_text_values(container.get("text")))
    return texts


def _jsonl_event_containers(payload: dict[str, object]) -> list[dict[str, object]]:
    containers = [payload]
    for field in ("properties", "data"):
        value = payload.get(field)
        if isinstance(value, dict):
            containers.append(value)
    return containers


def _event_allows_text(payload: dict[str, object]) -> bool:
    event_type = str(payload.get("type") or "").lower().replace("_", "-")
    if not event_type:
        return isinstance(payload.get("message"), dict)
    return (
        event_type == "text"
        or "message" in event_type
        or "assistant" in event_type
        or "content" in event_type
    )


def _container_allows_assistant_text(
    payload: dict[str, object],
    *,
    event_allows_text: bool,
) -> bool:
    if _container_has_assistant_role(payload):
        return True
    role = _container_role(payload)
    return role is None and event_allows_text


def _container_has_assistant_role(payload: dict[str, object]) -> bool:
    role = _container_role(payload)
    return isinstance(role, str) and role.lower() in {"assistant", "model"}


def _container_role(payload: dict[str, object]) -> object:
    role = payload.get("role")
    if role is None and isinstance(payload.get("message"), dict):
        role = payload["message"].get("role")
    return role


def _part_allows_text(payload: dict[str, object]) -> bool:
    part_type = payload.get("type")
    if part_type is None:
        return True
    return str(part_type).lower() in {"text", "content", "message", "assistant"}


def _text_values(value: object) -> list[str]:
    if isinstance(value, str):
        stripped = value.strip()
        return [stripped] if stripped else []
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return [item.strip() for item in value if item.strip()]
    return []
