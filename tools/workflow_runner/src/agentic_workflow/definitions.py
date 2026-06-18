import json
from pathlib import Path

from .models import ArtifactSpec, WorkflowDefinition


def load_definition(repo_root: Path, workflow: str) -> WorkflowDefinition:
    path = repo_root / ".agentic" / "workflow" / "definitions" / f"{workflow}.json"
    if not path.exists():
        raise ValueError(f"workflow definition not found: {workflow}")
    data = json.loads(path.read_text(encoding="utf-8"))
    return WorkflowDefinition.from_dict(data)


def list_definitions(repo_root: Path) -> list[WorkflowDefinition]:
    root = repo_root / ".agentic" / "workflow" / "definitions"
    return [load_definition(repo_root, path.stem) for path in sorted(root.glob("*.json"))]


def validate_definition(repo_root: Path, workflow: str) -> dict[str, object]:
    definition = load_definition(repo_root, workflow)
    findings: list[str] = []
    contract = repo_root / definition.contract_path
    if not contract.exists():
        findings.append(f"contract missing: {definition.contract_path}")
    node_ids: set[str] = set()
    for node in definition.nodes:
        node_id = node.get("id")
        if not isinstance(node_id, str) or not node_id.strip():
            findings.append("node missing id")
            continue
        if node_id in node_ids:
            findings.append(f"duplicate node id: {node_id}")
        node_ids.add(node_id)
        for item in node.get("required_artifacts", []):
            try:
                ArtifactSpec.from_raw(item)
            except ValueError as error:
                findings.append(f"node {node_id} invalid required_artifacts: {error}")
        depends_on = node.get("depends_on", [])
        if not isinstance(depends_on, list):
            findings.append(f"node {node_id} depends_on must be an array")
            continue
        for dependency in depends_on:
            if not isinstance(dependency, str):
                findings.append(f"node {node_id} dependency must be a string")
            elif dependency not in node_ids:
                known_later = any(
                    candidate.get("id") == dependency for candidate in definition.nodes
                )
                if not known_later:
                    findings.append(f"node {node_id} dependency not found: {dependency}")
    return {
        "workflow": definition.name,
        "contract_path": definition.contract_path,
        "node_count": len(definition.nodes),
        "status": "PASS" if not findings else "FAIL",
        "findings": findings,
    }
