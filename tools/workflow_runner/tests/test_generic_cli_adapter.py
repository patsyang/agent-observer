import json
import sys
from pathlib import Path

import pytest

from agentic_workflow.adapters.registry import create_adapter
from agentic_workflow.models import WorkflowInput
from agentic_workflow.runner import create_run_context, execute_run, prepare_run
from agentic_workflow.runtime_profile import resolve_executable


def write_definition(repo_root: Path) -> None:
    definition_dir = repo_root / ".agentic" / "workflow" / "definitions"
    definition_dir.mkdir(parents=True)
    (definition_dir / "small-change.json").write_text(
        json.dumps(
            {
                "name": "small-change",
                "title": "small",
                "adapter": "local-governed",
                "contract_path": ".agentic/workflow/small-change.md",
                "primary_inputs": ["goal"],
                "stages": ["execute"],
                "verify_policy": "targeted",
                "nodes": [
                    {"id": "execute", "required_artifacts": ["implementation.md"]},
                ],
            }
        ),
        encoding="utf-8",
    )


def write_stdout_json_profile(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "id": "fake-json",
                "invocation": {
                    "args": ["--cwd", "{{cwd}}", "--prompt-file", "{{prompt_file}}"],
                    "stdin": None,
                },
                "prompt": {"write_file": True, "file_name": "runtime-prompt.md"},
                "final_message": {
                    "source": "stdout_json",
                    "json_path": ["result"],
                    "fallback": "last_non_empty_stdout_line",
                },
                "success": {
                    "exit_code": 0,
                    "json_conditions": [{"path": ["is_error"], "equals": False}],
                },
            }
        ),
        encoding="utf-8",
    )


def write_stdout_jsonl_profile(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "id": "fake-jsonl",
                "invocation": {
                    "args": ["--cwd", "{{cwd}}", "--prompt-file", "{{prompt_file}}"],
                    "stdin": None,
                },
                "prompt": {"write_file": True, "file_name": "runtime-prompt.md"},
                "final_message": {
                    "source": "stdout_jsonl_text",
                    "fallback": "last_non_empty_stdout_line",
                },
                "success": {"exit_code": 0},
            }
        ),
        encoding="utf-8",
    )


def test_create_generic_cli_adapter(tmp_path: Path) -> None:
    profile = tmp_path / "profile.json"
    write_stdout_json_profile(profile)

    adapter = create_adapter(
        "generic-cli",
        command=[sys.executable, "-c", "print('unused')"],
        profile_path=profile,
    )

    assert adapter.name == "generic-cli"


def test_generic_cli_execute_reads_stdout_json_result(tmp_path: Path) -> None:
    write_definition(tmp_path)
    profile = tmp_path / "profile.json"
    write_stdout_json_profile(profile)
    fake_cli = tmp_path / "fake_cli.py"
    fake_cli.write_text(
        "import json\nprint(json.dumps({'is_error': False, 'result': 'generic done'}))\n",
        encoding="utf-8",
    )
    context = create_run_context(
        tmp_path,
        WorkflowInput(workflow="small-change", goal="generic cli"),
        run_id="run_generic_json",
    )

    return_code = execute_run(
        context,
        adapter_name="generic-cli",
        adapter_command=[sys.executable, str(fake_cli)],
        adapter_profile=str(profile),
        skip_verify=True,
        timeout_seconds=10,
    )

    assert return_code == 0
    run_dir = tmp_path / "ai_docs" / "runs" / "run_generic_json"
    assert (run_dir / "runtime-prompt.md").exists()
    assert (run_dir / "generic-cli-final-message.md").read_text(encoding="utf-8") == "generic done"
    events = [
        json.loads(line)
        for line in (run_dir / "workflow-event.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert [event["step"] for event in events] == ["prepare", "adapter:generic-cli", "complete"]


def test_generic_cli_execute_fails_on_json_error_condition(tmp_path: Path) -> None:
    write_definition(tmp_path)
    profile = tmp_path / "profile.json"
    write_stdout_json_profile(profile)
    fake_cli = tmp_path / "fake_cli.py"
    fake_cli.write_text(
        "import json\nprint(json.dumps({'is_error': True, 'result': 'failed'}))\n",
        encoding="utf-8",
    )
    context = create_run_context(
        tmp_path,
        WorkflowInput(workflow="small-change", goal="generic cli"),
        run_id="run_generic_error",
    )

    return_code = execute_run(
        context,
        adapter_name="generic-cli",
        adapter_command=[sys.executable, str(fake_cli)],
        adapter_profile=str(profile),
        skip_verify=True,
        timeout_seconds=10,
    )

    assert return_code == 1


def test_generic_cli_execute_reads_stdout_jsonl_text(tmp_path: Path) -> None:
    write_definition(tmp_path)
    profile = tmp_path / "profile.json"
    write_stdout_jsonl_profile(profile)
    fake_cli = tmp_path / "fake_cli.py"
    fake_cli.write_text(
        "\n".join(
            [
                "import json",
                "print('diagnostic line')",
                "print(json.dumps({'type': 'session.updated', 'properties': {'text': 'session title'}}))",
                "print(json.dumps({'type': 'message.part.updated', 'properties': {'part': {'type': 'text', 'text': 'generic jsonl done'}}}))",
                "print(json.dumps({'type': 'session.updated', 'properties': {'text': 'late session title'}}))",
                "print(json.dumps({'type': 'text', 'text': 'late root status'}))",
            ]
        ),
        encoding="utf-8",
    )
    context = create_run_context(
        tmp_path,
        WorkflowInput(workflow="small-change", goal="generic cli jsonl"),
        run_id="run_generic_jsonl",
    )

    return_code = execute_run(
        context,
        adapter_name="generic-cli",
        adapter_command=[sys.executable, str(fake_cli)],
        adapter_profile=str(profile),
        skip_verify=True,
        timeout_seconds=10,
    )

    assert return_code == 0
    run_dir = tmp_path / "ai_docs" / "runs" / "run_generic_jsonl"
    assert (run_dir / "generic-cli-final-message.md").read_text(encoding="utf-8") == (
        "generic jsonl done"
    )


def test_generic_cli_codex_profile_uses_stdin_and_final_message_file(tmp_path: Path) -> None:
    write_definition(tmp_path)
    profile = Path(__file__).resolve().parents[3] / ".agentic" / "runtime-adapters" / "codex.json"
    fake_codex = tmp_path / "fake_codex.py"
    argv_log = tmp_path / "argv.json"
    stdin_log = tmp_path / "stdin.txt"
    fake_codex.write_text(
        "\n".join(
            [
                "import json, sys",
                "from pathlib import Path",
                f"Path(r'{argv_log}').write_text(json.dumps(sys.argv[1:]), encoding='utf-8')",
                "stdin = sys.stdin.read()",
                f"Path(r'{stdin_log}').write_text(stdin, encoding='utf-8', errors='replace')",
                "args = sys.argv[1:]",
                "Path(args[args.index('--output-last-message') + 1]).write_text('codex generic done', encoding='utf-8')",
            ]
        ),
        encoding="utf-8",
    )
    context = create_run_context(
        tmp_path,
        WorkflowInput(workflow="small-change", goal="generic codex"),
        run_id="run_generic_codex",
    )

    return_code = execute_run(
        context,
        adapter_name="generic-cli",
        adapter_command=[sys.executable, str(fake_codex)],
        adapter_profile=str(profile),
        skip_verify=True,
        timeout_seconds=10,
    )

    assert return_code == 0
    argv = json.loads(argv_log.read_text(encoding="utf-8"))
    assert argv[0] == "exec"
    assert "--cd" in argv
    assert argv[argv.index("--sandbox") + 1] == "danger-full-access"
    assert "--output-last-message" in argv
    assert argv[-1] == "-"
    assert "generic codex" in stdin_log.read_text(encoding="utf-8")
    run_dir = tmp_path / "ai_docs" / "runs" / "run_generic_codex"
    assert (run_dir / "generic-cli-final-message.md").read_text(encoding="utf-8") == "codex generic done"


def test_generic_cli_opencode_profile_uses_prompt_file_and_json_events(tmp_path: Path) -> None:
    write_definition(tmp_path)
    profile = Path(__file__).resolve().parents[3] / ".agentic" / "runtime-adapters" / "opencode.json"
    fake_opencode = tmp_path / "fake_opencode.py"
    argv_log = tmp_path / "argv.json"
    prompt_log = tmp_path / "prompt.txt"
    fake_opencode.write_text(
        "\n".join(
            [
                "import json, sys",
                "from pathlib import Path",
                f"Path(r'{argv_log}').write_text(json.dumps(sys.argv[1:]), encoding='utf-8')",
                "args = sys.argv[1:]",
                "prompt_file = Path(args[args.index('--file') + 1])",
                f"Path(r'{prompt_log}').write_text(prompt_file.read_text(encoding='utf-8'), encoding='utf-8')",
                "print(json.dumps({'type': 'message.part.updated', 'properties': {'part': {'type': 'text', 'text': 'opencode generic done'}}}))",
            ]
        ),
        encoding="utf-8",
    )
    context = create_run_context(
        tmp_path,
        WorkflowInput(workflow="small-change", goal="generic opencode"),
        run_id="run_generic_opencode",
    )

    return_code = execute_run(
        context,
        adapter_name="generic-cli",
        adapter_command=[sys.executable, str(fake_opencode)],
        adapter_profile=str(profile),
        skip_verify=True,
        timeout_seconds=10,
    )

    assert return_code == 0
    argv = json.loads(argv_log.read_text(encoding="utf-8"))
    assert argv[0] == "run"
    assert "--pure" in argv
    assert "--dir" in argv
    assert "--dangerously-skip-permissions" in argv
    assert "--file" in argv
    assert "--model" not in argv
    assert argv[argv.index("--format") + 1] == "json"
    assert not any("{{prompt" in item for item in argv)
    assert "generic opencode" in prompt_log.read_text(encoding="utf-8")
    run_dir = tmp_path / "ai_docs" / "runs" / "run_generic_opencode"
    assert (run_dir / "generic-cli-final-message.md").read_text(encoding="utf-8") == (
        "opencode generic done"
    )


def test_generic_cli_resolves_windows_shim(monkeypatch) -> None:
    monkeypatch.setattr(
        "agentic_workflow.runtime_profile.shutil.which",
        lambda name: r"C:\Users\me\AppData\Roaming\npm\qoderclicn.cmd" if name == "qoderclicn" else None,
    )

    assert resolve_executable(["qoderclicn"])[0].endswith("qoderclicn.cmd")


def test_generic_cli_rejects_prompt_in_args(tmp_path: Path) -> None:
    profile = tmp_path / "profile.json"
    profile.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "id": "bad",
                "invocation": {"args": ["{{  prompt  }}"], "stdin": None},
                "prompt": {"write_file": True, "file_name": "runtime-prompt.md"},
                "final_message": {"source": "stdout_text"},
                "success": {"exit_code": 0},
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="not allowed"):
        create_adapter("generic-cli", command=[sys.executable], profile_path=profile).execute(
            _prepared_context(tmp_path)
        )


def _prepared_context(tmp_path: Path):
    write_definition(tmp_path)
    context = create_run_context(
        tmp_path,
        WorkflowInput(workflow="small-change", goal="bad profile"),
        run_id="run_bad_profile",
    )
    prepare_run(context)
    return context
