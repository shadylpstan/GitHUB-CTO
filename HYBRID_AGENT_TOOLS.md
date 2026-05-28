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

## Aider Backend

The Flask app can also hand an issue to Aider:

```text
Issue -> selected files -> isolated temp git workspace -> aider CLI edits files -> Flask captures git diff -> review proposal
```

This avoids asking OpenAI to return perfect JSON patches. Aider owns the file-editing loop; Flask owns review and PR creation.

## Generic Validators

Aider proposals are validated before review. These checks are generic, not issue-specific:

- Python files must parse with `ast`.
- JSON files must parse.
- Jinja templates must compile.
- HTML-like files must not have obviously unbalanced common tags such as `form`, `button`, `section`, or `div`.
- Node/Java syntax checks run when `node` or `javac` are available.
- Proposal content is rejected if it contains merge/search-replace conflict markers or large commented-out replacement blocks.
