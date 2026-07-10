from __future__ import annotations

import json
import logging
import re
import threading
from datetime import UTC, datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

_LOGGER_NAME = "agent-observer"
_VALID_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR"}
_DEFAULT_LEVEL = "INFO"
_MAX_BYTES = 5 * 1024 * 1024
_BACKUP_COUNT = 3

_cache_lock = threading.Lock()
_cached_level: str = _DEFAULT_LEVEL


def _default_db_path() -> Path:
    from app.db.connection import default_db_path
    return default_db_path()


def setup_logging(db_path: Path | None = None) -> logging.Logger:
    db = db_path or _default_db_path()
    log_dir = db.parent / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "server.log"

    logger = logging.getLogger(_LOGGER_NAME)
    logger.setLevel(logging.DEBUG)

    if not logger.handlers:
        console = logging.StreamHandler()
        console.setFormatter(_ConsoleFormatter())
        console.setLevel(logging.INFO)
        logger.addHandler(console)

        file_handler = RotatingFileHandler(
            log_path, maxBytes=_MAX_BYTES, backupCount=_BACKUP_COUNT, encoding="utf-8",
        )
        file_handler.setFormatter(_JsonFormatter())
        file_handler.setLevel(logging.DEBUG)
        logger.addHandler(file_handler)

    with _cache_lock:
        # logger 始终 DEBUG；仅通过 handler 级别控制输出
        for handler in logger.handlers:
            if isinstance(handler, logging.StreamHandler) and not isinstance(handler, RotatingFileHandler):
                handler.setLevel(getattr(logging, _cached_level, logging.INFO))
    return logger


def apply_log_level(level: str) -> None:
    name = (level or "").strip().upper()
    if name not in _VALID_LEVELS:
        name = _DEFAULT_LEVEL
    with _cache_lock:
        global _cached_level
        _cached_level = name
    logger = logging.getLogger(_LOGGER_NAME)
    # logger 始终保持 DEBUG，仅通过 handler 级别控制过滤
    # 这样 FileHandler（始终 DEBUG）能收到所有记录
    logger.setLevel(logging.DEBUG)
    for handler in logger.handlers:
        if isinstance(handler, logging.StreamHandler) and not isinstance(handler, RotatingFileHandler):
            handler.setLevel(getattr(logging, name))


def cached_log_level() -> str:
    with _cache_lock:
        return _cached_level


def get_log_path(db_path: Path | None = None) -> Path:
    db = db_path or _default_db_path()
    return db.parent / "logs" / "server.log"


POLL_PATH_PREFIXES = (
    "/api/collectors",
)


def is_poll_path(path: str) -> bool:
    return any(path == prefix or path.startswith(prefix + "/") for prefix in POLL_PATH_PREFIXES)


_SANITIZE_PATTERN = re.compile(
    r'((?:api_key|token|authorization|password|secret)\s*[:=]\s*)["\']?[\w\-./+=]+["\']?',
    re.IGNORECASE,
)


def _sanitize(message: str) -> str:
    return _SANITIZE_PATTERN.sub(r'\1***', message)


class _ConsoleFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        ts = datetime.fromtimestamp(record.created, tz=UTC).strftime("%H:%M:%S")
        level = record.levelname
        msg = _sanitize(record.getMessage())
        prefix = f"[{ts}] {level:<5}"
        if record.exc_info and record.exc_info[1]:
            tb = _sanitize(self.formatException(record.exc_info)).replace("\n", f"\n{' ' * len(prefix)}  ")
            return f"{prefix}{msg}\n{' ' * len(prefix)}  {tb}"
        return f"{prefix}{msg}"


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry: dict = {
            "ts": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "msg": _sanitize(record.getMessage()),
            "module": record.name,
        }
        if record.exc_info and record.exc_info[1]:
            entry["traceback"] = _sanitize(self.formatException(record.exc_info))
        for key in ("method", "path", "status", "duration_ms"):
            value = getattr(record, key, None)
            if value is not None:
                entry[key] = value
        return json.dumps(entry, ensure_ascii=False, sort_keys=True)
