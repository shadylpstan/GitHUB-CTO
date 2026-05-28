# GitHub CTO

Codex-native Engineering Manager for GitHub issues. This Flask app connects to a real GitHub repository, runs a Codex-style issue-to-PR workflow, triages open issues, plans relevant file inspection, generates reviewable code changes, creates a branch, commits files, opens a pull request, and comments back on the issue.

## Features

- Real GitHub REST API integration.
- Server-rendered Flask frontend in the same app.
- Issue severity scoring with P0/P1/P2/P3 prioritization.
- Codex run timeline: intake, triage, repo scan, context selection, patch proposal, human review, GitHub execution.
- Repository file discovery through the GitHub tree API.
- Local SQLite vector index for semantic code discovery with file path, language, line range, SHA, and chunk metadata.
- Codex-style file selection and patch generation, including new files when needed.
- Reviewable diffs and editable proposed file contents before any PR is opened.
- Real branch creation, commits, pull request creation, and issue comments after approval.

## Setup

1. Create a virtual environment.

```powershell
python -m venv .venv
.\\.venv\\Scripts\\Activate.ps1
```

2. Install dependencies.

```powershell
pip install -r requirements.txt
```

3. Create `.env`.

```env
FLASK_SECRET_KEY=change-me
GITHUB_TOKEN=github_pat_or_ghp_token
GITHUB_REPOSITORY=owner/repo
OPENAI_API_KEY=sk-your-key
OPENAI_MODEL=gpt-4.1-mini
```

The GitHub token needs repository contents write access and pull request access. For private repositories, use a fine-grained token scoped to the target repository.

4. Run the app.

```powershell
python app.py
```

Open `http://127.0.0.1:5050`.

If you want a different port:

```powershell
$env:PORT=5051
python app.py
```

## Demo Flow

1. Connect a GitHub repository.
2. Open the dashboard.
3. Click `Rebuild Index` once so Codex can use semantic repository memory.
4. Pick a real GitHub issue.
5. Review severity and selected context files.
6. Click `Ask Codex To Generate Proposal`.
7. Review the Codex timeline, inspect diffs, edit proposed file contents if needed, then approve the run.
8. The app creates a real branch, commits the reviewed changes, opens a PR, and comments on the issue.

## Index Progress And Logs

The repository index rebuild runs in the background. The dashboard polls `/index/status` every second and updates:

- files scanned
- files indexed
- files skipped
- chunks created
- chunks embedded
- current file being processed

Logs are written to:

```text
instance/github_cto.log
```

The index intentionally skips noisy/generated files such as `__pycache__`, `node_modules`, logs, markdown, Excel/doc/PDF files, lockfiles, build folders, and vendor folders. Rebuild the index once after updating the app so the new filters are applied.

## Safety Notes

- The app can modify selected existing files and create new files proposed by Codex.
- You review and can edit every proposed file before the app writes to GitHub.
- The AI is instructed to make minimal changes, but you should demo against a repository where autonomous branches are safe.
- If `OPENAI_API_KEY` is missing, the app can still read and triage GitHub issues, but it will not create autonomous code patches.
