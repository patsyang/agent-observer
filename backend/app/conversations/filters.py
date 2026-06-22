from __future__ import annotations

from app.conversations.workspace import workspace_matches


def filter_conversations(
    conversations: list[dict],
    *,
    prompt_query: str | None,
    response_query: str | None,
    workspace_query: str | None,
) -> list[dict]:
    prompt = (prompt_query or "").strip().lower()
    response = (response_query or "").strip().lower()
    workspace = (workspace_query or "").strip()
    if not prompt and not response and not workspace:
        return conversations
    result = []
    for item in conversations:
        prompt_text = str(item.get("_prompt_search_text") or item["prompt_preview"]).lower()
        response_text = str(item.get("_response_search_text") or item["response_preview"]).lower()
        prompt_ok = not prompt or prompt in prompt_text
        response_ok = not response or response in response_text
        workspace_ok = workspace_matches(item.get("workspace") or {}, workspace)
        if prompt_ok and response_ok and workspace_ok:
            result.append(item)
    return result
