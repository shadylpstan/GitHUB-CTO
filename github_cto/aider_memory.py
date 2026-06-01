from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass
class AiderMemory:
    path: Path
    max_lessons: int = 40

    def load(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        if not isinstance(payload, list):
            return []
        return [item for item in payload if isinstance(item, dict)][-self.max_lessons :]

    def relevant(self, issue: dict[str, Any], selected_files: list[str], limit: int = 8) -> list[dict[str, Any]]:
        issue_text = f"{issue.get('title') or ''}\n{issue.get('body') or ''}".lower()
        selected = set(selected_files)
        scored = []
        for lesson in self.load():
            score = 0
            lesson_files = set(lesson.get("files") or [])
            if selected & lesson_files:
                score += 4
            tags = [str(tag).lower() for tag in lesson.get("tags") or []]
            score += sum(1 for tag in tags if tag and tag in issue_text)
            if score:
                scored.append((score, lesson))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [lesson for _, lesson in scored[:limit]]

    def remember(
        self,
        issue: dict[str, Any],
        files: list[str],
        lesson: str,
        source: str,
        tags: list[str] | None = None,
    ) -> None:
        if not lesson.strip():
            return
        lessons = self.load()
        entry = {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "issue_title": issue.get("title", ""),
            "files": files[:12],
            "lesson": lesson.strip()[:2000],
            "source": source,
            "tags": tags or _lesson_tags(issue, files, lesson),
        }
        lessons.append(entry)
        lessons = lessons[-self.max_lessons :]
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(lessons, indent=2), encoding="utf-8")


def _lesson_tags(issue: dict[str, Any], files: list[str], lesson: str) -> list[str]:
    text = f"{issue.get('title') or ''}\n{issue.get('body') or ''}\n{lesson}".lower()
    tags = []
    for tag in [
        "button",
        "form",
        "polling",
        "state",
        "flash",
        "notification",
        "template",
        "route",
        "validation",
        "css",
        "index",
        "rebuild",
        "repo_index",
        "aider",
        "pr",
        "branch",
        "token",
    ]:
        if tag in text:
            tags.append(tag)
    if any(path.endswith(".html") for path in files):
        tags.append("template")
    if any(path.endswith(".py") for path in files):
        tags.append("python")
    return sorted(set(tags))
