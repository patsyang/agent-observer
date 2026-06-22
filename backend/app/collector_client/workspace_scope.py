from __future__ import annotations

import json
import re
from pathlib import Path

from app.collector_client.telemetry_utils import arguments as _arguments, hash_value as _hash, payload as _payload


class WorkspaceResolver:
    def __init__(self, codex_home: Path) -> None:
        self.codex_home = codex_home
        self.labels = _load_codex_labels(codex_home)

    def resolve(self, path: Path, record: dict) -> dict:
        evidence = _workspace_evidence(record)
        if not evidence and isinstance(record.get("_workspace_hint"), dict):
            evidence = record["_workspace_hint"]
        workspace_path = _first_path(evidence)
        if not workspace_path:
            return {"agent_type": "codex", "workspace_confidence": "unknown"}
        normalized = _normalize_path(workspace_path)
        label = self.labels.get(normalized) or _basename(normalized)
        alias_source = "codex_global_state" if normalized in self.labels else "path_basename"
        confidence = "high" if evidence.get("source") in {"session_meta", "turn_context", "tool_workdir"} else "medium"
        return {
            "agent_type": "codex",
            "workspace_id": f"codex:{_hash(normalized)[:20]}",
            "workspace_path": normalized,
            "workspace_label": label,
            "workspace_alias_source": alias_source,
            "workspace_confidence": confidence,
            "workspace_evidence": evidence.get("source", "session_file"),
        }


def load_workspace_resolver(codex_home: Path) -> WorkspaceResolver:
    return WorkspaceResolver(codex_home)


def _load_codex_labels(codex_home: Path) -> dict[str, str]:
    path = codex_home / ".codex-global-state.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    labels = payload.get("electron-workspace-root-labels")
    if not isinstance(labels, dict):
        return {}
    return {_normalize_path(key): str(value).strip() for key, value in labels.items() if str(value).strip()}


def workspace_hint_from_file(path: Path, max_lines: int = 20) -> dict:
    decoder = json.JSONDecoder()
    try:
        with path.open("r", encoding="utf-8") as handle:
            for index, line in enumerate(handle, 1):
                if index > max_lines:
                    return {}
                try:
                    record = decoder.decode(line)
                except json.JSONDecodeError:
                    continue
                evidence = _workspace_evidence(record)
                if evidence:
                    return evidence
    except OSError:
        return {}
    return {}


def _workspace_evidence(record: dict) -> dict:
    payload = _payload(record)
    record_type = str(record.get("type") or "")
    if record_type == "session_meta":
        return _from_payload(payload, "session_meta")
    if record_type == "turn_context":
        return _from_payload(payload, "turn_context")
    if record.get("cwd") or record.get("workspace_roots"):
        return _from_payload(record, "record")
    args = _arguments(payload)
    if args.get("workdir"):
        return {"source": "tool_workdir", "workspace_path": str(args.get("workdir"))}
    return {}


def _from_payload(payload: dict, source: str) -> dict:
    roots = payload.get("workspace_roots")
    if isinstance(roots, list) and roots:
        return {"source": source, "workspace_path": str(roots[0]), "workspace_roots": [str(item) for item in roots if item]}
    if payload.get("cwd"):
        return {"source": source, "workspace_path": str(payload.get("cwd"))}
    return {}


def _first_path(evidence: dict) -> str:
    return str(evidence.get("workspace_path") or "").strip()


def _normalize_path(value: str) -> str:
    text = value.strip().replace("\\", "/")
    text = re.sub(r"^//\?/", "", text)
    text = re.sub(r"/+", "/", text)
    if len(text) >= 2 and text[1] == ":":
        text = text[0].upper() + text[1:]
    return text.rstrip("/")


def _basename(path: str) -> str:
    return path.rstrip("/").split("/")[-1] or path
