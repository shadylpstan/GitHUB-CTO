from __future__ import annotations

import logging
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .patch_utils import PatchApplyError, apply_unified_diff
from .proposals import unified_diff
from .workflow import GitHubCTOWorkflow, codex_timeline


logger = logging.getLogger(__name__)


@dataclass
class AgentLoopConfig:
    max_steps: int = 4
    test_command: str = ""
    test_timeout: int = 90
    openai_timeout: int = 60
    openai_max_retries: int = 0
    max_context_chars_per_file: int = 6000


class IterativeAgentLoop:
    def __init__(self, workflow: GitHubCTOWorkflow, config: AgentLoopConfig):
        self.workflow = workflow
        self.config = config

    def run(self, issue_number: int, selected_files: list[str] | None = None) -> dict[str, Any]:
        if not self.workflow.planner.enabled:
            raise RuntimeError("OPENAI_API_KEY is required to run the Codex agent loop.")

        original_retries = self.workflow.planner.max_retries
        self.workflow.planner.max_retries = self.config.openai_max_retries
        try:
            return self._run(issue_number, selected_files)
        finally:
            self.workflow.planner.max_retries = original_retries

    def _run(self, issue_number: int, selected_files: list[str] | None = None) -> dict[str, Any]:
        logger.info("Agent loading issue context issue=%s", issue_number)
        context = self.workflow.issue_context(issue_number)
        issue = context["issue"]
        triage = context["triage"]
        logger.info("Agent loading default branch issue=%s", issue_number)
        base_branch = self.workflow.github.default_branch()
        selected = (selected_files or self.workflow.plan_files(issue_number)["files"])[: self.workflow.max_selected_files]
        if not selected:
            raise RuntimeError("No files were selected for the agent run.")

        logger.info("Agent fetching selected files issue=%s files=%s", issue_number, selected)
        originals = self.workflow._proposal_context_files(selected, base_branch)
        logger.info("Agent fetched selected files issue=%s count=%s", issue_number, len(originals))
        workspace = {item["path"]: dict(item) for item in originals}
        steps: list[dict[str, Any]] = []
        test_output = ""
        patch_summary = "Iterative agent run completed."
        test_plan = "Review final diff and run the repository test suite."

        for step_number in range(1, self.config.max_steps + 1):
            context_files = [workspace[path] for path in selected if path in workspace]
            logger.info(
                "Agent step request issue=%s step=%s files=%s paths=%s timeout=%s",
                issue_number,
                step_number,
                len(context_files),
                [item["path"] for item in context_files],
                self.config.openai_timeout,
            )
            agent_step = self.workflow.planner.generate_agent_step(
                issue,
                context_files,
                history=steps,
                test_output=test_output,
                max_context_chars_per_file=self.config.max_context_chars_per_file,
                timeout=self.config.openai_timeout,
            )
            logger.info(
                "Agent step response issue=%s step=%s status=%s action=%s path=%s",
                issue_number,
                step_number,
                agent_step.get("status"),
                agent_step.get("action"),
                agent_step.get("path"),
            )
            status = (agent_step.get("status") or "continue").strip().lower()
            summary = agent_step.get("summary") or "Agent step completed."
            patch_summary = summary or patch_summary
            test_plan = agent_step.get("test_plan") or test_plan

            if status == "complete":
                if not self._has_changes(originals, workspace):
                    test_output = "Agent said complete, but no file changes exist yet. Choose one concrete edit."
                    steps.append(
                        {
                            "step": step_number,
                            "action": "complete_without_changes",
                            "status": "blocked",
                            "summary": summary,
                            "observation": test_output,
                        }
                    )
                    continue
                steps.append(
                    {
                        "step": step_number,
                        "action": "complete",
                        "status": "done",
                        "summary": summary,
                        "observation": test_output,
                    }
                )
                break

            path = self._safe_path(agent_step.get("path") or "")
            original = workspace.get(path)
            if original is None:
                original = self._fetch_or_new(path, base_branch)
                workspace[path] = original
                if path not in selected:
                    selected.append(path)

            before_content = original["content"]
            try:
                proposed = self._apply_step(path, before_content, agent_step)
            except RuntimeError as exc:
                test_output = (
                    f"Patch was rejected before tests ran: {exc}\n"
                    "Return full_content for the complete final file with a concrete code change."
                )
                steps.append(
                    {
                        "step": step_number,
                        "action": "patch_rejected",
                        "status": "blocked",
                        "path": path,
                        "summary": summary,
                        "observation": test_output,
                    }
                )
                try:
                    logger.info(
                        "Agent full-content repair request issue=%s step=%s path=%s",
                        issue_number,
                        step_number,
                        path,
                    )
                    repair = self.workflow.planner.generate_full_file_step(
                        issue,
                        {**original, "content": before_content},
                        history=steps,
                        observation=test_output,
                        max_context_chars=max(self.config.max_context_chars_per_file, 30000),
                        timeout=self.config.openai_timeout,
                    )
                    repaired_path = self._safe_path(repair.get("path") or path)
                    if repaired_path != path:
                        raise RuntimeError(f"Full-content repair returned a different path: {repaired_path}")
                    proposed = repair.get("full_content")
                    if proposed is None:
                        raise RuntimeError("Full-content repair did not return full_content.")
                    summary = repair.get("summary") or summary
                    test_plan = repair.get("test_plan") or test_plan
                except Exception as repair_exc:
                    test_output = f"{test_output}\nFull-content repair also failed: {repair_exc}"
                    steps[-1]["observation"] = test_output
                    continue
            if proposed == before_content:
                test_output = (
                    f"Agent returned unchanged content for {path}. "
                    "The next step must make a concrete code change or choose a different file."
                )
                logger.info(
                    "Agent unchanged edit issue=%s step=%s path=%s",
                    issue_number,
                    step_number,
                    path,
                )
                steps.append(
                    {
                        "step": step_number,
                        "action": "unchanged_edit",
                        "status": "blocked",
                        "path": path,
                        "summary": summary,
                        "observation": test_output,
                    }
                )
                continue
            workspace[path]["content"] = proposed
            workspace[path]["proposed_content"] = proposed
            workspace[path]["context_mode"] = "agent_workspace"

            test_result = self._run_tests(workspace)
            logger.info(
                "Agent test result issue=%s step=%s path=%s status=%s",
                issue_number,
                step_number,
                path,
                test_result["status"],
            )
            test_output = test_result["output"]
            steps.append(
                {
                    "step": step_number,
                    "action": "edit_file",
                    "status": "done",
                    "path": path,
                    "summary": summary,
                    "test_status": test_result["status"],
                    "observation": test_output[-3000:],
                }
            )
            if test_result["status"] == "passed":
                break

        changes = self._changes(originals, workspace)
        if not changes:
            recent = "; ".join(
                f"step {step.get('step')} {step.get('action')}: {step.get('observation', step.get('summary', ''))[:180]}"
                for step in steps[-3:]
            )
            raise RuntimeError(f"Agent loop completed without producing file changes. Recent observations: {recent}")

        return {
            "issue": {"number": issue.get("number"), "title": issue.get("title"), "html_url": issue.get("html_url")},
            "triage": {
                "severity": triage.severity,
                "score": triage.score,
                "rationale": triage.rationale,
                "recommended_action": triage.recommended_action,
            },
            "patch": {
                "summary": patch_summary,
                "test_plan": test_plan,
                "agent_steps": steps,
            },
            "base_branch": base_branch,
            "changes": changes,
            "codex": {
                "agent": "Codex Iterative Agent",
                "mode": "small-step Flask orchestrated loop",
                "model": self.workflow.planner.model,
                "timeline": codex_timeline(
                    "review",
                    proposed_files=len(changes),
                    base_branch=base_branch,
                    agent_steps=len(steps),
                ),
            },
        }

    def _safe_path(self, path: str) -> str:
        normalized = path.strip().replace("\\", "/").lstrip("/")
        if not normalized or ".." in normalized.split("/"):
            raise RuntimeError(f"Codex returned an unsafe path: {path}")
        return normalized

    def _fetch_or_new(self, path: str, base_branch: str) -> dict[str, Any]:
        try:
            payload = self.workflow.github.get_file(path, ref=base_branch)
            payload["status"] = "modified"
            return payload
        except Exception:
            return {"path": path, "sha": None, "content": "", "status": "new"}

    def _apply_step(self, path: str, original_content: str, agent_step: dict[str, Any]) -> str:
        if agent_step.get("new_file_content") is not None:
            return agent_step["new_file_content"]
        if agent_step.get("full_content") is not None:
            return agent_step["full_content"]
        diff = agent_step.get("unified_diff") or ""
        if not diff.strip():
            raise RuntimeError(f"Agent step for {path} did not include a patch.")
        try:
            return apply_unified_diff(original_content, diff)
        except PatchApplyError as exc:
            raise RuntimeError(f"Agent produced a patch that could not be applied to {path}.") from exc

    def _run_tests(self, workspace: dict[str, dict[str, Any]]) -> dict[str, str]:
        if not self.config.test_command:
            return {"status": "skipped", "output": "No AGENT_TEST_COMMAND configured."}

        source_root = Path.cwd()
        with tempfile.TemporaryDirectory(prefix="github-cto-agent-") as tmp:
            tmp_root = Path(tmp)
            shutil.copytree(
                source_root,
                tmp_root,
                dirs_exist_ok=True,
                ignore=shutil.ignore_patterns(
                    ".git",
                    ".venv",
                    "venv",
                    "__pycache__",
                    ".pytest_cache",
                    "instance",
                    "Github-CTO-backup-before-agent-loop-*",
                ),
            )
            for path, payload in workspace.items():
                destination = tmp_root / path
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_text(payload["content"], encoding="utf-8")

            try:
                completed = subprocess.run(
                    self.config.test_command,
                    cwd=tmp_root,
                    shell=True,
                    capture_output=True,
                    text=True,
                    timeout=self.config.test_timeout,
                )
                output = (completed.stdout or "") + (completed.stderr or "")
                status = "passed" if completed.returncode == 0 else f"failed ({completed.returncode})"
                return {"status": status, "output": output[-5000:] or "Test command produced no output."}
            except subprocess.TimeoutExpired as exc:
                output = ((exc.stdout or "") + (exc.stderr or "")) if isinstance(exc.stdout, str) else ""
                return {"status": "timeout", "output": (output[-5000:] or "Test command timed out.")}

    def _changes(self, originals: list[dict[str, Any]], workspace: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
        original_by_path = {item["path"]: item for item in originals}
        changes = []
        for path, payload in workspace.items():
            original = original_by_path.get(path)
            before = original["content"] if original else ""
            after = payload["content"]
            if before == after:
                continue
            changes.append(
                {
                    "path": path,
                    "status": "modified" if original else "new",
                    "sha": original["sha"] if original else None,
                    "original_content": before,
                    "proposed_content": after,
                    "unified_diff": unified_diff(path, before, after),
                }
            )
        return changes

    def _has_changes(self, originals: list[dict[str, Any]], workspace: dict[str, dict[str, Any]]) -> bool:
        original_by_path = {item["path"]: item for item in originals}
        for path, payload in workspace.items():
            original = original_by_path.get(path)
            before = original["content"] if original else ""
            if before != payload["content"]:
                return True
        return False
