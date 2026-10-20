"""Loop — wake, look, decide, act, record. Then sleep.

An agent wakes on a schedule or a change, reads what the World holds,
chooses from the registry, acts within the rules, and writes a ledger line
with a hash. The loop is the same for every resident; what differs is the
resident's name, its standing segments, the tools it may call, and what
wakes it.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from typing import Any

from .context import AssembledContext, ContextAssembler, KnowledgeSource, Mutation, Segment
from .guardrails import Guardrails, Proposed, Verdict, flagged, gbnf_for_tool_calls
from .ledger import Ledger
from .model import ModelManager
from .registry import ToolRegistry

# --------------------------------------------------------------------------
# What wakes an agent
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Wake:
    """One reason to run. ``kind`` is "schedule" or "change"; ``detail`` says which."""

    kind: str
    detail: str

    @property
    def label(self) -> str:
        return f"{self.kind}:{self.detail}"


class Trigger:
    """Yields a :class:`Wake` when the resident should run, else ``None``."""

    def poll(self) -> Wake | None:  # pragma: no cover - interface
        raise NotImplementedError


class OnSchedule(Trigger):
    """Every ``every_s`` seconds, measured from the last wake."""

    def __init__(self, every_s: float, clock: Callable[[], float] = time.monotonic) -> None:
        self.every_s = every_s
        self._clock = clock
        self._last = clock() - every_s  # eligible on first poll

    def poll(self) -> Wake | None:
        now = self._clock()
        if now - self._last >= self.every_s:
            self._last = now
            return Wake("schedule", f"every {self.every_s:g}s")
        return None


class OnChange(Trigger):
    """When the knowledge source's manifest hash differs from the last one seen."""

    def __init__(self, source: KnowledgeSource) -> None:
        self.source = source
        self._seen = source.manifest_hash()

    def poll(self) -> Wake | None:
        now = self.source.manifest_hash()
        if now != self._seen:
            old, self._seen = self._seen, now
            return Wake("change", f"manifest {old[:8]}→{now[:8]}")
        return None


# --------------------------------------------------------------------------
# The resident and its loop
# --------------------------------------------------------------------------


@dataclass(slots=True)
class Resident:
    """One agent standing in the harness."""

    name: str
    #: Standing instructions: who it is, the rules it keeps. STATIC by nature.
    standing: Sequence[Segment]
    triggers: Sequence[Trigger]
    source: KnowledgeSource | None = None
    #: How the resident is asked to choose. VOLATILE; appended last.
    ask: str = 'Choose exactly one tool call for this wake, or {"tool": "idle", "args": {}}.'
    max_tokens: int = 512


@dataclass(frozen=True, slots=True)
class Tick:
    """What one wake produced."""

    resident: str
    wake: Wake | None
    outcome: str
    proposed: Proposed | None = None
    result: Any = None
    verdicts: Sequence[Verdict] = ()
    context: AssembledContext | None = None


class Harness:
    """Registry + model + context + guardrails, run as a loop over residents."""

    IDLE = "idle"

    def __init__(
        self,
        *,
        registry: ToolRegistry,
        models: ModelManager,
        guardrails: Guardrails,
        ledger: Ledger,
        assembler: ContextAssembler | None = None,
    ) -> None:
        self.registry = registry
        self.models = models
        self.guardrails = guardrails
        self.ledger = ledger
        self.assembler = assembler or ContextAssembler()
        self._residents: dict[str, Resident] = {}
        self._session: dict[str, list[Segment]] = {}

    # -- residents ------------------------------------------------------------

    def admit(self, resident: Resident) -> None:
        if resident.name in self._residents:
            raise ValueError(f"resident {resident.name!r} is already admitted")
        self._residents[resident.name] = resident
        self._session[resident.name] = []

    def residents(self) -> Iterable[Resident]:
        return self._residents.values()

    # -- one wake ----------------------------------------------------------

    def tick(self, resident: Resident, wake: Wake | None = None) -> Tick:
        """Run one wake to completion and record it. Never raises past the ledger."""
        self.models.ensure_resident()
        if wake is None:
            wake = next((w for t in resident.triggers if (w := t.poll())), None)
            if wake is None:
                return Tick(resident.name, None, "asleep")

        try:
            return self._run(resident, wake)
        except Exception as exc:  # noqa: BLE001 - the ledger records, the loop goes on
            self.ledger.record(
                resident=resident.name,
                trigger=wake.label,
                tool=None,
                outcome="error",
                detail={"error": f"{type(exc).__name__}: {exc}"},
            )
            return Tick(resident.name, wake, "error", result=exc)

    def _run(self, resident: Resident, wake: Wake) -> Tick:
        # look
        schemas = self.registry.schemas_for(resident.name)
        schemas.append(
            {
                "name": self.IDLE,
                "version": "0",
                "description": "do nothing this wake",
                "parameters": {"type": "object", "properties": {}},
            }
        )
        tool_text = "\n".join(f"- {s['name']}@{s['version']}: {s['description']}" for s in schemas)
        ctx = self.assembler.assemble(
            standing=[
                *resident.standing,
                Segment("tools", f"Tools you may call:\n{tool_text}", Mutation.STATIC),
            ],
            source=resident.source,
            session=self._session[resident.name],
            volatile=[
                Segment("wake", f"Woke because: {wake.label}", Mutation.VOLATILE),
                Segment("ask", resident.ask, Mutation.VOLATILE),
            ],
        )

        # decide (shape-constrained)
        grammar = gbnf_for_tool_calls(schemas)
        completion = self.models.runtime.complete(
            self.models.policy.resident,
            ctx.text,
            grammar=grammar,
            max_tokens=resident.max_tokens,
            static_prefix_tokens=ctx.static_prefix_chars,
        )
        proposed = Proposed.parse(completion.text)
        base_detail: dict[str, Any] = {
            "context_sha256": ctx.full_hash,
            "static_prefix_sha256": ctx.static_prefix_hash,
            "usage": dict(completion.usage),
        }

        if proposed.tool == self.IDLE:
            self.ledger.record(
                resident=resident.name,
                trigger=wake.label,
                tool=None,
                outcome="idle",
                detail=base_detail,
            )
            return Tick(resident.name, wake, "idle", proposed, context=ctx)

        # act, within the rules
        spec = self.registry.get(proposed.tool)
        if not spec.may_call(resident.name):
            raise PermissionError(f"{resident.name} may not call {spec.qualified}")
        before = self.guardrails.before(proposed, resident.name)
        if (flag := flagged(before)) is not None:
            self.ledger.record(
                resident=resident.name,
                trigger=wake.label,
                tool=spec.qualified,
                outcome="flagged",
                detail={
                    **base_detail,
                    "stage": "before",
                    "rule": flag.rule,
                    "reason": flag.reason,
                    "args": dict(proposed.args),
                },
            )
            return Tick(resident.name, wake, "flagged", proposed, verdicts=before, context=ctx)

        result = spec.fn(**proposed.args)
        self.models.assert_resident_intact()

        after = self.guardrails.after(result, resident.name) if spec.gated else []
        if (flag := flagged(after)) is not None:
            self.ledger.record(
                resident=resident.name,
                trigger=wake.label,
                tool=spec.qualified,
                outcome="flagged",
                detail={**base_detail, "stage": "after", "rule": flag.rule, "reason": flag.reason},
            )
            return Tick(
                resident.name,
                wake,
                "flagged",
                proposed,
                result,
                verdicts=[*before, *after],
                context=ctx,
            )

        # record
        self.ledger.record(
            resident=resident.name,
            trigger=wake.label,
            tool=spec.qualified,
            outcome="acted",
            detail={
                **base_detail,
                "args": dict(proposed.args),
                "tool_schema_sha256": spec.schema_hash(),
            },
        )
        self._session[resident.name].append(
            Segment(
                f"did:{spec.name}",
                f"Last wake ({wake.label}) called {spec.qualified}.",
                Mutation.SESSION,
            )
        )
        return Tick(
            resident.name, wake, "acted", proposed, result, verdicts=[*before, *after], context=ctx
        )

    # -- always on -----------------------------------------------------------

    def run(
        self,
        *,
        poll_s: float = 1.0,
        until: Callable[[], bool] = lambda: False,
        sleep: Callable[[float], None] = time.sleep,
    ) -> int:
        """Poll every resident's triggers until ``until()`` is true. Returns ticks that woke."""
        woke = 0
        while not until():
            for r in list(self.residents()):
                t = self.tick(r)
                if t.wake is not None:
                    woke += 1
            sleep(poll_s)
        return woke
