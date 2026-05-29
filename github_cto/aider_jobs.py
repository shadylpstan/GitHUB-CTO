from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class AiderJob:
    id: str
    issue_number: int
    read_branch: str = ""
    target_branch: str = ""
    selected_files: list[str] = field(default_factory=list)
    state: str = "queued"
    message: str = "Queued Aider run."
    logs: list[str] = field(default_factory=list)
    error: str = ""
    proposal_id: str = ""
    started_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    finished_at: str = ""


class AiderJobRegistry:
    def __init__(self):
        self._lock = threading.Lock()
        self._jobs: dict[str, AiderJob] = {}

    def create(
        self,
        issue_number: int,
        read_branch: str = "",
        target_branch: str = "",
        selected_files: list[str] | None = None,
    ) -> AiderJob:
        job = AiderJob(
            id=uuid.uuid4().hex,
            issue_number=issue_number,
            read_branch=read_branch,
            target_branch=target_branch,
            selected_files=list(selected_files or []),
        )
        with self._lock:
            self._jobs[job.id] = job
        return job

    def get(self, job_id: str) -> AiderJob:
        with self._lock:
            if job_id not in self._jobs:
                raise KeyError("Aider job not found")
            return self._jobs[job_id]

    def update(self, job_id: str, **kwargs: Any) -> None:
        with self._lock:
            job = self._jobs[job_id]
            for key, value in kwargs.items():
                setattr(job, key, value)

    def append_log(self, job_id: str, message: str) -> None:
        with self._lock:
            job = self._jobs[job_id]
            job.logs.append(message)
            job.logs = job.logs[-120:]
            job.message = message

    def snapshot(self, job_id: str) -> dict[str, Any]:
        job = self.get(job_id)
        with self._lock:
            return {
                "id": job.id,
                "issue_number": job.issue_number,
                "read_branch": job.read_branch,
                "target_branch": job.target_branch,
                "selected_files_count": len(job.selected_files),
                "state": job.state,
                "message": job.message,
                "logs": list(job.logs),
                "error": job.error,
                "proposal_id": job.proposal_id,
                "started_at": job.started_at,
                "finished_at": job.finished_at,
            }
