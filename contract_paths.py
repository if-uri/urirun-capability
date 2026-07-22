"""Stable paths for the contract descriptors adopted by this prototype."""
from pathlib import Path


CONTRACTS_DIR = Path(__file__).resolve().parent / "contracts"


def contract_path(name: str) -> Path:
    """Return a bundled legacy-contract descriptor by its short name."""
    path = CONTRACTS_DIR / f"{name}.json"
    if not path.is_file():
        raise FileNotFoundError(f"unknown bundled contract: {name}")
    return path
