import re
from datetime import datetime, timezone
from typing import Any

from .ai import CodexEngineeringManager
from .evidence import evidence_rank
from .github_client import GitHubClient, is_probably_text_file
from .intent import architectural_rank, classify_issue_intent
from .repo_index import RepositoryIndex
from .triage import triage_issue


def safe_branch_name(issue_number: int, title: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", title.lower()).strip("-")[:48] or "issue"
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    return f"codex/issue-{issue_number}-{slug}-{stamp}"


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
        max_selected_files: int,
        max_context_chars_per_file: int,
        repo_index: RepositoryIndex | None = None,
    ):
        self.github = github
        self.planner = planner
        self.max_repo_files = max_repo_files
        self.max_file_bytes = max_file_bytes
        self.max_selected_files = max_selected_files
        self.max_context_chars_per_file = max_context_chars_per_file
        self.repo_index = repo_index

    def issue_context(self, issue_number: int) -> dict[str, Any]:
        issue = self.github.get_issue(issue_number)
        comments = self.github.list_issue_comments(issue_number)
        triage = triage_issue(issue, comments)
        return {"issue": issue, "comments": comments, "triage": triage}

    def candidate_files(self) -> list[str]:
        tree = self.github.get_tree()
        paths = [
            item["path"]
            for item in tree
            if item.get("type") == "blob" and is_probably_text_file(item.get("path", ""))
        ]
        ignored = (".lock", "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "dist/", "build/", "vendor/")
        filtered = [path for path in paths if not any(part in path for part in ignored)]
        return filtered[: self.max_repo_files]

    def plan_files(self, issue_number: int) -> dict[str, Any]:
        issue = self.github.get_issue(issue_number)
        intent = classify_issue_intent(issue)
        indexed_files = self._indexed_candidate_files(issue)
        base_files = indexed_files or self.candidate_files()
        evidence_hits = self._evidence_hits(issue, base_files)
        evidence_scores = {hit.path: hit.score for hit in evidence_hits}
        files = architectural_rank(base_files, intent, evidence_scores=evidence_scores)
        context_source = "vector_index" if indexed_files else "repo_tree"
        if not self.planner.enabled:
            return {
                "files": files[: self.max_selected_files],
                "reasoning": "Codex planning is disabled because OPENAI_API_KEY is not configured. Showing top repository files only.",
                "root_cause_justification": "",
                "intent": intent,
                "evidence": evidence_hits[:8],
                "ai_enabled": False,
                "timeline": codex_timeline(
                    "context",
                    context_source=context_source,
                    intent=intent.kind,
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
        return {
            "files": selected[: self.max_selected_files],
            "reasoning": plan.get("reasoning", ""),
            "root_cause_justification": plan.get("root_cause_justification", ""),
            "intent": intent,
            "evidence": evidence_hits[:8],
            "ai_enabled": True,
            "timeline": codex_timeline(
                "context",
                selected_files=len(selected[: self.max_selected_files]),
                context_source=context_source,
                intent=intent.kind,
                evidence_hits=len(evidence_hits),
            ),
        }

    def _indexed_candidate_files(self, issue: dict[str, Any]) -> list[str]:
        if not self.repo_index:
            return []
        repo = self.github.repo.full_name
        branch = self.github.default_branch()
        labels = " ".join(label.get("name", "") for label in issue.get("labels", []))
        query = f"{issue.get('title') or ''}\n\n{issue.get('body') or ''}\n\nlabels: {labels}"
        indexed_paths = self.repo_index.top_paths(repo, branch, query, limit=24)
        if not indexed_paths:
            return []
        all_files = self.candidate_files()
        indexed_set = set(indexed_paths)
        remaining = [path for path in all_files if path not in indexed_set]
        return indexed_paths + remaining[: max(0, self.max_repo_files - len(indexed_paths))]

    def _evidence_hits(self, issue: dict[str, Any], files: list[str]) -> list[Any]:
        issue_text = f"{issue.get('title') or ''}\n\n{issue.get('body') or ''}"
        branch = self.github.default_branch()
        cache: dict[str, str | None] = {}

        def fetch(path: str) -> str | None:
            if path in cache:
                return cache[path]
            try:
                payload = self.github.get_file(path, ref=branch)
                content = payload["content"]
                if len(content.encode("utf-8")) > self.max_file_bytes:
                    cache[path] = None
                else:
                    cache[path] = content
            except Exception:
                cache[path] = None
            return cache[path]

        return evidence_rank(files, issue_text, fetch_content=fetch)

    def generate_proposal(self, issue_number: int, selected_files: list[str] | None = None) -> dict[str, Any]:
        if not self.planner.enabled:
            raise RuntimeError("OPENAI_API_KEY is required to create autonomous code changes.")

        context = self.issue_context(issue_number)
        issue = context["issue"]
        triage = context["triage"]
        base_branch = self.github.default_branch()

        if selected_files is None:
            selected_files = self.plan_files(issue_number)["files"]
        selected_files = (selected_files or [])[: self.max_selected_files]

        fetched = []
        for path in selected_files or []:
            payload = self.github.get_file(path, ref=base_branch)
            fetched.append(payload)

        patch = self.planner.generate_patch(
            issue,
            fetched,
            max_context_chars_per_file=self.max_context_chars_per_file,
        )
        raw_changes = patch.get("changes", [])
        if not raw_changes:
            raise RuntimeError("AI did not produce any file changes.")

        fetched_by_path = {item["path"]: item for item in fetched}
        changes = []
        for change in raw_changes:
            path = (change.get("path") or "").strip().lstrip("/")
            content = change.get("full_content")
            if not path or content is None or ".." in path.split("/"):
                continue
            original = fetched_by_path.get(path)
            if original is None:
                try:
                    original = self.github.get_file(path, ref=base_branch)
                except Exception:
                    original = None
            changes.append(
                {
                    "path": path,
                    "status": "modified" if original else "new",
                    "sha": original["sha"] if original else None,
                    "original_content": original["content"] if original else "",
                    "proposed_content": content,
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
            "base_branch": base_branch,
            "changes": changes,
            "codex": {
                "agent": "Codex Engineering Manager",
                "mode": "GitHub-only",
                "model": self.planner.model,
                "timeline": codex_timeline("review", proposed_files=len(changes), base_branch=base_branch),
            },
        }

    def create_pr_from_proposal(self, proposal: dict[str, Any]) -> dict[str, Any]:
        issue = proposal["issue"]
        triage = proposal["triage"]
        patch = proposal["patch"]
        base_branch = proposal.get("base_branch") or self.github.default_branch()
        branch = safe_branch_name(issue["number"], issue.get("title", "issue"))

        self.github.create_branch(branch, from_branch=base_branch)

        committed_paths = []
        for change in proposal.get("changes", []):
            path = change.get("path")
            content = change.get("proposed_content")
            if not path or content is None:
                continue
            self.github.upsert_file(
                path=path,
                content=content,
                branch=branch,
                message=f"Fix issue #{issue['number']}: {issue.get('title')}",
                sha=change.get("sha"),
            )
            committed_paths.append(path)

        if not committed_paths:
            raise RuntimeError("No valid file changes were committed.")

        pr_body = self._pr_body(issue, triage, patch, committed_paths)
        pr = self.github.create_pull_request(
            branch=branch,
            title=f"Fix #{issue['number']}: {issue.get('title')}",
            body=pr_body,
            base=base_branch,
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
