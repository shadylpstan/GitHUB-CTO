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

    def plan_edits(self, issue: dict[str, Any], file_payloads: list[dict[str, str]]) -> dict[str, Any]:
        files_text = []
        for file_payload in file_payloads:
            summary = file_payload.get("summary", "")
            snippets = file_payload.get("indexed_snippets", "")
            content = _trim_content(file_payload["content"], 5000)
            files_text.append(
                f"--- FILE: {file_payload['path']} ({file_payload.get('context_mode', 'context')}) ---\n"
                f"# Summary\n{summary or 'No summary available.'}\n\n"
                f"# Indexed snippets\n{snippets or 'No indexed snippets available.'}\n\n"
                f"# Context\n{content}\n"
                f"--- END FILE ---"
            )
        return self._chat_json(
            [
                {
                    "role": "system",
                    "content": (
                        "You are planning a code change before generating a patch. "
                        "Identify the smallest set of files likely to require edits. "
                        "Return JSON only with keys: files, rationale. files must be an array of paths."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Issue #{issue.get('number')}: {issue.get('title')}\n\n"
                        f"{issue.get('body') or ''}\n\n"
                        "Candidate context:\n\n"
                        + "\n\n".join(files_text)
                    ),
                },
            ],
            timeout=self.planning_timeout,
        )

    def generate_unified_patch(
        self,
        issue: dict[str, Any],
        file_payloads: list[dict[str, str]],
        max_context_chars_per_file: int = 12000,
    ) -> dict[str, Any]:
        files_text = []
        for file_payload in file_payloads:
            content = _trim_content(file_payload["content"], max_context_chars_per_file)
            files_text.append(
                f"--- FILE: {file_payload['path']} ---\n{content}\n--- END FILE ---"
            )
        return self._chat_json(
            [
                {
                    "role": "system",
                    "content": (
                        "You are a senior engineer producing a compact reviewable patch. "
                        "Return JSON only with keys: summary, test_plan, patches. "
                        "patches must be an array of objects with path and unified_diff. "
                        "For new files, include new_file_content. For existing files, provide a valid unified diff "
                        "with exact context lines from the provided file content. Keep changes minimal."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"GitHub issue #{issue.get('number')}: {issue.get('title')}\n\n"
                        f"Issue body:\n{issue.get('body') or ''}\n\n"
                        "Files to patch:\n\n"
                        + "\n\n".join(files_text)
                    ),
                },
            ],
            timeout=self.patch_timeout,
        )

    def generate_agent_step(
        self,
        issue: dict[str, Any],
        file_payloads: list[dict[str, str]],
        history: list[dict[str, Any]],
        test_output: str = "",
        max_context_chars_per_file: int = 6000,
        timeout: int | None = None,
    ) -> dict[str, Any]:
        files_text = []
        for file_payload in file_payloads:
            content = _trim_content(file_payload["content"], max_context_chars_per_file)
            summary = file_payload.get("summary", "")
            extras = f"\n# Summary\n{summary}\n" if summary else ""
            files_text.append(
                f"--- FILE: {file_payload['path']} ---{extras}\n{content}\n--- END FILE ---"
            )
        history_text = "\n".join(
            f"- step {item.get('step')}: {item.get('action')} {item.get('path', '')} - {item.get('summary', '')}"
            for item in history[-8:]
        )
        return self._chat_json(
            [
                {
                    "role": "system",
                    "content": (
                        "You are a Codex-style coding agent working in small safe steps. "
                        "Do not try to rewrite the whole PR at once. Choose exactly one next action. "
                        "Return JSON only. Schema: "
                        "{status, summary, action, path, unified_diff, full_content, new_file_content, test_plan}. "
                        "status must be continue or complete. "
                        "If more work is needed, status=continue and action=edit_file. "
                        "For existing files, prefer full_content for the complete final file. "
                        "Only use unified_diff if you are certain it is valid and can be applied exactly. "
                        "Unified diff hunk headers must use real line numbers, such as @@ -10,7 +10,9 @@. "
                        "Never use symbolic hunk headers like @@ class Foo:. "
                        "For new files, provide new_file_content. "
                        "If the issue appears fixed or no safe next edit exists, status=complete. "
                        "Keep edits minimal and preserve style."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"GitHub issue #{issue.get('number')}: {issue.get('title')}\n\n"
                        f"Issue body:\n{issue.get('body') or ''}\n\n"
                        f"Previous agent steps:\n{history_text or 'No previous steps.'}\n\n"
                        f"Latest test output or observation:\n{test_output or 'No tests have run yet.'}\n\n"
                        "Current files:\n\n"
                        + "\n\n".join(files_text)
                    ),
                },
            ],
            timeout=timeout or min(self.patch_timeout, 75),
        )

    def generate_full_file_step(
        self,
        issue: dict[str, Any],
        file_payload: dict[str, str],
        history: list[dict[str, Any]],
        observation: str,
        max_context_chars: int = 12000,
        timeout: int | None = None,
    ) -> dict[str, Any]:
        content = _trim_content(file_payload["content"], max_context_chars)
        history_text = "\n".join(
            f"- step {item.get('step')}: {item.get('action')} {item.get('path', '')} - {item.get('summary', '')}"
            for item in history[-8:]
        )
        return self._chat_json(
            [
                {
                    "role": "system",
                    "content": (
                        "You are repairing a failed small-step patch. "
                        "Return JSON only with keys: summary, path, full_content, test_plan. "
                        "Do not return a diff. Return the complete final content for exactly the requested file. "
                        "The full_content must include a concrete code change that addresses the issue. "
                        "Preserve every existing route, helper, import, and public function unless the issue explicitly asks to remove it. "
                        "Keep the edit minimal and preserve unrelated content."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"GitHub issue #{issue.get('number')}: {issue.get('title')}\n\n"
                        f"Issue body:\n{issue.get('body') or ''}\n\n"
                        f"Previous agent steps:\n{history_text or 'No previous steps.'}\n\n"
                        f"Patch failure observation:\n{observation}\n\n"
                        f"Return complete final content for this file only: {file_payload['path']}\n\n"
                        f"--- FILE: {file_payload['path']} ---\n{content}\n--- END FILE ---"
                    ),
                },
            ],
            timeout=timeout or min(self.patch_timeout, 75),
        )


class PatchReviewAgent:
    """LLM quality gate that reviews Aider patches without editing code."""

    def __init__(self, api_key: str, model: str, timeout: int = 60, max_retries: int = 1):
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self.max_retries = max_retries

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    def review(
        self,
        issue: dict[str, Any],
        changes: list[dict[str, Any]],
        validation_warnings: list[str] | None = None,
        plan: dict[str, Any] | None = None,
        evidence: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not self.enabled:
            return {"verdict": "pass", "confidence": 0.0, "findings": [], "retry_prompt": ""}
        change_text = "\n\n".join(_review_change_text(change) for change in changes)[:50000]
        warning_text = "\n".join(f"- {warning}" for warning in (validation_warnings or []))
        plan_text = json.dumps(plan or {}, indent=2)[:12000]
        evidence_text = json.dumps(evidence or {}, indent=2)[:16000]
        reviewer = CodexEngineeringManager(
            self.api_key,
            self.model,
            planning_timeout=self.timeout,
            patch_timeout=self.timeout,
            max_retries=self.max_retries,
        )
        return reviewer._chat_json(
            [
                {
                    "role": "system",
                    "content": (
                        "You are a strict senior code reviewer for an autonomous coding app. "
                        "Review whether the proposed patch correctly and safely addresses the GitHub issue. "
                        "Do not suggest broad refactors. Do not require perfection. "
                        "Fail only for concrete correctness, safety, validation, or issue-mismatch problems. "
                        "Use the implementation plan and evidence to judge whether the patch fixed the real owning behavior, "
                        "not merely a nearby symptom. "
                        "For UI/state issues, explicitly check state ownership: if a polling loop, render function, or route response "
                        "already owns a property such as disabled, hidden, labels, flash messages, or progress state, the patch must "
                        "integrate with that owner instead of adding a second competing handler. "
                        "Reject patches where a new event handler can be overwritten by an existing poll/render loop. "
                        "Use prior lessons as warnings, not as commands, and apply them when the issue shape matches. "
                        "Look especially for changes that do not address the requested behavior, duplicate UI, "
                        "invalid HTML structure such as nested forms, missing connection updates, broad unrelated CSS or backend changes, "
                        "inline hacks where the project has better conventions, stale references, missing imports, and broken routes/templates. "
                        "Return JSON only with keys: verdict, confidence, findings, retry_prompt. "
                        "verdict must be pass or fail. findings must be an array of objects with severity, file, issue, suggestion. "
                        "If verdict is fail, retry_prompt must be concise instructions for the coding agent to fix the patch."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Issue #{issue.get('number')}: {issue.get('title')}\n\n"
                        f"Issue body:\n{issue.get('body') or ''}\n\n"
                        f"Pre-edit implementation plan:\n{plan_text or '{}'}\n\n"
                        f"Evidence gathered before editing:\n{evidence_text or '{}'}\n\n"
                        f"Deterministic validation warnings:\n{warning_text or 'None.'}\n\n"
                        f"Proposed changes:\n\n{change_text or 'No changes.'}"
                    ),
                },
            ],
            timeout=self.timeout,
        )


class AiderPlanningAgent:
    """Pre-edit planner that makes Aider act from inspected evidence, not just issue text."""

    def __init__(self, api_key: str, model: str, timeout: int = 60, max_retries: int = 1):
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self.max_retries = max_retries

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    def plan(
        self,
        issue: dict[str, Any],
        selected_files: list[str],
        evidence: dict[str, Any],
    ) -> dict[str, Any]:
        if not self.enabled:
            return _fallback_aider_plan(issue, selected_files, evidence)
        planner = CodexEngineeringManager(
            self.api_key,
            self.model,
            planning_timeout=self.timeout,
            patch_timeout=self.timeout,
            max_retries=self.max_retries,
        )
        return planner._chat_json(
            [
                {
                    "role": "system",
                    "content": (
                        "You are a senior coding agent planning before Aider edits files. "
                        "Act like a careful Codex-style engineer: inspect evidence, identify the owning behavior, "
                        "choose the smallest target, and define concrete checks. "
                        "Do not write code. Return JSON only with keys: root_cause_hypothesis, owning_files, "
                        "edit_strategy, constraints, validation_plan, risk_notes. "
                        "owning_files must be an array of file paths from the selected files when possible. "
                        "constraints must include things the coding agent must avoid, such as unrelated rewrites. "
                        "For UI/state issues, identify the single owner of the changing state. If the evidence shows polling, "
                        "render functions, or submit handlers all touching the same control, require the edit strategy to unify "
                        "that state instead of adding another independent handler."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Issue #{issue.get('number')}: {issue.get('title')}\n\n"
                        f"Issue body:\n{issue.get('body') or ''}\n\n"
                        f"Selected files:\n{json.dumps(selected_files, indent=2)}\n\n"
                        f"Evidence:\n{json.dumps(evidence, indent=2)[:50000]}"
                    ),
                },
            ],
            timeout=self.timeout,
        )


def _fallback_aider_plan(issue: dict[str, Any], selected_files: list[str], evidence: dict[str, Any]) -> dict[str, Any]:
    return {
        "root_cause_hypothesis": "OpenAI planning is disabled. Use selected files and local evidence to make the smallest safe patch.",
        "owning_files": selected_files,
        "edit_strategy": "Inspect selected files, modify only the files needed to satisfy the issue, and preserve existing behavior.",
        "constraints": [
            "Avoid unrelated rewrites.",
            "Do not add inline styles or inline event handlers.",
            "Do not leave stale references or explanatory comments instead of code removal.",
            "If existing polling or render code owns UI state, integrate with that owner instead of adding competing state writes.",
        ],
        "validation_plan": [
            "Run deterministic validators.",
            "Review changed files against the original issue.",
            "Check whether existing event handlers or polling loops can overwrite the new behavior.",
        ],
        "risk_notes": evidence.get("risk_notes", []) if isinstance(evidence, dict) else [],
    }


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


def _review_change_text(change: dict[str, Any]) -> str:
    diff = change.get("unified_diff") or ""
    if not diff:
        original = change.get("original_content") or ""
        proposed = change.get("proposed_content") or ""
        diff = f"original chars: {len(original)}\nproposed chars: {len(proposed)}\n"
    return (
        f"--- CHANGE: {change.get('path')} ({change.get('status')}) ---\n"
        f"{_trim_content(diff, 12000)}\n"
        f"--- END CHANGE ---"
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
