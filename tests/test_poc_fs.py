"""Pilot fs migration: descriptors reproduce the real connector, and the nuances are
caught — cross-route reversibility, inverse.args conforming to the inverse input, the
generated manifest matching the real connector's routes."""
from __future__ import annotations

import base64
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from capability import Capability, Registry, dispatch, check_reversibility  # noqa: E402
from projections import to_manifest  # noqa: E402
from flow import run_flow, plan_undo  # noqa: E402
from poc_connector_fs import fs_connector, _W, _D  # noqa: E402

GH = Path("/home/tom/github/if-uri")


def _tmp():
    return Path(tempfile.mkdtemp())


def test_write_delete_restore_roundtrip_on_real_files():
    base = _tmp()
    reg = fs_connector(base)
    payload = {"path": "/note.txt", "bytes_b64": base64.b64encode(b"important").decode()}
    dispatch(reg, _W, payload)
    assert (base / "note.txt").read_bytes() == b"important"
    # delete returns a concrete inverse; the runtime rolls it back
    ran = dispatch(reg, _D, {"path": "/note.txt"})
    assert not (base / "note.txt").exists()
    undo = plan_undo(reg, ran)
    assert undo["uri"] == _W
    dispatch(reg, undo["uri"], undo["payload"])
    assert (base / "note.txt").read_bytes() == b"important"      # restored byte-for-byte


def test_reversibility_gate_accepts_conforming_inverse_args():
    reg = fs_connector(_tmp())
    for uri in (_W, _D):
        r = check_reversibility(reg, reg.get(uri))
        assert r["reversible"] and r["ok"] and r["checked"] == 1


def test_reversibility_gate_catches_a_broken_rollback():
    # NUANCE: delete's inverse must supply bytes_b64 (write-b64 requires it). Drop it ->
    # the rollback would be rejected by the inverse route, and the gate says so.
    reg = fs_connector(_tmp())
    broken = Capability(**{**reg.get(_D).__dict__,
                           "examples": ({"input": {"path": "/a.txt"},
                                         "output": {"inverse": {"uri": _W,
                                                    "args": {"path": "/a.txt"}}}},)})  # no bytes_b64
    r = check_reversibility(reg, broken)
    assert not r["ok"] and r["failures"] and "reject" in r["failures"][0]["why"]


def test_isolation_is_recorded_in_the_descriptor():
    reg = fs_connector(_tmp())
    assert all(c.config.get("isolated") for c in reg._caps.values())   # not lost in migration


def test_generated_manifest_matches_the_real_fs_routes():
    reg = fs_connector(_tmp())
    man = to_manifest(reg, {"id": "fs"})
    generated = set(man["routes"])
    real_mf = next((p for p in (GH / "urirun-connector-fs").rglob("connector.manifest.json")
                    if "/venv/" not in str(p)), None)
    if not real_mf:
        return
    real = set(json.loads(real_mf.read_text()).get("routes", []))
    # every descriptor route exists in the real connector (interop; PoC covers 3 of 5)
    assert generated <= real, generated - real
