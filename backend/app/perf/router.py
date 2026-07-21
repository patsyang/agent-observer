"""性能观测路由：注册 /api/performance/* 端点。"""
from __future__ import annotations

from app.db.connection import connect
from app.perf.service import (
    _VALID_WINDOWS,
    build_perf_rollups,
    get_failure_timeline,
    get_perf_call_timeline,
    get_perf_rollups,
    get_perf_summary,
    get_perf_task_detail,
    get_perf_tasks,
)


def _check_window(window: str, http_exception) -> None:
    if window not in _VALID_WINDOWS:
        raise http_exception(status_code=400, detail=f"invalid window: {window}") from None


def _wrap_perf_call(fn, http_exception, *args, **kwargs):
    """M3: 捕获 service 层 ValueError（无效 start_at/end_at 等）转为 400，避免 500 污染日志。"""
    try:
        return fn(*args, **kwargs)
    except ValueError as exc:
        raise http_exception(status_code=400, detail=str(exc)) from None


def register_performance_routes(app, http_exception) -> None:
    @app.get("/api/performance/summary")
    def api_perf_summary(
        window: str = "24h",
        agent_type: str | None = None,
        span_type: str | None = None,
        start_at: str | None = None,
        end_at: str | None = None,
    ):
        _check_window(window, http_exception)
        with connect() as conn:
            return _wrap_perf_call(
                get_perf_summary, http_exception, conn,
                window=window, agent_type=agent_type, span_type=span_type,
                start_at=start_at, end_at=end_at,
            )

    @app.get("/api/performance/tasks")
    def api_perf_tasks(
        window: str = "24h",
        agent_type: str | None = None,
        page: int = 1,
        page_size: int = 20,
        start_at: str | None = None,
        end_at: str | None = None,
    ):
        _check_window(window, http_exception)
        with connect() as conn:
            return _wrap_perf_call(
                get_perf_tasks, http_exception, conn,
                window=window, agent_type=agent_type, page=page, page_size=page_size,
                start_at=start_at, end_at=end_at,
            )

    @app.get("/api/performance/tasks/{trace_id}")
    def api_perf_task_detail(trace_id: str):
        with connect() as conn:
            result = get_perf_task_detail(conn, trace_id)
            if result is None:
                raise http_exception(status_code=404, detail="task not found") from None
            return result

    @app.get("/api/performance/tasks/{trace_id}/calls")
    def api_perf_call_timeline(trace_id: str, span_type: str | None = None):
        with connect() as conn:
            return {"calls": get_perf_call_timeline(conn, trace_id, span_type=span_type)}

    @app.get("/api/performance/failures")
    def api_perf_failures(
        window: str = "24h",
        agent_type: str | None = None,
        start_at: str | None = None,
        end_at: str | None = None,
    ):
        _check_window(window, http_exception)
        with connect() as conn:
            return {
                "failures": _wrap_perf_call(
                    get_failure_timeline, http_exception, conn,
                    window=window, agent_type=agent_type,
                    start_at=start_at, end_at=end_at,
                )
            }

    @app.get("/api/performance/rollups")
    def api_perf_rollups(window: str = "24h", scope: str | None = None):
        _check_window(window, http_exception)
        with connect() as conn:
            return {"rollups": get_perf_rollups(conn, window=window, scope=scope)}

    @app.post("/api/performance/rebuild")
    def api_perf_rebuild(window: str = "24h"):
        _check_window(window, http_exception)
        with write_lock() as conn:
            return build_perf_rollups(conn, window=window)