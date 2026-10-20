"""Registry — every tool an agent can reach, declared once and versioned.

A tool that is not in the registry does not exist to the crew. The registry
owns three things the products used to scatter: discovery (what is there),
permission (who may call it), and the schema (what a well-formed call is).
The schema is what guardrails compile into a grammar, so a tool call cannot
be malformed.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, field
from typing import Any

JsonSchema = Mapping[str, Any]
ToolFn = Callable[..., Any]


class RegistryError(Exception):
    """A declaration or lookup the registry refuses."""


@dataclass(frozen=True, slots=True)
class ToolSpec:
    """One tool, as declared. Immutable; a new version is a new spec."""

    name: str
    version: str
    description: str
    parameters: JsonSchema
    fn: ToolFn = field(repr=False, compare=False)
    #: Which residents may call it. Empty means any resident.
    allowed: frozenset[str] = frozenset()
    #: Whether a successful call must pass the gate before it reaches the shelf.
    gated: bool = True

    @property
    def qualified(self) -> str:
        return f"{self.name}@{self.version}"

    def schema_hash(self) -> str:
        """Content hash of the call schema, for the ledger and for grammar caching."""
        canon = json.dumps(
            {"name": self.name, "version": self.version, "parameters": self.parameters},
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(canon.encode()).hexdigest()

    def may_call(self, resident: str) -> bool:
        return not self.allowed or resident in self.allowed


class ToolRegistry:
    """Declare, version, and look up tools. Nothing is reachable that is not here."""

    def __init__(self) -> None:
        self._tools: dict[str, dict[str, ToolSpec]] = {}

    # -- declaration --------------------------------------------------------

    def declare(self, spec: ToolSpec) -> ToolSpec:
        versions = self._tools.setdefault(spec.name, {})
        if spec.version in versions:
            raise RegistryError(
                f"{spec.qualified} is already declared; declare a new version instead"
            )
        versions[spec.version] = spec
        return spec

    def tool(
        self,
        name: str,
        version: str,
        description: str,
        parameters: JsonSchema,
        *,
        allowed: frozenset[str] | set[str] = frozenset(),
        gated: bool = True,
    ) -> Callable[[ToolFn], ToolFn]:
        """Decorator form of :meth:`declare`."""

        def wrap(fn: ToolFn) -> ToolFn:
            self.declare(
                ToolSpec(
                    name=name,
                    version=version,
                    description=description,
                    parameters=parameters,
                    fn=fn,
                    allowed=frozenset(allowed),
                    gated=gated,
                )
            )
            return fn

        return wrap

    # -- lookup --------------------------------------------------------------

    def get(self, name: str, version: str | None = None) -> ToolSpec:
        versions = self._tools.get(name)
        if not versions:
            raise RegistryError(f"no tool named {name!r} is declared")
        if version is None:
            return versions[max(versions, key=_version_key)]
        try:
            return versions[version]
        except KeyError:
            raise RegistryError(f"{name}@{version} is not declared") from None

    def visible_to(self, resident: str) -> list[ToolSpec]:
        """The latest version of every tool this resident may call."""
        out: list[ToolSpec] = []
        for name in sorted(self._tools):
            spec = self.get(name)
            if spec.may_call(resident):
                out.append(spec)
        return out

    def __iter__(self) -> Iterator[ToolSpec]:
        for name in sorted(self._tools):
            yield from (self._tools[name][v] for v in sorted(self._tools[name], key=_version_key))

    def __len__(self) -> int:
        return sum(len(v) for v in self._tools.values())

    def __contains__(self, name: str) -> bool:
        return name in self._tools

    # -- export --------------------------------------------------------------

    def schemas_for(self, resident: str) -> list[dict[str, Any]]:
        """The call schemas a resident may use, in the shape guardrails compile."""
        return [
            {
                "name": s.name,
                "version": s.version,
                "description": s.description,
                "parameters": dict(s.parameters),
                "sha256": s.schema_hash(),
            }
            for s in self.visible_to(resident)
        ]

    def manifest_hash(self) -> str:
        """One hash over every declared schema. Changes when the registry does."""
        h = hashlib.sha256()
        for spec in self:
            h.update(spec.schema_hash().encode())
        return h.hexdigest()


def _version_key(v: str) -> tuple[int | str, ...]:
    parts: list[int | str] = []
    for p in v.split("."):
        parts.append(int(p) if p.isdigit() else p)
    return tuple(parts)
