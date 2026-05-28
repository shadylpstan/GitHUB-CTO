# GitHub CTO, Codex-Native No-Python Edition

This folder is a Flask-free version of the GitHub CTO prototype. It keeps the lessons from the dashboard demo, but moves the product surface to GitHub itself:

- GitHub issues are the task inbox.
- GitHub Actions is the runner.
- The repository checkout is the working memory.
- OpenAI/Codex-style planning creates reviewable edits.
- Pull requests and issue comments are the review surface.

No Flask server, local dashboard, SQLite index, or Python runtime is required.

## What Changed From The Flask Prototype

| Flask prototype | No-Python version |
| --- | --- |
| Dashboard polls issues | GitHub issue and comment events trigger workflow runs |
| SQLite vector index | Lightweight local file ranking plus optional model selection |
| Review page with editable files | Pull request diff and normal GitHub review |
| Flask session state | GitHub Actions run logs and issue comments |
| GitHub REST adapter in Python | Node scripts using GitHub REST API and local git |
| Approve button | PR review/merge policy |

## Runtime Flow

```text
GitHub issue / @codex fix comment
  -> GitHub Actions workflow
  -> checkout repo
  -> triage issue intent and severity
  -> rank likely files from local checkout
  -> fetch selected context
  -> ask OpenAI for minimal JSON file edits
  -> write files to a new branch
  -> run configured tests
  -> push branch
  -> open PR
  -> comment back on the issue
```

## Setup

Keep the agent implementation in `No-Python`, and make sure the workflow file is committed at the repository root:

```text
.github/workflows/codex-issue-manager.yml
```

GitHub Actions will not discover workflows stored only inside `No-Python/.github/workflows`.

Install dependencies locally if you want to test scripts before pushing:

```powershell
cd No-Python
npm install
```

Add repository secrets:

- `OPENAI_API_KEY`: required for planning and patch generation.
- `GH_CTO_TOKEN`: optional. Use this when the default `GITHUB_TOKEN` cannot create PRs in your repo policy.

Configure repository variables if needed:

- `OPENAI_MODEL`: default `gpt-4.1-mini`.
- `GH_CTO_TEST_COMMAND`: command to run before opening a PR, such as `npm test` or `pytest`. Empty means skip tests.
- `GH_CTO_MAX_FILES`: default `8`.
- `GH_CTO_MAX_FILE_BYTES`: default `80000`.

## Triggering A Run

Add the label `codex` to an open issue, or comment:

```text
@codex fix
```

The workflow will create a branch like:

```text
codex/issue-123-short-title-20260528172011
```

Then it opens a PR titled:

```text
Fix #123: issue title
```

## Safety Model

This version deliberately makes GitHub the human checkpoint:

- The agent only writes to a new branch.
- The PR diff is the review UI.
- Tests can be required by branch protection.
- The issue gets a comment with changed files, test status, and PR link.
- Existing Flask code is untouched.

## Files

- `.github/workflows/codex-issue-manager.yml`: GitHub Actions entrypoint.
- `src/runIssue.js`: orchestrates issue intake, planning, edit application, PR creation, and comments.
- `src/repoContext.js`: local file discovery, filtering, ranking, and context extraction.
- `src/openaiPlanner.js`: model calls and JSON validation.
- `src/github.js`: GitHub REST helpers.
- `src/triage.js`: deterministic severity and intent heuristics copied from the prototype's product lessons.
- `src/commentTemplates.js`: PR and issue comment bodies.
- `prompts/patch-system.md`: the model contract for minimal reviewable edits.

## Migration Notes

The Flask prototype taught three things that remain important here:

1. Context selection matters more than raw repository size.
2. The agent should produce reviewable file-level changes, not opaque prose.
3. The safe execution boundary is branch, commit, PR, and issue comment.

The parts intentionally left behind are the local dashboard, live polling, SQLite embedding progress UI, and browser review screen. GitHub already gives us the durable version of those surfaces.
