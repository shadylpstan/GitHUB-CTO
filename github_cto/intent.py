from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class IssueIntent:
    kind: str
    confidence: float
    rationale: str


def classify_issue_intent(issue: dict[str, Any]) -> IssueIntent:
    title = (issue.get("title") or "").lower()
    body = (issue.get("body") or "").lower()
    labels = " ".join(label.get("name", "").lower() for label in issue.get("labels", []))
    text = f"{title}\n{body}\n{labels}"

    if any(term in text for term in ["documentation", "docs", "readme", "typo", "example text"]):
        return IssueIntent("docs", 0.78, "Issue appears documentation-oriented.")
    if any(term in text for term in ["feature", "enhancement", "add support", "new option", "request"]):
        return IssueIntent("enhancement", 0.72, "Issue asks for new or expanded behavior.")
    if any(term in text for term in ["bug", "error", "fails", "failure", "crash", "regression", "not recognized", "incorrect"]):
        return IssueIntent("bug", 0.84, "Issue describes broken or incorrect behavior.")
    if any(term in labels for term in ["bug", "defect"]):
        return IssueIntent("bug", 0.8, "Issue labels indicate a bug.")
    return IssueIntent("unknown", 0.45, "Issue intent is ambiguous.")


def architectural_rank(paths: list[str], intent: IssueIntent) -> list[str]:
    scored = [(path, _path_score(path, intent)) for path in paths]
    scored.sort(key=lambda item: item[1], reverse=True)
    return [path for path, _ in scored]


def _path_score(path: str, intent: IssueIntent) -> int:
    normalized = path.replace("\\", "/").lower()
    name = Path(normalized).name
    score = 0

    if intent.kind in {"bug", "enhancement"}:
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
