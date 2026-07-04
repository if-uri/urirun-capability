"""Real filepair handlers on the adopted contract — so a reversible flow genuinely
does something (snapshot+delete a file, then restore it) and auto-rollback is real.
"""
from __future__ import annotations

from pathlib import Path

from contracts_adopt import adopt_contracts

FILES: dict[str, str] = {}   # an in-memory 'filesystem'


def _snapshot_delete(path: str) -> dict:
    content = FILES.pop(path, None)          # take a snapshot, then delete
    snapshot = {"path": path, "content": content}
    return {"ok": True, "connector": "fs", "action": "file-snapshot-delete",
            "reversible": True, "snapshot": snapshot,
            # the contract requires the connector to return its own inverse metadata
            "inverse": {"path": "file/command/restore", "args": {"snapshot": snapshot}}}


def _restore(snapshot: dict) -> dict:
    FILES[snapshot["path"]] = snapshot.get("content")   # put it back
    return {"ok": True, "connector": "fs", "action": "file-restore",
            "reversible": True, "restored": True, "path": snapshot["path"],
            "inverse": {"path": "file/command/snapshot-delete",
                        "args": {"path": snapshot["path"]}}}


HANDLERS = {
    "file/command/snapshot-delete": _snapshot_delete,
    "file/command/restore": _restore,
}


def load_filepair(contracts_json: Path | None = None):
    src = contracts_json or Path("/home/tom/github/if-uri/urirun-contract-filepair/contracts.json")
    reg = adopt_contracts(src, scheme="fs", handlers=HANDLERS)
    # relax the auto-derived output schema: real results carry extra fields
    return reg
