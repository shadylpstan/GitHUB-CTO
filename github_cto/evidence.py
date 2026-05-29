from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable


ContentFetcher = Callable[[str], str | None]


@dataclass(frozen=True)
class EvidenceHit:
    path: str
    score: int
    reason: str


def evidence_rank(paths: list[str], issue_text: str, fetch_content: ContentFetcher, max_files: int = 120) -> list[EvidenceHit]:
    terms = _issue_terms(issue_text)
    domain_terms = _domain_terms(terms)
    issue_roles = _issue_roles(issue_text)
    hits: list[EvidenceHit] = []

    for path in paths[:max_files]:
        content = fetch_content(path)
        if not content:
            continue
        normalized_content = content.lower()
        normalized_path = path.lower()
        file_roles = _file_roles(path, normalized_content)
        score = 0
        reasons: list[str] = []

        content_term_hits = [term for term in terms if term in normalized_content]
        if content_term_hits:
            score += min(len(content_term_hits), 8) * 10
            reasons.append(f"content matches issue terms: {', '.join(content_term_hits[:5])}")

        path_term_hits = [term for term in terms if term in normalized_path and term not in content_term_hits]
        if path_term_hits:
            score += min(len(path_term_hits), 4) * 2
            reasons.append(f"path weakly matches issue terms: {', '.join(path_term_hits[:3])}")

        domain_hits = [term for term in domain_terms if term in normalized_content]
        if domain_hits:
            score += min(len(domain_hits), 5) * 16
            reasons.append(f"shares domain language in content: {', '.join(domain_hits[:5])}")

        role_overlap = sorted(issue_roles & file_roles)
        if role_overlap:
            score += len(role_overlap) * 24
            reasons.append(f"matches requested file role: {', '.join(role_overlap)}")

        if "ui_surface" in issue_roles and "ui_control_owner" in file_roles and domain_hits:
            score += 34
            reasons.append("owns an existing UI control for the same domain")

        if "route_surface" in issue_roles and "route_owner" in file_roles and domain_hits:
            score += 30
            reasons.append("owns an existing route for the same domain")

        if "data_operation" in issue_roles and "data_access" in file_roles and domain_hits:
            score += 26
            reasons.append("owns data/index operation code for the same domain")

        if score > 0:
            hits.append(EvidenceHit(path=path, score=score, reason="; ".join(reasons)))

    hits.sort(key=lambda hit: hit.score, reverse=True)
    return hits


def _issue_terms(issue_text: str) -> list[str]:
    stop = {
        "there",
        "should",
        "would",
        "could",
        "application",
        "option",
        "once",
        "case",
        "first",
        "place",
        "have",
        "does",
        "want",
        "with",
        "from",
        "that",
        "this",
    }
    words = re.findall(r"[a-zA-Z_/-]{4,}", issue_text.lower())
    terms = []
    for word in words:
        cleaned = word.strip("-_/")
        if cleaned and cleaned not in stop and cleaned not in terms:
            terms.append(cleaned)
    return terms[:24]


def _domain_terms(terms: list[str]) -> list[str]:
    generic_verbs = {
        "add",
        "added",
        "create",
        "delete",
        "remove",
        "update",
        "change",
        "show",
        "hide",
        "click",
        "submit",
        "support",
        "allow",
        "need",
        "needs",
    }
    return [term for term in terms if term not in generic_verbs][:12]


def _issue_roles(issue_text: str) -> set[str]:
    text = issue_text.lower()
    roles: set[str] = set()
    if any(
        term in text
        for term in [
            "button",
            "option",
            "ui",
            "screen",
            "page",
            "show",
            "dashboard",
            "application",
            "dropdown",
            "drop down",
            "select",
            "selector",
            "control",
            "form",
        ]
    ):
        roles.add("ui_surface")
    if any(term in text for term in ["route", "endpoint", "post", "request", "submit", "branch", "pr target"]):
        roles.add("route_surface")
    if any(term in text for term in ["delete", "remove", "clear", "store", "save", "database", "index"]):
        roles.add("data_operation")
    return roles


def _file_roles(path: str, normalized_content: str) -> set[str]:
    normalized = path.replace("\\", "/").lower()
    roles: set[str] = set()
    is_template = "/templates/" in normalized or normalized.startswith("templates/")

    if is_template:
        roles.add("ui_surface")
    if is_template and any(
        term in normalized_content
        for term in ["<form", "<button", "<select", "<option", "type=\"submit\"", "type='submit'", "url_for("]
    ):
        roles.add("ui_control_owner")
    if any(term in normalized_content for term in ["@app.route", "blueprint", "methods=[", "def post", "def get"]):
        roles.add("route_owner")
    if any(term in normalized_content for term in ["sqlite3", "delete from", "insert into", "select ", "update ", "connection.execute"]):
        roles.add("data_access")
    return roles
