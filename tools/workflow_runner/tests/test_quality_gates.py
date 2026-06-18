from pathlib import Path

from agentic_workflow.quality_gates import check_spec_artifacts


def test_check_spec_artifacts_passes_ready_production_spec(tmp_path: Path) -> None:
    spec = tmp_path / "spec.md"
    spec.write_text(_valid_spec(), encoding="utf-8")

    result = check_spec_artifacts(spec_path=spec)

    assert result.ok


def test_check_spec_artifacts_fails_missing_stack_contract_reference(tmp_path: Path) -> None:
    spec = tmp_path / "spec.md"
    spec.write_text(
        _valid_spec().replace("stack_contract_ref: sample-stack@1", "contract pending"),
        encoding="utf-8",
    )

    result = check_spec_artifacts(spec_path=spec)

    assert not result.ok
    assert any("stack_contract_ref" in message for message in result.messages)


def test_check_spec_artifacts_fails_missing_acceptance_reference(tmp_path: Path) -> None:
    spec = tmp_path / "spec.md"
    spec.write_text(_valid_spec().replace("acceptance_id: AC-001", "no mapped acceptance"), encoding="utf-8")

    result = check_spec_artifacts(spec_path=spec)

    assert not result.ok
    assert any("Acceptance Matrix Draft" in message for message in result.messages)


def _valid_spec() -> str:
    sections = [
        "Product Outcome",
        "User Roles and Production Workflows",
        "Domain Objects and States",
        "Frontend Product Surface",
        "Backend and Data Contracts",
        "Error, Empty, Partial and Recovery States",
        "Security and Privacy Boundaries",
        "Operational Concerns",
        "Release Gates",
    ]
    body = "# Feature - Spec\n\n" + "\n\n".join(f"## {section}\n内容" for section in sections)
    return body + "\n\n## Acceptance Matrix Draft\n- acceptance_id: AC-001\n\nstack_contract_ref: sample-stack@1\n"
