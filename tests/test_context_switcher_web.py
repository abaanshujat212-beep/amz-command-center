from pathlib import Path

ROOT = Path(__file__).parents[1]
OPTIONS = (ROOT / "apps/web/app/api/context/options/route.ts").read_text()
SWITCHER = (ROOT / "apps/web/components/context-switcher.tsx").read_text()
LAYOUT = (ROOT / "apps/web/app/layout.tsx").read_text()


def test_options_are_session_authorized_and_operate_filtered():
    assert "session_memberships($1)" in OPTIONS
    assert "session_workspaces($1)" in OPTIONS
    assert "w.portfolio_enabled && w.can_operate_tenants" in OPTIONS


def test_single_account_fast_path_hides_switcher():
    assert "options.tenants.length <= 1" in SWITCHER
    assert "options.workspaces.length === 0" in SWITCHER


def test_open_account_uses_revalidating_endpoint_and_internal_route():
    assert 'fetch("/api/tenant/select"' in SWITCHER
    assert "returnTo: pathname" in SWITCHER
    assert "router.push(result.returnTo)" in SWITCHER
    assert "ContextSwitcher" in LAYOUT
    assert "currentContext()" in LAYOUT
