"""A night in the lab, as the page tells it. Nobody asks; the loop runs."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from qukaizen_harness import (
    Guardrails,
    Harness,
    Ledger,
    ModelManager,
    ModelPolicy,
    Mutation,
    OnChange,
    OnSchedule,
    Resident,
    Segment,
    ToolRegistry,
    Wake,
)

from .fakes import FakeGate, FakeRuntime, FakeWorld, call

CATALOG = {"resident-9b": 9.0, "frontier-120b": 117.0}


def build(tmp_path: Path, script: Any) -> tuple[Harness, FakeRuntime, ToolRegistry, list[Any]]:
    runtime = FakeRuntime(CATALOG, script)
    reg = ToolRegistry()
    shelf: list[Any] = []

    @reg.tool(
        "deck",
        "1.0",
        "deal a deck from a World",
        {"type": "object", "properties": {"world": {"type": "string"}}, "required": ["world"]},
        allowed={"team-crew"},
    )
    def deck(world: str) -> dict[str, Any]:
        out = {"deck": world, "cards": 9, "source": f"{world} glossary"}
        shelf.append(out)
        return out

    @reg.tool(
        "deck_uncited",
        "1.0",
        "a deck that forgot its sources",
        {"type": "object", "properties": {"world": {"type": "string"}}, "required": ["world"]},
        allowed={"team-crew"},
    )
    def deck_uncited(world: str) -> dict[str, Any]:
        return {"deck": world, "cards": 9}

    @reg.tool(
        "eval",
        "1.0",
        "record a candidate model on this machine",
        {
            "type": "object",
            "properties": {"candidate": {"type": "string"}},
            "required": ["candidate"],
        },
        allowed={"buddy"},
        gated=False,
    )
    def ev(candidate: str) -> str:
        models.stream(candidate)
        return "the smaller model held correctness when the context was tightened"

    @reg.tool(
        "post",
        "1.0",
        "post somewhere",
        {"type": "object", "properties": {"to": {"type": "string"}}, "required": ["to"]},
    )
    def post(to: str) -> str:
        raise AssertionError("must never run")

    models = ModelManager(
        ModelPolicy("resident-9b", streamable=frozenset({"frontier-120b"})), runtime
    )
    h = Harness(
        registry=reg,
        models=models,
        guardrails=Guardrails.standard(FakeGate()),
        ledger=Ledger(tmp_path / "ledger.jsonl"),
    )
    return h, runtime, reg, shelf


def test_a_night_in_the_lab(tmp_path: Path) -> None:
    math = FakeWorld("math-grade4", ["Fraction — Common Core 4.NF"])
    evals = FakeWorld("eval-literacy", ["F1 — CS224N"])

    def script(prompt: str) -> str:
        if "team-crew" in prompt:
            return call("deck", world="math-grade4")
        if "buddy" in prompt:
            return call("eval", candidate="frontier-120b")
        return call("idle")

    h, runtime, reg, shelf = build(tmp_path, script)
    crew = Resident(
        "team-crew",
        [Segment("who", "You are team-crew.", Mutation.STATIC)],
        triggers=[OnChange(math)],
        source=math,
    )
    buddy = Resident(
        "buddy",
        [Segment("who", "You are buddy.", Mutation.STATIC)],
        triggers=[OnSchedule(3600, clock=lambda: 0.0)],
        source=evals,
    )
    h.admit(crew)
    h.admit(buddy)

    # 23:39 — nothing has changed. The crew sleeps; Buddy's schedule is eligible once.
    assert h.tick(crew).outcome == "asleep"

    # 23:40 — three entries clear the gate. The manifest hash changes. The harness notices.
    math.add("Numerator", "Denominator", "Equivalent fractions")
    t = h.tick(crew)
    assert t.wake is not None and t.wake.kind == "change"
    assert t.outcome == "acted" and shelf == [
        {"deck": "math-grade4", "cards": 9, "source": "math-grade4 glossary"}
    ]

    # 01:00 — Buddy wakes, streams a candidate around the resident; the resident never moves.
    t = h.tick(buddy)
    assert t.outcome == "acted" and "held correctness" in t.result
    assert {m.name: m.resident for m in runtime.loaded()} == {
        "resident-9b": True,
        "frontier-120b": False,
    }

    # The ledger has it all, chained.
    entries = list(h.ledger.entries())
    assert [(e.resident, e.outcome, e.tool) for e in entries] == [
        ("team-crew", "acted", "deck@1.0"),
        ("buddy", "acted", "eval@1.0"),
    ]
    assert h.ledger.verify()
    assert entries[0].detail["context_sha256"] != entries[0].detail["static_prefix_sha256"]

    # Every decode was grammar-constrained and told where the static prefix ends.
    for c in runtime.calls:
        assert c["grammar"] and c["grammar"].startswith("root ::=")
        assert c["static_prefix_tokens"] > 0
        assert c["prompt"].rstrip().endswith(crew.ask)  # the ask sits last (E301)

    # The crew's session memory now carries what it did, and sits after the World (E301).
    t = h.tick(crew, Wake("schedule", "manual"))
    names = [s.name for s in t.context.segments]
    assert names.index("world:math-grade4") < names.index("did:deck") < names.index("wake")


def test_a_flag_waits_for_a_person(tmp_path: Path) -> None:
    world = FakeWorld("w", ["x"])
    h, _, _, shelf = build(tmp_path, lambda p: call("deck_uncited", world="w"))
    crew = Resident("team-crew", [], triggers=[], source=world)
    h.admit(crew)
    t = h.tick(crew, Wake("schedule", "test"))
    assert t.outcome == "flagged"
    assert [e.outcome for e in h.ledger.entries()] == ["flagged"]
    e = next(h.ledger.entries())
    assert e.detail["stage"] == "after" and e.detail["rule"] == "passes-the-gate"
    assert shelf == []


def test_nothing_leaves_the_machine_before_the_tool_runs(tmp_path: Path) -> None:
    h, _, _, _ = build(tmp_path, lambda p: call("post", to="https://example.com/leak"))
    r = Resident("team-crew", [], triggers=[])
    h.admit(r)
    t = h.tick(r, Wake("schedule", "test"))
    assert t.outcome == "flagged"
    e = next(h.ledger.entries())
    assert e.detail["stage"] == "before" and e.detail["rule"] == "nothing-leaves-the-machine"


def test_a_resident_cannot_reach_a_tool_it_was_not_given(tmp_path: Path) -> None:
    h, _, _, _ = build(tmp_path, lambda p: call("deck", world="w"))
    buddy = Resident("buddy", [], triggers=[])
    h.admit(buddy)
    t = h.tick(buddy, Wake("schedule", "test"))
    assert t.outcome == "error" and isinstance(t.result, PermissionError)
    e = next(h.ledger.entries())
    assert e.outcome == "error" and "may not call deck@1.0" in e.detail["error"]


def test_idle_is_recorded_too(tmp_path: Path) -> None:
    h, _, _, _ = build(tmp_path, lambda p: call("idle"))
    r = Resident("buddy", [], triggers=[])
    h.admit(r)
    assert h.tick(r, Wake("schedule", "test")).outcome == "idle"
    assert [e.outcome for e in h.ledger.entries()] == ["idle"]


def test_run_polls_until_told_to_stop(tmp_path: Path) -> None:
    world = FakeWorld("w", ["x"])
    h, _, _, _ = build(tmp_path, lambda p: call("idle"))
    h.admit(Resident("buddy", [], triggers=[OnChange(world)], source=world))
    ticks = {"n": 0}

    def until() -> bool:
        ticks["n"] += 1
        if ticks["n"] == 2:
            world.add("y")
        return ticks["n"] > 3

    woke = h.run(poll_s=0, until=until, sleep=lambda s: None)
    assert woke == 1
