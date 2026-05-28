import base64
import mimetypes
from dataclasses import dataclass
from typing import Any

import requests


class GitHubError(RuntimeError):
    pass


@dataclass(frozen=True)
class GitHubRepo:
    owner: str
    name: str

    @classmethod
    def parse(cls, value: str) -> "GitHubRepo":
        normalized = value.strip().removeprefix("https://github.com/").strip("/")
        parts = normalized.split("/")
        if len(parts) < 2 or not parts[0] or not parts[1]:
            raise ValueError("Repository must look like owner/repo or https://github.com/owner/repo")
        return cls(owner=parts[0], name=parts[1])

    @property
    def full_name(self) -> str:
        return f"{self.owner}/{self.name}"


class GitHubClient:
    def __init__(self, token: str, repo: str):
        if not token:
            raise ValueError("GitHub token is required")
        self.repo = GitHubRepo.parse(repo)
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "github-cto-hackathon-app",
            }
        )
        self.base_url = "https://api.github.com"

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        url = f"{self.base_url}{path}"
        response = self.session.request(method, url, timeout=40, **kwargs)
        if response.status_code >= 400:
            message = response.text
            try:
                message = response.json().get("message", message)
            except ValueError:
                pass
            raise GitHubError(f"GitHub API {response.status_code}: {message}")
        if response.status_code == 204:
            return None
        return response.json()

    def current_user(self) -> dict[str, Any]:
        return self._request("GET", "/user")

    def repository(self) -> dict[str, Any]:
        return self._request("GET", f"/repos/{self.repo.full_name}")

    def list_issues(self, state: str = "open", limit: int = 25) -> list[dict[str, Any]]:
        issues = self._request(
            "GET",
            f"/repos/{self.repo.full_name}/issues",
            params={"state": state, "per_page": min(limit, 100), "sort": "updated", "direction": "desc"},
        )
        return [issue for issue in issues if "pull_request" not in issue]

    def get_issue(self, number: int) -> dict[str, Any]:
        return self._request("GET", f"/repos/{self.repo.full_name}/issues/{number}")

    def list_issue_comments(self, number: int) -> list[dict[str, Any]]:
        return self._request("GET", f"/repos/{self.repo.full_name}/issues/{number}/comments")

    def default_branch(self) -> str:
        return self.repository()["default_branch"]

    def get_ref_sha(self, branch: str) -> str:
        ref = self._request("GET", f"/repos/{self.repo.full_name}/git/ref/heads/{branch}")
        return ref["object"]["sha"]

    def create_branch(self, branch: str, from_branch: str | None = None) -> str:
        base_branch = from_branch or self.default_branch()
        sha = self.get_ref_sha(base_branch)
        self._request(
            "POST",
            f"/repos/{self.repo.full_name}/git/refs",
            json={"ref": f"refs/heads/{branch}", "sha": sha},
        )
        return sha

    def get_tree(self, branch: str | None = None, recursive: bool = True) -> list[dict[str, Any]]:
        branch_name = branch or self.default_branch()
        tree = self._request(
            "GET",
            f"/repos/{self.repo.full_name}/git/trees/{branch_name}",
            params={"recursive": "1" if recursive else "0"},
        )
        return tree.get("tree", [])

    def get_file(self, path: str, ref: str | None = None) -> dict[str, Any]:
        payload = self._request(
            "GET",
            f"/repos/{self.repo.full_name}/contents/{path}",
            params={"ref": ref or self.default_branch()},
        )
        if payload.get("encoding") != "base64":
            raise GitHubError(f"Unsupported encoding for {path}")
        content = base64.b64decode(payload["content"]).decode("utf-8", errors="replace")
        return {"path": path, "sha": payload["sha"], "content": content}

    def upsert_file(self, path: str, content: str, branch: str, message: str, sha: str | None = None) -> dict[str, Any]:
        encoded = base64.b64encode(content.encode("utf-8")).decode("ascii")
        payload: dict[str, Any] = {"message": message, "content": encoded, "branch": branch}
        if sha:
            payload["sha"] = sha
        return self._request("PUT", f"/repos/{self.repo.full_name}/contents/{path}", json=payload)

    def create_pull_request(self, branch: str, title: str, body: str, base: str | None = None) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/repos/{self.repo.full_name}/pulls",
            json={"title": title, "head": branch, "base": base or self.default_branch(), "body": body},
        )

    def comment_on_issue(self, number: int, body: str) -> dict[str, Any]:
        return self._request("POST", f"/repos/{self.repo.full_name}/issues/{number}/comments", json={"body": body})


TEXT_EXTENSIONS = {
    ".py",
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".java",
    ".go",
    ".rs",
    ".rb",
    ".php",
    ".cs",
    ".html",
    ".css",
    ".scss",
    ".md",
    ".json",
    ".yaml",
    ".yml",
    ".toml",
    ".ini",
    ".txt",
    ".sql",
    ".sh",
}


def is_probably_text_file(path: str) -> bool:
    guess, _ = mimetypes.guess_type(path)
    if guess and guess.startswith("text/"):
        return True
    return any(path.endswith(ext) for ext in TEXT_EXTENSIONS)
