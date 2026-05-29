from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class IssueIntent:
    kind: str
    confidence: float
    rationale: str


@dataclass(frozen=True)
class IssueScope:
    kind: str
    ui_needed: bool
    backend_needed: bool
    data_needed: bool
    tests_needed: bool
    config_needed: bool
    rationale: str


def classify_issue_intent(issue: dict[str, Any]) -> IssueIntent:
    title = (issue.get("title") or "").lower()
    body = (issue.get("body") or "").lower()
    labels = " ".join(label.get("name", "").lower() for label in issue.get("labels", []))
    text = f"{title}\n{body}\n{labels}"

    if any(term in text for term in ["documentation", "docs", "readme", "typo", "example text"]):
        return IssueIntent("docs", 0.78, "Issue appears documentation-oriented.")
    if any(
        term in text
        for term in [
            "feature",
            "enhancement",
            "add support",
            "new option",
            "request",
            "add ",
            "dropdown",
            "drop down",
            "control",
            "selector",
            "select ",
        ]
    ):
        return IssueIntent("enhancement", 0.72, "Issue asks for new or expanded behavior.")
    if any(term in text for term in ["bug", "error", "fails", "failure", "crash", "regression", "not recognized", "incorrect"]):
        return IssueIntent("bug", 0.84, "Issue describes broken or incorrect behavior.")
    if any(term in labels for term in ["bug", "defect"]):
        return IssueIntent("bug", 0.8, "Issue labels indicate a bug.")
    return IssueIntent("unknown", 0.45, "Issue intent is ambiguous.")


def architectural_rank(paths: list[str], intent: IssueIntent, evidence_scores: dict[str, int] | None = None) -> list[str]:
    evidence_scores = evidence_scores or {}
    scored = [(path, _path_score(path, intent) + evidence_scores.get(path, 0)) for path in paths]
    scored.sort(key=lambda item: item[1], reverse=True)
    return [path for path, _ in scored]


def classify_issue_scope(issue: dict[str, Any]) -> IssueScope:
    title = (issue.get("title") or "").lower()
    body = (issue.get("body") or "").lower()
    labels = " ".join(label.get("name", "").lower() for label in issue.get("labels", []))
    text = f"{title}\n{body}\n{labels}"

    ui_terms = ["ui", "screen", "page", "dashboard", "button", "form", "dropdown", "drop down", "select", "selector", "control", "template", "html", "css"]
    backend_terms = ["api", "route", "endpoint", "request", "response", "workflow", "aider", "github", "pr", "pull request", "branch", "session", "token"]
    data_terms = ["database", "sqlite", "index", "storage", "persist", "delete data", "clear", "cache", "embedding"]
    test_terms = ["test", "pytest", "coverage", "assert", "failing test"]
    config_terms = ["config", "env", "ci", "workflow", "github actions", "docker", "requirements", "dependency"]

    ui_needed = _contains_terms(text, ui_terms)
    backend_needed = _contains_terms(text, backend_terms)
    data_needed = _contains_terms(text, data_terms)
    tests_needed = _contains_terms(text, test_terms)
    config_needed = _contains_terms(text, config_terms)
    if any(phrase in text for phrase in ["do not change the repository indexing logic", "do not change indexing logic", "do not change the indexing logic"]):
        data_needed = False

    if ui_needed and (backend_needed or data_needed):
        kind = "full_stack"
    elif ui_needed:
        kind = "frontend_only"
    elif config_needed:
        kind = "config_ci"
    elif data_needed:
        kind = "data_layer"
    elif backend_needed:
        kind = "backend_only"
    elif tests_needed:
        kind = "test_only"
    else:
        kind = "unknown"

    rationale_parts = []
    if ui_needed:
        rationale_parts.append("mentions UI/control/page language")
    if backend_needed:
        rationale_parts.append("mentions backend/API/workflow/branch language")
    if data_needed:
        rationale_parts.append("mentions data/index/storage language")
    if tests_needed:
        rationale_parts.append("mentions tests")
    if config_needed:
        rationale_parts.append("mentions config/CI")
    return IssueScope(
        kind=kind,
        ui_needed=ui_needed,
        backend_needed=backend_needed,
        data_needed=data_needed,
        tests_needed=tests_needed,
        config_needed=config_needed,
        rationale=", ".join(rationale_parts) or "no strong scope signals",
    )


def file_scope(path: str) -> str:
    normalized = path.replace("\\", "/").lower()
    name = Path(normalized).name
    if _looks_like_ui_surface(normalized):
        return "frontend"
    if normalized.startswith(("tests/", "test/")) or "/tests/" in normalized or name.startswith("test_") or ".test." in name:
        return "test"
    if name in {"requirements.txt", "pyproject.toml", "package.json", "dockerfile"} or normalized.startswith((".github/", "config/")):
        return "config"
    if any(term in normalized for term in ["repo_index", "database", "storage", "models", "schema", "migration"]):
        return "data"
    if _looks_like_route_owner(normalized) or normalized.endswith(".py"):
        return "backend"
    return "other"


def _contains_terms(text: str, terms: list[str]) -> bool:
    for term in terms:
        if " " in term:
            if term in text:
                return True
            continue
        if re.search(rf"\b{re.escape(term)}\b", text):
            return True
    return False


def _path_score(path: str, intent: IssueIntent) -> int:
    normalized = path.replace("\\", "/").lower()
    name = Path(normalized).name
    score = 0

    if intent.kind in {"bug", "enhancement"}:
        if _looks_like_ui_surface(normalized):
            score += 34
        if _looks_like_route_owner(normalized):
            score += 24
        if normalized.startswith(("tests/", "test/")) or "/tests/" in normalized:
            score += 28
        if _looks_like_package_source(normalized):
            score += 58
        if name.startswith("test_") or name.endswith("_test.py") or ".test." in name:
            score += 24
        if normalized.startswith(("docs/", "docs_src/", "examples/", "example/")) or "/docs_src/" in normalized:
            score -= 70
        if "tutorial" in normalized or "example" in normalized:
            score -= 35
    elif intent.kind == "docs":
        if normalized.startswith(("docs/", "docs_src/")) or "/docs/" in normalized:
            score += 55
        if normalized.endswith((".md", ".rst")):
            score += 35
    else:
        if _looks_like_package_source(normalized):
            score += 20
        if normalized.startswith(("tests/", "test/")) or "/tests/" in normalized:
            score += 15

    if normalized.endswith(".py"):
        score += 12
    if name in {"__init__.py", "main.py", "core.py"}:
        score += 8
    if normalized.endswith((".md", ".rst")) and intent.kind != "docs":
        score -= 35
    return score


def _looks_like_package_source(path: str) -> bool:
    if not path.endswith(".py"):
        return False
    first = path.split("/", 1)[0]
    if first in {"docs", "docs_src", "examples", "example", "tests", "test", "scripts"}:
        return False
    return "/" in path or first.endswith(".py")


def _looks_like_ui_surface(path: str) -> bool:
    return (
        "/templates/" in path
        or path.startswith("templates/")
        or path.endswith((".html", ".jinja", ".j2", ".jsx", ".tsx", ".css"))
    )


def _looks_like_route_owner(path: str) -> bool:
    name = Path(path).name
    return name in {"app.py", "routes.py", "views.py", "server.py"} or "/routes/" in path or "/views/" in path
