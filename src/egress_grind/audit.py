"""Hash-chained audit log. One JSON line per request, never any content.

Each line carries the hash of the line before it, so deleting, reordering or editing a line breaks
the chain from that point on. `verify()` walks the file and reports the first broken line.
The log records what was decided and which entity types were involved, never a value.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
from pathlib import Path

GENESIS = "0" * 64


def _digest(prev: str, record: dict) -> str:
    body = json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256((prev + body).encode()).hexdigest()


class AuditLog:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._lock = threading.Lock()
        self._prev = self._last_hash()

    def _last_hash(self) -> str:
        if not self.path.exists():
            return GENESIS
        last = None
        with self.path.open(encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    last = line
        return json.loads(last)["hash"] if last else GENESIS

    def write(self, **fields) -> str:
        with self._lock:
            record = {"ts": round(time.time(), 3), **fields, "prev": self._prev}
            h = _digest(self._prev, record)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as f:
                f.write(json.dumps({**record, "hash": h}, ensure_ascii=False) + "\n")
            self._prev = h
            return h


def verify(path: str | Path) -> tuple[bool, int | None]:
    """Returns (ok, first_bad_line_number). Line numbers start at 1."""
    prev = GENESIS
    with Path(path).open(encoding="utf-8") as f:
        for n, line in enumerate(f, 1):
            if not line.strip():
                continue
            rec = json.loads(line)
            h = rec.pop("hash", None)
            if rec.get("prev") != prev or _digest(prev, rec) != h:
                return False, n
            prev = h
    return True, None
