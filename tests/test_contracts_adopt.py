"""The generic adopter turns EVERY urirun-contract-* package into Capabilities."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from contracts_adopt import adopt_contracts, mini_to_jsonschema  # noqa: E402
from capability import dispatch  # noqa: E402
from openapi import to_openapi  # noqa: E402

GH = Path("/home/tom/github/if-uri")
PKGS = ["capture-click", "filepair", "kvstore", "windowpair"]


def _present(name):
    return (GH / f"urirun-contract-{name}" / "contracts.json").exists()


def test_mini_schema_mapping():
    s = mini_to_jsonschema({"key": "str", "n": "?int", "flag": "const:true"})
    assert s["properties"]["key"] == {"type": "string"}
    assert s["properties"]["n"] == {"type": "integer"}
    assert s["properties"]["flag"] == {"const": True}
    assert s["required"] == ["key", "flag"]  # optional 'n' not required


@pytest.mark.parametrize("name", PKGS)
def test_every_package_adopts_to_working_capabilities(name):
    if not _present(name):
        pytest.skip(f"urirun-contract-{name} not present")
    cj = GH / f"urirun-contract-{name}" / "contracts.json"
    reg = adopt_contracts(cj, scheme="x")
    assert len(reg._caps) >= 1
    for cap in reg._caps.values():
        # typed effect carried over, content-addressed
        assert cap.effect in ("query", "command")
        assert cap.id().startswith("cap-")
        # every capability dispatches (stub replays the golden example)
        ex = cap.examples[0]["input"] if cap.examples else {}
        out = dispatch(reg, cap.uri, ex)
        assert out["ok"], f"{cap.uri}: {out.get('error')}"
    # reversible pairs keep their inverse link
    if name in ("filepair", "windowpair"):
        assert any(c.reversible and c.inverse for c in reg._caps.values()), \
            "reversible contract lost its inverse"
    # OpenAPI generates from the adopted set
    assert len(to_openapi(reg)["paths"]) == len(reg._caps)
