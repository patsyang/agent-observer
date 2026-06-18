from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def main() -> int:
    args = sys.argv[1:]
    if not args or args[0] != "exec":
        print("missing codex exec", file=sys.stderr)
        return 11
    if "--output-last-message" not in args:
        print("missing --output-last-message", file=sys.stderr)
        return 12

    final_message = Path(args[args.index("--output-last-message") + 1])
    artifacts_dir = Path(os.environ["AO_ARTIFACTS_DIR"])
    workflow = os.environ["AO_WORKFLOW"]
    node_id = os.environ["AO_NODE_ID"]
    required = json.loads(os.environ.get("AO_REQUIRED_ARTIFACTS", "[]"))
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    for artifact_name in required:
        _write_artifact(artifacts_dir, artifact_name, workflow=workflow, node_id=node_id)

    if node_id == "independent-review":
        (artifacts_dir / "review.md").write_text(
            "| 状态 | 计数 |\n| --- | --- |\n| OK | 1 |\n| WARN | 0 |\n| FAIL | 0 |\n",
            encoding="utf-8",
        )
    if node_id == "acceptance-matrix":
        _write_acceptance_matrix(artifacts_dir)

    final = _final_message(node_id)
    final_message.write_text(final, encoding="utf-8")
    print(final)
    return 0


def _write_artifact(artifacts_dir: Path, artifact_name: str, *, workflow: str, node_id: str) -> None:
    path = artifacts_dir / artifact_name
    if artifact_name == "changed-files.txt":
        path.write_text("apps/agentic_factory/demo.txt\n", encoding="utf-8")
        return
    if artifact_name == "task-graph.json":
        path.write_text(
            json.dumps(
                {
                    "workflow": workflow,
                    "node_id": node_id,
                    "tasks": [
                        {
                            "id": "T001",
                            "write_set": ["apps/agentic_factory/**"],
                            "depends_on": [],
                        }
                    ],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        return
    if artifact_name in {"stories.json", "implementation-state.json"}:
        path.write_text(
            json.dumps({"stories": [{"id": "S1", "passes": True}]}, ensure_ascii=False),
            encoding="utf-8",
        )
        return
    if artifact_name == "acceptance-matrix.json":
        _write_acceptance_matrix(artifacts_dir)
        return
    path.write_text(
        f"# {artifact_name}\n\nworkflow={workflow}\nnode={node_id}\n",
        encoding="utf-8",
    )


def _write_acceptance_matrix(artifacts_dir: Path) -> None:
    run_dir = artifacts_dir.parent
    (run_dir / "logs").mkdir(exist_ok=True)
    (run_dir / "e2e").mkdir(exist_ok=True)
    (run_dir / "logs" / "verify.txt").write_text("ok", encoding="utf-8")
    (run_dir / "e2e" / "primary.png").write_bytes(b"png")
    matrix = [
        {
            "acceptance_id": "A01",
            "story_id": "S1",
            "result": "PASS",
            "evidence": [
                {
                    "type": "command",
                    "command": "python scripts/verify.py",
                    "exit_code": 0,
                    "log_path": "logs/verify.txt",
                },
                {
                    "type": "playwright",
                    "scenario": "primary workflow",
                    "assertions": ["state changed"],
                    "screenshot_path": "e2e/primary.png",
                },
            ],
        }
    ]
    (artifacts_dir / "acceptance-matrix.json").write_text(
        json.dumps(matrix, ensure_ascii=False),
        encoding="utf-8",
    )


def _final_message(node_id: str) -> str:
    if node_id == "implement-loop":
        return "COMPLETE"
    if node_id == "fix-loop":
        return "NO_ACTIONABLE_WARNINGS"
    return node_id


if __name__ == "__main__":
    raise SystemExit(main())
