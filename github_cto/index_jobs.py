from __future__ import annotations

import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class IndexJobStatus:
    state: str = "idle"
    message: str = "Index has not been started."
    current_file: str = ""
    files_seen: int = 0
    files_indexed: int = 0
    files_skipped: int = 0
    total_files: int = 0
    chunks_created: int = 0
    chunks_embedded: int = 0
    error: str = ""
    started_at: str = ""
    finished_at: str = ""
    repo: str = ""
    branch: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


class IndexJobRegistry:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._status = IndexJobStatus()

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return asdict(self._status)

    def is_running(self) -> bool:
        with self._lock:
            return self._status.state == "running"

    def start(self, repo: str, branch: str) -> None:
        with self._lock:
            self._status = IndexJobStatus(
                state="running",
                message="Starting repository index rebuild...",
                repo=repo,
                branch=branch,
                started_at=_now(),
            )

    def update(self, **kwargs: Any) -> None:
        with self._lock:
            for key, value in kwargs.items():
                if hasattr(self._status, key):
                    setattr(self._status, key, value)
                else:
                    self._status.extra[key] = value

    def finish(self, message: str) -> None:
        with self._lock:
            self._status.state = "complete"
            self._status.message = message
            self._status.finished_at = _now()

    def fail(self, error: str) -> None:
        with self._lock:
            self._status.state = "error"
            self._status.message = "Index rebuild failed."
            self._status.error = error
            self._status.finished_at = _now()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
