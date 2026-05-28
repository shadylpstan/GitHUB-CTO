# Codex-Native Architecture

GitHub CTO is built around a Codex-style autonomous engineering loop. The Flask app is the command center; the Codex Engineering Manager is the reasoning layer; GitHub is the execution surface.

## Runtime Flow

```text
GitHub issue
  -> Flask intake
  -> Codex triage
  -> GitHub repository scan
  -> SQLite vector index retrieval
  -> Codex context selection
  -> Codex patch proposal
  -> Human review/edit checkpoint
  -> GitHub branch + commits + PR + issue comment
```

## Codex Concepts In The App

- `CodexEngineeringManager`: the code-planning agent that chooses files and drafts patch proposals.
- `codex_timeline`: the visible orchestration trace shown to the user.
- `RepositoryIndex`: local semantic memory for repo chunks with path, SHA, language, and line metadata.
- Proposal review page: the human-in-the-loop checkpoint before any write happens to GitHub.
- GitHub client: the connector-like execution adapter for real GitHub operations.

## Why This Is Codex-Native

- The app treats issues as tasks, not forms.
- It reasons over repository structure before editing code.
- It separates planning from execution.
- It creates reviewable file-level changes instead of opaque output.
- It executes through scoped GitHub operations: branch, commit, PR, and issue comment.

## Honest Boundary

This hackathon version does not call the Codex desktop GitHub plugin directly from Flask. Instead, it implements the same product pattern using:

- Flask for the product shell.
- OpenAI API for Codex-style reasoning and patch generation.
- GitHub REST API for real repository execution.

That makes it demoable today while preserving a clean path to swap the GitHub REST adapter for an official Codex/GitHub connector workflow later.
