"""Context — the World, injected.

A knowledge source compiles the mounted World into the wire payload the
model reads. The harness orders it so the parts that never change sit first
and stay cached, and the parts that just happened sit last — DDaC's E301
rule (segments ordered by mutation frequency), applied at assembly time
rather than left to each consumer. Nothing is pasted by hand.

The harness does not know what a World is. It knows a :class:`Segment` and a
:class:`KnowledgeSource` that yields them; DDaC implements the source.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from enum import IntEnum
from typing import Protocol, runtime_checkable


class Mutation(IntEnum):
    """How often a segment changes. Lower sits earlier in the prompt (E301)."""

    STATIC = 0  #: system prompt, standing rules, tool schemas
    WORLD = 1  #: the mounted World's compiled payload; changes when the manifest hash does
    SESSION = 2  #: this resident's standing memory for the run
    VOLATILE = 3  #: the trigger, the request, what just happened


@dataclass(frozen=True, slots=True)
class Segment:
    name: str
    text: str
    mutation: Mutation
    #: Set by the source when the segment is a compiled World bundle.
    source_hash: str | None = None

    def sha256(self) -> str:
        return hashlib.sha256(self.text.encode()).hexdigest()


@runtime_checkable
class KnowledgeSource(Protocol):
    """Yields the World (or Worlds) a resident has mounted. DDaC implements this."""

    def manifest_hash(self) -> str: ...

    def segments(self) -> Iterable[Segment]: ...


@dataclass(frozen=True, slots=True)
class AssembledContext:
    """The prompt, with the static-prefix boundary the runtime can pin."""

    segments: tuple[Segment, ...]
    text: str
    #: Characters (not tokens) in the cacheable prefix. The runtime's tokenizer
    #: converts; the harness only knows where the boundary is.
    static_prefix_chars: int
    #: Hash of the static prefix alone — the KV-cache key.
    static_prefix_hash: str
    #: Hash over everything — the ledger's record of what the model saw.
    full_hash: str


class ContextAssembler:
    """Orders segments by mutation frequency and marks the static prefix."""

    def __init__(self, separator: str = "\n\n") -> None:
        self.separator = separator

    def assemble(
        self,
        *,
        standing: Sequence[Segment] = (),
        source: KnowledgeSource | None = None,
        session: Sequence[Segment] = (),
        volatile: Sequence[Segment] = (),
        pin_through: Mutation = Mutation.WORLD,
    ) -> AssembledContext:
        """E301: stable sort by mutation, then mark everything up to ``pin_through``.

        ``pin_through`` is the last mutation class considered static for cache
        pinning. WORLD by default: the resident re-reads the World when its
        manifest hash changes, and between those changes the World sits in
        the cached prefix with the standing rules.
        """
        parts: list[Segment] = list(standing)
        if source is not None:
            parts.extend(source.segments())
        parts.extend(session)
        parts.extend(volatile)
        ordered = tuple(sorted(parts, key=lambda s: s.mutation))  # stable

        self._check_order(ordered)

        texts = [s.text for s in ordered]
        full = self.separator.join(texts)
        static_count = sum(1 for s in ordered if s.mutation <= pin_through)
        static_text = self.separator.join(texts[:static_count])
        return AssembledContext(
            segments=ordered,
            text=full,
            static_prefix_chars=len(static_text),
            static_prefix_hash=hashlib.sha256(static_text.encode()).hexdigest(),
            full_hash=hashlib.sha256(full.encode()).hexdigest(),
        )

    @staticmethod
    def _check_order(ordered: Sequence[Segment]) -> None:
        """Lint E301 as a build error, not documentation.

        A volatile segment at position zero kills every cacheable token behind
        it — measurably worse than no cache at all. The sort prevents it; this
        asserts it, so a future change to the sort cannot silently regress.
        """
        last = Mutation.STATIC
        for s in ordered:
            if s.mutation < last:
                raise ValueError(
                    f"E301: segment {s.name!r} ({s.mutation.name}) follows a "
                    f"{last.name} segment; volatile text must sit last"
                )
            last = s.mutation
