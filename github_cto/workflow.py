import re
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Any

from .ai import CodexEngineeringManager
from .evidence import evidence_rank
from .github_client import GitHubClient, is_probably_text_file
from .intent import architectural_rank, classify_issue_intent, classify_issue_scope, file_scope
from .patch_utils import PatchApplyError, apply_unified_diff
from .repo_index import RepositoryIndex
from .triage import triage_issue


logger = logging.getLogger(__name__)


def _is_template_or_ui(path: str) -> bool:
    normalized = path.replace("\\", "/").lower()
    return (
        "/templates/" in normalized
        or normalized.startswith("templates/")
        or normalized.endswith((".html", ".jinja", ".j2", ".jsx", ".tsx", ".css"))
    )


def _ui_candidate_score(path: str) -> int:
    normalized = path.replace("\\", "/").lower()
    score = 0
    if normalized.endswith("dashboard.html"):
        score += 45
    if normalized.endswith("issue.html"):
        score += 52
    if normalized.endswith("base.html"):
        score += 18
    if "/templates/" in normalized or normalized.startswith("templates/"):
        score += 30
    if normalized.endswith((".jsx", ".tsx")):
        score += 24
    return score


def _priority_score(path: str, priorities: list[str]) -> int:
    normalized = path.replace("\\", "/").lower()
    for index, candidate in enumerate(priorities):
        if normalized == candidate.lower():
            return 100 - index
    return 0


def safe_branch_name(issue_number: int, title: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", title.lower()).strip("-")[:48] or "issue"
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    return f"codex/issue-{issue_number}-{slug}-{stamp}"


def _local_file_summary(path: str, content: str) -> str:
    lines = content.splitlines()
    symbols = []
    for line_number, line in enumerate(lines, start=1):
        stripped = line.strip()
        if re.match(r"^(def|class)\s+\w+", stripped):
            symbols.append(f"line {line_number}: {stripped}")
        elif "@app.route" in stripped or "Blueprint(" in stripped or "url_for(" in stripped:
            symbols.append(f"line {line_number}: {stripped[:140]}")
        if len(symbols) >= 24:
            break
    symbol_text = "\n".join(symbols) if symbols else "No obvious Python symbols/routes/forms detected."
    return (
        f"path: {path}\n"
        f"lines: {len(lines)}\n"
        f"chars: {len(content)}\n"
        f"notable symbols/routes/forms:\n{symbol_text}"
    )


def codex_timeline(stage: str, **extra: Any) -> list[dict[str, str]]:
    stages = [
        ("intake", "Read GitHub issue", "Codex ingests title, body, labels, and discussion context."),
        ("triage", "Assign severity", "Codex scores urgency and chooses the response posture."),
        ("repo_scan", "Scan repository tree", "Codex reads the GitHub tree and filters useful source files."),
        ("context", "Select code context", "Codex chooses files to inspect before proposing changes."),
        ("patch", "Generate proposal", "Codex drafts modified and new files as a reviewable patch."),
        ("review", "Human checkpoint", "You inspect diffs and edit the proposed files before execution."),
        ("execute", "GitHub execution", "After approval, the app creates a branch, commits, opens a PR, and comments."),
    ]
    completed_order = {name: index for index, (name, _, _) in enumerate(stages)}
    current_index = completed_order.get(stage, 0)
    timeline = []
    for index, (name, title, detail) in enumerate(stages):
        if index < current_index:
            status = "done"
        elif index == current_index:
            status = "active"
        else:
            status = "pending"
        timeline.append({"key": name, "title": title, "detail": detail, "status": status})
    if extra:
        timeline.append({"key": "metadata", "title": "Agent metadata", "detail": ", ".join(f"{k}: {v}" for k, v in extra.items()), "status": "meta"})
    return timeline


class GitHubCTOWorkflow:
    def __init__(
        self,
        github: GitHubClient,
        planner: CodexEngineeringManager,
        max_repo_files: int,
        max_file_bytes: int,
        default_selected_files: int,
        max_selected_files: int,
        max_context_chars_per_file: int,
        max_parallel_fetches: int = 6,
        enable_file_summaries: bool = True,
        repo_index: RepositoryIndex | None = None,
    ):
        self.github = github
        self.planner = planner
        self.max_repo_files = max_repo_files
        self.max_file_bytes = max_file_bytes
        self.default_selected_files = default_selected_files
        self.max_selected_files = max_selected_files
        self.max_context_chars_per_file = max_context_chars_per_file
        self.max_parallel_fetches = max_parallel_fetches
        self.enable_file_summaries = enable_file_summaries
        self.repo_index = repo_index

    def issue_context(self, issue_number: int) -> dict[str, Any]:
        issue = self.github.get_issue(issue_number)
        comments = self.github.list_issue_comments(issue_number)
        triage = triage_issue(issue, comments)
        return {"issue": issue, "comments": comments, "triage": triage}

    def candidate_files(self, branch: str | None = None) -> list[str]:
        tree = self.github.get_tree(branch=branch)
        paths = [
            item["path"]
            for item in tree
            if item.get("type") == "blob" and is_probably_text_file(item.get("path", ""))
        ]
        ignored = (".lock", "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "dist/", "build/", "vendor/")
        filtered = [path for path in paths if not any(part in path for part in ignored)]
        return filtered[: self.max_repo_files]

    def plan_files(self, issue_number: int, branch: str | None = None) -> dict[str, Any]:
        branch = branch or self.github.default_branch()
        issue = self.github.get_issue(issue_number)
        intent = classify_issue_intent(issue)
        scope = classify_issue_scope(issue)
        indexed_files = self._indexed_candidate_files(issue, branch)
        base_files = indexed_files or self.candidate_files(branch)
        evidence_hits = self._evidence_hits(issue, base_files, branch)
        evidence_scores = {hit.path: hit.score for hit in evidence_hits}
        files = architectural_rank(base_files, intent, evidence_scores=evidence_scores)
        files = self._balance_scope_candidates(files, scope)
        context_source = "vector_index" if indexed_files else "repo_tree"
        if not self.planner.enabled:
            visible_files = files[: self.max_selected_files]
            return {
                "files": visible_files,
                "checked_files": visible_files[: self.default_selected_files],
                "reasoning": "Codex planning is disabled because OPENAI_API_KEY is not configured. Showing top repository files only.",
                "root_cause_justification": "",
                "intent": intent,
                "scope": scope,
                "evidence": evidence_hits[:8],
                "ai_enabled": False,
                "timeline": codex_timeline(
                    "context",
                    context_source=context_source,
                    read_branch=branch,
                    intent=intent.kind,
                    scope=scope.kind,
                    evidence_hits=len(evidence_hits),
                ),
            }
        plan = self.planner.select_files(
            issue,
            files,
            max_files=self.max_selected_files,
            intent=intent.__dict__,
            evidence=[hit.__dict__ for hit in evidence_hits],
        )
        selected = [path for path in plan.get("files", []) if path in files]
        selected = self._balance_scope_candidates(selected, scope, fallback=files)
        visible_files = selected[: self.max_selected_files]
        return {
            "files": visible_files,
            "checked_files": visible_files[: self.default_selected_files],
            "reasoning": plan.get("reasoning", ""),
            "root_cause_justification": plan.get("root_cause_justification", ""),
            "intent": intent,
            "scope": scope,
            "evidence": evidence_hits[:8],
            "ai_enabled": True,
            "timeline": codex_timeline(
                "context",
                selected_files=len(selected[: self.default_selected_files]),
                context_source=context_source,
                read_branch=branch,
                intent=intent.kind,
                scope=scope.kind,
                evidence_hits=len(evidence_hits),
            ),
        }

    def _indexed_candidate_files(self, issue: dict[str, Any], branch: str) -> list[str]:
        if not self.repo_index:
            return []
        repo = self.github.repo.full_name
        labels = " ".join(label.get("name", "") for label in issue.get("labels", []))
        query = f"{issue.get('title') or ''}\n\n{issue.get('body') or ''}\n\nlabels: {labels}"
        indexed_paths = self.repo_index.top_paths(repo, branch, query, limit=24)
        if not indexed_paths:
            return []
        all_files = self.candidate_files(branch)
        indexed_set = set(indexed_paths)
        remaining = [path for path in all_files if path not in indexed_set]
        return indexed_paths + remaining[: max(0, self.max_repo_files - len(indexed_paths))]

    def _evidence_hits(self, issue: dict[str, Any], files: list[str], branch: str) -> list[Any]:
        issue_text = f"{issue.get('title') or ''}\n\n{issue.get('body') or ''}"
        cache: dict[str, str | None] = {}
        metadata_by_path: dict[str, str] = {}
        if self.repo_index:
            try:
                metadata_by_path = self.repo_index.metadata_text_for_paths(self.github.repo.full_name, branch, files)
            except Exception as exc:
                logger.warning("Could not load file metadata evidence: %s", exc)

        def fetch(path: str) -> str | None:
            if path in cache:
                return cache[path]
            try:
                payload = self.github.get_file(path, ref=branch)
                content = payload["content"]
                if len(content.encode("utf-8")) > self.max_file_bytes:
                    cache[path] = None
                else:
                    metadata = metadata_by_path.get(path, "")
                    cache[path] = f"{metadata}\n\n{content}" if metadata else content
            except Exception:
                cache[path] = None
            return cache[path]

        return evidence_rank(files, issue_text, fetch_content=fetch)

    def _ensure_ui_candidates(self, issue: dict[str, Any], selected: list[str], candidates: list[str]) -> list[str]:
        issue_text = f"{issue.get('title') or ''}\n{issue.get('body') or ''}".lower()
        ui_terms = [
            "dropdown",
            "drop down",
            "select",
            "selector",
            "control",
            "button",
            "form",
            "page",
            "screen",
            "dashboard",
            "ui",
        ]
        if not any(term in issue_text for term in ui_terms):
            return selected

        selected_set = set(selected)
        ui_candidates = [
            path
            for path in candidates
            if _is_template_or_ui(path) and path not in selected_set
        ]
        prioritized = sorted(ui_candidates, key=_ui_candidate_score, reverse=True)
        merged = list(selected)
        for path in prioritized[:2]:
            merged.append(path)
        return merged

    def _balance_scope_candidates(self, selected: list[str], scope: Any, fallback: list[str] | None = None) -> list[str]:
        fallback = fallback or selected
        required: list[str] = []
        if scope.ui_needed:
            required.append("frontend")
        if scope.backend_needed:
            required.append("backend")
        if scope.data_needed:
            required.append("data")
        if scope.tests_needed:
            required.append("test")
        if scope.config_needed:
            required.append("config")

        if not required:
            return selected

        merged = list(selected)
        existing_scopes = {file_scope(path) for path in merged}
        for needed_scope in required:
            if needed_scope in existing_scopes:
                continue
            candidate = self._best_scope_candidate(fallback, needed_scope, exclude=set(merged))
            if candidate:
                insert_at = min(len(merged), 2)
                merged.insert(insert_at, candidate)
                existing_scopes.add(needed_scope)
        return merged

    def _best_scope_candidate(self, paths: list[str], needed_scope: str, exclude: set[str]) -> str | None:
        scoped = [path for path in paths if path not in exclude and file_scope(path) == needed_scope]
        if not scoped:
            return None
        if needed_scope == "frontend":
            return sorted(scoped, key=_ui_candidate_score, reverse=True)[0]
        priority_names = {
            "backend": ["github_cto/app.py", "github_cto/workflow.py", "github_cto/aider_backend.py", "github_cto/github_client.py"],
            "data": ["github_cto/repo_index.py", "github_cto/index_jobs.py"],
            "config": ["requirements.txt", ".env.example", "README.md"],
        }
        priorities = priority_names.get(needed_scope, [])
        return sorted(scoped, key=lambda path: _priority_score(path, priorities), reverse=True)[0]

    def generate_proposal(
        self,
        issue_number: int,
        selected_files: list[str] | None = None,
        proposal_mode: str = "fast",
        read_branch: str | None = None,
        target_branch: str | None = None,
    ) -> dict[str, Any]:
        if not self.planner.enabled:
            raise RuntimeError("OPENAI_API_KEY is required to create autonomous code changes.")

        context = self.issue_context(issue_number)
        issue = context["issue"]
        triage = context["triage"]
        read_branch = read_branch or self.github.default_branch()
        target_branch = target_branch or self.github.default_branch()

        if selected_files is None:
            selected_files = self.plan_files(issue_number, branch=read_branch)["files"]
        selected_files = (selected_files or [])[: self.max_selected_files]
        proposal_mode = proposal_mode if proposal_mode in {"fast", "deep"} else "fast"
        logger.info(
            "Generating proposal issue=%s mode=%s selected_files=%s files=%s",
            issue_number,
            proposal_mode,
            len(selected_files),
            selected_files,
        )

        planned_files = selected_files
        if proposal_mode == "fast" and selected_files:
            planning_context = self._proposal_context_files(selected_files, read_branch)
            edit_plan = self.planner.plan_edits(issue, planning_context)
            planned_files = [path for path in edit_plan.get("files", []) if path in selected_files]
            if not planned_files:
                planned_files = selected_files[: self.default_selected_files]
            planned_files = planned_files[: self.max_selected_files]
            logger.info(
                "Edit plan issue=%s planned_files=%s rationale=%s",
                issue_number,
                planned_files,
                edit_plan.get("rationale", ""),
            )

        fetched = self._proposal_context_files(planned_files, read_branch)
        logger.info(
            "Patch context issue=%s mode=%s context_files=%s modes=%s",
            issue_number,
            proposal_mode,
            [item["path"] for item in fetched],
            {item["path"]: item.get("context_mode") for item in fetched},
        )

        patch = self.planner.generate_unified_patch(
            issue,
            fetched,
            max_context_chars_per_file=self.max_context_chars_per_file,
        )
        raw_patches = patch.get("patches", [])
        if not raw_patches:
            raise RuntimeError("AI did not produce any file changes.")

        fetched_by_path = {item["path"]: item for item in fetched}
        changes = []
        for patch_item in raw_patches:
            path = (patch_item.get("path") or "").strip().lstrip("/")
            if not path or ".." in path.split("/"):
                continue
            original = fetched_by_path.get(path)
            if original is None:
                try:
                    original = self.github.get_file(path, ref=read_branch)
                except Exception:
                    original = None

            if patch_item.get("new_file_content") is not None:
                content = patch_item["new_file_content"]
            elif patch_item.get("full_content") is not None:
                content = patch_item["full_content"]
            else:
                if not original:
                    raise RuntimeError(f"Codex returned a diff for new file {path} without new_file_content.")
                try:
                    content = apply_unified_diff(original["content"], patch_item.get("unified_diff", ""))
                except PatchApplyError as exc:
                    raise RuntimeError(
                        f"Codex produced a patch that could not be applied to {path}. Retry with Deep Proposal."
                    ) from exc

            changes.append(
                {
                    "path": path,
                    "status": "modified" if original else "new",
                    "sha": original["sha"] if original else None,
                    "original_content": original["content"] if original else "",
                    "proposed_content": content,
                    "unified_diff": patch_item.get("unified_diff", ""),
                }
            )

        if not changes:
            raise RuntimeError("AI did not produce any valid file changes.")

        return {
            "issue": {"number": issue.get("number"), "title": issue.get("title"), "html_url": issue.get("html_url")},
            "triage": {
                "severity": triage.severity,
                "score": triage.score,
                "rationale": triage.rationale,
                "recommended_action": triage.recommended_action,
            },
            "patch": {
                "summary": patch.get("summary", "No summary provided."),
                "test_plan": patch.get("test_plan", "Review and run the repository test suite."),
            },
            "base_branch": read_branch,
            "read_branch": read_branch,
            "target_branch": target_branch,
            "changes": changes,
            "codex": {
                "agent": "Codex Engineering Manager",
                "mode": "GitHub-only",
                "model": self.planner.model,
                "timeline": codex_timeline(
                    "review",
                    proposed_files=len(changes),
                    read_branch=read_branch,
                    target_branch=target_branch,
                    proposal_mode=proposal_mode,
                    context_files=len(fetched),
                ),
            },
        }

    def _proposal_context_files(self, selected_files: list[str], branch: str) -> list[dict[str, str]]:
        repo = self.github.repo.full_name
        indexed_context: dict[str, list[str]] = {}
        if self.repo_index:
            for chunk in self.repo_index.chunks_for_paths(repo, branch, selected_files, max_chunks_per_file=2):
                indexed_context.setdefault(chunk["path"], []).append(
                    f"# lines {chunk['start_line']}-{chunk['end_line']}\n{chunk['content']}"
                )

        payloads_by_path: dict[str, dict[str, str]] = {}
        with ThreadPoolExecutor(max_workers=max(1, self.max_parallel_fetches)) as executor:
            futures = {executor.submit(self.github.get_file, path, branch): path for path in selected_files}
            for future in as_completed(futures):
                path = futures[future]
                payload = future.result()
                payload["context_mode"] = "full_file_parallel"
                if self.enable_file_summaries:
                    payload["summary"] = _local_file_summary(path, payload["content"])
                if path in indexed_context:
                    payload["indexed_snippets"] = "\n\n".join(indexed_context[path])
                payloads_by_path[path] = payload

        return [payloads_by_path[path] for path in selected_files if path in payloads_by_path]

    def create_pr_from_proposal(self, proposal: dict[str, Any]) -> dict[str, Any]:
        issue = proposal["issue"]
        triage = proposal["triage"]
        patch = proposal["patch"]
        target_branch = proposal.get("target_branch") or proposal.get("base_branch") or self.github.default_branch()
        branch = safe_branch_name(issue["number"], issue.get("title", "issue"))

        self.github.create_branch(branch, from_branch=target_branch)

        committed_paths = []
        for change in proposal.get("changes", []):
            path = change.get("path")
            content = change.get("proposed_content")
            if not path or content is None:
                continue
            try:
                target_file = self.github.get_file(path, ref=target_branch)
                sha = target_file["sha"]
            except Exception:
                sha = None
            self.github.upsert_file(
                path=path,
                content=content,
                branch=branch,
                message=f"Fix issue #{issue['number']}: {issue.get('title')}",
                sha=sha,
            )
            committed_paths.append(path)

        if not committed_paths:
            raise RuntimeError("No valid file changes were committed.")

        pr_body = self._pr_body(issue, triage, patch, committed_paths)
        pr = self.github.create_pull_request(
            branch=branch,
            title=f"Fix #{issue['number']}: {issue.get('title')}",
            body=pr_body,
            base=target_branch,
        )
        self.github.comment_on_issue(
            issue["number"],
            (
                "GitHub CTO created a reviewed Codex-agent PR.\n\n"
                f"- Severity: **{triage['severity']}** ({triage['score']}/100)\n"
                f"- PR: {pr.get('html_url')}\n"
                f"- Changed files: {', '.join(committed_paths)}"
            ),
        )
        return {"branch": branch, "pr": pr, "patch": patch, "changed_files": committed_paths, "triage": triage}

    def _pr_body(self, issue: dict[str, Any], triage: Any, patch: dict[str, Any], committed_paths: list[str]) -> str:
        severity = triage.severity if hasattr(triage, "severity") else triage["severity"]
        score = triage.score if hasattr(triage, "score") else triage["score"]
        recommended_action = (
            triage.recommended_action if hasattr(triage, "recommended_action") else triage["recommended_action"]
        )
        rationale_items = triage.rationale if hasattr(triage, "rationale") else triage["rationale"]
        rationale = "\n".join(f"- {item}" for item in rationale_items)
        changed = "\n".join(f"- `{path}`" for path in committed_paths)
        return (
            f"## Autonomous GitHub CTO Fix\n\n"
            f"Closes #{issue.get('number')}.\n\n"
            f"### Triage\n"
            f"- Severity: **{severity}**\n"
            f"- Priority score: **{score}/100**\n"
            f"- Recommended action: {recommended_action}\n\n"
            f"### Rationale\n{rationale}\n\n"
            f"### Summary\n{patch.get('summary', 'No summary provided.')}\n\n"
            f"### Changed Files\n{changed}\n\n"
            f"### Test Plan\n{patch.get('test_plan', 'Review and run the repository test suite.')}\n\n"
            "_Generated by GitHub CTO._"
        )
