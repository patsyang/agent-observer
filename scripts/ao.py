from __future__ import annotations

import sys
from pathlib import Path


def _configure_utf8_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


_configure_utf8_stdio()

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_RUNNER_SRC = REPO_ROOT / "tools/workflow_runner/src"
sys.path.insert(0, str(WORKFLOW_RUNNER_SRC))

from agentic_workflow.ao_entry import (  # noqa: E402
    build_alias_args,
    build_workflow_args,
    main,
    run_agentic_check,
)


if __name__ == "__main__":
    raise SystemExit(main())
