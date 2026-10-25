# Sprint brief — qukaizen-harness: completion and first residents

- **Date:** 2026-10-21
- **Origin:** Claude session `https://claude.ai/code/session_01VMUF1B6pxQtJH4MDET6JKm` (all site commits from `4e2f7a3`…`b22316d` carry this link in their trailers)
- **Inputs on disk:** `~/Downloads/qukaizen-harness-v0.2.0.tar.gz` (a git repo, two commits, 44 tests passing) · this brief
- **Agents:** visionary → architect → builder → qa. Visionary and architect may be brief; the architecture is decided (ADR-0001, ADR-0002 in the tarball). The work is completion, not design.

## Context (read first)

The agent harness is a standalone package — a repository, not a product — that the residents (Buddy, the TEAM crew, PaperAgents teams, 3DEval experiments) stand in. PaperAgents is the charter (declares; never runs). nanobot is the always-on gateway (door + clock). DDaC is the law beneath. Paperclip AI is an optional substrate, not required. The picture is on `qukaizen.com/topology.html#wiring` and `qukaizen.com/harness`; the vocabulary is on `qukaizen.com/language`.

**Hard rule:** the harness has zero product imports. DDaC, QueueLLM, ARAIL, PaperAgents and 3DEval reach it through Protocols (`KnowledgeSource`, `Gate`, `Runtime`, `Operator`). Ruff's banned-imports lint enforces it. Adapters live in the product repos, never in the harness.

**Buddy's charter line** (first line of his standing segment): *You are Buddy. Your goal is to take care of this World. You describe; you never prescribe. When a step is disruptive, you stop and wait for a person.*

## What is done (do not redo)

- `src/qukaizen_harness/` — registry, model (resident 8–14B pinned, never evicted), context (E301 static-first, static-prefix hash), guardrails (GBNF from schemas; NothingLeavesTheMachine, DescribeNeverPrescribe, PassesTheGate), loop (OnChange / OnSchedule triggers; wake→look→decide→act→record), ledger (hash-chained JSONL), **commands** (CommandSpec with enum-only args and classes read/restart/disruptive; Rulings file; DisruptiveNeedsRuling guardrail; SubprocessOperator; TmuxOperator with why-pane narration, pipe-pane capture, PROMPT_COMMAND exit hook; `python -m qukaizen_harness.commands | sh` builds the three-pane floor).
- `tests/` — 44 tests incl. "a night in the lab" and "Buddy on the floor" end to end; a real tmux round-trip when tmux is present.
- `examples/night_in_the_lab.py`, `examples/buddy_on_the_floor.py`.
- `docs/adr/0001-standalone-harness.md`, `0002-resident-model-policy.md`, README, Apache-2.0, CI matrix 3.11–3.13, `model-policy.example.json`.

## Scope — in order

### 1. Publish the repository
1. `tar xzf ~/Downloads/qukaizen-harness-v0.2.0.tar.gz -C /Users/netsushi/ProJects/`
2. Create the empty public repo `cdarnell/qukaizen-harness` (no README/license/gitignore — the commits carry them). Use `gh repo create cdarnell/qukaizen-harness --public --source=/Users/netsushi/ProJects/qukaizen-harness --push` if `gh` is authenticated; otherwise create on github.com and `git remote add origin git@github.com:cdarnell/qukaizen-harness.git && git push -u origin main`.
3. Confirm CI is green on GitHub (ruff, mypy strict, pytest, both examples).
4. In `qukaizen-site`, flip the repo CTAs on `app/harness/page.tsx` from `https://github.com/cdarnell` to `https://github.com/cdarnell/qukaizen-harness` (two occurrences). Run `npm run check:links && npm run check:copy && npm run build`; commit; merging to main deploys (the VM timer ships within ~2–3 min; `./refresh-vm.sh --force` only if it doesn't).

### 2. Buddy on the floor, for real (ARAIL repo: `/Users/netsushi/ProJects/arail`)
Create `src/arail/ops/buddy_floor.py` (or the repo's equivalent module path) that imports `qukaizen_harness` and declares the real commands. Templates, classes, approvals:

| name | template | class | approved unattended |
|---|---|---|---|
| `arailctl.doctor` | `arailctl doctor` | read | always |
| `arailctl.drift` | `arailctl drift` | read | always |
| `logs.tail` | `arailctl logs --since {since}` · `since ∈ {2m, 10m, 1h}` | read | always |
| `arailctl.restart` | `arailctl restart {flags}` · `flags ∈ {"", --debug}` | restart | `--debug` only |
| `arailctl.start` | `arailctl start {flags}` · `flags ∈ {"", --debug}` | restart | both |
| `pactl.validate` | `pactl validate {manifest}` · `manifest ∈ {teams.toml}` | read | always |
| `pactl.apply` | `pactl apply {manifest}` · `manifest ∈ {teams.toml}` | disruptive | never (waits for a ruling) |

Rules: no plain-string args anywhere (the harness refuses them); every arg is an enum. Rulings file at `~/.qukaizen/rulings.jsonl`; ledger at `~/.qukaizen/ledger.jsonl`; tmux logs at `~/.qukaizen/buddy/`.

Add the **trigger**: a `Trigger` whose `poll()` reads 3DEval's latest run result (wherever ARAIL writes it; if nothing exists yet, a JSON file `~/.qukaizen/3deval/last.json` with `{"world": ..., "failure_rate": ..., "run_sha": ...}`) and returns `Wake("change", f"eval.failure_rate {rate:.2f} > 0.15 on {world}")` when the threshold is crossed and the run_sha is new.

Add the **approval channel**: a tiny CLI `arailctl rule "<rendered command>" allow|deny` that appends to the rulings file — this is the `y` the person presses in their own pane.

Buddy's standing segment starts with the charter line above.

Acceptance: on the M5, `python -m qukaizen_harness.commands | sh`, `tmux attach -r -t buddy` in one terminal; in another, write a `last.json` with failure_rate 0.22; the floor shows: why-pane narration → `arailctl doctor` → `arailctl restart --debug` → flagged `pactl apply teams.toml` waiting; `arailctl rule "pactl apply teams.toml" allow` → it runs once → next wake waits again. Ledger verifies. The resident model (QueueLLM, 8–14B) never moves — if ARAIL's QueueLLM `Runtime` adapter does not exist yet, implement the Protocol in `src/arail/runtime/queuellm_adapter.py` with honest `loaded()` residency reporting; this is ADR-0002's one dependency.

### 3. The charter for the Grade 5 math World (PaperAgents repo: `/Users/netsushi/ProJects/qukaizen-paperagents`)
A `teams.toml` declaring two residents for the Grade 5 World (use its actual slug on the shelf):
- `docent` — tools `lookup`, `answer`; wakes on World manifest change.
- `experimenter` — tools `serialize(world, format ∈ {json, toon})`, `run_eval(bundle_sha, seeds ∈ {3})`, `record`; wakes on schedule; store policy says results file into the World through the gate.
Plus the store-policy lines (which store each kind of input lands in) and a pre-registered experiment plan `experiments/<date>-grade5-serialization/PLAN.md` in the qkz experiment-plan shape: hypothesis with magnitude and mechanism, null, dataset by sha, eval harness by commit, ≥3 seeds, mean ± CI. `pactl validate` must pass on the TOML. Do not run the bake (rung 3); baseline and the one experiment only.

### 4. Non-goals this sprint
- No nanobot adapter yet (spike only if time remains: map `Runtime`, `KnowledgeSource`, `Gate`, `Operator` onto nanobot's provider/tool/hook surface and report go/no-go per Protocol; no code).
- No Paperclip AI work. No Shihan resident. No phone app.
- No changes to the harness package itself beyond bug fixes found by the adapters; if a Protocol needs widening, open an issue on `cdarnell/qukaizen-harness` with the exact signature.

## Verification (qa)
- `cdarnell/qukaizen-harness` CI green; `qukaizen.com/harness` CTAs resolve to the repo.
- Floor acceptance scenario above recorded as a `TEST_REPORT.md` with the ledger excerpt and a `tmux capture-pane` of pane 1.
- `pactl validate teams.toml` passes; PLAN.md has every section filled with a concrete number.
- `ruff check` and `mypy` clean in every touched repo; no `import arail`/`qukaizen_dac`/`queuellm`/`paperagents` inside the harness.

## Second floor (keep sneaky, cite origin)
- 常駐 jōchū — resident (the TSR word); 土台 dodai — the harness as sill; 窓 mado — the pane you watch through; 世話 sewa — to take care of (世 is the first character of 世界).
