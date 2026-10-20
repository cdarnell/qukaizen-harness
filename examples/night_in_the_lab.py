"""A night in the lab, runnable. No products required.

    python examples/night_in_the_lab.py

Stands up a registry with three tools, a scripted runtime standing in for
QueueLLM, two fake Worlds standing in for DDaC, and two residents — the TEAM
crew (wakes on a World change) and Buddy (wakes on a schedule). Then it adds
three entries to the math World and lets the loop run. Prints the ledger.
"""

from __future__ import annotations

import hashlib
import json
import tempfile
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

from qukaizen_harness import (
    Completion,
    Guardrails,
    Harness,
    Ledger,
    ModelInfo,
    ModelManager,
    ModelPolicy,
    Mutation,
    OnChange,
    OnSchedule,
    Resident,
    Segment,
    ToolRegistry,
)

# -- stand-ins for the products ----------------------------------------------


class ScriptedRuntime:
    """Answers like a well-behaved resident model would, given the grammar."""

    catalog = {"resident-9b": 9.0, "candidate-120b": 117.0}

    def __init__(self) -> None:
        self._loaded: dict[str, ModelInfo] = {}

    def describe(self, model: str) -> ModelInfo:
        return ModelInfo(model, self.catalog[model])

    def load(self, model: str, *, pin: bool = False) -> ModelInfo:
        info = ModelInfo(model, self.catalog[model], resident=pin)
        self._loaded[model] = info
        return info

    def loaded(self) -> Sequence[ModelInfo]:
        return list(self._loaded.values())

    def complete(
        self,
        model: str,
        prompt: str,
        *,
        grammar: str | None = None,
        max_tokens: int = 512,
        static_prefix_tokens: int = 0,
    ) -> Completion:
        if "You are the TEAM crew" in prompt:
            answer = {"tool": "deck", "args": {"world": "math-grade4"}}
        elif "You are Buddy" in prompt:
            answer = {"tool": "eval", "args": {"candidate": "candidate-120b"}}
        else:
            answer = {"tool": "idle", "args": {}}
        return Completion(
            json.dumps(answer),
            usage={"prompt_chars": len(prompt), "static_prefix_chars": static_prefix_tokens},
        )


class World:
    def __init__(self, name: str, entries: Iterable[str]) -> None:
        self.name, self.entries = name, list(entries)

    def manifest_hash(self) -> str:
        return hashlib.sha256(json.dumps(self.entries).encode()).hexdigest()

    def segments(self) -> Iterable[Segment]:
        body = "\n".join(f"- {e}" for e in self.entries)
        yield Segment(
            f"world:{self.name}",
            f"World {self.name}:\n{body}",
            Mutation.WORLD,
            source_hash=self.manifest_hash(),
        )


class Gate:
    def check(self, artifact: Any) -> Sequence[str]:
        if isinstance(artifact, dict) and artifact.get("source"):
            return []
        return ["entry does not cite its origin"]


# -- the harness ---------------------------------------------------------------


def main() -> None:
    runtime = ScriptedRuntime()
    policy = ModelPolicy("resident-9b", streamable=frozenset({"candidate-120b"}))
    models = ModelManager(policy, runtime)
    reg = ToolRegistry()
    shelf: list[dict[str, Any]] = []

    @reg.tool(
        "deck",
        "1.0",
        "deal a flash-card deck from a World",
        {"type": "object", "properties": {"world": {"type": "string"}}, "required": ["world"]},
        allowed={"team-crew"},
    )
    def deck(world: str) -> dict[str, Any]:
        out = {"deck": world, "cards": 9, "source": f"{world} glossary"}
        shelf.append(out)
        return out

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

    math = World("math-grade4", ["Fraction — Common Core 4.NF.1"])
    evals = World("eval-literacy", ["F1 — CS224N"])

    with tempfile.TemporaryDirectory() as tmp:
        ledger = Ledger(Path(tmp) / "ledger.jsonl")
        h = Harness(
            registry=reg, models=models, guardrails=Guardrails.standard(Gate()), ledger=ledger
        )
        h.admit(
            Resident(
                "team-crew",
                [Segment("who", "You are the TEAM crew. Cite the glossary.", Mutation.STATIC)],
                triggers=[OnChange(math)],
                source=math,
            )
        )
        h.admit(
            Resident(
                "buddy",
                [Segment("who", "You are Buddy, the lab's resident colleague.", Mutation.STATIC)],
                triggers=[OnSchedule(3600, clock=lambda: 0.0)],
                source=evals,
            )
        )

        print("23:39  nothing has changed.")
        for r in h.residents():
            t = h.tick(r)
            print(f"       {r.name}: {t.outcome}")

        print("23:40  three entries clear the gate; the manifest hash changes.")
        math.entries += ["Numerator", "Denominator", "Equivalent fractions"]
        for r in h.residents():
            t = h.tick(r)
            if t.wake:
                print(
                    f"       {r.name} woke ({t.wake.label}) → {t.outcome}: "
                    f"{t.proposed.tool if t.proposed else '-'}"
                )

        print()
        print("the shelf:", shelf)
        print(
            "loaded:",
            {m.name: ("resident" if m.resident else "streamed") for m in runtime.loaded()},
        )
        print()
        print("the ledger (verified:", ledger.verify(), ")")
        for e in ledger.entries():
            print(
                f"  {e.sha256[:12]}  {e.resident:<10} {e.outcome:<8} {e.tool or '-':<10} "
                f"← {e.trigger}"
            )
        print()
        print("Nobody asked. The loop ran.")


if __name__ == "__main__":
    main()
