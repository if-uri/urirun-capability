"""PoC end-to-end: a whole connector from descriptors — it hashes correctly, the
contract is enforced, and the manifest/OpenAPI are generated (so they can't drift)."""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from capability import dispatch, check_examples  # noqa: E402
from projections import to_manifest, to_openapi  # noqa: E402
from poc_connector_hash import hash_connector  # noqa: E402


def test_connector_hashes_correctly_across_algorithms():
    reg = hash_connector()
    for algo, ref in (("sha256", hashlib.sha256), ("md5", hashlib.md5),
                      ("blake2b", hashlib.blake2b)):
        out = dispatch(reg, f"hash://host/text/query/{algo}", {"text": "hello"})
        assert out["ok"] and out["result"]["hex"] == ref(b"hello").hexdigest()


def test_output_and_input_contracts_are_enforced():
    reg = hash_connector()
    bad = dispatch(reg, "hash://host/text/query/sha256", {})     # missing 'text'
    assert not bad["ok"] and bad["error"]["category"] == "INVALID_ARGUMENT"


def test_examples_conform_for_every_route():
    reg = hash_connector()
    for cap in reg._caps.values():
        r = check_examples(reg, cap)
        assert r["passed"] == r["total"]


def test_manifest_is_generated_and_matches_the_real_connector_uri():
    reg = hash_connector()
    man = to_manifest(reg, {"id": "hash"})
    # generated, not hand-written -> routes ARE the capability uris (drift impossible)
    assert man["routes"] == list(reg._caps)
    # interop: the descriptor produces the real connector's URI form
    assert "hash://host/text/query/sha256" in man["routes"]
    assert len(to_openapi(reg)["paths"]) == len(reg._caps)


def test_the_whole_connector_is_one_small_file_no_sibling_boilerplate():
    # the connector is one module: descriptors + one-line handlers. No hand-maintained
    # contracts.json / manifest.json / toolkit gate ship alongside it — those are the
    # boilerplate the descriptor model removes (they'd be generated on demand).
    here = Path(__file__).resolve().parents[1]
    assert (here / "poc_connector_hash.py").exists()
    for boilerplate in ("poc_connector_hash.contracts.json", "poc_connector_hash.manifest.json"):
        assert not (here / boilerplate).exists()
    loc = (here / "poc_connector_hash.py").read_text().count("\n")
    assert loc < 100                       # 4 working routes + generated manifest/OpenAPI
