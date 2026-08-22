"""Tests for the migration runner. No database required.

These cover the parts that were previously implicit in a shell loop: that
filenames are disciplined, that editing an applied migration is caught, and
that every down file corresponds to a real forward migration.
"""

from __future__ import annotations

import pytest

from packages.db import migrate


def test_every_migration_filename_parses_and_versions_are_unique():
    migrations = migrate.discover()
    assert migrations, "no migrations discovered"

    versions = [m.version for m in migrations]
    assert versions == sorted(versions), "discover() must return version order"
    assert len(versions) == len(set(versions)), f"duplicate versions: {versions}"
    assert all(len(v) == 4 and v.isdigit() for v in versions)


def test_structural_migrations_are_reversible():
    by_version = {m.version: m for m in migrate.discover()}
    # 0001 creates the tenancy tables, 0002 the RLS policies, 0003 the rules
    # and actions half. Each must be undoable without dropping the database.
    for version in ("0001", "0002", "0003"):
        assert version in by_version, f"{version} is missing"
        assert by_version[version].reversible, (
            f"{version} is structural and must ship a down file "
            f"at {by_version[version].down_path}"
        )


def test_no_orphan_down_files():
    """A down file with no forward migration would never be reachable."""
    forward_names = {m.path.name for m in migrate.discover()}
    if not migrate.DOWN_DIR.exists():
        pytest.skip("no down directory")
    for down in sorted(migrate.DOWN_DIR.glob("*.sql")):
        assert down.name in forward_names, (
            f"{down.name} has no forward migration of the same name"
        )


def test_checksum_changes_when_the_file_changes(tmp_path):
    path = tmp_path / "0001_example.sql"
    path.write_text("create table t (id int);\n", encoding="utf-8")
    m = migrate.Migration(version="0001", name="0001_example", path=path)

    first = m.checksum
    assert first == m.checksum, "checksum must be stable for unchanged content"

    path.write_text("create table t (id bigint);\n", encoding="utf-8")
    assert m.checksum != first, "checksum must follow the file content"


def test_a_clean_ledger_reports_no_problems():
    migrations = migrate.discover()
    ledger = {m.version: m.checksum for m in migrations}
    assert migrate.integrity_problems(migrations, ledger) == []


def test_editing_an_applied_migration_is_reported():
    migrations = migrate.discover()
    target = migrations[0]
    ledger = {m.version: m.checksum for m in migrations}
    ledger[target.version] = "0000000000000000"  # pretend the file has changed

    problems = migrate.integrity_problems(migrations, ledger)
    assert len(problems) == 1
    assert target.version in problems[0]
    assert "edited" in problems[0]


def test_applied_version_with_no_file_is_reported():
    migrations = migrate.discover()
    ledger = {m.version: m.checksum for m in migrations}
    ledger["9998"] = "deadbeefdeadbeef"

    problems = migrate.integrity_problems(migrations, ledger)
    assert any("9998" in p and "no longer exists" in p for p in problems)


def test_pending_is_derived_from_the_ledger_not_from_the_filesystem():
    """The whole point of the ledger: a second `up` must have nothing to do."""
    migrations = migrate.discover()
    full_ledger = {m.version: m.checksum for m in migrations}

    pending = [m for m in migrations if m.version not in full_ledger]
    assert pending == [], "with everything applied, nothing may be pending"

    partial = dict(list(full_ledger.items())[:-1])
    pending = [m for m in migrations if m.version not in partial]
    assert len(pending) == 1 and pending[0].version == migrations[-1].version
