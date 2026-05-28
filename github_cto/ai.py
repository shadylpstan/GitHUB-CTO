import json
from typing import Any

import requests


class CodexUnavailable(RuntimeError):
    pass


class CodexEngineeringManager:
    """Codex-style planner that turns GitHub issues into reviewable engineering work."""

    def __init__(self, api_key: str, model: str):
        self.api_key = api_key
        self.model = model

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    def _chat_json(self, messages: list[dict[str, str]]) -> dict[str, Any]:
        if not self.api_key:
            raise CodexUnavailable("OPENAI_API_KEY is required for Codex agent planning.")
        response = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            json={
                "model": self.model,
                "messages": messages,
                "temperature": 0.2,
                "response_format": {"type": "json_object"},
            },
            timeout=90,
        )
        if response.status_code >= 400:
            raise CodexUnavailable(f"OpenAI API {response.status_code}: {response.text}")
        content = response.json()["choices"][0]["message"]["content"]
        return json.loads(content)

    def select_files(
        self,
        issue: dict[str, Any],
        files: list[str],
        max_files: int = 5,
        intent: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        file_listing = "\n".join(files[:800])
        intent = intent or {"kind": "unknown", "rationale": "No intent classification provided."}
        return self._chat_json(
            [
                {
                    "role": "system",
                    "content": (
                        "You are an autonomous engineering manager. Select the most relevant repository files "
                        "to inspect for a GitHub issue. You work like Codex: reason over repository structure, "
                        "choose context deliberately, and prepare safe code changes for human review. "
                        "For framework/library bugs, prefer root-cause implementation and tests over docs, examples, "
                        "tutorials, or reproduction snippets. Avoid selecting files that only patch the symptom. "
                        "Return JSON with keys: files (array of paths), reasoning, root_cause_justification. "
                        "root_cause_justification should explain why the chosen files are likely responsible for the behavior."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Issue title: {issue.get('title')}\n\n"
                        f"Issue body:\n{issue.get('body') or ''}\n\n"
                        f"Classified intent: {intent.get('kind')} ({intent.get('rationale')})\n\n"
                        f"Repository files:\n{file_listing}\n\n"
                        f"Select at most {max_files} files."
                    ),
                },
            ]
        )

    def generate_patch(self, issue: dict[str, Any], file_payloads: list[dict[str, str]]) -> dict[str, Any]:
        files_text = []
        for file_payload in file_payloads:
            files_text.append(
                f"--- FILE: {file_payload['path']} ---\n{file_payload['content']}\n--- END FILE ---"
            )
        return self._chat_json(
            [
                {
                    "role": "system",
                    "content": (
                        "You are a senior software engineer making a minimal, safe GitHub PR. "
                        "You operate as a Codex-style coding agent: inspect provided context, infer missing "
                        "implementation needs from the issue, and prepare reviewable full-file changes. "
                        "Return JSON only with keys: summary, test_plan, changes. "
                        "changes must be an array of objects with path and full_content. "
                        "Include modified existing files and any new files needed to satisfy the issue. "
                        "Preserve style and avoid unrelated rewrites. Do not delete files."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"GitHub issue #{issue.get('number')}: {issue.get('title')}\n\n"
                        f"Issue body:\n{issue.get('body') or ''}\n\n"
                        "Relevant files:\n\n"
                        + "\n\n".join(files_text)
                    ),
                },
            ]
        )
