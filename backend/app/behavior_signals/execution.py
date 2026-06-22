from __future__ import annotations

import sqlite3
from collections import defaultdict
from typing import Callable

from app.behavior_signals.common import loads, signal_id
from app.behavior_signals.helpers import (
    conversation_refs,
    enrichment_group,
    exit_code_from_summary,
    failure_group,
    first_text,
    primary_projection,
    signature_facts,
)

UpsertSignal = Callable[..., dict]


def build_tool_execution_failures(conn: sqlite3.Connection, reason: str, upsert_signal: UpsertSignal) -> list[dict]:
    signatures = conn.execute(
        "select * from error_signatures where category in ('tool_execution_failure', 'workflow_step_failure') order by signature_key"
    ).fetchall()
    groups: dict[str, list[tuple[sqlite3.Row, dict]]] = defaultdict(list)
    seen: set[str] = set()
    for signature in signatures:
        for fact in signature_facts(conn, [signature]):
            if fact["fact_id"] in seen:
                continue
            seen.add(fact["fact_id"])
            projection = primary_projection(conn, fact["fact_id"])
            groups[_execution_group_key(fact, projection)].append((fact, projection))
    results = []
    for key, entries in groups.items():
        facts = [fact for fact, _ in entries]
        projections = [projection for _, projection in entries]
        tool = first_text(projections, "tool_name", "tool", "name") or "工具调用"
        exit_code = first_text(projections, "exit_code") or exit_code_from_summary(facts[-1]["summary"])
        workflow = first_text(projections, "workflow")
        run_id = first_text(projections, "run_id")
        kind = "workflow_step_failure" if workflow and run_id else "tool_execution_failure"
        title = _execution_title(kind, facts, tool, exit_code, workflow, "失败")
        signal_key = f"{kind}:{key}"
        results.append(
            upsert_signal(
                conn,
                signal_key=signal_key,
                signal_kind=kind,
                title=title,
                why_it_matters=f"同类失败在 {len(conversation_refs(facts)):,} 个会话中出现 {len(facts):,} 次，应优先核对命令、环境和最近输入。",
                severity="high",
                confidence="high",
                priority_score=95,
                facts=facts,
                affected_scope={"conversation_count": len(conversation_refs(facts)), "failure_count": len(facts), "tool_names": [tool], "exit_codes": [exit_code] if exit_code else [], "workflows": [workflow] if workflow else [], "run_ids": [run_id] if run_id else []},
                evidence_groups=[failure_group(conn, "failure", "命中事件", facts, projections), enrichment_group(conn, signal_id(signal_key))],
                suggested_actions=["打开命中会话查看完整输入输出和错误摘要；若同一命令反复失败，优先修复环境或参数。"],
                reason=reason,
            )
        )
    return results


def build_execution_timeouts(conn: sqlite3.Connection, reason: str, upsert_signal: UpsertSignal) -> list[dict]:
    rows = conn.execute(
        "select * from observed_facts where category in ('tool_execution_timeout', 'workflow_step_timeout') order by occurred_at, fact_id"
    ).fetchall()
    groups: dict[str, list[sqlite3.Row]] = defaultdict(list)
    projections: dict[str, dict] = {}
    for row in rows:
        projection = primary_projection(conn, row["fact_id"])
        projections[row["fact_id"]] = projection
        key = f"workflow:{projection.get('workflow')}:{projection.get('run_id')}:{projection.get('command_fingerprint')}" if row["category"] == "workflow_step_timeout" and projection.get("workflow") and projection.get("run_id") else _execution_group_key(row, projection)
        groups[key].append(row)
    signals = []
    for key, facts in groups.items():
        latest = projections.get(facts[-1]["fact_id"], {})
        workflow = str(latest.get("workflow") or "")
        run_id = str(latest.get("run_id") or "")
        kind = "workflow_step_timeout" if facts[-1]["category"] == "workflow_step_timeout" and workflow and run_id else "tool_execution_timeout"
        tool = str(latest.get("tool_name") or latest.get("tool") or latest.get("name") or "工具调用")
        title = _execution_title(kind, facts, tool, str(latest.get("exit_code") or ""), workflow, "超时")
        signals.append(
            upsert_signal(
                conn,
                signal_key=f"{kind}:{key}",
                signal_kind=kind,
                title=title,
                why_it_matters="超时发生在用户会话或 Agent Workflow 执行过程中，需要确认命令是否卡住、超时阈值是否合理以及是否需要拆分任务。",
                severity="high",
                confidence="high" if latest.get("command") or workflow else "medium",
                priority_score=90,
                facts=facts,
                affected_scope={"run_ids": [run_id] if run_id else [], "workflows": [workflow] if workflow else [], "timeout_count": len(facts), "duration_seconds": latest.get("wall_time_seconds"), "command_categories": [latest.get("command_category")] if latest.get("command_category") else []},
                evidence_groups=[failure_group(conn, "failure", "命中事件", facts, [projections.get(f["fact_id"], {}) for f in facts])],
                suggested_actions=["打开命中会话，核对超时命令、最近输入输出和工作区状态。"],
                reason=reason,
            )
        )
    return signals


def _execution_group_key(fact: sqlite3.Row, projection: dict) -> str:
    refs = loads(fact["source_refs_json"])
    agent_type = refs.get("agent_type") or fact["source"] or "unknown-agent"
    workspace = refs.get("workspace_id") or refs.get("workspace_path") or "unknown-workspace"
    conversation = fact["conversation_ref"] or fact["session_ref"] or "unknown-conversation"
    tool = projection.get("tool_name") or projection.get("tool") or projection.get("name") or "tool"
    status = "timeout" if projection.get("is_timeout") else f"exit:{projection.get('exit_code') or exit_code_from_summary(fact['summary']) or 'unknown'}"
    workflow = projection.get("workflow") or ""
    run_id = projection.get("run_id") or ""
    if workflow and run_id:
        return f"{agent_type}:{workspace}:workflow:{workflow}:{run_id}:{tool}:{status}"
    return f"{agent_type}:{workspace}:{conversation}:{tool}:{status}"


def _execution_title(kind: str, facts: list[sqlite3.Row], tool: str, exit_code: str, workflow: str, action: str) -> str:
    if kind.startswith("workflow_step"):
        suffix = f"，退出码 {exit_code}" if exit_code and action == "失败" else ""
        return f"Workflow {workflow or '未知'} 步骤{action}{suffix}"
    status = "超时" if action == "超时" else f"执行失败，退出码 {exit_code}" if exit_code else "执行失败"
    scope = "本会话" if len(conversation_refs(facts)) <= 1 else f"{len(conversation_refs(facts))} 个会话"
    return f"{scope} {len(facts):,} 次 {tool} {status}"
