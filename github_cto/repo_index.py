import json
import logging
import math
import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import requests

from .github_client import GitHubClient, is_probably_text_file


ProgressCallback = Callable[..., None]
logger = logging.getLogger(__name__)


class RepoIndexError(RuntimeError):
    pass


@dataclass
class IndexStats:
    repo: str
    branch: str
    files: int
    chunks: int
    updated_at: str | None


class OpenAIEmbedder:
    def __init__(self, api_key: str, model: str):
        self.api_key = api_key
        self.model = model

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not self.api_key:
            raise RepoIndexError("OPENAI_API_KEY is required to build or search the repository index.")
        response = requests.post(
            "https://api.openai.com/v1/embeddings",
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            json={"model": self.model, "input": texts},
            timeout=90,
        )
        if response.status_code >= 400:
            raise RepoIndexError(f"OpenAI embeddings API {response.status_code}: {response.text}")
        data = response.json()["data"]
        return [item["embedding"] for item in sorted(data, key=lambda item: item["index"])]


class RepositoryIndex:
    def __init__(self, db_path: str | Path, embedder: OpenAIEmbedder, chunk_lines: int = 80, overlap_lines: int = 12):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.embedder = embedder
        self.chunk_lines = chunk_lines
        self.overlap_lines = overlap_lines
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _init_db(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS chunks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    repo TEXT NOT NULL,
                    branch TEXT NOT NULL,
                    path TEXT NOT NULL,
                    sha TEXT,
                    language TEXT,
                    start_line INTEGER NOT NULL,
                    end_line INTEGER NOT NULL,
                    content TEXT NOT NULL,
                    embedding TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            connection.execute("CREATE INDEX IF NOT EXISTS idx_chunks_repo_branch ON chunks(repo, branch)")
            connection.execute("CREATE INDEX IF NOT EXISTS idx_chunks_path ON chunks(path)")

    def stats(self, repo: str, branch: str) -> IndexStats:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT COUNT(DISTINCT path) AS files, COUNT(*) AS chunks, MAX(updated_at) AS updated_at
                FROM chunks
                WHERE repo = ? AND branch = ?
                """,
                (repo, branch),
            ).fetchone()
        return IndexStats(
            repo=repo,
            branch=branch,
            files=int(row["files"] or 0),
            chunks=int(row["chunks"] or 0),
            updated_at=row["updated_at"],
        )

    def indexed_files(self, repo: str, branch: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    path,
                    language,
                    COUNT(*) AS chunks,
                    MIN(start_line) AS start_line,
                    MAX(end_line) AS end_line,
                    MAX(updated_at) AS updated_at
                FROM chunks
                WHERE repo = ? AND branch = ?
                GROUP BY path, language
                ORDER BY path
                """,
                (repo, branch),
            ).fetchall()
        return [dict(row) for row in rows]

    def delete_index(self, repo: str, branch: str) -> int:
        connection = self._connect()
        try:
            cursor = connection.execute(
                "DELETE FROM chunks WHERE repo = ? AND branch = ?",
                (repo, branch),
            )
            connection.commit()
            return cursor.rowcount
        finally:
            connection.close()

    def rebuild(
        self,
        github: GitHubClient,
        max_files: int,
        max_file_bytes: int,
        progress: ProgressCallback | None = None,
    ) -> IndexStats:
        if not self.embedder.enabled:
            raise RepoIndexError("OPENAI_API_KEY is required to rebuild the repository index.")

        repo = github.repo.full_name
        branch = github.default_branch()
        self._progress(progress, message="Fetching repository tree...", repo=repo, branch=branch)
        logger.info("Index rebuild started for %s on %s", repo, branch)
        tree = github.get_tree(branch=branch)
        paths = [
            item["path"]
            for item in tree
            if item.get("type") == "blob"
            and should_index_path(item.get("path", ""))
        ][:max_files]
        self._progress(progress, total_files=len(paths), message=f"Found {len(paths)} candidate files.")
        logger.info("Index rebuild candidate files=%s repo=%s", len(paths), repo)

        records: list[dict[str, Any]] = []
        for index, path in enumerate(paths, start=1):
            self._progress(
                progress,
                files_seen=index,
                current_file=path,
                message=f"Reading {path}",
            )
            try:
                file_payload = github.get_file(path, ref=branch)
            except Exception as exc:
                logger.warning("Skipping %s while indexing: %s", path, exc)
                self._progress(progress, files_skipped=index - len({record["path"] for record in records}))
                continue
            content = file_payload["content"]
            if len(content.encode("utf-8")) > max_file_bytes:
                logger.info("Skipping oversized file during index: %s", path)
                self._progress(progress, files_skipped=index - len({record["path"] for record in records}))
                continue
            file_chunks = self._chunk_file(path, file_payload["sha"], content)
            records.extend(file_chunks)
            indexed_files = len({record["path"] for record in records})
            self._progress(
                progress,
                files_indexed=indexed_files,
                files_skipped=index - indexed_files,
                chunks_created=len(records),
                message=f"Chunked {path} into {len(file_chunks)} chunk(s).",
            )

        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as connection:
            connection.execute("DELETE FROM chunks WHERE repo = ? AND branch = ?", (repo, branch))
            embedded_so_far = 0
            for batch in _batched(records, 32):
                self._progress(
                    progress,
                    message=f"Embedding chunks {embedded_so_far + 1}-{min(len(records), embedded_so_far + len(batch))} of {len(records)}...",
                )
                texts = [self._embedding_text(record) for record in batch]
                embeddings = self.embedder.embed(texts)
                for record, embedding in zip(batch, embeddings):
                    connection.execute(
                        """
                        INSERT INTO chunks
                        (repo, branch, path, sha, language, start_line, end_line, content, embedding, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            repo,
                            branch,
                            record["path"],
                            record["sha"],
                            record["language"],
                            record["start_line"],
                            record["end_line"],
                            record["content"],
                            json.dumps(embedding),
                            now,
                        ),
                    )
                embedded_so_far = min(len(records), embedded_so_far + len(batch))
                self._progress(progress, chunks_embedded=embedded_so_far)
        stats = self.stats(repo, branch)
        self._progress(
            progress,
            files_indexed=stats.files,
            chunks_embedded=stats.chunks,
            message=f"Index complete: {stats.files} files, {stats.chunks} chunks.",
        )
        logger.info("Index rebuild complete repo=%s files=%s chunks=%s", repo, stats.files, stats.chunks)
        return stats

    def search(self, repo: str, branch: str, query: str, limit: int = 8) -> list[dict[str, Any]]:
        if not self.embedder.enabled:
            return []
        stats = self.stats(repo, branch)
        if stats.chunks == 0:
            return []
        query_embedding = self.embedder.embed([query])[0]
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT path, language, start_line, end_line, content, embedding
                FROM chunks
                WHERE repo = ? AND branch = ?
                """,
                (repo, branch),
            ).fetchall()

        scored = []
        for row in rows:
            embedding = json.loads(row["embedding"])
            scored.append(
                {
                    "path": row["path"],
                    "language": row["language"],
                    "start_line": row["start_line"],
                    "end_line": row["end_line"],
                    "content": row["content"],
                    "score": _cosine_similarity(query_embedding, embedding),
                }
            )
        scored.sort(key=lambda item: item["score"], reverse=True)
        return scored[:limit]

    def top_paths(self, repo: str, branch: str, query: str, limit: int = 12) -> list[str]:
        chunks = self.search(repo, branch, query, limit=max(limit * 2, 12))
        best_by_path: dict[str, float] = defaultdict(float)
        for chunk in chunks:
            best_by_path[chunk["path"]] = max(best_by_path[chunk["path"]], chunk["score"])
        ranked = sorted(best_by_path.items(), key=lambda item: item[1], reverse=True)
        return [path for path, _ in ranked[:limit]]

    def chunks_for_paths(self, repo: str, branch: str, paths: list[str], max_chunks_per_file: int = 2) -> list[dict[str, Any]]:
        if not paths:
            return []
        placeholders = ",".join("?" for _ in paths)
        with self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT path, sha, language, start_line, end_line, content
                FROM chunks
                WHERE repo = ? AND branch = ? AND path IN ({placeholders})
                ORDER BY path, start_line
                """,
                (repo, branch, *paths),
            ).fetchall()

        by_path: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            by_path[row["path"]].append(dict(row))

        selected = []
        for path in paths:
            selected.extend(by_path.get(path, [])[:max_chunks_per_file])
        return selected

    def _chunk_file(self, path: str, sha: str, content: str) -> list[dict[str, Any]]:
        lines = content.splitlines()
        if not lines:
            return []
        language = _language_for_path(path)
        chunks = []
        step = max(1, self.chunk_lines - self.overlap_lines)
        for start in range(0, len(lines), step):
            end = min(start + self.chunk_lines, len(lines))
            chunk_text = "\n".join(lines[start:end]).strip()
            if chunk_text:
                chunks.append(
                    {
                        "path": path,
                        "sha": sha,
                        "language": language,
                        "start_line": start + 1,
                        "end_line": end,
                        "content": chunk_text,
                    }
                )
            if end >= len(lines):
                break
        return chunks

    def _embedding_text(self, record: dict[str, Any]) -> str:
        return (
            f"path: {record['path']}\n"
            f"language: {record['language']}\n"
            f"lines: {record['start_line']}-{record['end_line']}\n\n"
            f"{record['content']}"
        )

    def _progress(self, progress: ProgressCallback | None, **kwargs: Any) -> None:
        if progress:
            progress(**kwargs)


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    dot = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return dot / (left_norm * right_norm)


def _batched(items: list[dict[str, Any]], size: int) -> list[list[dict[str, Any]]]:
    return [items[index : index + size] for index in range(0, len(items), size)]


def _language_for_path(path: str) -> str:
    suffix = Path(path).suffix.lower().lstrip(".")
    return {
        "py": "python",
        "js": "javascript",
        "jsx": "javascript",
        "ts": "typescript",
        "tsx": "typescript",
        "html": "html",
        "css": "css",
        "md": "markdown",
        "json": "json",
        "yml": "yaml",
        "yaml": "yaml",
    }.get(suffix, suffix or "text")


INDEX_EXTENSIONS = {
    ".py",
    ".txt",
    ".json",
    ".toml",
    ".ini",
    ".cfg",
    ".yaml",
    ".yml",
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".css",
    ".html",
}

SKIP_PARTS = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "node_modules",
    "dist",
    "build",
    "vendor",
    "coverage",
}

SKIP_SUFFIXES = {
    ".lock",
    ".log",
    ".md",
    ".csv",
    ".xls",
    ".xlsx",
    ".doc",
    ".docx",
    ".pdf",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".zip",
}

SKIP_FILENAMES = {
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
}


def should_index_path(path: str) -> bool:
    normalized = path.replace("\\", "/")
    parts = set(normalized.split("/"))
    name = Path(normalized).name
    suffix = Path(normalized).suffix.lower()
    if parts & SKIP_PARTS:
        return False
    if name in SKIP_FILENAMES:
        return False
    if suffix in SKIP_SUFFIXES:
        return False
    return suffix in INDEX_EXTENSIONS and is_probably_text_file(normalized)
