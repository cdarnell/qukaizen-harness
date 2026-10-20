"""Ledger — every run leaves a line with a hash. If it isn't in the ledger, it didn't happen.

Append-only JSON lines. Each entry carries the hash of the previous entry,
so the ledger is a chain: a line removed or edited breaks every line after
it. The file is the record; nothing else is.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Iterator, Mapping
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

GENESIS = "0" * 64


@dataclass(frozen=True, slots=True)
class Entry:
    ts: float
    resident: str
    trigger: str
    tool: str | None
    outcome: str  #: "acted" | "flagged" | "idle" | "error"
    detail: Mapping[str, Any] = field(default_factory=dict)
    prev: str = GENESIS
    sha256: str = ""

    def body(self) -> dict[str, Any]:
        d = asdict(self)
        d.pop("sha256")
        return d

    def computed_hash(self) -> str:
        canon = json.dumps(self.body(), sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(canon.encode()).hexdigest()


class Ledger:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.touch(exist_ok=True)
        self._head = self._last_hash()

    @property
    def head(self) -> str:
        return self._head

    def record(
        self,
        *,
        resident: str,
        trigger: str,
        tool: str | None,
        outcome: str,
        detail: Mapping[str, Any] | None = None,
    ) -> Entry:
        draft = Entry(
            ts=time.time(),
            resident=resident,
            trigger=trigger,
            tool=tool,
            outcome=outcome,
            detail=dict(detail or {}),
            prev=self._head,
        )
        entry = Entry(**{**draft.body(), "sha256": draft.computed_hash()})
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(asdict(entry), sort_keys=True, default=str) + "\n")
        self._head = entry.sha256
        return entry

    def entries(self) -> Iterator[Entry]:
        with self.path.open(encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    yield Entry(**json.loads(line))

    def verify(self) -> bool:
        """True if every line hashes to itself and chains to the one before."""
        prev = GENESIS
        for e in self.entries():
            if e.prev != prev or e.computed_hash() != e.sha256:
                return False
            prev = e.sha256
        return True

    def _last_hash(self) -> str:
        last = GENESIS
        for e in self.entries():
            last = e.sha256
        return last
