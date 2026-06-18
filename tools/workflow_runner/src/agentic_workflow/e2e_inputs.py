from __future__ import annotations

import json
from pathlib import Path

from .features import init_source_package_from_document
from .models import RunContext


def run_system_import_node(
    context: RunContext,
    *,
    artifacts_dir: Path,
    worktree_path: Path,
) -> str:
    if context.workflow_input.prd_path:
        result = init_source_package_from_document(
            repo_root=context.repo_root,
            project_name=context.project_name or context.project_root.name,
            doc_type="prd",
            source_path=context.workflow_input.prd_path,
            target_root=worktree_path,
        )
    elif context.workflow_input.source_spec_path:
        result = init_source_package_from_document(
            repo_root=context.repo_root,
            project_name=context.project_name or context.project_root.name,
            doc_type="spec",
            source_path=context.workflow_input.source_spec_path,
            target_root=worktree_path,
        )
    else:
        result = {
            "project_name": context.project_name or context.project_root.name,
            "doc_type": "none",
            "feature_dir": None,
            "source_path": None,
            "imported_path": None,
            "source_package_path": None,
            "spec_path": context.workflow_input.spec_path,
            "plan_path": context.workflow_input.plan_path,
            "generated_seed_artifacts": [],
            "expected_artifacts": [],
        }
    path = artifacts_dir / "imported-source.json"
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return json.dumps(result, ensure_ascii=False)
