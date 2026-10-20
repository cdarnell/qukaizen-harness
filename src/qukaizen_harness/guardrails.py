"""Guardrails — the standing rules.

Two kinds, and the harness keeps them apart:

* **Shape.** Output is grammar-constrained from the registry's own schemas,
  so a tool call cannot be malformed. The harness compiles a GBNF grammar
  from the schemas a resident may use and hands it to the runtime.
* **Conduct.** Everything a crew produces passes the same gate a World
  passes, and the crew describes, never prescribes. These are
  :class:`Rule` objects run over a proposed action before it executes and
  over its output before it reaches the shelf. A flag waits for a person.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

# --------------------------------------------------------------------------
# Shape: schemas → grammar
# --------------------------------------------------------------------------


def gbnf_for_tool_calls(schemas: Sequence[Mapping[str, Any]]) -> str:
    """Compile a GBNF grammar that admits exactly one well-formed tool call.

    The shape is ``{"tool": "<name>", "args": {...}}`` where ``args`` is
    constrained per tool from its JSON-schema ``parameters``. Supported
    schema subset: ``object`` with ``properties`` of ``string``, ``integer``,
    ``number``, ``boolean``, ``array`` (of those) and ``enum``; ``required``
    is honored, optional properties are omitted (not nullable). Enough for
    MCP-shaped tools; anything richer is a build error here, not a surprise
    at decode time.
    """
    if not schemas:
        raise ValueError("no schemas: a resident with no tools has nothing to call")
    rules: list[str] = []
    alts: list[str] = []
    for i, s in enumerate(schemas):
        rule = f"call{i}"
        args_rule = f"args{i}"
        name_lit = _lit(s["name"])
        rules.append(
            f'{rule} ::= "{{" ws "\\"tool\\"" ws ":" ws {name_lit} ws "," ws '
            f'"\\"args\\"" ws ":" ws {args_rule} ws "}}"'
        )
        rules.extend(_object_rules(args_rule, s["parameters"]))
        alts.append(rule)
    head = "root ::= " + " | ".join(alts)
    prims = _PRIMS
    return "\n".join([head, *rules, prims])


_PRIMS = r"""
ws ::= [ \t\n]*
string ::= "\"" ( [^"\\] | "\\" ["\\/bfnrt] )* "\""
integer ::= "-"? ( "0" | [1-9] [0-9]* )
number ::= integer ( "." [0-9]+ )? ( [eE] [-+]? [0-9]+ )?
boolean ::= "true" | "false"
""".strip()


def _lit(s: str) -> str:
    return '"\\"' + s.replace("\\", "\\\\").replace('"', '\\"') + '\\""'


def _object_rules(rule: str, schema: Mapping[str, Any]) -> list[str]:
    if schema.get("type", "object") != "object":
        raise ValueError(f"{rule}: tool parameters must be an object schema")
    props: Mapping[str, Mapping[str, Any]] = schema.get("properties", {})
    required = list(schema.get("required", []))
    for r in required:
        if r not in props:
            raise ValueError(f"{rule}: required property {r!r} is not declared")
    out: list[str] = []
    members: list[str] = []
    # Required properties in declared order; optional ones are left out of
    # the grammar (the model cannot emit them) — explicit over permissive.
    for k in required:
        sub = f"{rule}_{_ident(k)}"
        out.extend(_value_rules(sub, props[k]))
        members.append(f'{_lit(k)} ws ":" ws {sub}')
    if members:
        body = ' ws "," ws '.join(members)
        out.append(f'{rule} ::= "{{" ws {body} ws "}}"')
    else:
        out.append(f'{rule} ::= "{{" ws "}}"')
    return out


def _value_rules(rule: str, schema: Mapping[str, Any]) -> list[str]:
    if "enum" in schema:
        alts = " | ".join(_lit(str(v)) for v in schema["enum"])
        return [f"{rule} ::= {alts}"]
    t = schema.get("type", "string")
    if t in ("string", "integer", "number", "boolean"):
        return [f"{rule} ::= {t}"]
    if t == "array":
        item = f"{rule}_item"
        return [
            *_value_rules(item, schema.get("items", {"type": "string"})),
            f'{rule} ::= "[" ws ( {item} ( ws "," ws {item} )* )? ws "]"',
        ]
    if t == "object":
        return _object_rules(rule, schema)
    raise ValueError(f"{rule}: unsupported schema type {t!r}")


def _ident(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9]", "_", s)


# --------------------------------------------------------------------------
# Conduct: rules over actions and outputs
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Proposed:
    """A tool call the model emitted, parsed, not yet executed."""

    tool: str
    args: Mapping[str, Any]
    raw: str

    @classmethod
    def parse(cls, text: str) -> Proposed:
        data = json.loads(text)
        if not isinstance(data, dict) or "tool" not in data or "args" not in data:
            raise ValueError("not a tool call: expected {'tool': ..., 'args': {...}}")
        return cls(tool=str(data["tool"]), args=dict(data["args"]), raw=text)


@dataclass(frozen=True, slots=True)
class Verdict:
    ok: bool
    rule: str
    reason: str = ""

    @staticmethod
    def allow(rule: str) -> Verdict:
        return Verdict(True, rule)

    @staticmethod
    def flag(rule: str, reason: str) -> Verdict:
        return Verdict(False, rule, reason)


@runtime_checkable
class Rule(Protocol):
    name: str

    def check_action(self, proposed: Proposed, resident: str) -> Verdict: ...

    def check_output(self, output: Any, resident: str) -> Verdict: ...


class _Base:
    name = "rule"

    def check_action(self, proposed: Proposed, resident: str) -> Verdict:
        return Verdict.allow(self.name)

    def check_output(self, output: Any, resident: str) -> Verdict:
        return Verdict.allow(self.name)


class DescribeNeverPrescribe(_Base):
    """The crew describes. It never prescribes.

    A conservative lexical rule: prescriptive modal phrasing in generated
    prose is flagged, not rewritten. A flag waits for a person.
    """

    name = "describe-never-prescribe"
    _pat = re.compile(
        r"\b(you (should|must|need to|have to)|we recommend|it is advised)\b", re.IGNORECASE
    )

    def check_output(self, output: Any, resident: str) -> Verdict:
        if isinstance(output, str) and (m := self._pat.search(output)):
            return Verdict.flag(self.name, f"prescriptive phrasing: {m.group(0)!r}")
        return Verdict.allow(self.name)


class NothingLeavesTheMachine(_Base):
    """Sharing moves rules, never data. Any arg that looks like a remote target is flagged."""

    name = "nothing-leaves-the-machine"
    _pat = re.compile(r"^(https?|ftp|s3|gs)://", re.IGNORECASE)

    def check_action(self, proposed: Proposed, resident: str) -> Verdict:
        for k, v in _walk(proposed.args):
            if isinstance(v, str) and self._pat.match(v) and "localhost" not in v:
                return Verdict.flag(self.name, f"arg {k!r} targets a remote: {v!r}")
        return Verdict.allow(self.name)


@runtime_checkable
class Gate(Protocol):
    """The same gate a World passes. DDaC implements this; the harness only calls it."""

    def check(self, artifact: Any) -> Sequence[str]:
        """Return the list of violations; empty means it passed."""


class PassesTheGate(_Base):
    """Nothing reaches the shelf without passing the gate — a crew's output included."""

    name = "passes-the-gate"

    def __init__(self, gate: Gate) -> None:
        self.gate = gate

    def check_output(self, output: Any, resident: str) -> Verdict:
        problems = list(self.gate.check(output))
        if problems:
            return Verdict.flag(self.name, "; ".join(problems))
        return Verdict.allow(self.name)


@dataclass(slots=True)
class Guardrails:
    """The standing rules, run in order. First flag wins; the rest still run for the ledger."""

    rules: list[Rule] = field(default_factory=list)

    @classmethod
    def standard(cls, gate: Gate | None = None) -> Guardrails:
        rules: list[Rule] = [NothingLeavesTheMachine(), DescribeNeverPrescribe()]
        if gate is not None:
            rules.append(PassesTheGate(gate))
        return cls(rules)

    def before(self, proposed: Proposed, resident: str) -> list[Verdict]:
        return [r.check_action(proposed, resident) for r in self.rules]

    def after(self, output: Any, resident: str) -> list[Verdict]:
        return [r.check_output(output, resident) for r in self.rules]


def flagged(verdicts: Iterable[Verdict]) -> Verdict | None:
    return next((v for v in verdicts if not v.ok), None)


def _walk(obj: Any, prefix: str = "") -> Iterable[tuple[str, Any]]:
    if isinstance(obj, Mapping):
        for k, v in obj.items():
            yield from _walk(v, f"{prefix}.{k}" if prefix else str(k))
    elif isinstance(obj, (list, tuple)):
        for i, v in enumerate(obj):
            yield from _walk(v, f"{prefix}[{i}]")
    else:
        yield prefix, obj
