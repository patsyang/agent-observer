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


def test_acceptance_matrix_accepts_structured_single_command_evidence(tmp_path):
    """复现 claude 实际生成的 evidence 格式：command（单数）+ exit_code + type。

    命令契约 ao-spec-acceptance-matrix.md 只规定"PASS 必须有 command 等行为证据"，
    未强制 commands 复数列表。claude 自然生成 command 单数 + exit_code + type=package。
    _validate_structured_evidence 应与 _evidence_type 推断逻辑（line 671-672）一致，
    识别 command 单数 + exit_code 作为命令行为证据。
    """
    matrix = tmp_path / "acceptance-matrix.json"
    matrix.write_text(
        json.dumps(
            {
                "result": "PASS",
                "acceptance_items": [
                    {
                        "acceptance_id": "ACC-001",
                        "story_id": "story-001",
                        "result": "PASS",
                        "behavior": "对包含真实 OpenAI key 的测试数据，100% 识别为 sensitive_content_exposure signal",
                        "evidence": {
                            "type": "package",
                            "test_file": "backend/tests/test_sensitivity_rules.py",
                            "test_count": 38,
                            "test_result": "38 passed, 0 failed",
                            "command": "cd backend && python -m pytest tests/test_sensitivity_rules.py -v",
                            "exit_code": 0,
                            "source_file": "backend/app/behavior_signals/sensitivity_rules.py",
                            "details": "25 种预编译正则各有一条命中真实数据样本测试",
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    result = validate_acceptance_matrix(matrix, run_dir=tmp_path)

    assert result[0]["acceptance_id"] == "ACC-001"


def test_acceptance_matrix_rejects_structured_single_command_with_failure(tmp_path):
    """command 单数 + exit_code 非 0 应判为命令证据失败。"""
    matrix = tmp_path / "acceptance-matrix.json"
    matrix.write_text(
        json.dumps(
            {
                "result": "PASS",
                "acceptance_items": [
                    {
                        "acceptance_id": "ACC-001",
                        "story_id": "story-001",
                        "result": "PASS",
                        "behavior": "命令执行验证行为",
                        "evidence": {
                            "type": "package",
                            "command": "cd backend && python -m pytest tests/test_sensitivity_rules.py -v",
                            "exit_code": 1,
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ProductionGateError, match="command evidence failed"):
        validate_acceptance_matrix(matrix, run_dir=tmp_path)


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


def test_frontend_template_selection_accepts_visual_quality_rubric_as_object(tmp_path):
    """visual_quality_rubric 为对象形态（多维度质量标准）应通过验证。

    回归点：验证器曾只接受 str/list，把 dict 形态误判为缺失，
    导致 claude 生成的结构化质量标准（label_correctness/type_safety 等维度）被拒。
    """
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
                "visual_quality_rubric": {
                    "label_correctness": "新增标签均有中文映射",
                    "type_safety": "TypeScript 编译通过",
                },
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


def test_frontend_template_selection_rejects_empty_visual_quality_rubric_object(tmp_path):
    """visual_quality_rubric 为空对象仍应被拒绝，确保放宽形态不降低非空要求。"""
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
                "visual_quality_rubric": {},
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

    with pytest.raises(ProductionGateError, match="visual_quality_rubric"):
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


def test_placeholder_scan_allows_exclude_context(tmp_path):
    """排除占位符的描述性文本不应被门禁拒绝。"""
    artifact = tmp_path / "product-prd.md"
    artifact.write_text(
        "\n".join(
            [
                "# Product PRD",
                "",
                "- 排除占位符模式：`<your-api-key>`、`${ENV_VAR}`",
                "| ACC-004 | P0-A | 误报控制 | 排除占位符、环境变量引用 |",
            ]
        ),
        encoding="utf-8",
    )

    validate_required_artifact_specs(
        [ArtifactSpec(path="product-prd.md", kind="markdown")],
        artifacts_dir=tmp_path,
    )


def test_placeholder_scan_allows_zhanweifu_meta_reference(tmp_path):
    """讨论占位符概念的元引用文本（含"占位符"三字）不应被门禁拒绝。

    回归点：PLACEHOLDER_PATTERNS 中"占位"会匹配到"占位符"这种元引用，
    导致 production-spec.md 中描述验收标准、正则注释、误报指标的行被误判。
    修复后将"占位符"加入 META_PLACEHOLDER_CONTEXT，允许元引用通过。
    """
    artifact = tmp_path / "production-spec.md"
    artifact.write_text(
        "\n".join(
            [
                "# Production Spec",
                "",
                "1. 25 种识别类型 100% 命中真实数据、0% 误报占位符/环境变量引用。",
                "    re.compile(r'(?:placeholder|example|sample|dummy|test)'), # 占位符关键词",
                "| 零误报 | 占位符/环境变量引用/校验失败数字串 0% 误报 | 阻断 release |",
            ]
        ),
        encoding="utf-8",
    )

    validate_required_artifact_specs(
        [ArtifactSpec(path="production-spec.md", kind="markdown")],
        artifacts_dir=tmp_path,
    )


def test_placeholder_scan_rejects_bare_zhanwei(tmp_path):
    """真正的"占位"占位符（不含"占位符"三字）仍应被门禁拒绝。"""
    artifact = tmp_path / "implementation.md"
    artifact.write_text(
        "\n".join(
            [
                "# Implementation",
                "",
                "此处为占位，待后续补充。",
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ProductionGateError, match="placeholder"):
        validate_required_artifact_specs(
            [ArtifactSpec(path="implementation.md", kind="markdown")],
            artifacts_dir=tmp_path,
        )


def test_placeholder_scan_allows_vague_phrase_in_sentence(tmp_path):
    """空泛短语作为句子成分时不应被门禁拒绝。

    回归点：PLACEHOLDER_PHRASE_PATTERNS 中的"正常工作"、"提升体验"等是日常
    中文表述，出现在完整句子里是合法的（如"从根目录运行正常工作"、"提升
    用户体验"）。子串匹配会误伤，改为整行匹配后应通过。
    """
    artifact = tmp_path / "full-verify.md"
    artifact.write_text(
        "\n".join(
            [
                "# Full Verify",
                "",
                "但从项目根目录运行（via `scripts/ao.py verify`）正常工作。341 tests collected.",
                "本次改动旨在提升体验，不引入回归。",
            ]
        ),
        encoding="utf-8",
    )

    validate_required_artifact_specs(
        [ArtifactSpec(path="full-verify.md", kind="markdown")],
        artifacts_dir=tmp_path,
    )


def test_placeholder_scan_rejects_vague_phrase_as_line_unit(tmp_path):
    """空泛短语作为独立内容单元（整行/标题/列表项）时应被门禁拒绝。"""
    artifact = tmp_path / "implementation.md"
    artifact.write_text(
        "\n".join(
            [
                "# 实现相关功能",
                "",
                "处理相关逻辑",
                "",
                "- 正常工作",
                "",
                "1. 提升体验",
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ProductionGateError, match="placeholder"):
        validate_required_artifact_specs(
            [ArtifactSpec(path="implementation.md", kind="markdown")],
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


def test_gate_pass_validator_accepts_overall_result_pass_with_preexisting(tmp_path):
    """overall_result=PASS_WITH_PREEXISTING 应通过 gate_pass 验证。

    回归点：full-verify.json 顶层用 overall_result 字段（需与子项 result 区分），
    值为 PASS_WITH_PREEXISTING（本次 run 无引入失败，仅存在历史预存失败）。
    验证器曾只查 result/status/decision，导致 raw_result=None 被误判为 not passing。
    """
    artifact = tmp_path / "full-verify.json"
    artifact.write_text(
        json.dumps(
            {
                "overall_result": "PASS_WITH_PREEXISTING",
                "summary": {"tasks_introduced_fail": 0, "tasks_preexisting_fail": 2},
                "introduced_failures": [],
                "preexisting_failures": [{"id": "PRE-ERR-001"}],
            }
        ),
        encoding="utf-8",
    )

    validate_required_artifact_specs(
        [
            ArtifactSpec(
                path="full-verify.json",
                kind="json",
                validators=["gate_pass"],
            )
        ],
        artifacts_dir=tmp_path,
    )


def test_gate_pass_validator_rejects_overall_result_fail(tmp_path):
    """overall_result=FAIL 仍应被拒绝，确保扩展字段不降低 FAIL 拦截能力。"""
    artifact = tmp_path / "full-verify.json"
    artifact.write_text(
        json.dumps({"overall_result": "FAIL", "introduced_failures": ["FAIL-001"]}),
        encoding="utf-8",
    )

    with pytest.raises(ProductionGateError, match="not passing"):
        validate_required_artifact_specs(
            [
                ArtifactSpec(
                    path="full-verify.json",
                    kind="json",
                    validators=["gate_pass"],
                )
            ],
            artifacts_dir=tmp_path,
        )


def test_gate_pass_validator_prefers_result_over_overall_result(tmp_path):
    """同时存在 result 和 overall_result 时，以 result 为准。

    回归点：扩展 overall_result 字段后，必须保持原有字段优先级
    （result > status > decision > overall_result），不能让 overall_result
    覆盖顶层 result=FAIL 的 gate 产物。
    """
    artifact = tmp_path / "spec-gate.json"
    artifact.write_text(
        json.dumps({"result": "FAIL", "overall_result": "PASS"}),
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
