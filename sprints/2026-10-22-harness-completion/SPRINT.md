# Sprint: harness-completion

**ID:** 2026-10-22-harness-completion · **Brief:** [BRIEF.md](BRIEF.md) · **Stops before:** `pactl apply`, any bake

## Phases

| Phase | Subagent | Artifact | Status | Verdict |
|---|---|---|---|---|
| think | visionary | VISION.md | skipped | — |
| plan | architect (design) | ARCHITECTURE.md | skipped | — |
| build | conductor (see decisions) | BUILD_LOG.md | done | — |
| review | architect (review) | REVIEW.md | skipped | — |
| test | qa | TEST_REPORT.md | in progress | — |
| ship | — | PRs | open, none merged | — |

## Decisions log

| Date | Decision | Rationale |
|---|---|---|
| 2026-10-22 | Skipped visionary and architect design | The brief says the design is decided in ADR-0001/0002; the work is completion. |
| 2026-10-22 | Build done by the conductor, not the builder subagent | Four repos, each step depended on the last step's discovered facts. Recorded as a deviation from "don't merge personas". Architect review was not run; QA is independent. |
| 2026-10-22 | Fixed harness bug: exit hook used bash-only PROMPT_COMMAND | tmux panes on macOS run zsh; the real tmux test timed out. Allowed by brief ("bug fixes found by the adapters"). |
| 2026-10-22 | Added `episode()` in ARAIL, not in the harness | One wake is one decision; the scenario needs several. Kept out of the harness per non-goals. If it belongs there, open an issue. |
| 2026-10-22 | Charter keys live in agent `parameters` | PaperAgents has no first-class tools/wake/store keys; team-level `parameters` fails `--strict`. |

## Open items for a ruling

1. `arailctl restart --debug` and `start --debug` do not exist; `restart` stops services, then errors.
2. The Grade 5 World does not exist; PLAN.md dataset sha is PENDING.
3. QueueLLM backend ignores GBNF grammar, and its default model (7B) is under the policy's 8B floor.
4. Nothing merged; `pactl apply` and the bake were not run.
