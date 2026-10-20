import json
import re

import pytest

from qukaizen_harness import (
    DescribeNeverPrescribe,
    Guardrails,
    NothingLeavesTheMachine,
    PassesTheGate,
    Proposed,
    gbnf_for_tool_calls,
)
from qukaizen_harness.guardrails import flagged

from .fakes import FakeGate

DECK = {
    "name": "deck",
    "version": "1.0",
    "description": "deal",
    "parameters": {
        "type": "object",
        "properties": {
            "world": {"type": "string"},
            "n": {"type": "integer"},
            "depth": {"enum": ["terse", "balanced", "expansive"]},
            "tags": {"type": "array", "items": {"type": "string"}},
            "optional_note": {"type": "string"},
        },
        "required": ["world", "n", "depth", "tags"],
    },
}
IDLE = {"name": "idle", "version": "0", "description": "", "parameters": {"type": "object"}}


def test_grammar_has_a_root_and_one_alternative_per_tool() -> None:
    g = gbnf_for_tool_calls([DECK, IDLE])
    root = next(line for line in g.splitlines() if line.startswith("root ::="))
    assert root == "root ::= call0 | call1"
    assert 'call0 ::= "{" ws "\\"tool\\"" ws ":" ws "\\"deck\\""' in g
    assert "args0 ::=" in g and "args0_depth ::=" in g
    assert '"\\"terse\\"" | "\\"balanced\\"" | "\\"expansive\\""' in g
    # Optional properties are not emitted by the grammar.
    assert "optional_note" not in g
    for prim in ("ws ::=", "string ::=", "integer ::=", "boolean ::="):
        assert prim in g


def test_grammar_rejects_undeclared_required_and_unknown_types() -> None:
    bad = {**DECK, "parameters": {"type": "object", "properties": {}, "required": ["x"]}}
    with pytest.raises(ValueError, match="not declared"):
        gbnf_for_tool_calls([bad])
    weird = {
        **DECK,
        "parameters": {"type": "object", "properties": {"x": {"type": "null"}}, "required": ["x"]},
    }
    with pytest.raises(ValueError, match="unsupported"):
        gbnf_for_tool_calls([weird])
    with pytest.raises(ValueError):
        gbnf_for_tool_calls([])


def test_grammar_rule_names_are_well_formed() -> None:
    g = gbnf_for_tool_calls([DECK, IDLE])
    for line in g.splitlines():
        assert re.match(r"^[A-Za-z0-9_]+ ::= ", line), line


def test_proposed_parses_only_tool_calls() -> None:
    p = Proposed.parse(json.dumps({"tool": "deck", "args": {"world": "biology"}}))
    assert p.tool == "deck" and p.args == {"world": "biology"}
    with pytest.raises(ValueError):
        Proposed.parse(json.dumps({"hello": "world"}))


def test_nothing_leaves_the_machine() -> None:
    rule = NothingLeavesTheMachine()
    remote = Proposed("post", {"to": "https://example.com/x"}, "")
    local = Proposed("post", {"to": "http://localhost:3000/x", "nested": [{"p": "/tmp/a"}]}, "")
    assert not rule.check_action(remote, "crew").ok
    assert rule.check_action(local, "crew").ok


def test_describe_never_prescribe() -> None:
    rule = DescribeNeverPrescribe()
    assert not rule.check_output("You should take this supplement.", "docent").ok
    assert rule.check_output("An adaptation is a heritable trait.", "docent").ok
    assert rule.check_output({"not": "prose"}, "docent").ok


def test_gate_runs_on_crew_output() -> None:
    g = Guardrails.standard(gate=FakeGate())
    assert flagged(g.after({"term": "x"}, "crew")).rule == "passes-the-gate"
    assert flagged(g.after({"term": "x", "source": "Campbell"}, "crew")) is None
    assert isinstance(g.rules[-1], PassesTheGate)
