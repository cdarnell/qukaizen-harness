"""Commands — a terminal vocabulary, declared.

A resident that operates a machine does not get a shell. It gets commands:
each one a template with typed arguments, a class that says how much it may
disturb, and the variants that are pre-approved to run unattended. The
registry turns each into an ordinary tool, so the grammar only admits
commands that exist and flags that were declared.

Three classes:

* ``read``       — observes; always allowed (doctor, drift, tail).
* ``restart``    — disturbs a process; allowed unattended only for the
                   variants listed in ``approved``.
* ``disruptive`` — changes state (apply, rebuild); waits for a ruling
                   unless the exact invocation is pre-approved.

An :class:`Operator` runs the rendered command. :class:`SubprocessOperator`
runs it quietly; :class:`TmuxOperator` types it into a pane a person can
attach to read-only, so what they watch is what the resident sees.
"""

from __future__ import annotations

import hashlib
import json
import re
import shlex
import subprocess
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from .guardrails import Proposed, Verdict
from .registry import ToolRegistry, ToolSpec

CommandClass = str  # "read" | "restart" | "disruptive"
CLASSES: tuple[CommandClass, ...] = ("read", "restart", "disruptive")


class CommandError(Exception):
    """A declaration or invocation the command layer refuses."""


# --------------------------------------------------------------------------
# Declaration
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CommandSpec:
    """One command, as declared in the charter."""

    name: str  #: registry name, e.g. "arailctl.restart"
    template: str  #: "arailctl restart {flags}"
    cls: CommandClass
    #: Argument name → allowed values. Every placeholder in ``template``
    #: must be declared here; every declared arg must be an enum. A plain
    #: string arg would let the model compose arbitrary shell.
    args: Mapping[str, Sequence[str]] = field(default_factory=dict)
    #: Rendered invocations allowed unattended for restart/disruptive classes.
    approved: frozenset[str] = frozenset()
    description: str = ""
    version: str = "1.0"
    allowed: frozenset[str] = frozenset()  #: residents; empty = any

    def __post_init__(self) -> None:
        if self.cls not in CLASSES:
            raise CommandError(f"{self.name}: class must be one of {CLASSES}, not {self.cls!r}")
        placeholders = set(re.findall(r"{(\w+)}", self.template))
        declared = set(self.args)
        if placeholders != declared:
            raise CommandError(
                f"{self.name}: template placeholders {sorted(placeholders)} "
                f"must match declared args {sorted(declared)}"
            )
        for k, vals in self.args.items():
            if not vals:
                raise CommandError(f"{self.name}: arg {k!r} must enumerate its allowed values")

    def render(self, **kwargs: str) -> str:
        for k, v in kwargs.items():
            if k not in self.args:
                raise CommandError(f"{self.name}: unknown arg {k!r}")
            if v not in self.args[k]:
                raise CommandError(f"{self.name}: {k}={v!r} is not in {list(self.args[k])}")
        missing = set(self.args) - set(kwargs)
        if missing:
            raise CommandError(f"{self.name}: missing args {sorted(missing)}")
        rendered = self.template.format(**kwargs)
        return " ".join(rendered.split())  # collapse the hole an empty flag leaves

    def needs_ruling(self, rendered: str) -> bool:
        if self.cls == "read":
            return False
        return rendered not in self.approved

    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {k: {"enum": list(v)} for k, v in self.args.items()},
            "required": list(self.args),
        }


# --------------------------------------------------------------------------
# Operators — where the command actually runs
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RunResult:
    command: str
    exit_code: int
    output: str
    output_sha256: str
    seconds: float

    def as_ledger(self) -> dict[str, Any]:
        return {
            "command": self.command,
            "exit": self.exit_code,
            "out_sha256": self.output_sha256,
            "seconds": round(self.seconds, 3),
        }


@runtime_checkable
class Operator(Protocol):
    def say(self, why: str) -> None:
        """Narrate before acting. Written before the command, never after."""

    def run(self, command: str, *, timeout_s: float = 120.0) -> RunResult: ...


class SubprocessOperator:
    """Runs quietly. For tests, batch lanes, and headless boxes."""

    def __init__(self, cwd: str | Path | None = None) -> None:
        self.cwd = str(cwd) if cwd else None
        self.said: list[str] = []

    def say(self, why: str) -> None:
        self.said.append(why)

    def run(self, command: str, *, timeout_s: float = 120.0) -> RunResult:
        t0 = time.monotonic()
        p = subprocess.run(
            shlex.split(command), capture_output=True, text=True, timeout=timeout_s, cwd=self.cwd
        )
        out = p.stdout + p.stderr
        return RunResult(command, p.returncode, out, _sha(out), time.monotonic() - t0)


class TmuxOperator:
    """Types the command into a tmux pane a person can watch (``tmux attach -r``).

    Layout it expects (one ``tmux`` script makes it):

        session ``buddy``, window ``floor``
          pane 0 — why      (the narration, written before each command)
          pane 1 — terminal (the commands, typed and run)
          pane 2 — ledger   (``tail -f ledger.jsonl``)

    Output is captured by ``pipe-pane`` into a log the operator reads back.
    The exit code comes from a ``PROMPT_COMMAND`` hook installed once in the
    terminal pane, so the viewer sees the bare command and the result is a
    fact, not something scraped from the screen.
    """

    def __init__(
        self,
        session: str = "buddy",
        window: str = "floor",
        log_dir: str | Path = "~/.qukaizen/buddy",
        tmux: str = "tmux",
    ) -> None:
        self.session, self.window, self.tmux = session, window, tmux
        self.log_dir = Path(log_dir).expanduser()
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self._hooked = False

    def _t(self, pane: int) -> str:
        return f"{self.session}:{self.window}.{pane}"

    def _tmux(self, *args: str) -> None:
        subprocess.run([self.tmux, *args], check=True, capture_output=True)

    def say(self, why: str) -> None:
        stamp = time.strftime("%H:%M")
        self._tmux("send-keys", "-t", self._t(0), f"echo '{stamp}  {_q(why)}'", "Enter")

    @property
    def exit_file(self) -> Path:
        return self.log_dir / "last.exit"

    def ensure_hook(self) -> None:
        """Install the exit-code hook once. Shown in the pane one time, then quiet."""
        if self._hooked:
            return
        self._tmux(
            "send-keys",
            "-t",
            self._t(1),
            # bash reads PROMPT_COMMAND; zsh (the macOS default) reads precmd.
            # Defining both is harmless in either shell.
            f"__qkz_x() {{ echo $? > {shlex.quote(str(self.exit_file))}; }}; "
            "PROMPT_COMMAND=__qkz_x; precmd() { __qkz_x; }; clear",
            "Enter",
        )
        self._hooked = True
        time.sleep(0.3)

    def run(self, command: str, *, timeout_s: float = 120.0) -> RunResult:
        self.ensure_hook()
        log = self.log_dir / f"{int(time.time())}-{_sha(command)[:8]}.log"
        before = self.exit_file.stat().st_mtime_ns if self.exit_file.exists() else -1
        self._tmux("pipe-pane", "-t", self._t(1), f"cat >> {shlex.quote(str(log))}")
        self._tmux("send-keys", "-t", self._t(1), command, "Enter")
        t0 = time.monotonic()
        while True:
            if self.exit_file.exists() and self.exit_file.stat().st_mtime_ns > before:
                break
            if time.monotonic() - t0 > timeout_s:
                self._tmux("pipe-pane", "-t", self._t(1))
                raise TimeoutError(f"{command!r} did not finish in {timeout_s}s")
            time.sleep(0.2)
        time.sleep(0.1)  # let pipe-pane flush the last line
        self._tmux("pipe-pane", "-t", self._t(1))
        code = int(self.exit_file.read_text().strip() or "1")
        out = log.read_text() if log.exists() else ""
        return RunResult(command, code, out, _sha(out), time.monotonic() - t0)

    @staticmethod
    def layout_script(session: str = "buddy", ledger: str = "~/.qukaizen/ledger.jsonl") -> str:
        """The one script that builds the three-pane floor."""
        return "\n".join(
            [
                "#!/bin/sh",
                f"tmux new-session -d -x 200 -y 50 -s {session} -n floor",
                f"tmux split-window -v -l 70% -t {session}:floor",
                f"tmux split-window -v -l 25% -t {session}:floor",
                f"tmux send-keys -t {session}:floor.2 'tail -f {ledger}' Enter",
                f"tmux select-pane -t {session}:floor.1",
                f"echo 'attach read-only with: tmux attach -r -t {session}'",
            ]
        )


# --------------------------------------------------------------------------
# Rulings — a disruptive step waits for a person
# --------------------------------------------------------------------------


class Rulings:
    """A small append-only file of rulings. ``y`` in your own pane writes here.

    Each line: ``{"command": "<rendered>", "ruling": "allow"|"deny", "ts": ...}``.
    A ruling is a boundary, not a rule: it allows that exact invocation once.
    If the person wants it to stand, the charter's ``approved`` list is where
    a ruling becomes a rule.
    """

    def __init__(self, path: str | Path = "~/.qukaizen/rulings.jsonl") -> None:
        self.path = Path(path).expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.touch(exist_ok=True)

    def record(self, command: str, ruling: str) -> None:
        if ruling not in ("allow", "deny"):
            raise CommandError("ruling must be 'allow' or 'deny'")
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"command": command, "ruling": ruling, "ts": time.time()}) + "\n")

    def take(self, command: str) -> str | None:
        """Consume the oldest unspent ruling for this exact command, if any."""
        rows = [json.loads(x) for x in self.path.read_text().splitlines() if x.strip()]
        for i, r in enumerate(rows):
            if r.get("command") == command and not r.get("spent"):
                rows[i]["spent"] = True
                self.path.write_text("".join(json.dumps(x) + "\n" for x in rows))
                return str(r["ruling"])
        return None


class DisruptiveNeedsRuling:
    """Guardrail: a restart/disruptive command runs only if pre-approved or ruled on."""

    name = "disruptive-needs-ruling"

    def __init__(self, specs: Mapping[str, CommandSpec], rulings: Rulings) -> None:
        self.specs = specs
        self.rulings = rulings

    def check_action(self, proposed: Proposed, resident: str) -> Verdict:
        spec = self.specs.get(proposed.tool)
        if spec is None:
            return Verdict.allow(self.name)
        rendered = spec.render(**{k: str(v) for k, v in proposed.args.items()})
        if not spec.needs_ruling(rendered):
            return Verdict.allow(self.name)
        ruling = self.rulings.take(rendered)
        if ruling == "allow":
            return Verdict.allow(self.name)
        if ruling == "deny":
            return Verdict.flag(self.name, f"denied by ruling: {rendered}")
        return Verdict.flag(self.name, f"waits for a ruling: {rendered}")

    def check_output(self, output: Any, resident: str) -> Verdict:
        return Verdict.allow(self.name)


# --------------------------------------------------------------------------
# Wiring commands into the registry
# --------------------------------------------------------------------------


def declare_commands(
    registry: ToolRegistry,
    specs: Sequence[CommandSpec],
    operator: Operator,
    *,
    narrate: bool = True,
) -> dict[str, CommandSpec]:
    """Declare each command as a registry tool whose body renders, narrates, and runs."""
    by_name: dict[str, CommandSpec] = {}
    for spec in specs:

        def make(spec: CommandSpec) -> Any:
            def fn(**kwargs: str) -> dict[str, Any]:
                rendered = spec.render(**kwargs)
                if narrate:
                    operator.say(f"{spec.name}: {rendered}")
                return operator.run(rendered).as_ledger()

            return fn

        registry.declare(
            ToolSpec(
                name=spec.name,
                version=spec.version,
                description=spec.description or spec.template,
                parameters=spec.parameters(),
                fn=make(spec),
                allowed=spec.allowed,
                gated=False,  # a command's output is a log, not a World entry
            )
        )
        by_name[spec.name] = spec
    return by_name


def _sha(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


def _q(s: str) -> str:
    return s.replace("'", "'\\''")


if __name__ == "__main__":  # pragma: no cover
    print(TmuxOperator.layout_script())
