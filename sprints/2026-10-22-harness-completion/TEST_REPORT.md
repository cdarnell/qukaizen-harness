# Test report: harness completion and first residents

**Date:** 2026-10-22
**Build:** no BUILD_LOG.md in this sprint (the conductor built it; see SPRINT.md). Commits QA'd:
`cdarnell/qukaizen-harness` main `ad1354e` (branch `qukaizen/harness-completion-sprint` @ `1737ffe`) ·
`cdarnell/qukaizen-arail#204` @ `3a270fe1` · `cdarnell/qukaizen-paperagents#7` @ `e13ff37` · `cdarnell/qukaizen-site#123` @ `79f0288`
**Verdict:** **FAIL**

## Why FAIL, in one paragraph

The step this floor exists for doesn't work against the real CLI. `arailctl restart --debug` is the only restart that `buddy_floor.py` lets run unattended. Run against a foreground lab, it stops the lab first and then fails, because `scripts/start.sh` rejects the flag with `Unknown flag: --debug` (exit 2). The lab is left down. Against a daemon-supervised lab, `--debug` is silently ignored. The harness then writes that run to the ledger as `acted` with no exit code. `RunResult.as_ledger()` is never called by the loop (QA-H6), so a failed restart looks like a successful one. Beyond that: the branch breaks one existing ARAIL test (`test_cli_verbs`, F33: the `drift` and `rule` verbs are missing from docs/cli.md). The rulings file can lose a ruling or spend one `allow` twice under concurrent writers (QA-H1/H2). And three of the brief's verification items aren't met yet: PLAN.md still has a PENDING dataset sha and an unpinned harness commit, the live /harness CTAs still point at the profile, and the floor was never run against the real CLI or a real model.

**Plain statement, as asked:** the floor acceptance run was **not** run against the real `arailctl`/`pactl` or a real 8–14B model. It used stub `arailctl`/`pactl` shell scripts (they `echo` their args) and a scripted model (`Scripted` from `tests/test_buddy_floor.py`, which replays a fixed plan). It also bypassed three parts of the scenario: `drive.py` hand-built the `Wake` instead of reading `last.json` through `EvalFailureTrigger`, called `episode()` directly instead of the `_run` daemon loop, and wrote the ruling with `bf.rule()` instead of `arailctl rule`. QA covered those three paths with stubbed tests (below). None of them has run on the M5 against the real lab.

## Floor acceptance run (recorded by the conductor; stubs only)

Driver: `/private/tmp/claude-501/floor/drive.py`; stubs `/private/tmp/claude-501/floor/bin/{arailctl,pactl}` (`echo "[stub arailctl] $*"`); state under `/private/tmp/claude-501/floor/home`.

`tmux capture-pane` of pane 1 (`/private/tmp/claude-501/floor/pane1.txt`, verbatim):

```
netsushi@M5MB36 floor % arailctl doctor
[stub arailctl] doctor
netsushi@M5MB36 floor % arailctl restart --debug
[stub arailctl] restart --debug
netsushi@M5MB36 floor % pactl apply teams.toml
[stub pactl] apply teams.toml
netsushi@M5MB36 floor %
```

Ledger excerpt (`/private/tmp/claude-501/floor/home/ledger.jsonl`, hashes trimmed to 12; all 7 rows, trigger `change:eval.failure_rate 0.22 > 0.15 on math-grade5`). `Ledger.verify()` re-run by QA: **True**.

| # | sha256 | prev | tool | args | outcome | reason |
|---|---|---|---|---|---|---|
| 1 | 4772ac4f6446 | 000000000000 | arailctl.doctor@1.0 | {} | acted | |
| 2 | 237c5a4bb95c | 4772ac4f6446 | arailctl.restart@1.0 | {"flags": "--debug"} | acted | |
| 3 | 00376a70d100 | 237c5a4bb95c | pactl.apply@1.0 | {"manifest": "teams.toml"} | flagged | waits for a ruling: pactl apply teams.toml |
| 4 | e06129b0aecb | 00376a70d100 | arailctl.doctor@1.0 | {} | acted | |
| 5 | 1b563a9e9103 | e06129b0aecb | arailctl.restart@1.0 | {"flags": "--debug"} | acted | |
| 6 | 715df43152ee | 1b563a9e9103 | pactl.apply@1.0 | {"manifest": "teams.toml"} | acted | |
| 7 | f3b17c3923f2 | 715df43152ee | pactl.apply@1.0 | {"manifest": "teams.toml"} | flagged | waits for a ruling: pactl apply teams.toml |

Rulings file after the run: one line, `{"command": "pactl apply teams.toml", "ruling": "allow", "spent": true}`.

How to read it:
- The pane shows only the **second** driver process. Each process's `ensure_hook` runs `clear`, so rows 1–3 come from a first process whose pane output was cleared. The five `buddy/*.log` files match two doctor, two restart and one apply run.
- Rows 4–5 show that resuming after a ruling **replays the whole episode**: doctor and `restart --debug` run again before apply. With a stateless or scripted model, every ruling costs another lab restart, and on the real CLI that restart leaves the lab down (QA-A4).
- Rows 6–7 do show "runs once, then waits again", but inside one episode. The brief's "next wake waits again" happened within the same wake.
- No row records an exit code. The stubs exited 0. The real `restart --debug` would exit 2 and still be ledgered `acted` (QA-H6).

## Real-CLI finding: `arailctl restart --debug` (verified without touching the lab)

- **Static read of `arailctl` (worktree @ 3a270fe1)**, `restart)` arm, foreground path (lines ~530–600): the target is resolved first, then `reset.sh stop` runs, then start runs with the same argv. Flags are never parsed here; that is left to start.sh.
- **`scripts/start.sh`**, argument loop (lines ~133–152): accepts only `--world --root --port --no-browser --list --pick --yes --warm -h/--help`, and anything else hits `*) echo "Unknown flag: $1"; exit 2`.
- **Run in a throwaway copy** (start.sh and scripts/lib copied to the scratchpad, isolated HOME, so not the real lab): `bash start.sh --debug` prints `Unknown flag: --debug` plus the usage line, exit **2**. It exits at argument parsing, before anything starts.
- **Daemon path:** `launchctl kickstart -k` ignores the flags, so `--debug` is accepted and does nothing. No trace is captured.
- `arailctl start --debug` fails the same way. It is approved unattended, but nothing is stopped first, so it's harmless.
- Regression guard filed: `test_every_declared_start_or_restart_flag_is_one_start_sh_accepts` (strict xfail, QA-A4). It reads start.sh statically and never runs it.

## Brief's verification list

| Item | Result | Evidence |
|---|---|---|
| `cdarnell/qukaizen-harness` CI green | **PASS** | run 39813104560 on main `ad1354e`: test (3.11/3.12/3.13) all success; ruff, ruff format, mypy, pytest 44 passed. Gap: CI runs only `examples/night_in_the_lab.py`. The brief says both examples. QA ran `buddy_on_the_floor.py --quiet` locally (isolated HOME): exit 0, apply flagged then acted once. |
| qukaizen.com/harness CTAs resolve to the repo | **NOT MET** | `curl -sL https://qukaizen.com/harness` still shows two `href="https://github.com/cdarnell"`. PR #123 is unmerged. Its diff is correct (two hrefs, lines 192 and 301), and `https://github.com/cdarnell/qukaizen-harness` returns 200. PR checks are red, but on a **pre-existing** gate also red on main (`firstLoadUncompressedJsBytes for "/" <= 535884`, got 535891, for the front page, not /harness; main run 39793791372 fails identically; branch `qukaizen/site-nav-3deval` re-measures it). The other 76 gates pass. |
| Floor acceptance recorded with ledger excerpt and pane capture | **Recorded, stubs only** | Above. Not run against the real CLI or model. |
| `pactl validate teams.toml` passes | **PASS** | `node dist/pactl/index.js validate --offline --strict configs/math-grade5/teams.toml` gives `ok`, exit 0. dist is not older than src. Negative controls: team-level `parameters` gives exit 1 (strict works), bad `modelTier` gives exit 1, **but a dangling `teamRef = "math-grade5/nope"` passes** (finding P1). PR #7 CI all green. |
| PLAN.md every section has a concrete number | **NOT MET** | Dataset sha is `PENDING` (Grade 5 World not compiled; known open item 2). The agent harness commit isn't pinned ("pin the commit … used at run time"), though `ad1354e` exists and could be. The model is unnamed ("the resident from model-policy.json"), and the only QueueLLM default (`Qwen2.5-7B-Instruct-4bit`) is under the 8B floor (open item 3). Everything else is concrete: 100 cases × 3 seeds × 2 arms = 600, seeds 1/2/3, ≥20% token cut, −5 pt non-inferiority margin, t=4.30 at 2 df (correct), 3D.EVAL `a0babb5` and DDaC `1c38512` (both exist and are on origin/main). |
| `ruff check` / `mypy` clean in every touched repo | **PASS with notes** | Harness: ruff, ruff format and mypy strict all clean, including QA's new tests. ARAIL: `ruff check` is clean on `src/arail/ops`, `src/arail/runtime` and the test file. `mypy` on the two new modules is clean with `--follow-imports=silent`. Without that flag it reports 35 errors, all in pre-existing modules it pulls in (e.g. `registry/binding.py`), none in the new files. ARAIL has no ruff/mypy CI step and isn't ruff-formatted (191 files would reformat), so `ruff format --check` failing on the new files is house style, not a finding. Site and PaperAgents changes are TOML/TSX/MD, so ruff/mypy don't apply. |
| No `import arail/qukaizen_dac/queuellm/paperagents` in the harness | **PASS** | `grep -rnE '^\s*(import|from)\s+(arail|qukaizen_dac|dac_world|queuellm|aerollm|aerollm_api|paperagents|pactl)' src tests examples` finds nothing. Ruff TID banned-api lists arail, qukaizen_dac, queuellm, paperagents and threedeval. It doesn't ban `dac_world` or `aerollm_api` (the real import names of DDaC's vendored package and QueueLLM's binding), so those would get past the lint (finding H7). |

## Test inventory

New tests: harness `tests/test_commands_qa.py` (22 cases) and ARAIL `tests/test_buddy_floor.py` (+56 cases appended below the existing 12). Each `xfail(strict=True)` reproduces a bug QA found and did not fix. Strict means a fix turns it into an XPASS failure, so the marker gets dropped. I confirmed every xfail fails for the stated reason with `--runxfail`.

| # | Test | Category | Covers | Status |
|---|---|---|---|---|
| H-a | `test_take_is_oldest_first_exact_match_and_spends_deny` | happy | Rulings order, exact match, deny is consumed | pass |
| H-b | `test_record_refuses_anything_but_allow_or_deny` | edge | `yes`, `ALLOW`, empty, `allow\n` refused; nothing written | pass |
| H-c | `test_ruling_written_while_buddy_takes_is_not_lost` | concurrency | record() lands between take()'s read and rewrite | **xfail QA-H1** |
| H-d | `test_one_allow_is_spent_once_even_with_two_takers` | concurrency | two takers, one allow | **xfail QA-H2** |
| H-e | `test_a_corrupt_line_does_not_hide_a_valid_ruling` ×4 | edge | torn JSON, `[1]`, `null`, `42` in rulings.jsonl | **xfail QA-H3** |
| H-f | `test_args_outside_the_enum_never_run_and_are_ledgered` ×7 | edge/adversarial | `--force`, None, list, int, `--debug; touch …`, extra arg, missing arg: none run, ledger verifies | pass |
| H-g | `test_allow_for_a_different_rendering_does_not_authorize` | edge | trailing space, double space, `./teams.toml`, empty | pass (fails closed) |
| H-h | `test_an_unknown_ruling_value_in_the_file_fails_closed` | edge | `"ruling": "yes"` in file | pass |
| H-i | `test_tick_ledgers_a_policy_refusal_instead_of_raising` | failure injection | 7B resident under the 8B floor | **xfail QA-H4** |
| H-j | `test_tmux_operator_reports_nonzero_exit_codes` ×2 | regression (zsh fix) | `false`→1, `exit 7`→7, `true`→0 in bash and zsh, on a private tmux socket | pass |
| H-k | `test_first_run_waits_for_the_command_not_the_hook_install` | concurrency | hook's `clear` finishing after the 0.3 s sleep | **xfail QA-H5** |
| H-l | `test_a_command_that_fails_is_ledgered_with_its_exit_code` | failure injection | `false` gives operator exit 1, ledger has no exit | **xfail QA-H6** |
| A-a | `test_trigger_is_quiet_on_non_object_or_empty_json` ×6 | edge | list, string, null, number, empty, `{}` | pass |
| A-b | `test_trigger_does_not_fire_at_or_below_threshold` ×4 | edge | −1, −0.5, 0, 0.15 | pass |
| A-c | `test_trigger_reads_a_partially_written_file_as_nothing_then_fires` | edge | torn last.json, then the complete file | pass |
| A-d | `test_trigger_ignores_non_finite_rates` ×3 | edge | `NaN`, `Infinity`, `"nan"` | **xfail QA-A1** |
| A-e | `test_trigger_ignores_boolean_rate` | edge | `true` reads as 1.00 | **xfail QA-A1** |
| A-f | `test_trigger_requires_a_real_run_sha_and_world` ×3 | edge | null sha becomes "None", empty sha, null world | **xfail QA-A2** |
| A-g | `test_trigger_does_not_refire_the_same_run_after_a_restart` | regression/edge | `_seen` is in-memory only | **xfail QA-A3** |
| A-h | `test_every_declared_start_or_restart_flag_is_one_start_sh_accepts` | regression (real CLI) | `--debug` vs start.sh's parser, read statically | **xfail QA-A4** |
| A-i | `test_out_of_vocabulary_proposals_never_reach_the_operator` ×9 | adversarial | bad flags, `&&` chaining, `1d`, `; cat ~/.ssh/id_rsa`, `../other.toml`, extra args, unknown tool `shell` | pass |
| A-j | `test_a_ruling_for_a_near_miss_string_does_not_authorize_apply` | edge | near-miss rulings via `bf.rule` | pass |
| A-k | `test_rule_refuses_a_command_buddy_can_never_propose` ×5 | edge/UX safety | `""`, `rm -rf /`, trailing space, `other.toml`, a read command | **xfail QA-A5** |
| A-l | `test_run_loop_waits_then_runs_apply_once_after_allow` | happy (`_run`) | last.json → wake → flagged → `rule allow` → apply once → waits; stub runtime and operator | pass |
| A-m | `test_run_loop_does_not_wake_itself_after_a_deny` | edge (`_run`) | take()'s own rewrite changes mtime and re-wakes | **xfail QA-A6** |
| A-n | `test_run_loop_survives_the_rulings_file_being_removed` | failure injection | `stat()` on a missing file | **xfail QA-A7** |
| A-o | `test_params_from_name_reads_the_total_count` ×5 | happy/edge | 8B, `qwen2.5:14b`, MoE `30B-A3B` → 30 (total), 7B default | pass |
| A-p | `test_params_from_name_reads_only_the_last_path_component` | edge | `/Volumes/models/v2b-run/Qwen3-14B-4bit` → 2.0 | **xfail QA-A8** |
| A-q | `test_params_from_name_refuses_expert_product_names` | edge | `Mixtral-8x7B` → 7.0 (a guess) | **xfail QA-A8** |
| A-r | `test_adapter_complete_before_load_refuses` | edge | complete() before load() | pass |
| A-s | `test_adapter_stops_claiming_residency_once_the_backend_closes` | edge | `_runtime=None` after close | pass |
| A-t | `test_logs_since_keeps_the_window_and_skips_malformed_lines` | edge | aware, naive-UTC, 30 min old, non-JSON, `[1,2]`, null, epoch int, no ts, non-UTF-8 bytes (throwaway copy of arailctl) | pass |
| A-u | `test_logs_since_refuses_an_undeclared_window` ×5 | edge | missing, `5m`, `1H`, `10`, `-1h` | pass |
| A-v | `test_logs_since_excludes_future_timestamps` | edge | ts 3 days ahead appears in a 2m window | **xfail QA-A9** |
| A-w | `test_rule_cli_argument_handling` | happy/edge | `arailctl rule` with good args; 1 arg, `ALLOW`, 3 args, 0 args refused; one row written | pass |
| A-x | `test_rule_without_a_venv_says_so` | setup | no `.venv` gives a clear refusal | pass |

Allocation: about 62% edge/adversarial/concurrency/failure injection, 20% happy path, 18% regression. The ARAIL tests also map onto ARAIL's 30/30/20/10/10 split, since its Buddy-behavior and security slices are most of this list.

Full suites:
- **Harness:** 57 passed, 9 xfailed (44 original + 13 new passing). ruff, format and mypy clean.
- **ARAIL `tests/test_buddy_floor.py`:** 49 passed, 19 xfailed on py3.14 (sprint venv) and py3.11 (lab venv).
- **ARAIL full suite** (lab venv plus worktree `src` and harness `src`, `HOME` set to a scratch dir): 43 failed, 594 passed, 23 skipped, 29 xfailed. All 43 failures were compared against an `origin/main` snapshot (`git archive f45c074a`):
  - 30 fail on main too.
  - 10 pass when re-run alone on the branch. They are order-dependent (logging, cost tracker, embedder) and touch nothing the branch changed.
  - 2 (`test_queuellm_rename_frozen_surface.py`) diff against the old base `5f775f1c` and are already red on main: main's pyproject.toml and portal/app.py differ from that base. The branch's `buddy` extra in pyproject.toml adds to an already-failing diff.
  - **1 is a real regression:** `tests/test_cli_verbs.py::test_verbs_driver_scenarios`, which fails with `F33: docs/cli.md is missing these arailctl verbs: drift rule` and passes on main. It isn't in any ARAIL CI workflow, which is why PR #204 is green.

## Failures

| # | Finding | Symptom | Minimal repro | Severity |
|---|---|---|---|---|
| QA-A4 | Approved unattended restart variant is broken on the real CLI | `arailctl restart --debug` stops the lab, then `Unknown flag: --debug` (exit 2), and the lab stays down. In daemon mode the flag is silently ignored. | `bash scripts/start.sh --debug` in a throwaway copy gives exit 2; test A-h | **High** |
| QA-H6 | Ledger never records a command's exit code | A failing command is ledgered `acted`; `RunResult.as_ledger()` goes to `Tick.result` but not into the ledger `detail` | test H-l; floor ledger rows 2, 5 | **High** (with A4: a down lab looks like success in the ledger) |
| R1 | `test_cli_verbs` F33 regression | `drift` and `rule` verbs aren't documented in `docs/cli.md`; `logs --since` isn't either (the F33 check only matches verbs) | `pytest tests/test_cli_verbs.py` | Medium |
| QA-H1 | Rulings lost under concurrent write | `take()` reads, then rewrites the whole file, so a `record()` in between is erased. Thread stress: 133–138 of 200 concurrent rulings survived. | test H-c | Medium |
| QA-H2 | One allow, two runs | Two takers both read before either writes, and both get `allow` | test H-d | Medium (needs two Buddy processes on one rulings file; the default path is shared by every resident) |
| QA-H5 | First `TmuxOperator.run` can return early with a wrong exit | The hook's own `clear` finishes after `ensure_hook`'s fixed 0.3 s sleep, so run() takes its exit-file write as the command's. Returned exit 0 after 1.9 s for `sleep 2; false`. Realistic on a pane whose zsh is still loading. | test H-k | Medium |
| QA-A3 | Same eval run re-fires after a Buddy restart | `_seen` is a set in memory; a new process wakes again on the same `run_sha` and replays doctor plus restart | test A-g | Medium |
| QA-A1 | Non-finite or boolean `failure_rate` wakes Buddy | `NaN`, `Infinity`, `"nan"`, `true` all fire (`eval.failure_rate nan > 0.15`). A broken eval writer causes an unattended restart. | tests A-d, A-e | Medium-low |
| CI1 | Floor tests never run in ARAIL CI | `pytest.importorskip("qukaizen_harness")`, and no workflow installs the `buddy` extra, so all of test_buddy_floor.py is skipped in CI | read `.github/workflows/*.yml` | Medium (process) |
| QA-A5 | `arailctl rule` accepts any string | `""`, `rm -rf /`, `"pactl apply teams.toml "` all print `ruled: allow …`, exit 0. They never match, so the person thinks they approved and Buddy keeps waiting. | test A-k; sandbox run of `arailctl rule` | Low-medium |
| QA-A6 | `_run` wakes itself | take()'s rewrite of rulings.jsonl changes mtime, so the next poll resumes the pending wake with no new ruling (one extra model call and ledger row) | test A-m | Low |
| QA-A7 | `_run` dies if rulings.jsonl disappears | uncaught `FileNotFoundError` from `stat()` | test A-n | Low |
| QA-H3 | One bad line in rulings.jsonl blocks every ruling | `JSONDecodeError` or `AttributeError` inside the guardrail, so the tick errors. It fails closed, but nothing recovers until the file is hand-fixed. | test H-e | Low |
| QA-H4 | `tick()` raises past the ledger on a policy refusal | `ensure_resident()` sits outside the `try`. The docstring says "Never raises past the ledger". `_run` crashes on its first wake with ARAIL's default 7B model. | test H-i | Low |
| QA-A8 | `params_from_name` misreads | an absolute model path is read from its directories (`v2b-run/Qwen3-14B` → 2.0); `8x7B` → 7.0, a guess the docstring says it never makes | tests A-p, A-q | Low |
| QA-A2 | Null or empty `run_sha`/`world` accepted | `run_sha: null` dedupes as the string `"None"` across all runs | test A-f | Low |
| QA-A9 | `logs --since` has no lower bound | a future-dated line appears in every window | test A-v | Low |
| P1 | `pactl validate --offline --strict` misses a dangling `teamRef` | `teamRef = "math-grade5/nope"` gives `ok` (pre-existing PaperAgents validator gap, not this PR) | sed the teamRef, then validate | Low |
| H7 | Banned-import lint doesn't name the real product modules | `dac_world`, `aerollm_api` aren't banned; only `arail/qukaizen_dac/queuellm/paperagents/threedeval` are | `pyproject.toml` `[tool.ruff.lint.flake8-tidy-imports.banned-api]` | Low |

Behaviors noted but not filed as bugs:
- Two `allow` rulings let apply run twice. That's the stated "a ruling allows that exact invocation once" design, but rulings never expire: an allow given today is spent whenever Buddy next proposes it, possibly weeks later.
- In `logs --since`, `Z`-suffixed timestamps are dropped silently on macOS `/usr/bin/python3` (3.9). Today's writer emits `+00:00`.
- Naive timestamps are treated as UTC.
- ANSI escapes in activity messages pass straight into Buddy's pane and log.
- Only the active `activity.jsonl` is read. Right after the 10 MB rotation, the window's events sit in `.jsonl.1`.
- `ensure_hook` overwrites any user `precmd` function. `precmd_functions+=(…)` would add to it instead.
- The layout script tails `~/.qukaizen/ledger.jsonl` even when `QKZ_HOME` points elsewhere.
- The `world` string from last.json goes verbatim into the prompt's wake segment (newlines included). It's bounded by enum-only args and the ruling gate.
- `teams.toml` declares `"run_eval.bundle_sha" = "from-serialize"`, a plain string in a block whose comment says every argument is an enum. The harness doesn't read that block yet.
- PLAN.md: with 3 seed means and t=4.30, the accuracy non-inferiority interval will probably be too wide to decide. The plan's own decision table anticipates that.

## Security review

| Surface | Checked | Findings |
|---|---|---|
| User input: `arailctl rule` | Ran it in a throwaway copy of arailctl (isolated HOME, fake `.venv`): arg count, case, empty, newline, leading `--` | Only `allow`/`deny` are accepted, and `json.dumps` escapes the command so it can't inject a line. The command string itself isn't checked at all (QA-A5). |
| User input: `last.json` | NaN, Infinity, bool, string numbers, negatives, >1, null/empty sha/world, non-object JSON, torn file, newline injection in `world` | Never crashes (good). Fires on non-finite and bool values (QA-A1) and accepts a null sha (QA-A2). The `world` text reaches the prompt (noted). |
| User input: model output, the command-injection path | 16 proposals outside the enum, including `;`, `&&`, `../`, unknown tool, extra or missing args, non-str values | None reached an operator. `CommandSpec.render` refuses before narration or run. `SubprocessOperator` uses `shlex.split` with no shell. `TmuxOperator` types only rendered enum strings. `say()` escapes single quotes via `_q`. No injection found. |
| Authentication: the rulings channel | Who can approve; replay; double spend; file mode | The file is created 0644 under a 0755 dir, so other local users can't write it, but any process running as the user can. That's the design (the `y` is "your own pane"). A ruling has no expiry or nonce and isn't bound to a wake or run_sha, so it can be replayed later. It can be double-spent (QA-H2). |
| File I/O | Races, torn writes, permissions, path traversal | `Rulings.take` does a non-atomic read-modify-write with no lock and loses data (QA-H1). Partial last.json and rulings lines are handled (or fail closed, QA-H3). No path traversal: manifest is the enum `teams.toml`, and the paths come from `QKZ_HOME`. tmux log names are `{epoch}-{sha8}.log`, so the same command in the same second appends both outputs to one log (cosmetic). |
| Network I/O | `NothingLeavesTheMachine`; adapter; harness deps | No network calls in the new code. The QueueLLM adapter is in-process. The guard flags http/ftp/s3/gs args. |
| Deserialization | Everything parsed | `json.loads` only (last.json, rulings, activity log, model output via `Proposed.parse`). No pickle or yaml. Python's json accepts `NaN`/`Infinity` literals, which is the root of QA-A1. |
| Crypto | Ledger hash chain | SHA-256 chain over a canonical body; the floor ledger verifies. It's tamper-evident, not tamper-proof: no MAC or signature, so anyone who can write the file can rewrite the whole chain consistently. Fine for a local operator log; worth a line in the README. No secret comparisons involved. |
| Dependencies | ARAIL `buddy` extra | `qukaizen-harness @ git+https://github.com/cdarnell/qukaizen-harness@ad1354e2…` is pinned by full commit, which counts as a versioned cross-repo edge (CLAUDE.md rule). ad1354e is on origin/main. No other new deps. PaperAgents and site PRs add no deps. |

## Performance

N/A. Nothing here is on a hot path. Notes: `_run` polls every 5 s. `Rulings.take` is O(n) and rewrites a file that is never compacted. `logs --since` reads the whole active log, up to 10 MB, per call.

## Coverage delta

Measured with stdlib `trace` (coverage.py isn't installed in any of the venvs), so these are line counts in trace's sense:

- `arail/ops/buddy_floor.py`: before 102 covered / 29 missed; after 123 / 8. `_run` is now exercised despite `pragma: no cover`.
- `arail/runtime/queuellm_adapter.py`: before 49 / 7; after 50 / 6.
- `qukaizen_harness/commands.py`: before 207 / 19; after 212 / 14.

## Notes for the next QA pass

- **Re-run the floor on the M5 against the real CLI**, after QA-A4 and QA-H6 are fixed, with a real 8–14B resident. Today no QueueLLM default fits the policy band (7B), and the backend ignores GBNF (open item 3), so the model's output shape is enforced only by `Proposed.parse` plus the guardrails. Drive it through `python -m arail.ops.buddy_floor run`, a real `last.json` and `./arailctl rule`, not `episode()`.
- Pattern: the conductor's acceptance path skipped the three edges where bugs actually were (trigger file, daemon loop, rule CLI). Future floor acceptance should go through the same entry points a person uses.
- Pattern: no ARAIL CI job runs the floor tests or `test_cli_verbs`. Add `.[buddy]` and both files to a workflow, or the strict xfails here won't flip when fixes land.
- Harness `Rulings` probably wants an `O_APPEND`-only design (append `spent` markers instead of rewriting) or an `fcntl.flock`. Either fixes H1 and H2 together. If that changes the file format, open the issue the brief asks for on `cdarnell/qukaizen-harness`.
- Process: during this pass, QA's attempt to skip the 8 arailctl-invoking test files didn't take effect (zsh doesn't word-split `$IGN`), so they ran too, with `HOME` set to a scratch dir. Nothing on the machine changed: the real `~/Library/LaunchAgents` are untouched (mtimes Jul–Oct), no `io.arail.*` agents are loaded, no lab processes were running before or after, and no `~/.qukaizen` was created. Two stray `logs/scheduler/*/20261022T164332Z.json` files the suite wrote into the ARAIL worktree were removed. Leftover tmux socket files from QA's private servers were removed, and the tmux tests now clean up their own.
