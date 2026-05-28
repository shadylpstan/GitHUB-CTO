from __future__ import annotations

import os
import logging
import shutil
import subprocess
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class AiderRunError(RuntimeError):
    pass


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AiderConfig:
    command: str = "aider"
    model: str = "gpt-4.1-mini"
    timeout: int = 600
    test_command: str = ""


class AiderBackend:
    def __init__(self, repo_root: str | Path, workspace_root: str | Path, config: AiderConfig):
        self.repo_root = Path(repo_root).resolve()
        self.workspace_root = Path(workspace_root).resolve()
        self.workspace_root.mkdir(parents=True, exist_ok=True)
        self.config = config

    def run_issue(
        self,
        issue: dict[str, Any],
        comments: list[dict[str, Any]],
        selected_files: list[str],
        openai_api_key: str,
    ) -> dict[str, Any]:
        if not openai_api_key:
            raise AiderRunError("OPENAI_API_KEY is required to run Aider.")
        run_id = uuid.uuid4().hex
        run_root = self.workspace_root / run_id
        workspace = run_root / "repo"
        prompt_path = run_root / "prompt.md"
        run_root.mkdir(parents=True, exist_ok=True)

        try:
            logger.info("Aider preparing isolated workspace run_id=%s", run_id)
            self._copy_workspace(workspace)
            logger.info("Aider initializing workspace git repo run_id=%s", run_id)
            self._baseline_git_repo(workspace)
            prompt_path.write_text(self._prompt(issue, comments, selected_files), encoding="utf-8")
            logger.info("Aider subprocess starting run_id=%s files=%s", run_id, selected_files)
            output = self._run_aider(workspace, prompt_path, selected_files, openai_api_key)
            logger.info("Aider subprocess completed run_id=%s", run_id)
            if self.config.test_command:
                logger.info("Aider running configured tests run_id=%s command=%s", run_id, self.config.test_command)
                output += "\n\n" + self._run_tests(workspace)
            changes = self._changed_files(workspace)
            logger.info("Aider captured changes run_id=%s changes=%s", run_id, len(changes))
            if not changes:
                raise AiderRunError("Aider completed without producing file changes.")
            return {"run_id": run_id, "workspace": str(workspace), "output": output, "changes": changes}
        except FileNotFoundError as exc:
            raise AiderRunError(
                "Aider executable was not found. Install it with `pip install aider-chat` "
                "or set AIDER_COMMAND to the full command."
            ) from exc

    def _copy_workspace(self, destination: Path) -> None:
        ignore = shutil.ignore_patterns(
            ".git",
            ".env",
            ".venv",
            "venv",
            "__pycache__",
            ".pytest_cache",
            ".mypy_cache",
            ".ruff_cache",
            "instance",
            "Github-CTO-backup-before-agent-loop-*",
            "*.pyc",
            "*.log",
        )
        shutil.copytree(self.repo_root, destination, ignore=ignore)

    def _baseline_git_repo(self, workspace: Path) -> None:
        self._git(workspace, "init")
        self._git(workspace, "config", "user.name", "github-cto-aider")
        self._git(workspace, "config", "user.email", "github-cto-aider@users.noreply.github.com")
        self._git(workspace, "add", ".")
        self._git(workspace, "commit", "-m", "baseline")

    def _run_aider(self, workspace: Path, prompt_path: Path, selected_files: list[str], openai_api_key: str) -> str:
        command = self._command_parts()
        args = [
            *command,
            "--model",
            self.config.model,
            "--openai-api-key",
            openai_api_key,
            "--message-file",
            str(prompt_path),
            "--yes",
            "--no-auto-commits",
            "--no-gitignore",
            *selected_files,
        ]
        env = os.environ.copy()
        env["OPENAI_API_KEY"] = openai_api_key
        env["AIDER_AUTO_COMMITS"] = "0"
        env["AIDER_YES"] = "1"
        env.setdefault("AIDER_ANALYTICS", "false")
        completed = subprocess.run(
            args,
            cwd=workspace,
            env=env,
            capture_output=True,
            text=True,
            timeout=self.config.timeout,
        )
        output = (completed.stdout or "") + (completed.stderr or "")
        if completed.returncode != 0:
            raise AiderRunError(f"Aider failed with exit code {completed.returncode}:\n{output[-5000:]}")
        return output[-12000:]

    def _run_tests(self, workspace: Path) -> str:
        completed = subprocess.run(
            self.config.test_command,
            cwd=workspace,
            shell=True,
            capture_output=True,
            text=True,
            timeout=min(self.config.timeout, 300),
        )
        output = (completed.stdout or "") + (completed.stderr or "")
        status = "passed" if completed.returncode == 0 else f"failed ({completed.returncode})"
        return f"Configured test command `{self.config.test_command}` {status}.\n{output[-5000:]}"

    def _changed_files(self, workspace: Path) -> list[dict[str, str]]:
        status = self._git_text(workspace, "status", "--porcelain")
        changes = []
        for line in status.splitlines():
            if not line.strip():
                continue
            path = line[3:].strip()
            if " -> " in path:
                path = path.split(" -> ", 1)[1].strip()
            if path.startswith(".aider"):
                continue
            file_path = workspace / path
            if not file_path.exists() or not file_path.is_file():
                continue
            proposed_content = file_path.read_text(encoding="utf-8", errors="replace")
            original_content = self._git_show(workspace, path)
            changes.append(
                {
                    "path": path.replace("\\", "/"),
                    "status": "modified" if original_content is not None else "new",
                    "original_content": original_content or "",
                    "proposed_content": proposed_content,
                    "unified_diff": self._git_text(workspace, "diff", "--", path),
                }
            )
        return changes

    def _prompt(self, issue: dict[str, Any], comments: list[dict[str, Any]], selected_files: list[str]) -> str:
        comment_text = "\n".join(
            f"- {comment.get('user', {}).get('login', 'user')}: {(comment.get('body') or '')[:1200]}"
            for comment in comments[-8:]
        )
        files = "\n".join(f"- {path}" for path in selected_files) or "- Let Aider choose files from the repo map."
        return (
            f"Fix GitHub issue #{issue.get('number')}: {issue.get('title')}\n\n"
            f"Issue body:\n{issue.get('body') or 'No issue body provided.'}\n\n"
            f"Recent comments:\n{comment_text or 'No comments.'}\n\n"
            f"Files selected by GitHub CTO:\n{files}\n\n"
            "Make the minimal code changes needed to address the issue. "
            "Preserve existing behavior and style. Do not create a PR or commit. "
            "Leave the edited files in the working tree for Flask to review as a diff."
        )

    def _command_parts(self) -> list[str]:
        value = self.config.command.strip()
        if not value:
            return ["aider"]
        if value == "python -m aider":
            return [sys.executable, "-m", "aider"]
        return value.split()

    def _git(self, workspace: Path, *args: str) -> None:
        subprocess.run(["git", *args], cwd=workspace, check=True, capture_output=True, text=True)

    def _git_text(self, workspace: Path, *args: str) -> str:
        completed = subprocess.run(["git", *args], cwd=workspace, check=True, capture_output=True, text=True)
        return completed.stdout

    def _git_show(self, workspace: Path, path: str) -> str | None:
        completed = subprocess.run(
            ["git", "show", f"HEAD:{path}"],
            cwd=workspace,
            capture_output=True,
            text=True,
        )
        if completed.returncode != 0:
            return None
        return completed.stdout
