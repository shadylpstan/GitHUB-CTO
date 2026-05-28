from dataclasses import dataclass
from typing import Any


SEVERITY_LABELS = {
    "P0": "Production outage or security incident",
    "P1": "User-facing bug or broken critical workflow",
    "P2": "Important bug or degraded behavior",
    "P3": "Low-risk enhancement or maintenance",
}


@dataclass
class TriageResult:
    severity: str
    score: int
    rationale: list[str]
    recommended_action: str


def triage_issue(issue: dict[str, Any], comments: list[dict[str, Any]] | None = None) -> TriageResult:
    comments = comments or []
    title = (issue.get("title") or "").lower()
    body = (issue.get("body") or "").lower()
    labels = [label.get("name", "").lower() for label in issue.get("labels", [])]
    text = " ".join([title, body, " ".join(labels)])

    score = 25
    rationale: list[str] = []

    critical_terms = ["outage", "down", "p0", "security", "breach", "data loss", "cannot login", "payment"]
    high_terms = ["bug", "crash", "exception", "error", "broken", "regression", "500", "timeout"]
    medium_terms = ["slow", "incorrect", "edge case", "failing test", "flaky"]

    if any(term in text for term in critical_terms):
        score += 45
        rationale.append("Issue contains production-critical or security-sensitive language.")
    if any(term in text for term in high_terms):
        score += 25
        rationale.append("Issue appears to describe a user-facing defect or runtime failure.")
    if any(term in text for term in medium_terms):
        score += 12
        rationale.append("Issue contains reliability or correctness indicators.")
    if "bug" in labels:
        score += 12
        rationale.append("GitHub label marks this as a bug.")
    if "good first issue" in labels or "documentation" in labels:
        score -= 10
        rationale.append("Labels suggest lower operational urgency.")
    if len(comments) >= 5:
        score += 8
        rationale.append("Active discussion suggests meaningful impact or ambiguity.")

    score = max(0, min(score, 100))
    if score >= 85:
        severity = "P0"
        action = "Investigate immediately, create a hotfix branch, and request urgent review."
    elif score >= 65:
        severity = "P1"
        action = "Create a focused fix branch, run tests, and open a PR with incident context."
    elif score >= 40:
        severity = "P2"
        action = "Prepare a normal-priority fix PR and include reproduction notes."
    else:
        severity = "P3"
        action = "Queue for planned maintenance or enhancement work."

    if not rationale:
        rationale.append("No high-risk signals found; defaulting to baseline prioritization.")

    return TriageResult(severity=severity, score=score, rationale=rationale, recommended_action=action)
