# Local gate checklist

Run this checklist before opening or merging MVP implementation PRs.

## Fast checks

```bash
ruff check .
pytest -q -m "not db"
```

## Database-backed checks

```bash
make up
python -m packages.db.migrate up
python -m packages.db.migrate up  # idempotency gate
python -m packages.db.migrate status
python -m packages.db.seed
pytest -q -m db
```

## Web checks

```bash
cd apps/web
npm install
npm run typecheck
npm run build
```

## Notes

- Fix CI failures on the same PR branch; do not create a separate fix PR.
- Keep each PR small enough that a failed gate has an obvious owner.
- Paste unusual failure logs on the PR before pushing the fix.
