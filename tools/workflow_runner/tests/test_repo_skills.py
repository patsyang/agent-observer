from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]


def test_codex_slash_commands_map_to_project_skills() -> None:
    commands_dir = REPO_ROOT / "commands"
    skills_dir = REPO_ROOT / ".codex" / "skills"
    expected = {
        "ao-spec": "spec-driven",
        "ao-plan": "plan-execute",
        "ao-small": "small-change",
    }

    for command_name, workflow in expected.items():
        command_file = commands_dir / f"{command_name}.md"
        skill_file = skills_dir / command_name / "SKILL.md"
        assert command_file.exists()
        assert skill_file.exists()
        command_text = command_file.read_text(encoding="utf-8")
        text = skill_file.read_text(encoding="utf-8")
        assert f"# /{command_name}" in command_text
        assert f".codex/skills/{command_name}/SKILL.md" in command_text
        assert ".agentic/workflow" in command_text
        assert workflow in text
        assert "中文" in text
        assert "run-report.md" in text

    old_skill_name = "-".join(["agent", "observer", "workflows"])
    assert not (REPO_ROOT / ".agents" / "skills" / old_skill_name).exists()
    assert not (commands_dir / "spec-driven.md").exists()
    assert not (commands_dir / "plan-execute.md").exists()
    assert not (commands_dir / "small-change.md").exists()
