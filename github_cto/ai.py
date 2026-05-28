import json
import time
from typing import Any

import requests


class CodexUnavailable(RuntimeError):
    pass


class CodexTimeout(CodexUnavailable):
    pass


class CodexTransientError(CodexUnavailable):
    pass


RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


class CodexEngineeringManager:
    """Codex-style planner that turns GitHub issues into reviewable engineering work."""

    def __init__(
        self,
        api_key: str,
        model: str,
        planning_timeout: int = 60,
        patch_timeout: int = 180,
        max_retries: int = 2,
    ):
        self.api_key = api_key
        self.model = model
        self.planning_timeout = planning_timeout
        self.patch_timeout = patch_timeout
        self.max_retries = max_retries

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    def _chat_json(self, messages: list[dict[str, str]], timeout: int) -> dict[str, Any]:
        if not self.api_key:
            raise CodexUnavailable("OPENAI_API_KEY is required for Codex agent planning.")
        response = self._post_with_retries(
            "https://api.openai.com/v1/chat/completions",
            json_payload={
                "model": self.model,
                "messages": messages,
                "temperature": 0.2,
                "response_format": {"type": "json_object"},
            },
            timeout=timeout,
        )
        if response.status_code >= 400:
            raise CodexUnavailable(_clean_openai_error(response))
        content = response.json()["choices"][0]["message"]["content"]
        return json.loads(content)

    def _post_with_retries(self, url: str, json_payload: dict[str, Any], timeout: int) -> requests.Response:
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                response = requests.post(
                    url,
                    headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                    json=json_payload,
                    timeout=timeout,
                )
                if response.status_code in RETRYABLE_STATUS_CODES:
                    if attempt >= self.max_retries:
                        raise CodexTransientError(_clean_openai_error(response))
                    time.sleep(_retry_delay(attempt, response))
                    continue
                return response
            except (requests.Timeout, requests.ConnectionError) as exc:
                last_error = exc
                if attempt >= self.max_retries:
                    break
                time.sleep(1.5 * (attempt + 1))
        raise CodexTimeout(
            "Codex timed out while talking to OpenAI. Reduce selected files or retry."
        ) from last_error

    def select_files(
        self,
        issue: dict[str, Any],
        files: list[str],
        max_files: int = 5,
        intent: dict[str, Any] | None = None,
        evidence: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        file_listing = "\n".join(files[:800])
        intent = intent or {"kind": "unknown", "rationale": "No intent classification provided."}
        evidence_text = "\n".join(
            f"- {item.get('path')}: {item.get('reason')}" for item in (evidence or [])[:12]
        )
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
                        "For UI/application issues, prefer templates/routes that contain the existing related control "
                        "or route, not generic filenames. Use evidence notes as stronger signal than filename similarity. "
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
                        f"Evidence from content search:\n{evidence_text or 'No content evidence available.'}\n\n"
                        f"Repository files:\n{file_listing}\n\n"
                        f"Select at most {max_files} files."
                    ),
                },
            ],
            timeout=self.planning_timeout,
        )

    def generate_patch(
        self,
        issue: dict[str, Any],
        file_payloads: list[dict[str, str]],
        max_context_chars_per_file: int = 24000,
    ) -> dict[str, Any]:
        files_text = []
        for file_payload in file_payloads:
            content = _trim_content(file_payload["content"], max_context_chars_per_file)
            context_mode = file_payload.get("context_mode", "full_file")
            summary = file_payload.get("summary", "")
            indexed_snippets = file_payload.get("indexed_snippets", "")
            extras = ""
            if summary:
                extras += f"\n# Local structural summary\n{summary}\n"
            if indexed_snippets:
                extras += f"\n# Retrieved index snippets\n{indexed_snippets}\n"
            files_text.append(
                f"--- FILE: {file_payload['path']} ({context_mode}) ---{extras}\n{content}\n--- END FILE ---"
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
                        "The main file content may be trimmed for large files, but summaries and retrieved snippets "
                        "are provided to preserve orientation. If a safe full-file replacement is not possible, "
                        "avoid changing that file and explain in the summary. "
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
            ],
            timeout=self.patch_timeout,
        )


def _trim_content(content: str, max_chars: int) -> str:
    if len(content) <= max_chars:
        return content
    head_chars = max_chars // 2
    tail_chars = max_chars - head_chars
    return (
        content[:head_chars]
        + "\n\n# ... content trimmed for Codex context budget ...\n\n"
        + content[-tail_chars:]
    )


def _retry_delay(attempt: int, response: requests.Response) -> float:
    retry_after = response.headers.get("Retry-After")
    if retry_after:
        try:
            return min(float(retry_after), 10.0)
        except ValueError:
            pass
    return min(2.0 * (attempt + 1), 8.0)


def _clean_openai_error(response: requests.Response) -> str:
    try:
        payload = response.json()
        message = payload.get("error", {}).get("message") or payload.get("message")
        if message:
            return f"OpenAI API {response.status_code}: {message}"
    except ValueError:
        pass

    if response.status_code in {502, 503, 504}:
        return (
            f"OpenAI API {response.status_code}: OpenAI is temporarily unavailable. "
            "Please retry in a moment."
        )
    if response.status_code == 429:
        return "OpenAI API 429: Rate limit or quota pressure. Please wait and retry."
    text = " ".join(response.text.split())
    if len(text) > 240:
        text = text[:240] + "..."
    return f"OpenAI API {response.status_code}: {text}"
