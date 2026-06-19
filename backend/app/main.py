from __future__ import annotations

from app.collectors.service import (
    delete_collector,
    heartbeat,
    list_collectors,
    register_collector,
    update_collector_display_name,
    update_collector_raw_upload,
)
from app.db.connection import connect
from app.diagnostics.service import (
    cancel_diagnostic,
    get_diagnostic_availability,
    get_next_collector_diagnostic,
    record_collector_diagnostic_result,
    record_diagnostic_result,
    request_diagnostic,
)
from app.facts.service import get_fact_detail, query_facts
from app.ingest.service import ingest_telemetry
from app.package.builder import build_windows_package
from app.policy import get_effective_policy, recent_audit, update_effective_policy
from app.risks.service import get_risk_summary
from app.stories.service import get_story_detail, handle_story, list_stories, mark_story_read, rebuild_stories
from app.usage.service import get_usage_summary
from app.validation.service import run_minimum_validation_experiment

try:
    from fastapi import FastAPI, HTTPException
    from fastapi.responses import FileResponse
except ImportError:  # pragma: no cover - allows service tests without optional runtime deps.
    FastAPI = None


def create_app():
    if FastAPI is None:
        raise RuntimeError("FastAPI is required to run the API server")
    app = FastAPI(title="Agent Observer")

    @app.get("/api/health")
    def health():
        with connect() as conn:
            policy = get_effective_policy(conn)
        return {
            "status": "ok",
            "stack_contract_ref": "agent-observer-stack@1",
            "policy_version": policy["policy_version"],
        }

    @app.post("/api/collectors/register")
    def api_register(payload: dict):
        with connect() as conn:
            return register_collector(conn, payload)

    @app.post("/api/collectors/{collector_id}/heartbeat")
    def api_heartbeat(collector_id: str, payload: dict):
        with connect() as conn:
            try:
                return heartbeat(conn, collector_id, payload)
            except LookupError as exc:
                raise HTTPException(status_code=404, detail="collector not found") from exc

    @app.patch("/api/collectors/{collector_id}/display-name")
    def api_collector_display_name(collector_id: str, payload: dict):
        with connect() as conn:
            try:
                return update_collector_display_name(conn, collector_id, payload.get("display_name", ""))
            except LookupError as exc:
                raise HTTPException(status_code=404, detail="collector not found") from exc
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.patch("/api/collectors/{collector_id}/raw-upload")
    def api_collector_raw_upload(collector_id: str, payload: dict):
        with connect() as conn:
            try:
                return update_collector_raw_upload(conn, collector_id, bool(payload.get("enabled")))
            except LookupError as exc:
                raise HTTPException(status_code=404, detail="collector not found") from exc
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc

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
                raise HTTPException(status_code=404, detail="collector not found") from exc

    @app.post("/api/telemetry/ingest")
    def api_ingest(payload: dict):
        with connect() as conn:
            try:
                return ingest_telemetry(conn, payload)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/facts")
    def api_facts(
        quality: str | None = None,
        fact_type: str | None = None,
        source: str | None = None,
        window: str = "1h",
        include_health: bool = False,
        limit: int = 50,
        offset: int = 0,
    ):
        with connect() as conn:
            return query_facts(
                conn,
                quality=quality,
                fact_type=fact_type,
                source=source,
                window=window,
                include_health=include_health,
                limit=limit,
                offset=offset,
            )

    @app.get("/api/facts/{fact_id}")
    def api_fact_detail(fact_id: str):
        with connect() as conn:
            try:
                return get_fact_detail(conn, fact_id)
            except LookupError as exc:
                raise HTTPException(status_code=404, detail="fact not found") from exc

    @app.get("/api/usage/summary")
    def api_usage_summary(window: str = "24h"):
        with connect() as conn:
            return get_usage_summary(conn, window=window)

    @app.get("/api/risks/summary")
    def api_risk_summary(mode: str = "summary", window: str = "24h"):
        with connect() as conn:
            return get_risk_summary(conn, mode=mode, window=window)

    @app.post("/api/validation/minimum-experiment")
    def api_minimum_validation():
        with connect() as conn:
            return run_minimum_validation_experiment(conn)

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
                raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/audit/recent")
    def api_recent_audit():
        with connect() as conn:
            return recent_audit(conn)

    @app.get("/api/stories")
    def api_stories(include_hidden: bool = False, window: str = "1h", queue: str = "actionable"):
        with connect() as conn:
            return list_stories(conn, include_hidden=include_hidden, window=window, queue=queue)

    @app.get("/api/stories/{story_id}")
    def api_story_detail(story_id: str):
        with connect() as conn:
            try:
                return get_story_detail(conn, story_id)
            except LookupError as exc:
                raise HTTPException(status_code=404, detail="story not found") from exc

    @app.post("/api/stories/rebuild")
    def api_rebuild_stories(payload: dict):
        with connect() as conn:
            return rebuild_stories(conn, reason=payload.get("reason", "api"))

    @app.post("/api/stories/{story_id}/read")
    def api_mark_story_read(story_id: str):
        with connect() as conn:
            try:
                return mark_story_read(conn, story_id)
            except LookupError as exc:
                raise HTTPException(status_code=404, detail="story not found") from exc

    @app.post("/api/stories/{story_id}/handle")
    def api_handle_story(story_id: str, payload: dict):
        with connect() as conn:
            try:
                return handle_story(conn, story_id, payload.get("conclusion_code"), payload.get("note"))
            except LookupError as exc:
                raise HTTPException(status_code=404, detail="story not found") from exc
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/stories/{story_id}/diagnostics/availability")
    def api_diagnostic_availability(story_id: str):
        with connect() as conn:
            try:
                return get_diagnostic_availability(conn, story_id)
            except LookupError as exc:
                raise HTTPException(status_code=404, detail="story not found") from exc

    @app.post("/api/stories/{story_id}/diagnostics")
    def api_request_diagnostic(story_id: str, payload: dict):
        with connect() as conn:
            try:
                return request_diagnostic(conn, story_id, payload.get("capability_id", ""))
            except LookupError as exc:
                raise HTTPException(status_code=404, detail="story not found") from exc
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/diagnostics/{job_id}/cancel")
    def api_cancel_diagnostic(job_id: str):
        with connect() as conn:
            try:
                return cancel_diagnostic(conn, job_id)
            except LookupError as exc:
                raise HTTPException(status_code=404, detail="diagnostic job not found") from exc
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/diagnostics/{job_id}/result")
    def api_diagnostic_result(job_id: str, payload: dict):
        with connect() as conn:
            try:
                return record_diagnostic_result(
                    conn,
                    job_id,
                    payload.get("status", ""),
                    payload.get("summary", ""),
                    payload.get("projection"),
                )
            except LookupError as exc:
                raise HTTPException(status_code=404, detail="diagnostic job not found") from exc
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/collectors/{collector_id}/diagnostics/next")
    def api_collector_next_diagnostic(collector_id: str):
        with connect() as conn:
            try:
                return get_next_collector_diagnostic(conn, collector_id)
            except LookupError as exc:
                raise HTTPException(status_code=404, detail="collector not found") from exc

    @app.post("/api/collectors/{collector_id}/diagnostics/{job_id}/result")
    def api_collector_diagnostic_result(collector_id: str, job_id: str, payload: dict):
        with connect() as conn:
            try:
                return record_collector_diagnostic_result(conn, collector_id, job_id, payload)
            except LookupError as exc:
                raise HTTPException(status_code=404, detail="diagnostic job not found") from exc
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/client-package/config")
    def api_config():
        with connect() as conn:
            return build_windows_package(conn)

    @app.get("/api/client-package/windows")
    def api_package():
        with connect() as conn:
            package = build_windows_package(conn)
        return FileResponse(package["path"], filename=package["filename"])

    return app


app = create_app() if FastAPI is not None else None
