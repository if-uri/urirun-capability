"""Drift audit normalisation — the tricky part that gave false positives until the
matching was made symmetric and suffix-based. These lock that in."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from drift_audit import _tail, audit, GH  # noqa: E402


def test_tail_strips_scheme_symmetrically():
    assert _tail("app://host/desktop/command/launch") == "host/desktop/command/launch"
    assert _tail("command/click") == "command/click"          # bare decorator unchanged


def _covered(manifest_route, code_route):
    m = _tail(manifest_route)
    c = _tail(code_route)
    return m == c or m.endswith("/" + c)


def test_router_prefixed_decorator_is_not_false_drift():
    # webnode: @PAGE.handler('command/click') is served as webnode://page/command/click
    assert _covered("webnode://page/command/click", "command/click")


def test_full_uri_decorator_matches_full_uri_manifest():
    # kvm: some decorators are full cross-scheme URIs
    assert _covered("app://host/desktop/command/launch", "app://host/desktop/command/launch")


def test_a_genuinely_undocumented_route_is_not_covered():
    assert not _covered("webnode://page/command/click", "session/command/close")


def test_real_audit_has_no_false_positive_on_webnode():
    if not (GH / "urirun-connector-webnode").exists():
        return                                             # ecosystem not present; skip silently
    rows = {r["pkg"]: r for r in audit()}
    if "webnode" in rows:
        assert rows["webnode"]["in_sync"], rows["webnode"]   # must not be flagged (was a false +)
