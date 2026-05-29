from __future__ import annotations

import os
import logging
import queue
import shutil
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote, urlparse


class AiderRunError(RuntimeError):
    pass


logger = logging.getLogger(__name__)
ProgressCallback = Callable[[str], None]


@dataclass(frozen=True)
class AiderConfig:
    command: str = "aider"
    model: str = "gpt-4.1-mini"
    timeout: int = 600
    test_command: str = ""
    keep_runs: int = 5


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
        github_token: str,
        repository: str,
        branch: str,
        progress: ProgressCallback | None = None,
    ) -> dict[str, Any]:
        if not openai_api_key:
            raise AiderRunError("OPENAI_API_KEY is required to run Aider.")
        run_id = uuid.uuid4().hex
        run_root = self.workspace_root / run_id
        workspace = run_root / "repo"
        prompt_path = run_root / "prompt.md"
        run_root.mkdir(parents=True, exist_ok=True)

        try:
            self.cleanup_old_runs()
            self._progress(progress, f"Preparing isolated workspace {run_id}.")
            logger.info("Aider preparing isolated workspace run_id=%s", run_id)
            self._clone_repository(workspace, github_token, repository, branch)
            self._progress(progress, "Cloned repository into isolated workspace.")
            logger.info("Aider initializing workspace git repo run_id=%s", run_id)
            self._baseline_git_repo(workspace)
            prompt_path.write_text(self._prompt(issue, comments, selected_files), encoding="utf-8")
            self._progress(progress, f"Starting Aider with {len(selected_files)} selected file(s).")
            logger.info("Aider subprocess starting run_id=%s files=%s", run_id, selected_files)
            output = self._run_aider(workspace, prompt_path, selected_files, openai_api_key, progress)
            self._progress(progress, "Aider subprocess completed.")
            logger.info("Aider subprocess completed run_id=%s", run_id)
            if self.config.test_command:
                self._progress(progress, f"Running configured tests: {self.config.test_command}")
                logger.info("Aider running configured tests run_id=%s command=%s", run_id, self.config.test_command)
                output += "\n\n" + self._run_tests(workspace)
            changes = self._changed_files(workspace)
            self._progress(progress, f"Captured {len(changes)} changed file(s).")
            logger.info("Aider captured changes run_id=%s changes=%s", run_id, len(changes))
            if not changes:
                raise AiderRunError("Aider completed without producing file changes.")
            return {"run_id": run_id, "workspace": str(workspace), "output": output, "changes": changes}
        except FileNotFoundError as exc:
            raise AiderRunError(
                "Aider executable was not found. Install it with `pip install aider-chat` "
                "or set AIDER_COMMAND to the full command."
            ) from exc
        finally:
            self.cleanup_old_runs()

    def cleanup_old_runs(self) -> None:
        keep = max(1, self.config.keep_runs)
        if not self.workspace_root.exists():
            return
        runs = [path for path in self.workspace_root.iterdir() if path.is_dir()]
        runs.sort(key=lambda path: path.stat().st_mtime, reverse=True)
        for old_run in runs[keep:]:
            shutil.rmtree(old_run, ignore_errors=True)
            logger.info("Removed old Aider workspace %s", old_run)

    def _clone_repository(self, destination: Path, token: str, repository: str, branch: str) -> None:
        repo_name = _normalize_repository(repository)
        if not repo_name:
            raise AiderRunError("GITHUB_REPOSITORY must be owner/repo or a GitHub repository URL.")

        clone_url = f"https://x-access-token:{quote(token, safe='')}@github.com/{repo_name}.git"
        completed = subprocess.run(
            ["git", "clone", "--depth", "1", "--branch", branch, clone_url, str(destination)],
            capture_output=True,
            text=True,
            timeout=180,
        )
        if completed.returncode != 0:
            safe_output = ((completed.stdout or "") + (completed.stderr or "")).replace(token, "***")
            raise AiderRunError(f"Could not clone {repo_name} branch {branch} for Aider:\n{safe_output[-1500:]}")

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
        self._git(workspace, "config", "user.name", "github-cto-aider")
        self._git(workspace, "config", "user.email", "github-cto-aider@users.noreply.github.com")
        self._git(workspace, "add", ".")
        status = self._git_text(workspace, "status", "--porcelain")
        if status.strip():
            self._git(workspace, "commit", "-m", "baseline")

    def _run_aider(
        self,
        workspace: Path,
        prompt_path: Path,
        selected_files: list[str],
        openai_api_key: str,
        progress: ProgressCallback | None,
    ) -> str:
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
            "--no-detect-urls",
            "--disable-playwright",
            "--no-pretty",
            "--no-fancy-input",
            "--no-stream",
            "--no-auto-lint",
            *selected_files,
        ]
        env = os.environ.copy()
        env["OPENAI_API_KEY"] = openai_api_key
        env["AIDER_AUTO_COMMITS"] = "0"
        env["AIDER_YES"] = "1"
        env["AIDER_DETECT_URLS"] = "false"
        env["AIDER_DISABLE_PLAYWRIGHT"] = "true"
        env["AIDER_PRETTY"] = "false"
        env["AIDER_FANCY_INPUT"] = "false"
        env["AIDER_STREAM"] = "false"
        env["AIDER_AUTO_LINT"] = "false"
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"] = "1"
        env["TERM"] = "dumb"
        env["NO_COLOR"] = "1"
        env.setdefault("AIDER_ANALYTICS", "false")
        started = time.monotonic()
        process = subprocess.Popen(
            args,
            cwd=workspace,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        output_parts: list[str] = []
        output_queue: queue.Queue[str | None] = queue.Queue()

        def read_output() -> None:
            try:
                if process.stdout:
                    for item in process.stdout:
                        output_queue.put(item)
            finally:
                output_queue.put(None)

        reader = threading.Thread(target=read_output, daemon=True)
        reader.start()
        last_heartbeat = 0.0
        output_closed = False
        while True:
            try:
                line = output_queue.get(timeout=0.5)
                if line is None:
                    output_closed = True
                else:
                    output_parts.append(line)
                    clean = line.strip()
                    if clean:
                        logger.info("Aider output: %s", clean[:500])
                        self._progress(progress, clean[:500])
            except queue.Empty:
                pass
            return_code = process.poll()
            elapsed = time.monotonic() - started
            if elapsed - last_heartbeat >= 15:
                logger.info("Aider still running elapsed=%ss timeout=%ss", int(elapsed), self.config.timeout)
                self._progress(progress, f"Aider still running after {int(elapsed)}s.")
                last_heartbeat = elapsed
            if elapsed > self.config.timeout:
                process.kill()
                output = "".join(output_parts)
                raise AiderRunError(f"Aider timed out after {self.config.timeout}s:\n{output[-5000:]}")
            if return_code is not None:
                while not output_closed:
                    try:
                        line = output_queue.get(timeout=0.2)
                        if line is None:
                            output_closed = True
                        else:
                            output_parts.append(line)
                    except queue.Empty:
                        break
                break

        output = "".join(output_parts)
        if process.returncode != 0:
            changes = self._changed_files(workspace)
            if changes:
                logger.warning(
                    "Aider exited nonzero after applying changes; preserving changes returncode=%s",
                    process.returncode,
                )
                return output[-12000:] + f"\n\nAider exited with code {process.returncode} after applying edits. Review carefully."
            raise AiderRunError(f"Aider failed with exit code {process.returncode}:\n{output[-5000:]}")
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
            "Leave the edited files in the working tree for Flask to review as a diff.\n\n"
            "Edit hygiene rules:\n"
            "- Use the selected files as the primary edit context. Make the requested issue change across selected files when they are relevant, including connected imports, template references, route/job wiring, JavaScript, and CSS.\n"
            "- If a selected stylesheet exists and the change needs styling, prefer updating the stylesheet instead of adding inline styles.\n"
            "- If a selected file appears related but does not need edits, leave it unchanged.\n"
            "- Do not comment out removed code. Delete obsolete code cleanly.\n"
            "- Do not leave explanatory comments in place of removed routes, forms, buttons, methods, or imports.\n"
            "- If removing UI, remove the complete related element, including its wrapper form and JavaScript references.\n"
            "- If removing backend behavior, remove the complete route/helper only when the issue asks for backend removal.\n"
            "- After the main edit, scan the edited files for stale IDs, variable names, routes, url_for calls, imports, CSS selectors, and helper references related to the removed behavior.\n"
            "- Before finishing, scan changed files for missing imports, stale references, undefined variables, broken template IDs, missing CSS classes, and mismatched route/template names.\n"
            "- Remove stale references in the same file when they no longer point to an existing element or route.\n"
            "- For UI removals, check both the HTML markup and the page script in the same template.\n"
            "- Keep changes minimal and do not rewrite unrelated sections.\n"
            "- The final files must parse/compile and must not contain SEARCH/REPLACE markers."
        )

    def _progress(self, progress: ProgressCallback | None, message: str) -> None:
        if progress:
            progress(message)

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


def _normalize_repository(repository: str) -> str:
    value = (repository or "").strip().strip("/").removesuffix(".git")
    if not value:
        return ""
    if value.startswith("http://") or value.startswith("https://"):
        parsed = urlparse(value)
        value = parsed.path.strip("/")
    if value.startswith("github.com/"):
        value = value.removeprefix("github.com/")
    parts = value.split("/")
    if len(parts) < 2:
        return ""
    return f"{parts[0]}/{parts[1]}"
