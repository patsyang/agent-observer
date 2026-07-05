"""会话物化层：写入时把 observed_facts 投射成 conversations / messages / hits / FTS。

设计原则：会话是一等存储实体。ingest 每写一条 fact，在**同一事务内**调用
``apply`` 维护物化表；查询只读物化层（见 ``app.conversations.service``）。
重建/裁剪走离线脚本（``scripts/rebuild_conversations`` / ``scripts/prune_conversations``）。

对外入口：
- ``FactProjection`` —— 一条 fact 的归一化投影（在线 ``from_item`` / 离线 ``from_rows``）。
- ``apply`` —— 新 fact 的唯一写入路径。
- ``refresh`` —— dedup（同 source_event_id 重传）刷新该 fact 的物化行。
- ``prune_before`` —— 按时间裁剪会话（含 FTS）。
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from typing import Any

from app.conversations.workspace import workspace_from_source_refs
from app.evidence.presentation import projection_preview

PROMPT_CATEGORIES = {"agent_prompt"}
RESPONSE_CATEGORIES = {"agent_response"}
HIT_FACT_TYPES = {"error", "risk", "tool", "unknown"}
PREVIEW_LIMIT = 220
_PROJ_TEXT_KEYS = ("prompt_text", "content_text", "message_text", "reasoning_text")


# ---------------------------------------------------------------------------
# 共享小工具（统一 service.py / presentation.py 里重复的实现）
# ---------------------------------------------------------------------------

def truncate_preview(value: str, limit: int = PREVIEW_LIMIT) -> str:
    """归一化空白并按字数截断（用单字符省略号，对齐 presentation._truncate）。"""
    normalized = " ".join((value or "").split())
    if len(normalized) <= limit:
        return normalized
    return f"{normalized[: limit - 1]}…"


def _extract_line_from_refs(refs: dict) -> int | None:
    try:
        return int(refs.get("line"))
    except (TypeError, ValueError):
        return None


def _extract_line_json(source_refs_json: str | None) -> int | None:
    try:
        refs = json.loads(source_refs_json or "{}")
    except json.JSONDecodeError:
        return None
    return _extract_line_from_refs(refs)


def _extract_text(value: Any) -> str:
    """从 JSON 结构里递归抽纯文本（text/content/message/prompt/output/result/payload）。"""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return " ".join(part for item in value if (part := _extract_text(item)))
    if not isinstance(value, dict):
        return ""
    for key in ("text", "content", "message", "prompt", "output", "result"):
        if key in value:
            text = _extract_text(value[key])
            if text:
                return text
    payload = value.get("payload")
    if payload is not None:
        text = _extract_text(payload)
        if text:
            return text
    return ""


def _raw_text(value: str | None) -> str:
    if not value:
        return ""
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return value
    return _extract_text(parsed)


def _int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _float(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _turn_start_line(conversation_ref: str) -> int | None:
    """turn|base|path|line → line；base_ref → None。"""
    parts = conversation_ref.split("|")
    if len(parts) == 4 and parts[0] == "turn":
        try:
            return int(parts[3])
        except ValueError:
            return None
    return None


# ---------------------------------------------------------------------------
# turn 归属解析（复刻 service._group_by_conversation / _turn_ref_for_fact）
# ---------------------------------------------------------------------------

_TURN_CACHE: dict | None = None


def enable_turn_cache(enable: bool = True) -> None:
    """启用/关闭 turn 解析缓存。离线 rebuild 全量数据下同桶 prompt 会被反复查询，
    缓存可消除重复；在线 ingest 不启用（每条 fact 只来一次）。"""
    global _TURN_CACHE
    _TURN_CACHE = {} if enable else None


def resolve_turn_ref(
    conn: sqlite3.Connection,
    base_ref: str,
    path_hash: str,
    line: int | None,
    category: str,
) -> str:
    """决定一条 fact 的会话 ref。

    - 无 path_hash 或无 line → base_ref（不切 turn）；
    - 自身是 prompt 且有 line → ``turn|base|path|line``；
    - 否则 → 同桶内 line ≤ 自身 line 的最大 prompt line；无则 base_ref。

    在线 ingest 时只能看到已入库的 prompt（罕见乱序偏差），离线 rebuild 时
    observed_facts 全量，归属按 line 解析正确。
    """
    if not path_hash or line is None:
        return base_ref
    if category in PROMPT_CATEGORIES:
        return f"turn|{base_ref}|{path_hash}|{line}"
    prompt_lines = _bucket_prompt_lines(conn, base_ref, path_hash)
    eligible = [candidate for candidate in prompt_lines if candidate <= line]
    return f"turn|{base_ref}|{path_hash}|{eligible[-1]}" if eligible else base_ref


def _bucket_prompt_lines(conn: sqlite3.Connection, base_ref: str, path_hash: str) -> list[int]:
    """同桶所有 prompt 的 source_line（升序）；启用缓存时按 (base_ref, path_hash) 复用。"""
    if _TURN_CACHE is not None:
        key = (base_ref, path_hash)
        cached = _TURN_CACHE.get(key)
        if cached is not None:
            return cached
        lines = _query_bucket_prompt_lines(conn, base_ref, path_hash)
        _TURN_CACHE[key] = lines
        return lines
    return _query_bucket_prompt_lines(conn, base_ref, path_hash)


def _query_bucket_prompt_lines(conn: sqlite3.Connection, base_ref: str, path_hash: str) -> list[int]:
    rows = conn.execute(
        "select source_refs_json from observed_facts "
        "where coalesce(nullif(conversation_ref, ''), nullif(session_ref, ''), fact_id) = ? "
        "  and source_path_hash = ? and category = 'agent_prompt'",
        (base_ref, path_hash),
    ).fetchall()
    return sorted(
        candidate
        for row in rows
        if (candidate := _extract_line_json(row["source_refs_json"])) is not None
    )


def _primary_projection_and_raw(item: dict) -> tuple[dict, str | None]:
    """从 ingest item 取主 projection dict 与 raw_content。"""
    projections = item.get("evidence_projections")
    if projections:
        first = projections[0]
        projection = first.get("projection") or first.get("projection_json") or {}
        if not isinstance(projection, dict):
            projection = {}
        raw = first.get("raw_content", item.get("raw_content"))
        return projection, raw
    projection = item.get("projection") or {}
    if not isinstance(projection, dict):
        projection = {}
    return projection, item.get("raw_content")


# ---------------------------------------------------------------------------
# FactProjection —— 一条 fact 的归一化投影
# ---------------------------------------------------------------------------

@dataclass
class FactProjection:
    fact_id: str
    conversation_ref: str           # 解析后的 turn|... 或 base_ref
    base_ref: str
    source_path_hash: str
    source_line: int | None
    fact_type: str
    category: str
    severity: str
    occurred_at: str
    summary: str
    agent_type: str
    source_id: str
    source_kind: str
    session_ref: str
    session_title: str
    workspace: dict                 # WorkspaceScope 6 键
    content_preview: str            # 给 hit 用（已算好的 projection_preview）
    projection: dict                # 主 projection dict（算 tool_context/message 用）
    raw_content: str | None
    sensitive_matches: list
    usage: dict | None              # item["usage"] 或 None
    raw_available: bool

    @property
    def is_prompt(self) -> bool:
        return self.category in PROMPT_CATEGORIES

    @property
    def is_response(self) -> bool:
        return self.category in RESPONSE_CATEGORIES

    @property
    def role(self) -> str | None:
        if self.is_prompt:
            return "user"
        if self.is_response:
            return "assistant"
        role = str(self.projection.get("role") or "")
        return role if role in {"user", "assistant"} else None

    @property
    def message_content(self) -> str:
        """复刻 service._projection_text：text 字段 → raw_text → 角色兜底标签。"""
        if self.role is None:
            return ""
        for key in _PROJ_TEXT_KEYS:
            value = self.projection.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        raw = _raw_text(self.raw_content).strip()
        if raw:
            return raw
        label = "提交 Prompt" if self.role == "user" else "响应内容"
        try:
            length = int(self.projection.get("content_length") or 0)
        except (TypeError, ValueError):
            length = 0
        return f"{label} 原文未上传" + (f"，长度 {length} 字符" if length else "")

    @property
    def tool_context(self) -> dict | None:
        """复刻 service._tool_context（dict 输入）。"""
        p = self.projection
        if not any(
            p.get(k) not in (None, "")
            for k in ("command", "command_excerpt", "tool_name", "exit_code", "is_timeout")
        ):
            return None
        return {
            "tool_name": str(p.get("tool_name") or p.get("tool") or p.get("name") or ""),
            "command": str(p.get("command") or ""),
            "command_excerpt": str(p.get("command_excerpt") or p.get("command") or ""),
            "command_category": str(p.get("command_category") or ""),
            "exit_code": p.get("exit_code"),
            "is_timeout": bool(p.get("is_timeout")),
            "timeout_ms": p.get("timeout_ms"),
            "timeout_after_ms": p.get("timeout_after_ms"),
            "wall_time_seconds": p.get("wall_time_seconds"),
            "error_excerpt": str(p.get("error_excerpt") or ""),
            "call_id": str(p.get("call_id") or ""),
        }

    @classmethod
    def from_item(
        cls,
        conn: sqlite3.Connection,
        *,
        fact_id: str,
        item: dict,
        sensitive_matches: list,
        preview: dict,
        agent_type: str,
        source_id: str,
        source_kind: str,
    ) -> "FactProjection":
        """在线：从 ingest 循环手头数据构造。preview = _list_projection_preview(item) 返回。"""
        refs = item.get("source_refs") or {}
        base_ref = str(refs.get("conversation_ref") or refs.get("session_ref") or fact_id)
        source_path_hash = str(refs.get("source_path_hash") or "")
        line = _extract_line_from_refs(refs)
        conversation_ref = resolve_turn_ref(
            conn, base_ref, source_path_hash, line, str(item.get("category") or "")
        )
        projection, raw_content = _primary_projection_and_raw(item)
        usage = item.get("usage") if isinstance(item.get("usage"), dict) else None
        return cls(
            fact_id=fact_id,
            conversation_ref=conversation_ref,
            base_ref=base_ref,
            source_path_hash=source_path_hash,
            source_line=line,
            fact_type=str(item.get("fact_type") or "unknown"),
            category=str(item.get("category") or "uncategorized"),
            severity=str(item.get("severity") or "low"),
            occurred_at=str(item.get("occurred_at") or ""),
            summary=str(item.get("summary") or ""),
            agent_type=str(agent_type or ""),
            source_id=str(source_id or ""),
            source_kind=str(source_kind or ""),
            session_ref=str(refs.get("session_ref") or ""),
            session_title=str(refs.get("session_title") or ""),
            workspace=workspace_from_source_refs(json.dumps(refs, ensure_ascii=False)),
            content_preview=preview["content_preview"],
            projection=projection,
            raw_content=raw_content,
            sensitive_matches=sensitive_matches or [],
            usage=usage,
            raw_available=bool(preview.get("raw_available")),
        )

    @classmethod
    def from_rows(
        cls,
        conn: sqlite3.Connection,
        fact_row: sqlite3.Row,
        proj_row: sqlite3.Row | None,
    ) -> "FactProjection":
        """离线 rebuild：从 observed_facts 行 + 主 evidence_projections 行构造。

        ``usage`` 留空（由 rebuild 流程按 fact_type=='usage' 单独从 usage_signals 注入）。
        """
        refs_json = fact_row["source_refs_json"]
        try:
            refs = json.loads(refs_json or "{}")
        except json.JSONDecodeError:
            refs = {}
        base_ref = fact_row["conversation_ref"] or fact_row["session_ref"] or fact_row["fact_id"]
        source_path_hash = fact_row["source_path_hash"] or ""
        line = _extract_line_from_refs(refs)
        conversation_ref = resolve_turn_ref(
            conn, base_ref, source_path_hash, line, fact_row["category"]
        )
        projection: dict = {}
        raw_content = None
        if proj_row is not None:
            try:
                parsed = json.loads(proj_row["projection_json"] or "{}")
            except json.JSONDecodeError:
                parsed = {}
            projection = parsed if isinstance(parsed, dict) else {}
            raw_content = proj_row["raw_content"]
        sensitive = (
            projection.get("sensitive_matches")
            if isinstance(projection.get("sensitive_matches"), list)
            else []
        )
        content_preview = fact_row["content_preview"] or projection_preview(
            projection, raw_content, fact_row["summary"], fact_row["category"]
        )
        return cls(
            fact_id=fact_row["fact_id"],
            conversation_ref=conversation_ref,
            base_ref=base_ref,
            source_path_hash=source_path_hash,
            source_line=line,
            fact_type=fact_row["fact_type"],
            category=fact_row["category"],
            severity=fact_row["severity"],
            occurred_at=fact_row["occurred_at"],
            summary=fact_row["summary"],
            agent_type=fact_row["agent_type"],
            source_id=fact_row["source_id"],
            source_kind=fact_row["source_kind"],
            session_ref=fact_row["session_ref"],
            session_title=str(refs.get("session_title") or ""),
            workspace=workspace_from_source_refs(refs_json),
            content_preview=content_preview,
            projection=projection,
            raw_content=raw_content,
            sensitive_matches=sensitive or [],
            usage=None,
            raw_available=bool(fact_row["raw_available"]),
        )


# ---------------------------------------------------------------------------
# 写入路径
# ---------------------------------------------------------------------------

def _is_hit(conn: sqlite3.Connection, fp: FactProjection) -> bool:
    """在线/离线统一：fact_type 命中 OR risk_signals 存在。"""
    if fp.fact_type in HIT_FACT_TYPES:
        return True
    return conn.execute(
        "select 1 from risk_signals where fact_id = ? limit 1", (fp.fact_id,)
    ).fetchone() is not None


def _usage_contribution(fp: FactProjection) -> dict:
    """单条 fact 对会话 token 聚合的增量贡献（非 usage fact 全 0）。"""
    usage = fp.usage or {}
    is_usage = fp.usage is not None
    input_tokens = _int(usage.get("input_tokens"))
    cache_observed_flag = is_usage and bool(usage.get("cache_observed")) and input_tokens > 0
    return {
        "effective_units": _int(usage.get("units")),
        "model_call_count": 1 if is_usage else 0,
        "max_single_call_units": _int(usage.get("units")),
        "cached_input_units": _int(usage.get("cached_input_tokens")),
        "input_token_units": input_tokens,
        "output_token_units": _int(usage.get("output_tokens")),
        "total_token_units": _int(usage.get("total_tokens")),
        "cache_write_input_units": _int(usage.get("cache_write_input_tokens")),
        "reasoning_output_units": _int(usage.get("reasoning_output_tokens")),
        "credit_total": _float(usage.get("credit")),
        "cache_observed_input_units": input_tokens if cache_observed_flag else 0,
    }


_UPSERT_SQL = """
insert into conversations (
  conversation_ref, base_ref, source_path_hash, start_line,
  session_ref, session_title, agent_type, source_id, source_kind,
  ws_agent_type, ws_workspace_id, ws_workspace_path, ws_workspace_label,
  ws_workspace_alias_source, ws_workspace_confidence,
  started_at, last_event_at, first_prompt_at, first_response_at,
  prompt_preview, response_preview,
  prompt_count, response_count, event_count, hit_count,
  effective_units, model_call_count, max_single_call_units,
  cached_input_units, input_token_units, output_token_units, total_token_units,
  cache_write_input_units, reasoning_output_units, credit_total,
  cache_observed_input_units, cache_hit_rate
) values (
  :conversation_ref, :base_ref, :source_path_hash, :start_line,
  :session_ref, :session_title, :agent_type, :source_id, :source_kind,
  :ws_agent_type, :ws_workspace_id, :ws_workspace_path, :ws_workspace_label,
  :ws_workspace_alias_source, :ws_workspace_confidence,
  :occurred_at, :occurred_at, null, null,
  '', '',
  :prompt_count, :response_count, 1, :hit_count,
  :effective_units, :model_call_count, :max_single_call_units,
  :cached_input_units, :input_token_units, :output_token_units, :total_token_units,
  :cache_write_input_units, :reasoning_output_units, :credit_total,
  :cache_observed_input_units, :cache_hit_rate
)
on conflict(conversation_ref) do update set
  session_ref = coalesce(nullif(conversations.session_ref, ''), excluded.session_ref),
  session_title = coalesce(nullif(conversations.session_title, ''), excluded.session_title),
  agent_type = coalesce(nullif(conversations.agent_type, ''), excluded.agent_type),
  source_id = coalesce(nullif(conversations.source_id, ''), excluded.source_id),
  source_kind = coalesce(nullif(conversations.source_kind, ''), excluded.source_kind),
  ws_agent_type = coalesce(nullif(conversations.ws_agent_type, ''), excluded.ws_agent_type),
  ws_workspace_id = coalesce(nullif(conversations.ws_workspace_id, ''), excluded.ws_workspace_id),
  ws_workspace_path = coalesce(nullif(conversations.ws_workspace_path, ''), excluded.ws_workspace_path),
  ws_workspace_label = coalesce(nullif(conversations.ws_workspace_label, ''), excluded.ws_workspace_label),
  ws_workspace_alias_source = coalesce(nullif(conversations.ws_workspace_alias_source, ''), excluded.ws_workspace_alias_source),
  ws_workspace_confidence = coalesce(nullif(conversations.ws_workspace_confidence, 'unknown'), excluded.ws_workspace_confidence),
  started_at = min(conversations.started_at, excluded.started_at),
  last_event_at = max(conversations.last_event_at, excluded.last_event_at),
  prompt_count = conversations.prompt_count + excluded.prompt_count,
  response_count = conversations.response_count + excluded.response_count,
  event_count = conversations.event_count + 1,
  hit_count = conversations.hit_count + excluded.hit_count,
  effective_units = conversations.effective_units + excluded.effective_units,
  model_call_count = conversations.model_call_count + excluded.model_call_count,
  max_single_call_units = max(conversations.max_single_call_units, excluded.max_single_call_units),
  cached_input_units = conversations.cached_input_units + excluded.cached_input_units,
  input_token_units = conversations.input_token_units + excluded.input_token_units,
  output_token_units = conversations.output_token_units + excluded.output_token_units,
  total_token_units = conversations.total_token_units + excluded.total_token_units,
  cache_write_input_units = conversations.cache_write_input_units + excluded.cache_write_input_units,
  reasoning_output_units = conversations.reasoning_output_units + excluded.reasoning_output_units,
  credit_total = conversations.credit_total + excluded.credit_total,
  cache_observed_input_units = conversations.cache_observed_input_units + excluded.cache_observed_input_units,
  cache_hit_rate = case when (conversations.cache_observed_input_units + excluded.cache_observed_input_units) > 0
    then round((conversations.cached_input_units + excluded.cached_input_units) * 1.0
      / (conversations.cache_observed_input_units + excluded.cache_observed_input_units), 4)
    else 0 end
"""


def _upsert_conversation(conn: sqlite3.Connection, fp: FactProjection, *, is_hit: bool) -> None:
    ws = fp.workspace or {}
    uc = _usage_contribution(fp)
    observed = uc["cache_observed_input_units"]
    cached = uc["cached_input_units"]
    initial_rate = round(cached / observed, 4) if observed > 0 else 0.0
    conn.execute(
        _UPSERT_SQL,
        {
            "conversation_ref": fp.conversation_ref,
            "base_ref": fp.base_ref,
            "source_path_hash": fp.source_path_hash,
            "start_line": _turn_start_line(fp.conversation_ref),
            "session_ref": fp.session_ref,
            "session_title": fp.session_title,
            "agent_type": fp.agent_type,
            "source_id": fp.source_id,
            "source_kind": fp.source_kind,
            "ws_agent_type": ws.get("agent_type", ""),
            "ws_workspace_id": ws.get("workspace_id", ""),
            "ws_workspace_path": ws.get("workspace_path", ""),
            "ws_workspace_label": ws.get("workspace_label", ""),
            "ws_workspace_alias_source": ws.get("workspace_alias_source", ""),
            "ws_workspace_confidence": ws.get("workspace_confidence", "") or "unknown",
            "occurred_at": fp.occurred_at,
            "prompt_count": 1 if fp.is_prompt else 0,
            "response_count": 1 if fp.is_response else 0,
            "hit_count": 1 if is_hit else 0,
            "effective_units": uc["effective_units"],
            "model_call_count": uc["model_call_count"],
            "max_single_call_units": uc["max_single_call_units"],
            "cached_input_units": uc["cached_input_units"],
            "input_token_units": uc["input_token_units"],
            "output_token_units": uc["output_token_units"],
            "total_token_units": uc["total_token_units"],
            "cache_write_input_units": uc["cache_write_input_units"],
            "reasoning_output_units": uc["reasoning_output_units"],
            "credit_total": uc["credit_total"],
            "cache_observed_input_units": uc["cache_observed_input_units"],
            "cache_hit_rate": initial_rate,
        },
    )


def _write_message(conn: sqlite3.Connection, fp: FactProjection) -> None:
    if fp.role is None:
        return
    content = fp.message_content
    if not content:
        return
    conn.execute(
        """
        insert into conversation_messages
          (fact_id, conversation_ref, base_ref, source_path_hash, source_line, role, category,
           occurred_at, content, raw_available, sensitive_matches_json)
        values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        on conflict(fact_id) do update set
          conversation_ref = excluded.conversation_ref,
          base_ref = excluded.base_ref,
          source_path_hash = excluded.source_path_hash,
          source_line = excluded.source_line,
          role = excluded.role,
          category = excluded.category,
          occurred_at = excluded.occurred_at,
          content = excluded.content,
          raw_available = excluded.raw_available,
          sensitive_matches_json = excluded.sensitive_matches_json
        """,
        (
            fp.fact_id, fp.conversation_ref, fp.base_ref, fp.source_path_hash, fp.source_line,
            fp.role, fp.category, fp.occurred_at, content, 1 if fp.raw_available else 0,
            json.dumps(fp.sensitive_matches or []),
        ),
    )


def _write_hit(conn: sqlite3.Connection, fp: FactProjection, is_hit: bool) -> None:
    if not is_hit:
        return
    tool_context = fp.tool_context
    conn.execute(
        """
        insert into conversation_hits
          (fact_id, conversation_ref, base_ref, source_path_hash, source_line, category, fact_type,
           severity, occurred_at, summary, content_preview, tool_context_json, sensitive_matches_json)
        values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        on conflict(fact_id) do update set
          conversation_ref = excluded.conversation_ref,
          base_ref = excluded.base_ref,
          source_path_hash = excluded.source_path_hash,
          source_line = excluded.source_line,
          category = excluded.category,
          fact_type = excluded.fact_type,
          severity = excluded.severity,
          occurred_at = excluded.occurred_at,
          summary = excluded.summary,
          content_preview = excluded.content_preview,
          tool_context_json = excluded.tool_context_json,
          sensitive_matches_json = excluded.sensitive_matches_json
        """,
        (
            fp.fact_id, fp.conversation_ref, fp.base_ref, fp.source_path_hash, fp.source_line,
            fp.category, fp.fact_type, fp.severity, fp.occurred_at, fp.summary, fp.content_preview,
            json.dumps(tool_context) if tool_context else None,
            json.dumps(fp.sensitive_matches or []),
        ),
    )


def _write_fts(conn: sqlite3.Connection, fp: FactProjection) -> None:
    if fp.role is None:
        return
    content = fp.message_content
    if not content:
        return
    conn.execute(
        "insert into conversation_messages_fts(content, conversation_ref, role, fact_id) values (?, ?, ?, ?)",
        (content, fp.conversation_ref, fp.role, fp.fact_id),
    )


def _refresh_previews(conn: sqlite3.Connection, conversation_ref: str) -> None:
    """从 conversation_messages 重算首条 prompt/response 文本（抗乱序，永远正确）。"""
    prompt = conn.execute(
        "select occurred_at, content from conversation_messages "
        "where conversation_ref = ? and role = 'user' order by occurred_at, fact_id limit 1",
        (conversation_ref,),
    ).fetchone()
    response = conn.execute(
        "select occurred_at, content from conversation_messages "
        "where conversation_ref = ? and role = 'assistant' order by occurred_at, fact_id limit 1",
        (conversation_ref,),
    ).fetchone()
    conn.execute(
        "update conversations set first_prompt_at = ?, prompt_preview = ?, "
        "first_response_at = ?, response_preview = ? where conversation_ref = ?",
        (
            prompt["occurred_at"] if prompt else None,
            truncate_preview(prompt["content"]) if prompt else "",
            response["occurred_at"] if response else None,
            truncate_preview(response["content"]) if response else "",
            conversation_ref,
        ),
    )


def apply(conn: sqlite3.Connection, fp: FactProjection, *, maintain_index: bool = True) -> None:
    """新 fact 的唯一写入路径（ingest 事务内调用，不 commit）。

    ``maintain_index=False`` 时跳过 FTS 写入与 preview 重算——供离线 rebuild 批量
    构建使用，结束后由调用方一次性重建（见 ``rebuild_secondary_indexes``）。
    """
    if fp.fact_type == "collector_health":
        return
    is_hit = _is_hit(conn, fp)
    _upsert_conversation(conn, fp, is_hit=is_hit)
    _write_message(conn, fp)
    _write_hit(conn, fp, is_hit)
    if maintain_index:
        _write_fts(conn, fp)
        _refresh_previews(conn, fp.conversation_ref)


def rebuild_secondary_indexes(conn: sqlite3.Connection) -> None:
    """离线 rebuild 收尾：一次性重建 FTS 与 previews（配合 ``apply(maintain_index=False)``）。"""
    conn.execute(
        "insert into conversation_messages_fts(content, conversation_ref, role, fact_id) "
        "select content, conversation_ref, role, fact_id from conversation_messages"
    )
    for row in conn.execute("select conversation_ref from conversations").fetchall():
        _refresh_previews(conn, row["conversation_ref"])
    conn.commit()


def refresh(conn: sqlite3.Connection, fact_id: str, fp: FactProjection) -> None:
    """dedup（同 source_event_id 重传）刷新该 fact 的物化行。

    删旧 message/hit/fts → 重插 → 重算 previews + hit_count；
    **不动** event_count / token（首次 ingest 已计入，dedup 不新增 fact）。
    """
    if fp.fact_type == "collector_health":
        return
    old = conn.execute(
        "select conversation_ref from conversation_messages where fact_id = ?", (fact_id,)
    ).fetchone()
    old_ref = old["conversation_ref"] if old else None
    conn.execute("delete from conversation_messages where fact_id = ?", (fact_id,))
    conn.execute("delete from conversation_hits where fact_id = ?", (fact_id,))
    conn.execute("delete from conversation_messages_fts where fact_id = ?", (fact_id,))
    is_hit = _is_hit(conn, fp)
    _write_message(conn, fp)
    _write_hit(conn, fp, is_hit)
    _write_fts(conn, fp)
    refs = {fp.conversation_ref}
    if old_ref:
        refs.add(old_ref)
    for ref in refs:
        if not ref:
            continue
        _refresh_previews(conn, ref)
        conn.execute(
            "update conversations set hit_count = "
            "(select count(*) from conversation_hits where conversation_ref = ?) "
            "where conversation_ref = ?",
            (ref, ref),
        )


def prune_before(conn: sqlite3.Connection, cutoff: str) -> int:
    """删除 last_event_at < cutoff 的会话（级联删 messages/hits；FTS 手动删）。返回删除数。"""
    rows = conn.execute(
        "select conversation_ref from conversations where last_event_at < ?", (cutoff,)
    ).fetchall()
    refs = [row["conversation_ref"] for row in rows]
    if not refs:
        return 0
    placeholders = ",".join("?" for _ in refs)
    conn.execute(
        f"delete from conversation_messages_fts where conversation_ref in ({placeholders})", refs
    )
    # conversations 删除 → messages/hits 经 on delete cascade 清除
    conn.execute(f"delete from conversations where conversation_ref in ({placeholders})", refs)
    return len(refs)
