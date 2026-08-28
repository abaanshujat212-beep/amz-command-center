# PR batch flow

This repo uses small PRs, but related documentation and helper-command work can be opened as a batch.

## Default flow

1. Create a small branch from `main`.
2. Push one focused change.
3. Open a PR with a clear summary and test notes.
4. If CI fails, push the fix to the same PR branch.
5. Merge only after CI is green.

## Batch flow

Use batch PRs only when the changes are independent and low-risk, such as docs, Makefile helpers, or read-only observability wiring.

Rules:

- Do not stack batch PRs on each other unless the dependency is explicit.
- Avoid touching the same file in multiple batch PRs unless merge order is known.
- Keep implementation and cleanup PRs separate from docs-only PRs.
- Never create a separate PR just to fix CI for an existing PR; fix the existing branch.

## Review checklist

- PR title names the subsystem first.
- Body includes Summary and Notes.
- Linked issue is included when applicable.
- CI failure logs are pasted before a corrective push.
