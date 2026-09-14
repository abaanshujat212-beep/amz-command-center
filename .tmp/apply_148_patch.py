from pathlib import Path

path = Path("services/rules/engine.py")
text = path.read_text()
text = text.replace(
    "from services.rules.query import SCOPE_SOURCES, fetch_candidates\n",
    "from services.rules.freshness import resolve_source_freshness\nfrom services.rules.query import SCOPE_SOURCES, fetch_candidates\n",
)
text = text.replace(
    "    errors: list = field(default_factory=list)\n",
    "    errors: list = field(default_factory=list)\n    source_freshness: dict = field(default_factory=dict)\n",
)
needle = """            s.rules_run += 1
            rows = fetch_candidates(
"""
replacement = """            settled_cutoff = now.date() - dt.timedelta(days=cfg.settlement_lag_days)
            freshness = resolve_source_freshness(
                cur,
                tenant_id=tenant_id,
                scope=rule[\"scope\"],
                now=now,
                settled_cutoff=settled_cutoff,
                max_age_hours=cfg.max_data_age_hours,
            )
            s.source_freshness[rule[\"scope\"]] = freshness.as_dict()
            if not freshness.usable:
                s.blocked[freshness.block_reason] = s.blocked.get(freshness.block_reason, 0) + 1
                continue

            s.rules_run += 1
            rows = fetch_candidates(
"""
if needle not in text:
    raise SystemExit("rule evaluation insertion point not found")
text = text.replace(needle, replacement)
text = text.replace("                through=through,\n", "                through=freshness.data_through,\n", 1)
text = text.replace(
    "                    data_through=through,\n                    data_loaded_at=now,\n",
    "                    data_through=freshness.data_through,\n                    data_loaded_at=freshness.data_loaded_at,\n",
)
text = text.replace(
    "                metrics = {k: v for k, v in row.items() if k != \"matched\"}\n",
    "                metrics = {k: v for k, v in row.items() if k != \"matched\"}\n                metrics[\"source_freshness\"] = freshness.as_dict()\n",
)
text = text.replace(
    "                        through,\n                        json.dumps(metrics, default=str),\n",
    "                        freshness.data_through,\n                        json.dumps(metrics, default=str),\n",
)
path.write_text(text)
