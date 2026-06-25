from __future__ import annotations

from app.collectors.service import (
    delete_collector,
    heartbeat,
    list_collectors,
    register_collector,
    update_collector_display_name,
)
from app.conversations.service import get_conversation_for_fact, get_conversation_query, query_conversations
from app.dashboard.service import get_dashboard_summary
from app.db.connection import connect
from app.evidence_enrichment.service import (
    cancel_enrichment,
    get_enrichment_availability,
    get_next_collector_enrichment,
    record_collector_enrichment_result,
    record_enrichment_result,
    request_enrichment,
)
from app.ingest.service import ingest_telemetry
from app.package.builder import build_windows_package
from app.policy import get_effective_policy, recent_audit, update_effective_policy
from app.processing.jobs import enqueue_global_signal_rebuild, processing_status, run_next_job
from app.risks.service import get_risk_summary
from app.behavior_signals.service import get_signal_detail, handle_signal, list_signals, mark_signal_read
from app.telemetry_batches.service import get_batch_status
from app.usage.service import get_usage_summary
from app.validation.service import run_minimum_validation_experiment


def register_routes(app, http_exception, file_response) -> None:
    register_health_routes(app)
    register_collector_routes(app, http_exception)
    register_ingest_routes(app, http_exception)
    register_conversation_routes(app, http_exception)
    register_policy_routes(app, http_exception)
    register_signal_routes(app, http_exception)
    register_processing_routes(app)
    register_enrichment_routes(app, http_exception)
    register_summary_routes(app)
    register_package_routes(app, file_response)


def register_health_routes(app) -> None:
    @app.get("/api/health")
    def health():
        with connect() as conn:
            policy = get_effective_policy(conn)
        return {"status": "ok", "stack_contract_ref": "agent-observer-stack@1", "policy_version": policy["policy_version"]}


def register_collector_routes(app, http_exception) -> None:
    @app.post("/api/collectors/register")
    def api_register(payload: dict):
        with connect() as conn:
            try:
                return register_collector(conn, payload)
            except ValueError as exc:
                raise http_exception(status_code=400, detail=str(exc)) from exc

    @app.post("/api/collectors/{collector_id}/heartbeat")
    def api_heartbeat(collector_id: str, payload: dict):
        with connect() as conn:
            try:
                return heartbeat(conn, collector_id, payload)
            except LookupError as exc:
                raise http_exception(status_code=404, detail="collector not found") from exc
            except ValueError as exc:
                raise http_exception(status_code=400, detail=str(exc)) from exc

    @app.patch("/api/collectors/{collector_id}/display-name")
    def api_collector_display_name(collector_id: str, payload: dict):
        with connect() as conn:
            try:
                return update_collector_display_name(conn, collector_id, payload.get("display_name", ""))
            except LookupError as exc:
                raise http_exception(status_code=404, detail="collector not found") from exc
            except ValueError as exc:
                raise http_exception(status_code=400, detail=str(exc)) from exc

    @app.get("/api/collectors")
    def api_collectors():
        with connect() as conn:
            return {"collectors": list_collectors(conn)}

    @app.delete("/api/collectors/{collector_id}")
    def api_delete_collector(collector_id: str):
        with connect() as conn:
            try:
                return delete_collector(conn, collector_id)
            except LookupError as exc:
                raise http_exception(status_code=404, detail="collector not found") from exc


def register_ingest_routes(app, http_exception) -> None:
    @app.post("/api/telemetry/ingest")
    def api_ingest(payload: dict):
        with connect() as conn:
            try:
                return ingest_telemetry(conn, payload)
            except ValueError as exc:
                raise http_exception(status_code=400, detail=str(exc)) from exc

    @app.get("/api/telemetry/batches/{batch_id}")
    def api_batch_status(batch_id: str):
        with connect() as conn:
            return get_batch_status(conn, batch_id)


def register_conversation_routes(app, http_exception) -> None:
    @app.get("/api/conversations")
    def api_conversations(
        window: str = "1h",
        start_at: str | None = None,
        end_at: str | None = None,
        prompt_query: str | None = None,
        response_query: str | None = None,
        workspace_query: str | None = None,
        agent_type: str | None = None,
        source_id: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ):
        with connect() as conn:
            return query_conversations(
                conn,
                window=window,
                start_at=start_at,
                end_at=end_at,
                prompt_query=prompt_query,
                response_query=response_query,
                workspace_query=workspace_query,
                agent_type=agent_type,
                source_id=source_id,
                page=page,
                page_size=page_size,
            )

    @app.get("/api/conversations/by-fact/{fact_id}")
    def api_conversation_by_fact(fact_id: str):
        with connect() as conn:
            try:
                return get_conversation_for_fact(conn, fact_id)
            except LookupError as exc:
                raise http_exception(status_code=404, detail="conversation not found") from exc

    @app.get("/api/conversations/{conversation_ref}")
    def api_conversation_detail(conversation_ref: str):
        with connect() as conn:
            try:
                return get_conversation_query(conn, conversation_ref)
            except LookupError as exc:
                raise http_exception(status_code=404, detail="conversation not found") from exc


def register_policy_routes(app, http_exception) -> None:
    @app.get("/api/policy")
    def api_policy():
        with connect() as conn:
            return get_effective_policy(conn)

    @app.patch("/api/policy")
    def api_update_policy(payload: dict):
        with connect() as conn:
            try:
                return update_effective_policy(conn, payload)
            except ValueError as exc:
                raise http_exception(status_code=400, detail=str(exc)) from exc

    @app.get("/api/audit/recent")
    def api_recent_audit():
        with connect() as conn:
            return recent_audit(conn)


def register_signal_routes(app, http_exception) -> None:
    @app.get("/api/signals")
    def api_signals(
        window: str = "1h",
        workspace_query: str | None = None,
        agent_type: str | None = None,
        start_at: str | None = None,
        end_at: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ):
        with connect() as conn:
            return list_signals(
                conn,
                window=window,
                workspace_query=workspace_query,
                agent_type=agent_type,
                start_at=start_at,
                end_at=end_at,
                page=page,
                page_size=page_size,
            )

    @app.get("/api/signals/{signal_id}")
    def api_signal_detail(signal_id: str):
        with connect() as conn:
            try:
                return get_signal_detail(conn, signal_id)
            except LookupError as exc:
                raise http_exception(status_code=404, detail="signal not found") from exc

    @app.post("/api/signals/rebuild")
    def api_rebuild_signals(payload: dict):
        with connect() as conn:
            return enqueue_global_signal_rebuild(conn, reason=payload.get("reason", "api"))

    @app.post("/api/signals/{signal_id}/read")
    def api_mark_signal_read(signal_id: str):
        with connect() as conn:
            try:
                return mark_signal_read(conn, signal_id)
            except LookupError as exc:
                raise http_exception(status_code=404, detail="signal not found") from exc

    @app.post("/api/signals/{signal_id}/handle")
    def api_handle_signal(signal_id: str, payload: dict):
        with connect() as conn:
            try:
                return handle_signal(conn, signal_id, payload.get("conclusion_code"), payload.get("note"))
            except LookupError as exc:
                raise http_exception(status_code=404, detail="signal not found") from exc
            except ValueError as exc:
                raise http_exception(status_code=400, detail=str(exc)) from exc


def register_processing_routes(app) -> None:
    @app.get("/api/processing/status")
    def api_processing_status():
        with connect() as conn:
            return processing_status(conn)

    @app.post("/api/processing/jobs/run-once")
    def api_processing_run_once():
        with connect() as conn:
            return run_next_job(conn, reason="api-run-once")


def register_enrichment_routes(app, http_exception) -> None:
    @app.get("/api/signals/{signal_id}/enrichments/availability")
    def api_enrichment_availability(signal_id: str):
        with connect() as conn:
            try:
                return get_enrichment_availability(conn, signal_id)
            except LookupError as exc:
                raise http_exception(status_code=404, detail="signal not found") from exc

    @app.post("/api/signals/{signal_id}/enrichments")
    def api_request_enrichment(signal_id: str, payload: dict):
        with connect() as conn:
            try:
                return request_enrichment(conn, signal_id, payload.get("capability_id", ""))
            except LookupError as exc:
                raise http_exception(status_code=404, detail="signal not found") from exc
            except ValueError as exc:
                raise http_exception(status_code=400, detail=str(exc)) from exc

    @app.post("/api/enrichments/{job_id}/cancel")
    def api_cancel_enrichment(job_id: str):
        with connect() as conn:
            try:
                return cancel_enrichment(conn, job_id)
            except LookupError as exc:
                raise http_exception(status_code=404, detail="enrichment job not found") from exc
            except ValueError as exc:
                raise http_exception(status_code=400, detail=str(exc)) from exc

    @app.post("/api/enrichments/{job_id}/result")
    def api_enrichment_result(job_id: str, payload: dict):
        with connect() as conn:
            try:
                return record_enrichment_result(
                    conn,
                    job_id,
                    payload.get("status", ""),
                    payload.get("summary", ""),
                    payload.get("projection"),
                    payload.get("redaction"),
                )
            except LookupError as exc:
                raise http_exception(status_code=404, detail="enrichment job not found") from exc
            except ValueError as exc:
                raise http_exception(status_code=400, detail=str(exc)) from exc

    @app.get("/api/collectors/{collector_id}/enrichments/next")
    def api_collector_next_enrichment(collector_id: str):
        with connect() as conn:
            try:
                return get_next_collector_enrichment(conn, collector_id)
            except LookupError as exc:
                raise http_exception(status_code=404, detail="collector not found") from exc

    @app.post("/api/collectors/{collector_id}/enrichments/{job_id}/result")
    def api_collector_enrichment_result(collector_id: str, job_id: str, payload: dict):
        with connect() as conn:
            try:
                return record_collector_enrichment_result(conn, collector_id, job_id, payload)
            except LookupError as exc:
                raise http_exception(status_code=404, detail="enrichment job not found") from exc
            except ValueError as exc:
                raise http_exception(status_code=400, detail=str(exc)) from exc


def register_summary_routes(app) -> None:
    @app.get("/api/dashboard/summary")
    def api_dashboard_summary(window: str = "1h", agent_type: str | None = None, start_at: str | None = None, end_at: str | None = None):
        with connect() as conn:
            return get_dashboard_summary(conn, window=window, agent_type=agent_type, start_at=start_at, end_at=end_at)

    @app.get("/api/usage/summary")
    def api_usage_summary(window: str = "24h", agent_type: str | None = None, start_at: str | None = None, end_at: str | None = None):
        with connect() as conn:
            return get_usage_summary(conn, window=window, agent_type=agent_type, start_at=start_at, end_at=end_at)

    @app.get("/api/risks/summary")
    def api_risk_summary(
        mode: str = "summary",
        window: str = "24h",
        agent_type: str | None = None,
        start_at: str | None = None,
        end_at: str | None = None,
    ):
        with connect() as conn:
            return get_risk_summary(conn, mode=mode, window=window, agent_type=agent_type, start_at=start_at, end_at=end_at)

    @app.post("/api/validation/minimum-experiment")
    def api_minimum_validation():
        with connect() as conn:
            return run_minimum_validation_experiment(conn)


def register_package_routes(app, file_response) -> None:
    @app.get("/api/client-package/config")
    def api_config():
        with connect() as conn:
            return build_windows_package(conn)

    @app.get("/api/client-package/windows")
    def api_package():
        with connect() as conn:
            package = build_windows_package(conn)
        return file_response(package["path"], filename=package["filename"])
