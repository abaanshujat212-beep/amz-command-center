"""Exercise the verifier entry point with PostgreSQL client calls substituted."""
from __future__ import annotations

import importlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "infra" / "scripts"


@pytest.mark.parametrize(
    ("target", "source", "digest_valid", "object_count", "expected"),
    [
        ("drill_scratch", "source", True, 0, ["psql", "pg_restore", "psql"]),
        ("drill_scratch", "source", True, 1, ["psql"]),
        ("drill", "source", True, 0, []),
        ("drill_scratch", "drill_scratch", True, 0, []),
        ("drill_scratch", "source", False, 0, []),
    ],
)
def test_restore_guard(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    target: str,
    source: str,
    digest_valid: bool,
    object_count: int,
    expected: list[str],
) -> None:
    monkeypatch.syspath_prepend(str(SCRIPTS))
    verifier = importlib.import_module("verify_postgres_restore")
    archive = tmp_path / "sample.dump"
    archive.write_bytes(b"synthetic archive fixture")
    globals_file = tmp_path / "globals.sql"
    globals_file.write_bytes(b"-- synthetic roles fixture")
    archive.with_suffix(".manifest.json").write_text(json.dumps({
        "database_name": source,
        "backup_file": archive.name,
        "backup_sha256": verifier.sha256_file(archive) if digest_valid else "bad",
        "globals_file": globals_file.name,
        "globals_sha256": verifier.sha256_file(globals_file),
    }))
    monkeypatch.setenv("RESTORE_DATABASE_URL", f"postgresql://localhost/{target}")
    monkeypatch.setattr(sys, "argv", ["verify_postgres_restore.py", "--backup", str(archive)])
    monkeypatch.setattr(verifier.shutil, "which", lambda name: name)
    calls: list[str] = []

    def run(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        del kwargs
        calls.append(argv[0])
        if len(calls) == 1:
            assert argv[0] == "psql"
            sql = argv[-1]
            assert "('pg_catalog', 'information_schema', 'public', 'pg_toast')" in sql
            assert "where n.nspname = 'public'" in sql
            return subprocess.CompletedProcess(argv, 0, stdout=str(object_count))
        if argv[0] == "pg_restore":
            assert "--exit-on-error" in argv
            assert "--single-transaction" in argv
        return subprocess.CompletedProcess(argv, 0, stdout="1")

    monkeypatch.setattr(verifier, "run_command", run)
    assert verifier.main() == (0 if "pg_restore" in expected else 1)
    assert calls == expected
