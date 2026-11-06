"""Load the frozen v1 manifest without changing its canonical representation."""

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONTRACT_PATH = ROOT / "contracts" / "arena-v1.json"
CONTRACT_SHA256 = "3e6a106d89e05d323d5fe280117d63e937fde6e134e8dda7ae65fcc914eeec80"


def canonical_bytes(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False).encode("utf-8")


def load_contract(path: Path = CONTRACT_PATH) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if hashlib.sha256(canonical_bytes(value)).hexdigest() != CONTRACT_SHA256:
        raise ValueError("Frozen arena-v1 contract digest mismatch")
    return value
