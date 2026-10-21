"""Buddy on the floor: declared commands, classes, rulings, and the ledger."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from qukaizen_harness import (
    Guardrails,
    Harness,
    Ledger,
    ModelManager,
    ModelPolicy,
    Mutation,
    Resident,
    Segment,
    ToolRegistry,
    Wake,
)
from qukaizen_harness.commands import (
    CommandError,
    CommandSpec,
    DisruptiveNeedsRuling,
    Rulings,
    SubprocessOperator,
    TmuxOperator,
    declare_commands,
)
from qukaizen_harness.guardrails import gbnf_for_tool_calls

from .fakes import FakeRuntime, call

DOCTOR = CommandSpec("lab.doctor", "echo doctor-ok", "read", description="check the lab")
RESTART = CommandSpec(
    "lab.restart",
    "echo restarting {flags}",
    "restart",
    args={"flags": ["", "--debug"]},
    approved=frozenset({"echo restarting --debug"}),
)
APPLY = CommandSpec(
    "lab.apply", "echo applying {manifest}", "disruptive", args={"manifest": ["teams.toml"]}
)


# -- declaration -----------------------------------------------------------


def test_every_placeholder_must_be_a_declared_enum() -> None:
    with pytest.raises(CommandError, match="placeholders"):
        CommandSpec("x", "echo {a}", "read")
    with pytest.raises(CommandError, match="enumerate"):
        CommandSpec("x", "echo {a}", "read", args={"a": []})
    with pytest.raises(CommandError, match="class"):
        CommandSpec("x", "echo", "yolo")


def test_render_refuses_undeclared_values() -> None:
    assert RESTART.render(flags="--debug") == "echo restarting --debug"
    assert RESTART.render(flags="") == "echo restarting"  # empty flag leaves no hole
    with pytest.raises(CommandError, match="not in"):
        RESTART.render(flags="--force")
    with pytest.raises(CommandError, match="unknown arg"):
        RESTART.render(flags="", extra="x")


def test_classes_decide_who_needs_a_ruling() -> None:
    assert not DOCTOR.needs_ruling("echo doctor-ok")
    assert not RESTART.needs_ruling("echo restarting --debug")  # pre-approved
    assert RESTART.needs_ruling("echo restarting")  # plain restart is not
    assert APPLY.needs_ruling("echo applying teams.toml")


def test_grammar_only_admits_declared_flags() -> None:
    reg = ToolRegistry()
    declare_commands(reg, [RESTART], SubprocessOperator())
    g = gbnf_for_tool_calls(reg.schemas_for("buddy"))
    assert '"\\"--debug\\""' in g and "--force" not in g


# -- running ------------------------------------------------------------------


def test_subprocess_operator_narrates_then_runs() -> None:
    op = SubprocessOperator()
    reg = ToolRegistry()
    declare_commands(reg, [DOCTOR], op)
    out = reg.get("lab.doctor").fn()
    assert op.said == ["lab.doctor: echo doctor-ok"]
    assert out["exit"] == 0 and len(out["out_sha256"]) == 64 and out["command"] == "echo doctor-ok"


def build(tmp_path: Path, script: str) -> tuple[Harness, SubprocessOperator, Rulings]:
    runtime = FakeRuntime({"resident-9b": 9.0}, lambda p: script)
    reg = ToolRegistry()
    op = SubprocessOperator()
    specs = declare_commands(reg, [DOCTOR, RESTART, APPLY], op)
    rulings = Rulings(tmp_path / "rulings.jsonl")
    guards = Guardrails.standard()
    guards.rules.append(DisruptiveNeedsRuling(specs, rulings))
    h = Harness(
        registry=reg,
        models=ModelManager(ModelPolicy("resident-9b"), runtime),
        guardrails=guards,
        ledger=Ledger(tmp_path / "ledger.jsonl"),
    )
    h.admit(Resident("buddy", [Segment("who", "You are Buddy.", Mutation.STATIC)], triggers=[]))
    return h, op, rulings


def test_read_commands_run_unattended(tmp_path: Path) -> None:
    h, op, _ = build(tmp_path, call("lab.doctor"))
    t = h.tick(next(iter(h.residents())), Wake("change", "eval.failure_rate 0.22"))
    assert t.outcome == "acted" and t.result["exit"] == 0
    assert op.said == ["lab.doctor: echo doctor-ok"]


def test_preapproved_restart_runs_unattended(tmp_path: Path) -> None:
    h, _, _ = build(tmp_path, call("lab.restart", flags="--debug"))
    t = h.tick(next(iter(h.residents())), Wake("change", "eval"))
    assert t.outcome == "acted" and t.result["command"] == "echo restarting --debug"


def test_disruptive_waits_for_a_person_then_runs_once(tmp_path: Path) -> None:
    h, op, rulings = build(tmp_path, call("lab.apply", manifest="teams.toml"))
    r = next(iter(h.residents()))
    t = h.tick(r, Wake("schedule", "nightly"))
    assert t.outcome == "flagged"
    e = list(h.ledger.entries())[-1]
    assert e.detail["rule"] == "disruptive-needs-ruling"
    assert "waits for a ruling: echo applying teams.toml" in e.detail["reason"]
    assert op.said == []  # nothing was narrated, nothing ran

    rulings.record("echo applying teams.toml", "allow")  # you press y
    t = h.tick(r, Wake("schedule", "nightly"))
    assert t.outcome == "acted" and t.result["exit"] == 0

    t = h.tick(r, Wake("schedule", "nightly"))  # the ruling was spent; it waits again
    assert t.outcome == "flagged"


def test_a_denial_is_recorded_as_such(tmp_path: Path) -> None:
    h, _, rulings = build(tmp_path, call("lab.restart", flags=""))
    rulings.record("echo restarting", "deny")
    t = h.tick(next(iter(h.residents())), Wake("schedule", "x"))
    assert t.outcome == "flagged"
    assert "denied by ruling" in list(h.ledger.entries())[-1].detail["reason"]


def test_layout_script_builds_three_panes() -> None:
    s = TmuxOperator.layout_script()
    assert "new-session -d -x 200 -y 50 -s buddy -n floor" in s and s.count("split-window") == 2
    assert "attach -r -t buddy" in s


@pytest.mark.skipif(shutil.which("tmux") is None, reason="tmux not installed")
def test_tmux_operator_types_into_the_pane(tmp_path: Path) -> None:
    import subprocess
    import uuid

    sess = f"t{uuid.uuid4().hex[:6]}"
    subprocess.run(
        ["tmux", "new-session", "-d", "-x", "200", "-y", "50", "-s", sess, "-n", "floor"],
        check=True,
    )
    subprocess.run(["tmux", "split-window", "-v", "-t", f"{sess}:floor"], check=True)
    try:
        op = TmuxOperator(session=sess, log_dir=tmp_path)
        op.say("checking the lab")
        res = op.run("echo hello-from-buddy", timeout_s=20)
        assert res.exit_code == 0 and "hello-from-buddy" in res.output
    finally:
        subprocess.run(["tmux", "kill-session", "-t", sess])
