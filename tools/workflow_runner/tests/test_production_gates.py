import json
import sys

import pytest

from agentic_workflow.e2e_runner import run_e2e_workflow
from agentic_workflow.models import ArtifactSpec, WorkflowInput
from agentic_workflow.production_gates import (
    ProductionGateError,
    select_next_story,
    validate_acceptance_matrix,
    validate_frontend_template_selection,
    validate_required_artifact_specs,
)
from agentic_workflow.runner import create_run_context, prepare_run


def write_production_spec_definition(repo_root):
    definition_dir = repo_root / ".agentic" / "workflow" / "definitions"
    definition_dir.mkdir(parents=True)
    (definition_dir / "spec-driven.json").write_text(
        json.dumps(
            {
                "name": "spec-driven",
                "title": "生产级规格驱动开发",
                "adapter": "local-governed",
                "contract_path": ".agentic/workflow/spec-driven.md",
                "primary_inputs": ["spec_path", "plan_path"],
                "stages": [
                    "generate-production-spec",
                    "story-production-gate",
                    "implement-loop",
                    "independent-review",
                    "e2e-proof",
                    "acceptance-matrix",
                ],
                "verify_policy": "full",
                "worktree": False,
                "nodes": [
                    {
                        "id": "generate-production-spec",
                        "required_artifacts": ["production-spec.md", "stories.json"],
                    },
                    {
                        "id": "implement-loop",
                        "type": "loop",
                        "until": "COMPLETE",
                        "max_iterations": 2,
                        "required_artifacts": ["implementation-state.json", "progress.md"],
                    },
                    {"id": "independent-review", "required_artifacts": ["review.md"]},
                    {"id": "e2e-proof", "required_artifacts": ["e2e-proof.md"]},
                    {"id": "acceptance-matrix", "required_artifacts": ["acceptance-matrix.json"]},
                ],
            }
        ),
        encoding="utf-8",
    )


def write_node_definition(repo_root):
    definition_dir = repo_root / ".agentic" / "workflow" / "definitions"
    definition_dir.mkdir(parents=True)
    (definition_dir / "small-change.json").write_text(
        json.dumps(
            {
                "name": "small-change",
                "title": "E2E 小改动",
                "adapter": "local-governed",
                "contract_path": ".agentic/workflow/small-change.md",
                "primary_inputs": ["goal", "goal_path"],
                "stages": ["scope-resolve", "execute", "review", "report"],
                "verify_policy": "targeted",
                "nodes": [
                    {
                        "id": "execute",
                        "required_artifacts": ["implementation.md", "changed-files.txt"],
                    },
                    {"id": "review", "required_artifacts": ["review.md"]},
                ],
            }
        ),
        encoding="utf-8",
    )


def write_project_config(project_root, *, adapter_command):
    config_dir = project_root / ".agentic"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "project.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "project_id": project_root.name,
                "project_name": project_root.name,
                "adapter": {"id": "codex", "command": adapter_command},
                "verify": {"command": [sys.executable, "-c", "print('verify')"]},
            }
        ),
        encoding="utf-8",
    )
    write_stack_contract(project_root)


def write_stack_contract(project_root):
    config_dir = project_root / ".agentic"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "stack-contract.json").write_text(
        json.dumps(
            {
                "contract_id": f"{project_root.name}-stack",
                "project_id": project_root.name,
                "revision": 1,
                "status": "confirmed",
                "components": [
                    {
                        "component_id": "app",
                        "kind": "service",
                        "language": "python",
                        "framework": "pytest",
                        "root": ".",
                        "package_manager": "pip",
                    }
                ],
                "commands": {"verify_all": ["python scripts/verify.py"]},
            }
        ),
        encoding="utf-8",
    )


def write_fake_codex(path):
    path.write_text(
        "\n".join(
            [
                "import json, os, sys",
                "from pathlib import Path",
                "args = sys.argv[1:]",
                "if not args or args[0] != 'exec':",
                "    print('missing codex exec', file=sys.stderr)",
                "    sys.exit(11)",
                "final_message = Path(args[args.index('--output-last-message') + 1])",
                "node = os.environ['AO_NODE_ID']",
                "artifacts = Path(os.environ['AO_ARTIFACTS_DIR'])",
                "run_dir = artifacts.parent",
                "ref = None",
                "if os.environ.get('AO_STACK_CONTRACT_HASH'):",
                "    ref = {'contract_id': os.environ['AO_STACK_CONTRACT_ID'], 'revision': int(os.environ['AO_STACK_CONTRACT_REVISION']), 'hash': os.environ['AO_STACK_CONTRACT_HASH']}",
                "for name in json.loads(os.environ.get('AO_REQUIRED_ARTIFACTS', '[]')):",
                "    path = artifacts / name",
                "    if name.endswith('.json'):",
                "        path.write_text('{}', encoding='utf-8')",
                "    else:",
                "        path.write_text(f'# {name}\\nnode={node}\\n', encoding='utf-8')",
                "if node == 'generate-production-spec':",
                "    (artifacts / 'stories.json').write_text(json.dumps({'stories': [{'id': 'S1', 'passes': True}]}), encoding='utf-8')",
                "if node == 'independent-review':",
                "    (artifacts / 'review.md').write_text('| 状态 | 计数 |\\n| --- | --- |\\n| OK | 1 |\\n| WARN | 0 |\\n| FAIL | 0 |\\n', encoding='utf-8')",
                "if node == 'acceptance-matrix':",
                "    (run_dir / 'logs').mkdir(exist_ok=True)",
                "    (run_dir / 'e2e').mkdir(exist_ok=True)",
                "    (run_dir / 'logs' / 'verify.txt').write_text('ok', encoding='utf-8')",
                "    (run_dir / 'e2e' / 'primary.png').write_bytes(b'png')",
                "    item = {'acceptance_id': 'A01', 'story_id': 'S1', 'result': 'PASS', 'evidence': [{'type': 'command', 'command': 'python scripts/verify.py', 'exit_code': 0, 'log_path': 'logs/verify.txt'}, {'type': 'playwright', 'scenario': 'primary workflow', 'assertions': ['state changed'], 'screenshot_path': 'e2e/primary.png'}]}",
                "    matrix = {'stack_contract_ref': ref, 'acceptance': [item]} if ref else [item]",
                "    (artifacts / 'acceptance-matrix.json').write_text(json.dumps(matrix), encoding='utf-8')",
                "    if ref:",
                "        (artifacts / 'component-evidence.json').write_text(json.dumps({'stack_contract_ref': ref, 'components': [{'component_id': 'app', 'evidence': ['production-spec.md']}]}), encoding='utf-8')",
                "        (artifacts / 'command-coverage.json').write_text(json.dumps({'stack_contract_ref': ref, 'commands': [{'name': 'verify_all', 'command': 'python scripts/verify.py', 'result': 'PASS'}]}), encoding='utf-8')",
                "final_message.write_text('COMPLETE' if node == 'implement-loop' else node, encoding='utf-8')",
                "print('COMPLETE' if node == 'implement-loop' else node)",
            ]
        ),
        encoding="utf-8",
    )


def test_story_selector_prefers_unblocked_priority_story():
    stories = [
        {"id": "S1", "priority": 20, "passes": False, "depends_on": []},
        {"id": "S2", "priority": 10, "passes": False, "depends_on": ["S3"]},
        {"id": "S3", "priority": 5, "passes": True, "depends_on": []},
    ]

    selected = select_next_story(stories)

    assert selected is not None
    assert selected["id"] == "S2"


def test_acceptance_matrix_requires_existing_evidence(tmp_path):
    matrix = tmp_path / "acceptance-matrix.json"
    matrix.write_text(
        json.dumps(
            [
                {
                    "acceptance_id": "A01",
                    "story_id": "S1",
                    "result": "PASS",
                    "evidence": [
                        {
                            "type": "command",
                            "command": "python scripts/verify.py",
                            "exit_code": 0,
                            "log_path": "logs/missing.txt",
                        }
                    ],
                }
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ProductionGateError, match="evidence path does not exist"):
        validate_acceptance_matrix(matrix, run_dir=tmp_path)


def test_review_fail_blocks_acceptance_matrix_pass(tmp_path):
    log_path = tmp_path / "logs" / "verify.txt"
    log_path.parent.mkdir()
    log_path.write_text("ok", encoding="utf-8")
    review = tmp_path / "review.md"
    review.write_text("| 状态 | 计数 |\n| --- | --- |\n| OK | 0 |\n| WARN | 0 |\n| FAIL | 1 |\n", encoding="utf-8")
    matrix = tmp_path / "acceptance-matrix.json"
    matrix.write_text(
        json.dumps(
            [
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
                        }
                    ],
                }
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ProductionGateError, match="review contains unresolved FAIL/WARN"):
        validate_acceptance_matrix(matrix, run_dir=tmp_path, review_path=review)


def test_review_fail_with_fix_loop_resolution_allows_acceptance_matrix_pass(tmp_path):
    log_path = tmp_path / "logs" / "verify.txt"
    log_path.parent.mkdir()
    log_path.write_text("ok", encoding="utf-8")
    review = tmp_path / "review-findings.json"
    review.write_text(
        json.dumps(
            {
                "findings": [
                    {"id": "FAIL-001", "severity": "FAIL", "story_id": "S1"}
                ]
            }
        ),
        encoding="utf-8",
    )
    fix = tmp_path / "fix-state.json"
    fix.write_text(
        json.dumps(
            {
                "status": "NO_ACTIONABLE_WARNINGS",
                "resolved_findings": [
                    {
                        "id": "FAIL-001",
                        "verification": [
                            {
                                "command": "python scripts/verify.py",
                                "exit_code": 0,
                                "evidence_path": "logs/verify.txt",
                            }
                        ],
                    }
                ],
                "unresolved_findings": [],
            }
        ),
        encoding="utf-8",
    )
    matrix = tmp_path / "acceptance-matrix.json"
    matrix.write_text(
        json.dumps(
            [
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
                        }
                    ],
                }
            ]
        ),
        encoding="utf-8",
    )

    result = validate_acceptance_matrix(
        matrix,
        run_dir=tmp_path,
        review_path=review,
        fix_path=fix,
    )

    assert result[0]["acceptance_id"] == "A01"


def test_review_fail_with_unresolved_fix_state_blocks_acceptance_matrix_pass(tmp_path):
    log_path = tmp_path / "logs" / "verify.txt"
    log_path.parent.mkdir()
    log_path.write_text("ok", encoding="utf-8")
    review = tmp_path / "review.md"
    review.write_text("| 状态 | 计数 |\n| --- | --- |\n| OK | 0 |\n| WARN | 0 |\n| FAIL | 1 |\n", encoding="utf-8")
    fix = tmp_path / "fix-state.json"
    fix.write_text(
        json.dumps(
            {
                "status": "NO_ACTIONABLE_WARNINGS",
                "unresolved_findings": [{"id": "FAIL-001"}],
            }
        ),
        encoding="utf-8",
    )
    matrix = tmp_path / "acceptance-matrix.json"
    matrix.write_text(
        json.dumps(
            [
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
                        }
                    ],
                }
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ProductionGateError, match="review contains unresolved FAIL/WARN"):
        validate_acceptance_matrix(
            matrix,
            run_dir=tmp_path,
            review_path=review,
            fix_path=fix,
        )


def test_review_fail_requires_fix_state_to_cover_all_findings(tmp_path):
    log_path = tmp_path / "logs" / "verify.txt"
    log_path.parent.mkdir()
    log_path.write_text("ok", encoding="utf-8")
    review = tmp_path / "review-findings.json"
    review.write_text(
        json.dumps(
            {
                "findings": [
                    {"id": "FAIL-001", "severity": "FAIL"},
                    {"id": "WARN-001", "severity": "WARN"},
                ]
            }
        ),
        encoding="utf-8",
    )
    fix = tmp_path / "fix-state.json"
    fix.write_text(
        json.dumps(
            {
                "status": "NO_ACTIONABLE_WARNINGS",
                "resolved_findings": [
                    {
                        "id": "FAIL-001",
                        "verification": [
                            {
                                "command": "python scripts/verify.py",
                                "exit_code": 0,
                                "evidence_path": "logs/verify.txt",
                            }
                        ],
                    }
                ],
                "unresolved_findings": [],
            }
        ),
        encoding="utf-8",
    )
    matrix = tmp_path / "acceptance-matrix.json"
    matrix.write_text(
        json.dumps(
            [
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
                        }
                    ],
                }
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ProductionGateError, match="review contains unresolved FAIL/WARN"):
        validate_acceptance_matrix(
            matrix,
            run_dir=tmp_path,
            review_path=review,
            fix_path=fix,
        )


def test_acceptance_matrix_allows_enveloped_acceptance_items(tmp_path):
    log_path = tmp_path / "logs" / "verify.txt"
    log_path.parent.mkdir()
    log_path.write_text("ok", encoding="utf-8")
    matrix = tmp_path / "acceptance-matrix.json"
    matrix.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "result": "PASS",
                "acceptance": [
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
                            }
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    result = validate_acceptance_matrix(matrix, run_dir=tmp_path)

    assert result[0]["story_id"] == "S1"


def test_acceptance_matrix_allows_v2_acceptance_items_and_structured_evidence(tmp_path):
    source_path = tmp_path / "artifacts" / "st-001-verification.json"
    source_path.parent.mkdir()
    source_path.write_text("{}", encoding="utf-8")
    matrix = tmp_path / "acceptance-matrix.json"
    matrix.write_text(
        json.dumps(
            {
                "schema_version": "0.1",
                "result": "PASS",
                "acceptance_items": [
                    {
                        "acceptance_id": "A01",
                        "story_id": "S1",
                        "result": "PASS",
                        "behavior": "A real command proved the behavior.",
                        "evidence": {
                            "evidence_types": ["command", "api"],
                            "commands": [
                                {
                                    "command": "python scripts/verify.py",
                                    "exit_code": 0,
                                    "result": "PASS",
                                    "source": "artifacts/st-001-verification.json",
                                }
                            ],
                            "paths": ["artifacts/st-001-verification.json"],
                            "screenshot_only": False,
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    result = validate_acceptance_matrix(matrix, run_dir=tmp_path)

    assert result[0]["acceptance_id"] == "A01"


def test_ui_acceptance_requires_browser_or_playwright_evidence(tmp_path):
    source_path = tmp_path / "artifacts" / "st-008-verification.json"
    source_path.parent.mkdir()
    source_path.write_text("{}", encoding="utf-8")
    matrix = tmp_path / "acceptance-matrix.json"
    matrix.write_text(
        json.dumps(
            {
                "result": "PASS",
                "acceptance_items": [
                    {
                        "acceptance_id": "AC-012",
                        "story_id": "ST-008",
                        "result": "PASS",
                        "behavior": "Dashboard UI marks a message handled from the product surface.",
                        "evidence": {
                            "evidence_types": ["command", "api"],
                            "commands": [
                                {
                                    "command": "go test ./internal/server/http",
                                    "exit_code": 0,
                                    "source": "artifacts/st-008-verification.json",
                                }
                            ],
                            "paths": ["artifacts/st-008-verification.json"],
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ProductionGateError, match="browser/UI evidence"):
        validate_acceptance_matrix(matrix, run_dir=tmp_path)


def test_ui_acceptance_allows_browser_equivalent_action_evidence(tmp_path):
    source_path = tmp_path / "artifacts" / "st-008-verification.json"
    source_path.parent.mkdir()
    source_path.write_text("{}", encoding="utf-8")
    matrix = tmp_path / "acceptance-matrix.json"
    matrix.write_text(
        json.dumps(
            {
                "result": "PASS",
                "acceptance_items": [
                    {
                        "acceptance_id": "AC-012",
                        "story_id": "ST-008",
                        "result": "PASS",
                        "behavior": "Dashboard UI marks a message handled from the product surface.",
                        "evidence": {
                            "evidence_types": ["command", "browser"],
                            "commands": [
                                {
                                    "command": "go test ./internal/server/http",
                                    "exit_code": 0,
                                    "source": "artifacts/st-008-verification.json",
                                }
                            ],
                            "browser": {
                                "submitted_form": True,
                                "persisted_state": True,
                                "assertions": ["status feedback rendered"],
                                "screenshot_only": False,
                            },
                            "paths": ["artifacts/st-008-verification.json"],
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    result = validate_acceptance_matrix(matrix, run_dir=tmp_path)

    assert result[0]["acceptance_id"] == "AC-012"


def test_frontend_template_selection_requires_implementation_contract(tmp_path):
    selection = tmp_path / "frontend-template-selection.json"
    selection.write_text(
        json.dumps(
            {
                "frontend_required": True,
                "template_id": "observability-dashboard",
                "required_views": ["summary"],
                "required_components": ["AppShell"],
                "required_states": ["loading"],
                "required_interactions": ["navigate"],
                "api_contracts": ["GET /api/dashboard/summary"],
                "e2e_scenarios": ["open summary"],
                "visual_quality_rubric": ["operational density"],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ProductionGateError, match="frontend_implementation"):
        validate_frontend_template_selection(selection)


def test_new_frontend_template_selection_rejects_unapproved_server_rendered_fallback(tmp_path):
    selection = tmp_path / "frontend-template-selection.json"
    selection.write_text(
        json.dumps(
            {
                "frontend_required": True,
                "template_id": "observability-dashboard",
                "required_views": ["summary"],
                "required_components": ["AppShell"],
                "required_states": ["loading"],
                "required_interactions": ["navigate"],
                "api_contracts": ["GET /api/dashboard/summary"],
                "e2e_scenarios": ["open summary"],
                "visual_quality_rubric": ["operational density"],
                "frontend_implementation": {
                    "mode": "server_rendered_equivalent",
                    "stack_source": "project_standard",
                    "source_root": "internal/server/http",
                    "test_commands": ["go test ./internal/server/http"],
                    "e2e_commands": ["go test ./internal/server/http -run Dashboard"],
                    "quality_equivalence": "Matches frontend product gate.",
                },
            }
        ),
        encoding="utf-8",
    )
    inspection = tmp_path / "project-inspection.json"
    inspection.write_text(json.dumps({"frontend": {"exists": False}}), encoding="utf-8")

    with pytest.raises(ProductionGateError, match="server-rendered frontend requires"):
        validate_frontend_template_selection(
            selection,
            project_inspection_path=inspection,
        )


def test_frontend_template_selection_accepts_traceable_independent_stack(tmp_path):
    selection = tmp_path / "frontend-template-selection.json"
    selection.write_text(
        json.dumps(
            {
                "frontend_required": True,
                "template_id": "observability-dashboard",
                "required_views": ["summary"],
                "required_components": ["AppShell"],
                "required_states": ["loading"],
                "required_interactions": ["navigate"],
                "api_contracts": ["GET /api/dashboard/summary"],
                "e2e_scenarios": ["open summary"],
                "visual_quality_rubric": ["operational density"],
                "frontend_implementation": {
                    "mode": "independent_frontend",
                    "stack_source": "spec_tech_stack",
                    "source_root": "frontend",
                    "package_manifest": "frontend/package.json",
                    "framework": "React",
                    "language": "TypeScript",
                    "package_manager": "npm",
                    "test_commands": ["npm --prefix frontend test"],
                    "build_commands": ["npm --prefix frontend run build"],
                    "e2e_commands": ["npx playwright test"],
                },
            }
        ),
        encoding="utf-8",
    )

    validate_frontend_template_selection(selection)


def test_acceptance_matrix_infers_command_evidence_type(tmp_path):
    log_path = tmp_path / "logs" / "verify.txt"
    log_path.parent.mkdir()
    log_path.write_text("ok", encoding="utf-8")
    matrix = tmp_path / "acceptance-matrix.json"
    matrix.write_text(
        json.dumps(
            [
                {
                    "acceptance_id": "A01",
                    "story_id": "S1",
                    "result": "PASS",
                    "evidence": [
                        {
                            "command": "python scripts/verify.py",
                            "exit_code": 0,
                            "path": "logs/verify.txt",
                            "assertions": ["verified behavior"],
                        }
                    ],
                }
            ]
        ),
        encoding="utf-8",
    )

    result = validate_acceptance_matrix(matrix, run_dir=tmp_path)

    assert result[0]["acceptance_id"] == "A01"


def test_e2e_gate_rejects_screenshot_only_proof(tmp_path):
    screenshot = tmp_path / "e2e" / "screen.png"
    screenshot.parent.mkdir()
    screenshot.write_bytes(b"not really a png")
    matrix = tmp_path / "acceptance-matrix.json"
    matrix.write_text(
        json.dumps(
            [
                {
                    "acceptance_id": "A01",
                    "story_id": "S1",
                    "result": "PASS",
                    "evidence": [
                        {
                            "type": "screenshot",
                            "screenshot_path": "e2e/screen.png",
                        }
                    ],
                }
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ProductionGateError, match="screenshot-only"):
        validate_acceptance_matrix(matrix, run_dir=tmp_path)


def test_spec_driven_uses_production_acceptance_matrix(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTIC_FACTORY_HOME", str(tmp_path / "home"))
    write_production_spec_definition(tmp_path)
    project_root = tmp_path / "apps" / "sample"
    fake_codex = tmp_path / "fake_codex.py"
    write_fake_codex(fake_codex)
    write_project_config(project_root, adapter_command=[sys.executable, str(fake_codex)])
    spec = project_root / "specs" / "001-prod" / "spec.md"
    spec.parent.mkdir(parents=True)
    spec.write_text("# Spec\n", encoding="utf-8")
    context = create_run_context(
        tmp_path,
        WorkflowInput(workflow="spec-driven", spec_path=str(spec), project_root=str(project_root)),
        run_id="run_spec_production",
    )
    prepare_run(context)

    result = run_e2e_workflow(context, use_worktree=False)

    assert result.return_code == 0
    acceptance = json.loads((context.run_dir / "acceptance-matrix.json").read_text())
    assert acceptance["stack_contract_ref"]["contract_id"] == "sample-stack"
    assert acceptance["acceptance"][0]["story_id"] == "S1"
    assert acceptance["acceptance"][0]["evidence"][1]["type"] == "playwright"


def test_spec_driven_without_project_adapter_fails(tmp_path):
    write_production_spec_definition(tmp_path)
    spec = tmp_path / "apps" / "sample" / "specs" / "001-prod" / "spec.md"
    spec.parent.mkdir(parents=True)
    spec.write_text("# Spec\n", encoding="utf-8")
    context = create_run_context(
        tmp_path,
        WorkflowInput(workflow="spec-driven", spec_path=str(spec)),
        run_id="run_builtin_codex",
    )
    prepare_run(context)

    with pytest.raises(RuntimeError, match="project runtime adapter is required"):
        run_e2e_workflow(context, use_worktree=False)

    run_state = json.loads((context.run_dir / "run.json").read_text(encoding="utf-8"))
    assert run_state["status"] == "FAILED"
    assert run_state["failed_node"] == "generate-production-spec"
    report = (context.run_dir / "run-report.md").read_text(encoding="utf-8")
    assert "status: `failed`" in report
    assert "project runtime adapter is required" in report


def test_run_e2e_workflow_writes_failed_state_with_resume_command(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTIC_FACTORY_HOME", str(tmp_path / "home"))
    write_node_definition(tmp_path)
    project_root = tmp_path / "apps" / "app-a"
    project_root.mkdir(parents=True)
    fake_codex = tmp_path / "fake_codex_fail.py"
    fake_codex.write_text("import sys\nprint('boom', file=sys.stderr)\nsys.exit(7)\n", encoding="utf-8")
    write_project_config(project_root, adapter_command=[sys.executable, str(fake_codex)])
    context = create_run_context(
        tmp_path,
        WorkflowInput(
            workflow="small-change",
            goal="修复 Dashboard",
            project_root=str(project_root),
        ),
        run_id="run_failed_state",
    )
    prepare_run(context)

    with pytest.raises(RuntimeError, match="node failed"):
        run_e2e_workflow(context, use_worktree=False)

    run_state = json.loads((context.run_dir / "run.json").read_text(encoding="utf-8"))
    assert run_state["status"] == "FAILED"
    assert run_state["failed_node"] == "execute"
    assert "workflow resume --run-id run_failed_state" in run_state["resume_command"]


def test_waiting_state_final_message_fails_node(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTIC_FACTORY_HOME", str(tmp_path / "home"))
    write_node_definition(tmp_path)
    project_root = tmp_path / "apps" / "app-a"
    project_root.mkdir(parents=True)
    fake_codex = tmp_path / "fake_codex_waiting.py"
    fake_codex.write_text(
        "\n".join(
            [
                "import json, os, sys",
                "from pathlib import Path",
                "args = sys.argv[1:]",
                "final_message = Path(args[args.index('--output-last-message') + 1])",
                "artifacts = Path(os.environ['AO_ARTIFACTS_DIR'])",
                "for name in json.loads(os.environ.get('AO_REQUIRED_ARTIFACTS', '[]')):",
                "    (artifacts / name).write_text('real artifact', encoding='utf-8')",
                "final_message.write_text('请提供这个工作流节点的具体任务', encoding='utf-8')",
                "print('请提供这个工作流节点的具体任务')",
            ]
        ),
        encoding="utf-8",
    )
    write_project_config(project_root, adapter_command=[sys.executable, str(fake_codex)])
    context = create_run_context(
        tmp_path,
        WorkflowInput(
            workflow="small-change",
            goal="修复 Dashboard",
            project_root=str(project_root),
        ),
        run_id="run_waiting_state",
    )
    prepare_run(context)

    with pytest.raises(RuntimeError, match="adapter exited 66"):
        run_e2e_workflow(context, use_worktree=False)

    diagnostics = (
        context.run_dir / "nodes" / "execute" / "adapter-diagnostics.json"
    )
    assert diagnostics.exists()
    payload = json.loads(diagnostics.read_text(encoding="utf-8"))
    assert payload["reason"] == "waiting_state_final_message"


def test_object_required_artifact_rejects_placeholder_markdown(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTIC_FACTORY_HOME", str(tmp_path / "home"))
    definition_dir = tmp_path / ".agentic" / "workflow" / "definitions"
    definition_dir.mkdir(parents=True)
    (definition_dir / "small-change.json").write_text(
        json.dumps(
            {
                "name": "small-change",
                "title": "E2E 小改动",
                "adapter": "local-governed",
                "contract_path": ".agentic/workflow/small-change.md",
                "primary_inputs": ["goal"],
                "stages": ["execute"],
                "verify_policy": "targeted",
                "nodes": [
                    {
                        "id": "execute",
                        "required_artifacts": [
                            {
                                "path": "implementation.md",
                                "kind": "markdown",
                                "validators": ["non_placeholder"],
                            }
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    project_root = tmp_path / "apps" / "app-a"
    project_root.mkdir(parents=True)
    fake_codex = tmp_path / "fake_codex_placeholder.py"
    fake_codex.write_text(
        "\n".join(
            [
                "import os, sys",
                "from pathlib import Path",
                "args = sys.argv[1:]",
                "final_message = Path(args[args.index('--output-last-message') + 1])",
                "artifacts = Path(os.environ['AO_ARTIFACTS_DIR'])",
                "(artifacts / 'implementation.md').write_text('# <短标题>\\n', encoding='utf-8')",
                "final_message.write_text('done', encoding='utf-8')",
                "print('done')",
            ]
        ),
        encoding="utf-8",
    )
    write_project_config(project_root, adapter_command=[sys.executable, str(fake_codex)])
    context = create_run_context(
        tmp_path,
        WorkflowInput(workflow="small-change", goal="x", project_root=str(project_root)),
        run_id="run_placeholder_gate",
    )
    prepare_run(context)

    with pytest.raises(RuntimeError, match="placeholder"):
        run_e2e_workflow(context, use_worktree=False)


def test_placeholder_scan_allows_negative_gate_report(tmp_path):
    artifact = tmp_path / "product-state-gate.md"
    artifact.write_text(
        "\n".join(
            [
                "# Product State Gate",
                "",
                "| Check | Result | Finding |",
                "| --- | --- | --- |",
                "| Template and placeholder scan | PASS | No `TODO`, `TBD`, or template residue was found. |",
                "",
                "The following placeholder references were reviewed and treated as allowed product text.",
            ]
        ),
        encoding="utf-8",
    )

    validate_required_artifact_specs(
        [ArtifactSpec(path="product-state-gate.md", kind="markdown")],
        artifacts_dir=tmp_path,
    )


def test_gate_pass_validator_rejects_failed_gate_json(tmp_path):
    artifact = tmp_path / "spec-gate.json"
    artifact.write_text(
        json.dumps({"result": "FAIL", "failures": ["missing section"]}),
        encoding="utf-8",
    )

    with pytest.raises(ProductionGateError, match="not passing"):
        validate_required_artifact_specs(
            [
                ArtifactSpec(
                    path="spec-gate.json",
                    kind="json",
                    validators=["gate_pass"],
                )
            ],
            artifacts_dir=tmp_path,
        )


def test_gate_pass_validator_accepts_stable_gate_status(tmp_path):
    artifact = tmp_path / "stabilize-state.json"
    artifact.write_text(json.dumps({"status": "STABLE"}), encoding="utf-8")

    validate_required_artifact_specs(
        [
            ArtifactSpec(
                path="stabilize-state.json",
                kind="json",
                validators=["gate_pass"],
            )
        ],
        artifacts_dir=tmp_path,
    )
