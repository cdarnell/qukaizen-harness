"""Test doubles standing in for the products. None of these import a product."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterable, Sequence
from typing import Any

from qukaizen_harness import Completion, ModelInfo, Mutation, Segment


class FakeRuntime:
    """A runtime that answers with whatever the test scripted, and tracks residency."""

    def __init__(self, catalog: dict[str, float], script: Callable[[str], str]) -> None:
        self.catalog = catalog
        self.script = script
        self._loaded: dict[str, ModelInfo] = {}
        self.calls: list[dict[str, Any]] = []
        self.evict_on_load = False  # flip to simulate a policy violation

    def describe(self, model: str) -> ModelInfo:
        return ModelInfo(model, self.catalog[model])

    def load(self, model: str, *, pin: bool = False) -> ModelInfo:
        if self.evict_on_load and not pin:
            self._loaded = {k: v for k, v in self._loaded.items() if not v.resident}
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
        self.calls.append(
            {
                "model": model,
                "prompt": prompt,
                "grammar": grammar,
                "static_prefix_tokens": static_prefix_tokens,
            }
        )
        return Completion(self.script(prompt), usage={"prompt_chars": len(prompt)})


class FakeWorld:
    """A knowledge source whose manifest hash moves when entries are added."""

    def __init__(self, name: str, entries: Iterable[str] = ()) -> None:
        self.name = name
        self.entries = list(entries)

    def manifest_hash(self) -> str:
        return hashlib.sha256(json.dumps(self.entries).encode()).hexdigest()

    def segments(self) -> Iterable[Segment]:
        yield Segment(
            f"world:{self.name}",
            f"World {self.name}:\n" + "\n".join(f"- {e}" for e in self.entries),
            Mutation.WORLD,
            source_hash=self.manifest_hash(),
        )

    def add(self, *entries: str) -> None:
        self.entries.extend(entries)


class FakeGate:
    """Passes anything that is a dict with a 'source' key — the gate's smallest rule."""

    def check(self, artifact: Any) -> Sequence[str]:
        if isinstance(artifact, dict) and artifact.get("source"):
            return []
        return ["entry does not cite its origin"]


def call(tool: str, **args: Any) -> str:
    return json.dumps({"tool": tool, "args": args})
