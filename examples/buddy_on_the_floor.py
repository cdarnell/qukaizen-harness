"""Buddy on the floor — watch a resident operate a machine, with the rules on.

    # terminal 1: build the floor and watch it (read-only)
    python -m qukaizen_harness.commands | sh      # prints the three-pane layout script
    tmux attach -r -t buddy

    # terminal 2: run Buddy
    python examples/buddy_on_the_floor.py            # uses tmux if the 'buddy' session exists
    python examples/buddy_on_the_floor.py --quiet    # SubprocessOperator, no tmux needed

Stand-ins for the lab commands are plain `echo`s so this runs anywhere; swap
the templates for `arailctl …` / `pactl …` on a real box. The scripted model
walks the exact scene from the harness page: an eval flags a high failure
rate → doctor (read) → restart --debug (pre-approved) → apply (waits for you).
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path

from qukaizen_harness import (
    Completion,
    Guardrails,
    Harness,
    Ledger,
    ModelInfo,
    ModelManager,
    ModelPolicy,
    Mutation,
    Resident,
    Segment,
    ToolRegistry,
    Wake,
)
from qukaizen_harness.commands import (
    CommandSpec,
    DisruptiveNeedsRuling,
    Rulings,
    SubprocessOperator,
    TmuxOperator,
    declare_commands,
)

SPECS = [
    CommandSpec(
        "lab.doctor",
        "echo '✓ sqlite  ✓ lancedb  ⚠ farm-world index degraded'",
        "read",
        description="check the lab's stores and indexes",
    ),
    CommandSpec(
        "lab.restart",
        "echo 'restarting qukaizen-arail {flags} … pid 41822'",
        "restart",
        args={"flags": ["", "--debug"]},
        approved=frozenset({"echo 'restarting qukaizen-arail --debug … pid 41822'"}),
        description="restart the lab; --debug captures the trace",
    ),
    CommandSpec(
        "lab.apply",
        "echo 'applying {manifest}'",
        "disruptive",
        args={"manifest": ["teams.toml"]},
        description="re-apply the charter (rebuilds indexes)",
    ),
]


class ScriptedRuntime:
    """Plays Buddy's three decisions in order."""

    catalog = {"resident-9b": 9.0}
    plan: Sequence[dict] = (
        {"tool": "lab.doctor", "args": {}},
        {"tool": "lab.restart", "args": {"flags": "--debug"}},
        {"tool": "lab.apply", "args": {"manifest": "teams.toml"}},
    )

    def __init__(self) -> None:
        self.i = 0
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
        step = self.plan[min(self.i, len(self.plan) - 1)]
        self.i += 1
        return Completion(json.dumps(step))


def tmux_has(session: str) -> bool:
    try:
        return (
            subprocess.run(["tmux", "has-session", "-t", session], capture_output=True).returncode
            == 0
        )
    except FileNotFoundError:
        return False


def main() -> None:
    quiet = "--quiet" in sys.argv
    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp)
        op = (
            SubprocessOperator() if (quiet or not tmux_has("buddy")) else TmuxOperator(log_dir=home)
        )
        reg = ToolRegistry()
        specs = declare_commands(reg, SPECS, op)
        rulings = Rulings(home / "rulings.jsonl")
        guards = Guardrails.standard()
        guards.rules.append(DisruptiveNeedsRuling(specs, rulings))
        h = Harness(
            registry=reg,
            models=ModelManager(ModelPolicy("resident-9b"), ScriptedRuntime()),
            guardrails=guards,
            ledger=Ledger(home / "ledger.jsonl"),
        )
        buddy = Resident(
            "buddy",
            [
                Segment(
                    "who",
                    "You are Buddy. Your goal is to take care of this World.",
                    Mutation.STATIC,
                )
            ],
            triggers=[],
        )
        h.admit(buddy)

        wake = Wake("change", "eval.failure_rate 0.22 > 0.15 on math-grade5")
        for n in range(3):
            t = h.tick(buddy, wake)
            tool = t.proposed.tool if t.proposed else "-"
            line = f"[{n + 1}] {tool:<12} → {t.outcome}"
            if t.outcome == "flagged":
                line += f"   ({t.verdicts[-1].reason})"
            print(line)

        print()
        print("you press y:  rulings.record('echo \\'applying teams.toml\\'', 'allow')")
        rulings.record("echo 'applying teams.toml'", "allow")
        t = h.tick(buddy, wake)
        print(f"[4] {(t.proposed.tool if t.proposed else '-'):<12} → {t.outcome}")

        print()
        print("ledger (verified:", h.ledger.verify(), ")")
        for e in h.ledger.entries():
            extra = e.detail.get("reason") or e.detail.get("args") or ""
            print(f"  {e.sha256[:12]}  {e.outcome:<8} {e.tool or '-':<16} {extra}")
        if isinstance(op, SubprocessOperator):
            print()
            print("buddy said, before each command:")
            for s in op.said:
                print("  ", s)


if __name__ == "__main__":
    main()
