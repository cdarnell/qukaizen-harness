"""Model — the resident model, pinned.

The policy is a file, enforced at load. An 8–14B model lives in memory and is
never evicted: not when the runtime streams a frontier model off disk
overnight, not when a bake runs. The harness never talks to a runtime
directly; it talks to :class:`Runtime`, and the consumer hands it one.
QueueLLM is the expected implementation, but the harness does not import it.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, runtime_checkable


class PolicyError(Exception):
    """A load or run the model policy refuses."""


@dataclass(frozen=True, slots=True)
class ModelPolicy:
    """What is allowed to run, and what must stay resident."""

    #: The pinned model. Loaded first, never evicted.
    resident: str
    #: Parameter ceiling for the resident, in billions. ARAIL 2.0's rule is 14.
    resident_max_params_b: float = 14.0
    #: Parameter floor for the resident, in billions. Below this it is a drafter.
    resident_min_params_b: float = 8.0
    #: Models that may be streamed from disk around the resident (batch lanes).
    streamable: frozenset[str] = frozenset()
    #: Hard rule: the resident may not be evicted by any load. Here to be read, not toggled.
    protect_resident: bool = True

    @classmethod
    def load(cls, path: str | Path) -> ModelPolicy:
        data = json.loads(Path(path).read_text())
        return cls(
            resident=data["resident"],
            resident_max_params_b=float(data.get("resident_max_params_b", 14.0)),
            resident_min_params_b=float(data.get("resident_min_params_b", 8.0)),
            streamable=frozenset(data.get("streamable", ())),
            protect_resident=bool(data.get("protect_resident", True)),
        )

    def dump(self) -> dict[str, Any]:
        return {
            "resident": self.resident,
            "resident_max_params_b": self.resident_max_params_b,
            "resident_min_params_b": self.resident_min_params_b,
            "streamable": sorted(self.streamable),
            "protect_resident": self.protect_resident,
        }


@dataclass(frozen=True, slots=True)
class ModelInfo:
    """What a runtime reports about a loaded or loadable model."""

    name: str
    params_b: float
    resident: bool = False


@dataclass(slots=True)
class Completion:
    text: str
    #: The runtime's own usage figures, passed through untouched for the ledger.
    usage: Mapping[str, Any] = field(default_factory=dict)


@runtime_checkable
class Runtime(Protocol):
    """The inference runtime, as the harness needs it. QueueLLM implements this."""

    def describe(self, model: str) -> ModelInfo: ...

    def load(self, model: str, *, pin: bool = False) -> ModelInfo: ...

    def loaded(self) -> Sequence[ModelInfo]: ...

    def complete(
        self,
        model: str,
        prompt: str,
        *,
        grammar: str | None = None,
        max_tokens: int = 512,
        static_prefix_tokens: int = 0,
    ) -> Completion: ...


class ModelManager:
    """Applies a :class:`ModelPolicy` to a :class:`Runtime`.

    Every load goes through here. The resident is loaded once and pinned; any
    other model is streamed only if the policy names it, and only around the
    resident, never in its place.
    """

    def __init__(self, policy: ModelPolicy, runtime: Runtime) -> None:
        self.policy = policy
        self.runtime = runtime
        self._resident: ModelInfo | None = None

    def ensure_resident(self) -> ModelInfo:
        if self._resident is not None:
            return self._resident
        info = self.runtime.describe(self.policy.resident)
        lo, hi = self.policy.resident_min_params_b, self.policy.resident_max_params_b
        if not lo <= info.params_b <= hi:
            raise PolicyError(f"resident {info.name} is {info.params_b}B; policy allows {lo}–{hi}B")
        self._resident = self.runtime.load(info.name, pin=self.policy.protect_resident)
        return self._resident

    def resident(self) -> ModelInfo:
        return self.ensure_resident()

    def stream(self, model: str) -> ModelInfo:
        """Load a non-resident model for a batch lane, around the resident."""
        if model == self.policy.resident:
            return self.ensure_resident()
        if model not in self.policy.streamable:
            raise PolicyError(f"{model} is not in the policy's streamable set")
        self.ensure_resident()
        info = self.runtime.load(model, pin=False)
        self.assert_resident_intact()
        return info

    def assert_resident_intact(self) -> None:
        """The residency rule, checked. Raises if the resident was evicted."""
        if not self.policy.protect_resident:
            return
        names = {m.name for m in self.runtime.loaded() if m.resident}
        if self.policy.resident not in names:
            raise PolicyError(f"resident {self.policy.resident} was evicted — policy violated")
