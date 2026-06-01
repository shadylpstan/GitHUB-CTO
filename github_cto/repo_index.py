import ast
import json
import logging
import math
import re
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


class OpenAIFileSummarizer:
    def __init__(self, api_key: str, model: str, timeout: int = 45, enabled: bool = True):
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self._enabled = enabled

    @property
    def enabled(self) -> bool:
        return bool(self.api_key and self._enabled)

    def summarize(self, path: str, language: str, facts: str, content: str) -> dict[str, Any]:
        if not self.enabled:
            return {"summary": "", "keywords": []}
        trimmed = content[:12000]
        try:
            response = requests.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                json={
                    "model": self.model,
                    "temperature": 0.1,
                    "response_format": {"type": "json_object"},
                    "messages": [
                        {
                            "role": "system",
                            "content": (
                                "Summarize code file responsibility for repository search. "
                                "Return JSON with keys summary and keywords. "
                                "summary must be one concise sentence about what behavior this file owns. "
                                "keywords must be 5-12 short phrases grounded in the code. Do not invent behavior."
                            ),
                        },
                        {
                            "role": "user",
                            "content": (
                                f"path: {path}\n"
                                f"language: {language}\n\n"
                                f"deterministic facts:\n{facts or 'none'}\n\n"
                                f"content:\n{trimmed}"
                            ),
                        },
                    ],
                },
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            logger.warning("File metadata summary request failed for %s: %s", path, exc)
            return {"summary": "", "keywords": []}
        if response.status_code >= 400:
            logger.warning("File metadata summary failed for %s: %s", path, response.text[:500])
            return {"summary": "", "keywords": []}
        try:
            payload = json.loads(response.json()["choices"][0]["message"]["content"])
        except Exception as exc:
            logger.warning("File metadata summary parse failed for %s: %s", path, exc)
            return {"summary": "", "keywords": []}
        keywords = payload.get("keywords", [])
        if not isinstance(keywords, list):
            keywords = []
        return {
            "summary": str(payload.get("summary") or "")[:600],
            "keywords": [str(item)[:80] for item in keywords[:12]],
        }


class RepositoryIndex:
    def __init__(
        self,
        db_path: str | Path,
        embedder: OpenAIEmbedder,
        chunk_lines: int = 80,
        overlap_lines: int = 12,
        file_summarizer: OpenAIFileSummarizer | None = None,
    ):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.embedder = embedder
        self.file_summarizer = file_summarizer
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
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS file_metadata (
                    repo TEXT NOT NULL,
                    branch TEXT NOT NULL,
                    path TEXT NOT NULL,
                    sha TEXT,
                    language TEXT,
                    facts TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    keywords TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (repo, branch, path)
                )
                """
            )
            connection.execute("CREATE INDEX IF NOT EXISTS idx_file_metadata_repo_branch ON file_metadata(repo, branch)")

    def stats(self, repo: str, branch: str) -> IndexStats:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT
                    (SELECT COUNT(DISTINCT path) FROM file_metadata WHERE repo = ? AND branch = ?) AS files,
                    (SELECT COUNT(*) FROM chunks WHERE repo = ? AND branch = ?) AS chunks,
                    MAX(updated_at) AS updated_at
                FROM (
                    SELECT updated_at FROM chunks WHERE repo = ? AND branch = ?
                    UNION ALL
                    SELECT updated_at FROM file_metadata WHERE repo = ? AND branch = ?
                )
                """,
                (repo, branch, repo, branch, repo, branch, repo, branch),
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
                    metadata.path,
                    metadata.language,
                    COUNT(chunks.id) AS chunks,
                    MIN(chunks.start_line) AS start_line,
                    MAX(chunks.end_line) AS end_line,
                    MAX(COALESCE(chunks.updated_at, metadata.updated_at)) AS updated_at
                FROM file_metadata metadata
                LEFT JOIN chunks
                    ON chunks.repo = metadata.repo
                    AND chunks.branch = metadata.branch
                    AND chunks.path = metadata.path
                WHERE metadata.repo = ? AND metadata.branch = ?
                GROUP BY metadata.path, metadata.language
                ORDER BY metadata.path
                """,
                (repo, branch),
            ).fetchall()
        return [dict(row) for row in rows]

    def metadata_for_paths(self, repo: str, branch: str, paths: list[str]) -> dict[str, dict[str, Any]]:
        if not paths:
            return {}
        placeholders = ",".join("?" for _ in paths)
        with self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT path, language, facts, summary, keywords
                FROM file_metadata
                WHERE repo = ? AND branch = ? AND path IN ({placeholders})
                """,
                (repo, branch, *paths),
            ).fetchall()
        return {row["path"]: dict(row) for row in rows}

    def metadata_text_for_paths(self, repo: str, branch: str, paths: list[str]) -> dict[str, str]:
        metadata = self.metadata_for_paths(repo, branch, paths)
        return {path: _metadata_search_text(item) for path, item in metadata.items()}

    def delete_index(self, repo: str, branch: str) -> int:
        connection = self._connect()
        try:
            cursor = connection.execute(
                "DELETE FROM chunks WHERE repo = ? AND branch = ?",
                (repo, branch),
            )
            connection.execute("DELETE FROM file_metadata WHERE repo = ? AND branch = ?", (repo, branch))
            connection.commit()
            return cursor.rowcount
        finally:
            connection.close()

    def rebuild(
        self,
        github: GitHubClient,
        max_files: int,
        max_file_bytes: int,
        branch: str | None = None,
        progress: ProgressCallback | None = None,
    ) -> IndexStats:
        if not self.embedder.enabled:
            raise RepoIndexError("OPENAI_API_KEY is required to rebuild the repository index.")

        repo = github.repo.full_name
        branch = branch or github.default_branch()
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
        metadata_records: list[dict[str, Any]] = []
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
            language = _language_for_path(path)
            metadata = self._file_metadata(repo, branch, path, file_payload["sha"], language, content)
            metadata_records.append(metadata)
            if len(content.encode("utf-8")) > max_file_bytes:
                logger.info("Indexing metadata only for oversized file: %s", path)
                metadata_files = len({record["path"] for record in metadata_records})
                self._progress(
                    progress,
                    files_indexed=metadata_files,
                    files_skipped=index - metadata_files,
                    chunks_created=len(records),
                    message=f"Captured metadata for oversized file {path}.",
                )
                continue
            metadata_text = _metadata_search_text(metadata)
            file_chunks = self._chunk_file(path, file_payload["sha"], content, metadata_text=metadata_text)
            records.extend(file_chunks)
            indexed_files = len({record["path"] for record in metadata_records})
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
            connection.execute("DELETE FROM file_metadata WHERE repo = ? AND branch = ?", (repo, branch))
            for metadata in metadata_records:
                connection.execute(
                    """
                    INSERT INTO file_metadata
                    (repo, branch, path, sha, language, facts, summary, keywords, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        repo,
                        branch,
                        metadata["path"],
                        metadata["sha"],
                        metadata["language"],
                        metadata["facts"],
                        metadata["summary"],
                        json.dumps(metadata["keywords"]),
                        now,
                    ),
                )
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
            best_by_path[chunk["path"]] = max(best_by_path[chunk["path"]], chunk["score"] * 0.65)
        for item in self.metadata_search(repo, branch, query):
            best_by_path[item["path"]] = best_by_path[item["path"]] + item["score"]
        ranked = sorted(best_by_path.items(), key=lambda item: item[1], reverse=True)
        return [path for path, _ in ranked[:limit]]

    def metadata_search(self, repo: str, branch: str, query: str) -> list[dict[str, Any]]:
        terms = _query_terms(query)
        if not terms:
            return []
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT path, language, facts, summary, keywords
                FROM file_metadata
                WHERE repo = ? AND branch = ?
                """,
                (repo, branch),
            ).fetchall()
        scored = []
        for row in rows:
            text = _metadata_search_text(dict(row)).lower()
            score = 0.0
            exact_hits = [term for term in terms if term in text]
            if exact_hits:
                score += len(exact_hits) * 0.18
            for phrase in _query_phrases(query):
                if phrase in text:
                    score += 0.24
            if "route" in terms and "flask routes:" in text:
                score += 0.35
            if "page" in terms and ("renders templates:" in text or "jinja blocks:" in text):
                score += 0.22
            if "job" in terms and ("job" in text or "aider" in text):
                score += 0.20
            if score > 0:
                scored.append({"path": row["path"], "score": score, "reason": f"metadata matched {len(exact_hits)} issue term(s)"})
        scored.sort(key=lambda item: item["score"], reverse=True)
        return scored

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

    def _file_metadata(self, repo: str, branch: str, path: str, sha: str, language: str, content: str) -> dict[str, Any]:
        facts = extract_file_facts(path, content)
        cached = self._cached_metadata(repo, branch, path, sha)
        if cached:
            return cached
        ai_summary = {"summary": "", "keywords": []}
        if self.file_summarizer and self.file_summarizer.enabled:
            ai_summary = self.file_summarizer.summarize(path, language, facts, content)
        return {
            "path": path,
            "sha": sha,
            "language": language,
            "facts": facts,
            "summary": ai_summary.get("summary", ""),
            "keywords": ai_summary.get("keywords", []),
        }

    def _cached_metadata(self, repo: str, branch: str, path: str, sha: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT path, sha, language, facts, summary, keywords
                FROM file_metadata
                WHERE repo = ? AND branch = ? AND path = ? AND sha = ?
                """,
                (repo, branch, path, sha),
            ).fetchone()
        if not row:
            return None
        result = dict(row)
        try:
            result["keywords"] = json.loads(result.get("keywords") or "[]")
        except Exception:
            result["keywords"] = []
        return result

    def _chunk_file(self, path: str, sha: str, content: str, metadata_text: str = "") -> list[dict[str, Any]]:
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
                        "metadata_text": metadata_text,
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
            f"{record.get('metadata_text', '')}\n\n"
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


def extract_file_facts(path: str, content: str) -> str:
    normalized = path.replace("\\", "/").lower()
    if normalized.endswith(".py"):
        return _python_facts(content)
    if normalized.endswith((".html", ".jinja", ".j2")):
        return _template_facts(content)
    if normalized.endswith((".js", ".jsx", ".ts", ".tsx")):
        return _script_facts(content)
    return _generic_facts(content)


def _python_facts(content: str) -> str:
    facts: list[str] = []
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return _generic_facts(content)
    imports: list[str] = []
    functions: list[str] = []
    classes: list[str] = []
    routes: list[str] = []
    templates: list[str] = []
    endpoints: list[str] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            imports.extend(f"{module}.{alias.name}".strip(".") for alias in node.names)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            functions.append(node.name)
            for decorator in node.decorator_list:
                route = _route_from_decorator(decorator)
                if route:
                    routes.append(f"{node.name}: {route}")
        elif isinstance(node, ast.ClassDef):
            classes.append(node.name)
        elif isinstance(node, ast.Call):
            call_name = _call_name(node.func)
            if call_name == "render_template" and node.args and isinstance(node.args[0], ast.Constant):
                templates.append(str(node.args[0].value))
            elif call_name == "url_for" and node.args and isinstance(node.args[0], ast.Constant):
                endpoints.append(str(node.args[0].value))

    if imports:
        facts.append("imports: " + ", ".join(_unique(imports)[:24]))
    if classes:
        facts.append("classes: " + ", ".join(_unique(classes)[:24]))
    if functions:
        facts.append("functions: " + ", ".join(_unique(functions)[:60]))
    if routes:
        facts.append("flask routes: " + ", ".join(_unique(routes)[:32]))
    if templates:
        facts.append("renders templates: " + ", ".join(_unique(templates)[:24]))
    if endpoints:
        facts.append("url_for endpoints: " + ", ".join(_unique(endpoints)[:24]))
    return "\n".join(facts)


def _route_from_decorator(node: ast.AST) -> str:
    if not isinstance(node, ast.Call):
        return ""
    name = _call_name(node.func)
    if not name.endswith(".route") and name != "route":
        return ""
    route = ""
    if node.args and isinstance(node.args[0], ast.Constant):
        route = str(node.args[0].value)
    methods = []
    for keyword in node.keywords:
        if keyword.arg == "methods" and isinstance(keyword.value, (ast.List, ast.Tuple)):
            methods = [str(item.value) for item in keyword.value.elts if isinstance(item, ast.Constant)]
    return f"{route} methods={methods or ['GET']}"


def _call_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _call_name(node.value)
        return f"{parent}.{node.attr}" if parent else node.attr
    return ""


def _template_facts(content: str) -> str:
    facts = []
    blocks = re.findall(r"{%\s*block\s+([a-zA-Z_][\w-]*)", content)
    extends = re.findall(r"{%\s*extends\s+[\"']([^\"']+)", content)
    includes = re.findall(r"{%\s*include\s+[\"']([^\"']+)", content)
    url_for = re.findall(r"url_for\([\"']([^\"']+)", content)
    forms = re.findall(r"<form[^>]+action=\"?{{\s*url_for\([\"']([^\"']+)", content)
    ids = re.findall(r"\sid=[\"']([^\"']+)", content)
    buttons = re.findall(r"<button[^>]*>(.*?)</button>", content, flags=re.DOTALL)
    if extends:
        facts.append("extends: " + ", ".join(_unique(extends)))
    if includes:
        facts.append("includes: " + ", ".join(_unique(includes)))
    if blocks:
        facts.append("jinja blocks: " + ", ".join(_unique(blocks)))
    if url_for:
        facts.append("url_for endpoints: " + ", ".join(_unique(url_for)[:32]))
    if forms:
        facts.append("form actions: " + ", ".join(_unique(forms)[:24]))
    if ids:
        facts.append("element ids: " + ", ".join(_unique(ids)[:32]))
    if buttons:
        labels = [re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", item)).strip() for item in buttons]
        labels = [label for label in labels if label]
        facts.append("button labels: " + ", ".join(_unique(labels)[:16]))
    return "\n".join(facts)


def _script_facts(content: str) -> str:
    facts = []
    imports = re.findall(r"import\s+(?:[^'\";]+?\s+from\s+)?[\"']([^\"']+)", content)
    exports = re.findall(r"export\s+(?:default\s+)?(?:function|class|const|let|var)\s+([A-Za-z_$][\w$]*)", content)
    functions = re.findall(r"(?:function\s+|const\s+|let\s+|var\s+)([A-Za-z_$][\w$]*)\s*(?:=|\()", content)
    selectors = re.findall(r"getElementById\([\"']([^\"']+)", content)
    if imports:
        facts.append("imports: " + ", ".join(_unique(imports)[:24]))
    if exports:
        facts.append("exports: " + ", ".join(_unique(exports)[:24]))
    if functions:
        facts.append("functions/constants: " + ", ".join(_unique(functions)[:40]))
    if selectors:
        facts.append("dom ids: " + ", ".join(_unique(selectors)[:24]))
    return "\n".join(facts)


def _generic_facts(content: str) -> str:
    matches = re.findall(r"\b(?:class|def|function|route|url_for|render_template|import)\b[^\n]{0,120}", content)
    return "notable lines: " + " | ".join(matches[:20]) if matches else ""


def _metadata_search_text(metadata: dict[str, Any]) -> str:
    keywords = metadata.get("keywords") or []
    if isinstance(keywords, str):
        try:
            keywords = json.loads(keywords)
        except Exception:
            keywords = [keywords]
    return (
        "# File responsibility metadata\n"
        f"purpose: {metadata.get('summary') or ''}\n"
        f"keywords: {', '.join(str(item) for item in keywords[:12])}\n"
        f"facts:\n{metadata.get('facts') or ''}"
    ).strip()


def _query_terms(query: str) -> list[str]:
    stop = {
        "about",
        "after",
        "before",
        "branch",
        "change",
        "display",
        "enhance",
        "issue",
        "should",
        "show",
        "that",
        "this",
        "when",
        "which",
        "with",
    }
    terms = []
    for term in re.findall(r"[a-zA-Z_][a-zA-Z0-9_/-]{2,}", query.lower()):
        cleaned = term.strip("-_/")
        if cleaned and cleaned not in stop and cleaned not in terms:
            terms.append(cleaned)
    return terms[:32]


def _query_phrases(query: str) -> list[str]:
    words = _query_terms(query)
    phrases = []
    for size in (3, 2):
        for index in range(0, max(0, len(words) - size + 1)):
            phrases.append(" ".join(words[index : index + size]))
    return phrases[:24]


def _unique(items: list[str]) -> list[str]:
    seen = set()
    unique = []
    for item in items:
        item = item.strip()
        if item and item not in seen:
            unique.append(item)
            seen.add(item)
    return unique


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
    "npm",
    "dist",
    "build",
    "vendor",
    "coverage",
    "env",
    "environment",
    "config",
    "configs",
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
    ".env",
    ".env.example",
    ".ini",
    ".toml",
    ".cfg",
    ".conf",
    ".bak",
}

SKIP_FILENAMES = {
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    ".env",
    ".env.example",
    "config.yaml",
    "config.yml",
    "config.json",
    "environment.yml",
    "environment.yaml",
    "environment.json",
    "settings.json",
    "settings.yaml",
    "settings.yml",
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
