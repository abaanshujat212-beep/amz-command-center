# Local gate checklist

Run this checklist before opening or merging MVP implementation PRs.

## Fast checks

```bash
uv sync --locked --extra dev
uv run --locked ruff check .
uv run --locked pytest -q -m "not db"
```

## Database-backed checks

```bash
make up
uv run --locked python -m packages.db.migrate up
uv run --locked python -m packages.db.migrate up  # idempotency gate
uv run --locked python -m packages.db.migrate status
uv run --locked python -m packages.db.seed
uv run --locked pytest -q -m db
```

## Web checks

```bash
cd apps/web
npm ci
npm run typecheck
npm run build
```

## Notes

- Fix CI failures on the same PR branch; do not create a separate fix PR.
- Keep each PR small enough that a failed gate has an obvious owner.
- Paste unusual failure logs on the PR before pushing the fix.
