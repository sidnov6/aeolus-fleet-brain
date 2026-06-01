"""Immutable, tamper-evident audit log (hash-chained append-only JSONL).

Each entry links to the previous via a SHA-256 hash chain, so any retroactive
edit breaks verification — the software analogue of Delta time-travel for this
portfolio build. Captures the full reasoning chain: what was considered, the
alternatives, the confidence, the decision, and who approved it.
"""
from __future__ import annotations

import hashlib
import json

import pandas as pd

from aeolus import config as C

_LOG = C.AUDIT_DIR / "audit_log.jsonl"
GENESIS = "0" * 64


def _now() -> str:
    return pd.Timestamp.now(tz="UTC").isoformat()


def _hash(prev: str, payload: dict) -> str:
    blob = prev + json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode()).hexdigest()


def _last_hash() -> str:
    if not _LOG.exists():
        return GENESIS
    last = GENESIS
    for line in _LOG.read_text().splitlines():
        if line.strip():
            last = json.loads(line)["hash"]
    return last


def append(event_type: str, payload: dict) -> dict:
    prev = _last_hash()
    entry_core = {"timestamp": _now(), "event_type": event_type, "payload": payload,
                  "prev_hash": prev}
    entry = {**entry_core, "hash": _hash(prev, entry_core)}
    with open(_LOG, "a") as fh:
        fh.write(json.dumps(entry, default=str) + "\n")
    return entry


def read_all() -> list[dict]:
    if not _LOG.exists():
        return []
    return [json.loads(l) for l in _LOG.read_text().splitlines() if l.strip()]


def verify_chain() -> dict:
    prev = GENESIS
    entries = read_all()
    for i, e in enumerate(entries):
        core = {k: e[k] for k in ("timestamp", "event_type", "payload", "prev_hash")}
        if e["prev_hash"] != prev or _hash(prev, core) != e["hash"]:
            return {"valid": False, "broken_at": i, "count": len(entries)}
        prev = e["hash"]
    return {"valid": True, "count": len(entries)}


def reset() -> None:
    if _LOG.exists():
        _LOG.unlink()
