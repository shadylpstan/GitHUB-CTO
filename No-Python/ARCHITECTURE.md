# Codex-Native Architecture

The No-Python version removes the Flask command center and uses GitHub as the entire product surface.

## Core Loop

```text
Issue trigger
  -> GitHub Actions runner
  -> local checkout inspection
  -> deterministic triage and file ranking
  -> OpenAI patch generation
  -> branch commit
  -> pull request
  -> issue comment
```

## Preserved Prototype Lessons

The Flask prototype had useful product logic that is still present:

- Triage before editing: `src/triage.js` preserves severity and intent classification.
- Context before patching: `src/repoContext.js` ranks files by issue terms, file roles, and source-layout signals.
- Reviewable edits: `src/openaiPlanner.js` requires complete final file contents in structured JSON.
- Human checkpoint: GitHub PR review replaces the dashboard proposal page.
- Scoped execution: the agent writes only to a new branch and comments back with the PR link.

## Intentionally Removed

- Flask routes, sessions, templates, and polling.
- Local SQLite embedding index.
- Browser review UI.
- Server-side approval button.

Those were useful for the demo, but GitHub already has durable equivalents: workflow logs, PR diffs, comments, branch protection, and reviews.

## Safety Boundaries

- The workflow is triggered only by the `codex` label, `@codex fix`, or manual dispatch.
- Edits are committed to a generated `codex/issue-*` branch.
- The agent folder is ignored by default during repository context ranking.
- Tests are configurable with `GH_CTO_TEST_COMMAND`.
- Test failures are reported in the PR body instead of hiding the output.
