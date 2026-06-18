from pathlib import Path

import pytest

from agentic_workflow.features import init_source_package_from_document


def test_init_feature_from_prd_creates_numbered_feature_dir(tmp_path: Path) -> None:
    source = tmp_path / "local-observer-prd.md"
    source.write_text("# Local Codex Observer\n\n需求正文", encoding="utf-8")

    result = init_source_package_from_document(
        repo_root=tmp_path,
        project_name="agentic_factory",
        doc_type="prd",
        source_path=str(source),
    )

    feature_dir = tmp_path / "apps" / "agentic_factory" / "specs" / "001-local-codex-observer"
    assert result["feature_dir"] == "apps/agentic_factory/specs/001-local-codex-observer"
    assert result["imported_path"] == "apps/agentic_factory/specs/001-local-codex-observer/source-prd.md"
    assert (feature_dir / "source-prd.md").read_text(encoding="utf-8").startswith("# Local Codex Observer")
    assert (feature_dir / "source-package.json").exists()
    assert result["generated_seed_artifacts"] == []
    assert not (feature_dir / "spec.md").exists()
    assert not (feature_dir / "plan.md").exists()
    assert not (feature_dir / "tasks.md").exists()


def test_init_feature_from_spec_uses_next_number(tmp_path: Path) -> None:
    specs_root = tmp_path / "apps" / "agentic_factory" / "specs"
    (specs_root / "001-existing").mkdir(parents=True)
    source = tmp_path / "diagnostics-spec.md"
    source.write_text("# Diagnostics Query\n\n规格正文", encoding="utf-8")

    result = init_source_package_from_document(
        repo_root=tmp_path,
        project_name="agentic_factory",
        doc_type="spec",
        source_path="diagnostics-spec.md",
    )

    assert result["feature_dir"] == "apps/agentic_factory/specs/002-diagnostics-query"
    assert result["imported_path"] == "apps/agentic_factory/specs/002-diagnostics-query/source-spec.md"


def test_init_feature_with_target_root_writes_target_project_specs(tmp_path: Path) -> None:
    target_root = tmp_path / "apps" / "app-a"
    target_root.mkdir(parents=True)
    source = tmp_path / "billing-prd.md"
    source.write_text("# Billing Export\n\n需求正文", encoding="utf-8")

    result = init_source_package_from_document(
        repo_root=tmp_path,
        project_name="app-a",
        doc_type="prd",
        source_path=str(source),
        target_root=target_root,
    )

    feature_dir = target_root / "specs" / "001-billing-export"
    assert result["feature_dir"] == str(feature_dir.resolve())
    assert result["imported_path"] == str((feature_dir / "source-prd.md").resolve())
    assert (feature_dir / "source-prd.md").exists()
    assert not (tmp_path / "apps" / "app-a" / "apps").exists()


def test_init_feature_rejects_unsafe_project_name(tmp_path: Path) -> None:
    source = tmp_path / "prd.md"
    source.write_text("# Any Feature\n", encoding="utf-8")

    with pytest.raises(ValueError, match="project_name"):
        init_source_package_from_document(
            repo_root=tmp_path,
            project_name="../bad",
            doc_type="prd",
            source_path=str(source),
        )
