import json
from pathlib import Path

from qukaizen_harness import Ledger
from qukaizen_harness.ledger import GENESIS


def test_entries_chain_and_verify(tmp_path: Path) -> None:
    led = Ledger(tmp_path / "ledger.jsonl")
    assert led.head == GENESIS
    a = led.record(resident="crew", trigger="change:x", tool="deck@1.0", outcome="acted")
    b = led.record(resident="crew", trigger="schedule", tool=None, outcome="idle")
    assert a.prev == GENESIS and b.prev == a.sha256 and led.head == b.sha256
    assert led.verify()


def test_reopening_continues_the_chain(tmp_path: Path) -> None:
    p = tmp_path / "ledger.jsonl"
    first = Ledger(p).record(resident="r", trigger="t", tool=None, outcome="idle")
    second = Ledger(p)
    assert second.head == first.sha256
    second.record(resident="r", trigger="t", tool=None, outcome="idle")
    assert second.verify() and len(list(second.entries())) == 2


def test_tampering_breaks_verification(tmp_path: Path) -> None:
    p = tmp_path / "ledger.jsonl"
    led = Ledger(p)
    led.record(resident="r", trigger="t", tool="a", outcome="acted")
    led.record(resident="r", trigger="t", tool="b", outcome="acted")
    lines = p.read_text().splitlines()
    row = json.loads(lines[0])
    row["tool"] = "c"  # edit without re-hashing
    lines[0] = json.dumps(row, sort_keys=True)
    p.write_text("\n".join(lines) + "\n")
    assert not Ledger(p).verify()
