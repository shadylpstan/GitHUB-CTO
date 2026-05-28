# Hybrid Agent Tools

This project should use the model for planning and deterministic tools for known safe edits.

## Current Deterministic Tool

`delete_repository_index` is now implemented directly in the Flask code:

- `RepositoryIndex.delete_index(repo, branch)` deletes indexed chunks from SQLite.
- `/index/delete` calls that method for the connected repository default branch.
- The dashboard exposes a `Delete Index` button next to `Rebuild Index`.

## Why This Pattern

The model can identify intent and relevant files, but model-generated unified diffs were unreliable for exact application. For repeatable product operations, the app should invoke a safe edit/tool path rather than asking the model to produce patch text.

Recommended loop:

```text
Issue -> model identifies intent -> app chooses deterministic tool -> tool edits safely -> tests/review -> PR
```

The experimental iterative patch UI is hidden from the issue screen while this safer path is developed.
