"""QA pass, sprint 2026-10-22-harness-completion: edges the v0.2.0 tests did not reach.

Tests marked ``xfail(strict=True)`` reproduce a bug found in QA (finding ids match
the sprint's TEST_REPORT.md). They are strict so that a fix turns them into XPASS
failures, which tells whoever fixed it to drop the marker.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from qukaizen_harness import (
    Guardrails,
    Harness,
    Ledger,
    ModelManager,
    ModelPolicy,
    Mutation,
    Resident,
    RunResult,
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
from qukaizen_harness.model import PolicyError

from .fakes import FakeRuntime, call

APPLY = "echo applying teams.toml"

# --------------------------------------------------------------------------
# Rulings: the file a person's ``y`` lands in
# --------------------------------------------------------------------------


def _interleave_on_read(
    monkeypatch: pytest.MonkeyPatch, path: Path, between: Callable[[], object]
) -> None:
    """Run ``between()`` once, right after ``path`` is read: a second writer arriving
    between Rulings.take's read and its rewrite. Deterministic, no threads."""
    orig = Path.read_text
    fired = {"done": False}

    def read_text(self: Path, *a: Any, **k: Any) -> str:
        out = orig(self, *a, **k)
        if self == path and not fired["done"]:
            fired["done"] = True
            between()
        return out

    monkeypatch.setattr(Path, "read_text", read_text)


def test_take_is_oldest_first_exact_match_and_spends_deny(tmp_path: Path) -> None:
    r = Rulings(tmp_path / "rulings.jsonl")
    r.record(APPLY, "deny")
    r.record(APPLY, "allow")
    assert r.take(APPLY + " ") is None  # exact string only
    assert r.take(APPLY) == "deny"
    assert r.take(APPLY) == "allow"
    assert r.take(APPLY) is None


def test_record_refuses_anything_but_allow_or_deny(tmp_path: Path) -> None:
    r = Rulings(tmp_path / "rulings.jsonl")
    for bad in ("yes", "ALLOW", "", "allow\n"):
        with pytest.raises(CommandError):
            r.record(APPLY, bad)
    assert r.path.read_text() == ""


def test_ruling_written_while_buddy_takes_is_not_lost(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    p = tmp_path / "rulings.jsonl"
    buddy, person = Rulings(p), Rulings(p)
    buddy.record(APPLY, "allow")
    _interleave_on_read(monkeypatch, p, lambda: person.record("echo restarting", "allow"))
    assert buddy.take(APPLY) == "allow"
    monkeypatch.undo()
    assert Rulings(p).take("echo restarting") == "allow"


def test_one_allow_is_spent_once_even_with_two_takers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    p = tmp_path / "rulings.jsonl"
    first, second = Rulings(p), Rulings(p)
    first.record(APPLY, "allow")
    got: list[str | None] = []
    _interleave_on_read(monkeypatch, p, lambda: got.append(second.take(APPLY)))
    got.append(first.take(APPLY))
    assert got.count("allow") == 1


@pytest.mark.parametrize("junk", ['{"command": "x", "ruling": "al', "[1]", "null", "42"])
def test_a_corrupt_line_does_not_hide_a_valid_ruling(tmp_path: Path, junk: str) -> None:
    r = Rulings(tmp_path / "rulings.jsonl")
    r.path.write_text(junk + "\n")
    r.record(APPLY, "allow")
    assert r.take(APPLY) == "allow"


# --------------------------------------------------------------------------
# The guardrail and the loop, with model output outside the declaration
# --------------------------------------------------------------------------

RESTART = CommandSpec(
    "lab.restart",
    "echo restarting {flags}",
    "restart",
    args={"flags": ["", "--debug"]},
    approved=frozenset({"echo restarting --debug"}),
)
APPLY_SPEC = CommandSpec(
    "lab.apply", "echo applying {manifest}", "disruptive", args={"manifest": ["teams.toml"]}
)


class _Recorder(SubprocessOperator):
    def __init__(self) -> None:
        super().__init__()
        self.ran: list[str] = []

    def run(self, command: str, *, timeout_s: float = 120.0) -> RunResult:
        self.ran.append(command)
        return super().run(command, timeout_s=timeout_s)


def _floor(
    tmp_path: Path, step: str, params_b: float = 9.0
) -> tuple[Harness, Resident, _Recorder, Rulings]:
    op = _Recorder()
    reg = ToolRegistry()
    specs = declare_commands(reg, [RESTART, APPLY_SPEC], op)
    rulings = Rulings(tmp_path / "rulings.jsonl")
    guards = Guardrails.standard()
    guards.rules.append(DisruptiveNeedsRuling(specs, rulings))
    rt = FakeRuntime({"m": params_b}, lambda _p: step)
    h = Harness(
        registry=reg,
        models=ModelManager(ModelPolicy("m"), rt),
        guardrails=guards,
        ledger=Ledger(tmp_path / "ledger.jsonl"),
    )
    r = Resident("buddy", [Segment("c", "charter", Mutation.STATIC)], triggers=[])
    h.admit(r)
    return h, r, op, rulings


def _raw(tool: str, args: dict[str, Any]) -> str:
    return json.dumps({"tool": tool, "args": args})


@pytest.mark.parametrize(
    "args",
    [
        {"flags": "--force"},
        {"flags": None},
        {"flags": ["--debug"]},
        {"flags": 1},
        {"flags": "--debug; touch /tmp/qkz-qa-pwned"},
        {"flags": "--debug", "extra": "x"},
        {},
    ],
)
def test_args_outside_the_enum_never_run_and_are_ledgered(
    tmp_path: Path, args: dict[str, Any]
) -> None:
    h, r, op, _ = _floor(tmp_path, _raw("lab.restart", args))
    t = h.tick(r, Wake("change", "x"))
    assert t.outcome == "error" and op.ran == []
    assert h.ledger.verify()
    assert not Path("/tmp/qkz-qa-pwned").exists()


def test_allow_for_a_different_rendering_does_not_authorize(tmp_path: Path) -> None:
    h, r, op, rulings = _floor(tmp_path, call("lab.apply", manifest="teams.toml"))
    for near_miss in (APPLY + " ", "echo  applying teams.toml", "echo applying ./teams.toml", ""):
        rulings.record(near_miss, "allow")
    assert h.tick(r, Wake("change", "x")).outcome == "flagged" and op.ran == []


def test_an_unknown_ruling_value_in_the_file_fails_closed(tmp_path: Path) -> None:
    h, r, op, rulings = _floor(tmp_path, call("lab.apply", manifest="teams.toml"))
    rulings.path.write_text(json.dumps({"command": APPLY, "ruling": "yes"}) + "\n")
    assert h.tick(r, Wake("change", "x")).outcome == "flagged" and op.ran == []


def test_tick_ledgers_a_policy_refusal_instead_of_raising(tmp_path: Path) -> None:
    h, r, _, _ = _floor(tmp_path, call("lab.restart", flags="--debug"), params_b=7.0)
    try:
        t = h.tick(r, Wake("change", "x"))
    except PolicyError:
        pytest.fail("tick raised past the ledger")
    assert t.outcome == "error"


# --------------------------------------------------------------------------
# TmuxOperator on a private tmux server (never the user's sessions)
# --------------------------------------------------------------------------

needs_tmux = pytest.mark.skipif(shutil.which("tmux") is None, reason="tmux not installed")


def _private_floor(tmp_path: Path, shell: str, slow_clear: bool = False) -> Path:
    """A two-pane floor on its own tmux socket; returns a ``tmux`` wrapper for it."""
    sock = f"qkzqa{uuid.uuid4().hex[:6]}"
    wrapper = tmp_path / "tmux"
    wrapper.write_text(f'#!/bin/sh\nexec tmux -L {sock} "$@"\n')
    wrapper.chmod(0o755)
    path = os.environ.get("PATH", "")
    if slow_clear:
        b = tmp_path / "bin"
        b.mkdir()
        (b / "clear").write_text("#!/bin/sh\nsleep 1.5\n")
        (b / "clear").chmod(0o755)
        path = f"{b}:{path}"
    (tmp_path / "zd").mkdir()
    cmd = f"env PATH='{path}' ZDOTDIR='{tmp_path}/zd' HOME='{tmp_path}' {shell}"
    w = str(wrapper)
    subprocess.run(
        [w, "new-session", "-d", "-x", "200", "-y", "50", "-s", "s", "-n", "floor", cmd],
        check=True,
    )
    subprocess.run([w, "split-window", "-v", "-t", "s:floor", cmd], check=True)
    time.sleep(0.5)
    return wrapper


def _kill(wrapper: Path) -> None:
    """Stop the private server and remove its socket file."""
    subprocess.run([str(wrapper), "kill-server"], capture_output=True)
    sock = wrapper.read_text().split("-L ")[1].split()[0]
    Path(f"/tmp/tmux-{os.getuid()}/{sock}").unlink(missing_ok=True)
    Path(f"/private/tmp/tmux-{os.getuid()}/{sock}").unlink(missing_ok=True)


@needs_tmux
@pytest.mark.parametrize("shell", ["bash --norc -i", "zsh -f -i"])
def test_tmux_operator_reports_nonzero_exit_codes(tmp_path: Path, shell: str) -> None:
    if shutil.which(shell.split()[0]) is None:
        pytest.skip(f"{shell.split()[0]} not installed")
    w = _private_floor(tmp_path, shell)
    try:
        op = TmuxOperator(session="s", log_dir=tmp_path / "logs", tmux=str(w))
        assert op.run("false", timeout_s=10).exit_code == 1
        assert op.run("sh -c 'exit 7'", timeout_s=10).exit_code == 7
        assert op.run("true", timeout_s=10).exit_code == 0
    finally:
        _kill(w)


@needs_tmux
def test_first_run_waits_for_the_command_not_the_hook_install(tmp_path: Path) -> None:
    w = _private_floor(tmp_path, "bash --norc -i", slow_clear=True)
    try:
        op = TmuxOperator(session="s", log_dir=tmp_path / "logs", tmux=str(w))
        t0 = time.monotonic()
        res = op.run("sleep 2; false", timeout_s=15)
        assert time.monotonic() - t0 >= 2.0
        assert res.exit_code == 1
    finally:
        _kill(w)


FAILING = CommandSpec("lab.broken", "false", "read", description="always exits 1")


def test_a_command_that_fails_is_ledgered_with_its_exit_code(tmp_path: Path) -> None:
    op = SubprocessOperator()
    reg = ToolRegistry()
    declare_commands(reg, [FAILING], op)
    rt = FakeRuntime({"m": 9.0}, lambda _p: call("lab.broken"))
    h = Harness(
        registry=reg,
        models=ModelManager(ModelPolicy("m"), rt),
        guardrails=Guardrails.standard(),
        ledger=Ledger(tmp_path / "ledger.jsonl"),
    )
    r = Resident("buddy", [Segment("c", "charter", Mutation.STATIC)], triggers=[])
    h.admit(r)
    t = h.tick(r, Wake("change", "x"))
    assert t.result["exit"] == 1  # the operator saw it ...
    row = json.loads((tmp_path / "ledger.jsonl").read_text().splitlines()[-1])
    assert "1" in json.dumps(
        row["detail"].get("result", {}).get("exit", "")
    )  # ... the ledger did not
