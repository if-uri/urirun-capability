"""Adopt real urirun v2 bindings as Capabilities — observe the model on real data.

Shows the shrunk core interoperates with what already exists: a urirun
`urirun.bindings.v2` registry maps 1:1 onto Capabilities, gains content-addressed
identity + a lockfile, executes for real, and emits events by construction.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from capability import Capability, Registry, Events, dispatch


def adopt_v2(binding: dict) -> Capability:
    """Map one urirun v2 binding -> a Capability (typed effect, one schema, plugin adapter)."""
    uri = binding["uri"]
    # effect: prefer the declared kind; the URL segment is only a hint now
    effect = binding.get("kind") or ("command" if "/command/" in uri else "query")
    adapter, config = "python", {}
    if binding.get("adapter") in ("argv-template", "shell-template") and binding.get("argv"):
        adapter, config = "subprocess", {"argv": binding["argv"]}
    return Capability(
        uri=uri, effect=effect,
        input=binding.get("inputSchema", {}),
        output=binding.get("outputSchema", {}),   # v2 rarely declares this — a gap we can close
        errors=tuple(binding.get("errors", ())),
        adapter=adapter, config=config,
    )


def load_registry(path: Path) -> Registry:
    doc = json.loads(path.read_text())
    reg = Registry()
    for binding in doc.get("bindings", {}).values():
        reg.add(adopt_v2(binding))
    return reg


def main() -> int:
    fixture = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(
        "/home/tom/github/if-uri/urirun-multiplatform-test/fixtures/registry.json")
    reg = load_registry(fixture)

    print("== Adoptowane zdolności (content-addressed):")
    lock = reg.lock()
    for uri, cid in lock.items():
        cap = reg.get(uri)
        print(f"  {cid}  [{cap.effect:<7}] {uri}  (adapter={cap.adapter})")

    print("\n== Realne wykonanie echo przez adapter subprocess:")
    ev = Events()
    out = dispatch(reg, "demo://local/echo/query/text", {"text": "capability-2.0"}, events=ev)
    print("  ok:", out["ok"], "| result:", out.get("result"))
    print("  zdarzenia URI (z definicji):")
    for e in ev.log:
        print(f"    {e['uri']}")

    print("\n== Wykrywanie dryfu przez lockfile:")
    # symuluj zmianę kontraktu (jak zbundlowana przestarzała kopia routera, na którą wpadałem)
    changed = Capability(**{**reg.get("demo://local/echo/query/text").__dict__,
                            "input": {"type": "object", "required": ["text", "lang"]}})
    reg.add(changed)
    for d in reg.drift(lock):
        print(f"  {d['issue'].upper():<8} {d['uri']}"
              + (f"  {d.get('was')} -> {d.get('now')}" if d.get("now") else ""))

    return 0


if __name__ == "__main__":
    sys.exit(main())
