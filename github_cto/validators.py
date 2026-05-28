from __future__ import annotations

import ast
import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from flask import Flask


class ProposalValidationError(RuntimeError):
    pass


def validate_proposal_changes(app: Flask, changes: list[dict[str, Any]]) -> list[str]:
    warnings: list[str] = []
    errors: list[str] = []
    for change in changes:
        path = change.get("path", "")
        content = change.get("proposed_content", "")
        try:
            warnings.extend(_validate_single_file(app, path, content))
        except ProposalValidationError as exc:
            errors.append(f"{path}: {exc}")
    if errors:
        raise ProposalValidationError("\n".join(errors))
    return warnings


def _validate_single_file(app: Flask, path: str, content: str) -> list[str]:
    normalized = path.replace("\\", "/")
    suffix = Path(normalized).suffix.lower()
    warnings: list[str] = []
    warnings.extend(_generic_text_checks(content))

    if suffix == ".py":
        ast.parse(content)
    elif suffix == ".json":
        json.loads(content)
    elif suffix in {".html", ".jinja", ".j2"}:
        _validate_template(app, normalized, content)
        _validate_html_balance(content)
    elif suffix in {".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"}:
        _validate_with_command(["node", "--check"], normalized, content, suffix)
    elif suffix == ".java":
        _validate_with_command(["javac"], normalized, content, suffix)

    return warnings


def _generic_text_checks(content: str) -> list[str]:
    warnings = []
    if "<<<<<<<" in content or "=======" in content or ">>>>>>>" in content:
        raise ProposalValidationError("contains merge/search-replace conflict markers")
    if _large_commented_block_count(content) >= 1:
        raise ProposalValidationError("contains a large commented-out code block instead of a clean edit")
    if "\x00" in content:
        raise ProposalValidationError("contains NUL bytes")
    return warnings


def _validate_template(app: Flask, path: str, content: str) -> None:
    previous = app.jinja_loader
    with tempfile.TemporaryDirectory(prefix="github-cto-template-") as tmp:
        template_path = Path(tmp) / path
        template_path.parent.mkdir(parents=True, exist_ok=True)
        template_path.write_text(content, encoding="utf-8")
        try:
            from jinja2 import FileSystemLoader

            app.jinja_loader = FileSystemLoader(tmp)
            app.jinja_env.get_template(path)
        finally:
            app.jinja_loader = previous


def _validate_html_balance(content: str) -> None:
    for tag in ["form", "button", "section", "div"]:
        opens = len(re.findall(rf"<{tag}(\s|>|/)", content, flags=re.IGNORECASE))
        closes = len(re.findall(rf"</{tag}>", content, flags=re.IGNORECASE))
        self_closing = len(re.findall(rf"<{tag}[^>]*/>", content, flags=re.IGNORECASE))
        if opens - self_closing != closes:
            raise ProposalValidationError(f"unbalanced <{tag}> tags")


def _validate_with_command(command: list[str], path: str, content: str, suffix: str) -> None:
    executable = shutil.which(command[0])
    if not executable:
        return
    with tempfile.TemporaryDirectory(prefix="github-cto-validate-") as tmp:
        file_path = Path(tmp) / Path(path).name
        if suffix in {".tsx", ".ts"} and command[0] == "node":
            return
        file_path.write_text(content, encoding="utf-8")
        completed = subprocess.run(
            [executable, *command[1:], str(file_path)],
            cwd=tmp,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if completed.returncode != 0:
            output = ((completed.stdout or "") + (completed.stderr or "")).strip()
            raise ProposalValidationError(output[:1000] or f"{command[0]} validation failed")


def _large_commented_block_count(content: str) -> int:
    count = 0
    lines = content.splitlines()
    streak = 0
    for line in lines:
        stripped = line.strip()
        is_comment = (
            stripped.startswith("#")
            or stripped.startswith("//")
            or stripped.startswith("{#")
            or stripped.startswith("/*")
            or stripped.startswith("*")
        )
        if is_comment and len(stripped) > 4:
            streak += 1
        else:
            if streak >= 5:
                count += 1
            streak = 0
    if streak >= 5:
        count += 1
    return count
