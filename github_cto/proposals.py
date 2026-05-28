import difflib
import json
import uuid
from pathlib import Path
from typing import Any


class ProposalStore:
    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def save(self, proposal: dict[str, Any]) -> str:
        proposal_id = uuid.uuid4().hex
        proposal["id"] = proposal_id
        path = self.root / f"{proposal_id}.json"
        path.write_text(json.dumps(proposal, indent=2), encoding="utf-8")
        return proposal_id

    def load(self, proposal_id: str) -> dict[str, Any]:
        if not proposal_id.isalnum():
            raise ValueError("Invalid proposal id")
        path = self.root / f"{proposal_id}.json"
        if not path.exists():
            raise FileNotFoundError("Proposal not found")
        return json.loads(path.read_text(encoding="utf-8"))

    def update(self, proposal: dict[str, Any]) -> None:
        proposal_id = proposal.get("id", "")
        if not proposal_id.isalnum():
            raise ValueError("Invalid proposal id")
        path = self.root / f"{proposal_id}.json"
        path.write_text(json.dumps(proposal, indent=2), encoding="utf-8")


def unified_diff(path: str, before: str, after: str) -> str:
    before_lines = before.splitlines(keepends=True)
    after_lines = after.splitlines(keepends=True)
    diff = difflib.unified_diff(
        before_lines,
        after_lines,
        fromfile=f"a/{path}",
        tofile=f"b/{path}",
        lineterm="",
    )
    return "".join(diff) or "No text changes."


def structured_diff(path: str, before: str, after: str) -> list[dict[str, str]]:
    raw = unified_diff(path, before, after)
    lines = []
    for line in raw.splitlines():
        if line.startswith("---") or line.startswith("+++"):
            kind = "file"
        elif line.startswith("@@"):
            kind = "hunk"
        elif line.startswith("+"):
            kind = "add"
        elif line.startswith("-"):
            kind = "remove"
        else:
            kind = "context"
        lines.append({"kind": kind, "text": line})
    return lines or [{"kind": "context", "text": "No text changes."}]


def attach_diffs(proposal: dict[str, Any]) -> dict[str, Any]:
    for change in proposal.get("changes", []):
        change["diff"] = unified_diff(
            change["path"],
            change.get("original_content") or "",
            change.get("proposed_content") or "",
        )
        change["diff_lines"] = structured_diff(
            change["path"],
            change.get("original_content") or "",
            change.get("proposed_content") or "",
        )
    return proposal
