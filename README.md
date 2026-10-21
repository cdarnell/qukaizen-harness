# qukaizen-harness

**A repository, not a product.** The code the QuKaiZen products stand in when
they run unattended: a tool registry, a resident model, a World in context,
the standing rules, and the loop itself.

> A chatbot answers and forgets. A dashboard shows and never learns. The lab
> works the long loop and TEAM works the quick one — and the harness is what
> keeps either one running when no one is at the keyboard.
> — [qukaizen.com/harness](https://qukaizen.com/harness)

## Five parts, one repository

| Module | What it owns | The rule it enforces |
|---|---|---|
| `registry` | every tool an agent can reach, declared once and versioned | a tool not in the registry does not exist to the crew |
| `model` | the resident model and the policy file | the resident is never evicted ([ADR-0002](docs/adr/0002-resident-model-policy.md)) |
| `context` | assembling the World into the prompt | static first, volatile last (E301); the static prefix is hashed for cache pinning |
| `guardrails` | shape (GBNF from the registry's schemas) and conduct (standing rules) | a tool call cannot be malformed; nothing leaves the machine; the crew describes, never prescribes; nothing reaches the shelf without the gate |
| `loop` | wake · look · decide · act · record | every run leaves a ledger line with a hash |

Plus `ledger`: an append-only, hash-chained JSON-lines file. If it isn't in
the ledger, it didn't happen.

## Where it sits

```
   Buddy          TEAM crew        PaperAgents teams     3DEval experiments
   (the lab)      (the face)       (declared, validated)  (the coach)
      │               │                   │                    │
      └───────────────┴─────────┬─────────┴────────────────────┘
                                │
                       qukaizen-harness
             registry · model · context · guardrails · loop
                                │
              ┌─────────────────┴─────────────────┐
              │                                   │
            DDaC                              QueueLLM
   Worlds, PaC contracts, grammars       the runtime, residency, cache
```

**Zero product imports.** The harness never imports DDaC, QueueLLM, ARAIL,
PaperAgents or 3DEval. Each reaches the harness through a Protocol the consumer
implements — `KnowledgeSource` (DDaC), `Runtime` (QueueLLM), `Gate` (DDaC's
gate) — and ruff's banned-imports lint turns a product import into a build
error. See [ADR-0001](docs/adr/0001-standalone-harness.md).

## Run the night

```bash
pip install -e ".[dev]"
python examples/night_in_the_lab.py
```

```
23:39  nothing has changed.
       team-crew: asleep
       buddy: acted
23:40  three entries clear the gate; the manifest hash changes.
       team-crew woke (change:manifest fdcc818f→adb05bef) → acted: deck

the ledger (verified: True )
  0fee9d4fdbbc  buddy      acted    eval@1.0   ← schedule:every 3600s
  02edef862650  team-crew  acted    deck@1.0   ← change:manifest fdcc818f→adb05bef

Nobody asked. The loop ran.
```

That example uses stand-ins for the products. The same code runs against
QueueLLM and a DDaC World once their adapters implement the two Protocols.

## Standing in it

```python
from qukaizen_harness import *

reg = ToolRegistry()

@reg.tool("deck", "1.0", "deal a flash-card deck from a World",
          {"type": "object", "properties": {"world": {"type": "string"}},
           "required": ["world"]}, allowed={"team-crew"})
def deck(world: str) -> dict:
    ...

models = ModelManager(ModelPolicy.load("model-policy.json"), queuellm_runtime)
h = Harness(registry=reg, models=models,
            guardrails=Guardrails.standard(gate=ddac_gate),
            ledger=Ledger("~/.qukaizen/ledger.jsonl"))

h.admit(Resident("team-crew",
                 standing=[Segment("who", "You are the TEAM crew. Cite the glossary.", Mutation.STATIC)],
                 triggers=[OnChange(math_world)], source=math_world))

h.run(poll_s=30)   # always on
```

A `model-policy.json`:

```json
{
  "resident": "qwen3-9b-instruct",
  "resident_min_params_b": 8,
  "resident_max_params_b": 14,
  "streamable": ["gpt-oss-120b"],
  "protect_resident": true
}
```

## Buddy on the floor

A resident that operates a machine does not get a shell. It gets **declared
commands**: a template with enum'd arguments, a class (`read` · `restart` ·
`disruptive`), and the variants pre-approved to run unattended. The grammar
only admits commands that exist. A `disruptive` step stops and **waits for a
ruling**; you press `y` in your own pane, the ruling is spent once, and if you
want it to stand, the charter's `approved` list is where a ruling becomes a rule.

`TmuxOperator` types each command into a tmux pane you attach to read-only, so
what you watch is what the resident sees — narration first, then the command,
then the ledger line.

```bash
python -m qukaizen_harness.commands | sh    # builds the three-pane floor
tmux attach -r -t buddy                     # watch (read-only)
python examples/buddy_on_the_floor.py       # in another terminal
```

```
[1] lab.doctor   → acted
[2] lab.restart  → acted            (--debug is pre-approved)
[3] lab.apply    → flagged          (waits for a ruling: echo 'applying teams.toml')
you press y
[4] lab.apply    → acted
```

## The standing rules

- The resident model is never evicted. Everything else yields to it.
- Nothing reaches the shelf without passing the gate — a crew's output included.
- Nothing leaves the machine. Sharing moves rules, never data.
- Every run leaves a ledger line with a hash. If it isn't in the ledger, it didn't happen.
- The crew describes. It never prescribes. A flag waits for a person.
- A correction becomes code. An exception becomes a rule, once.

## Develop

```bash
pip install -e ".[dev]"
pytest            # 44 tests, including the night in the lab and Buddy on the floor
ruff check . && ruff format --check .
mypy              # strict
```

## Status

v0.2.0 — the five parts with their contracts and tests, plus declared commands and the tmux floor. Not yet here: the
QueueLLM `Runtime` adapter, the DDaC `KnowledgeSource`/`Gate` adapters, and a
daemon entry point. Those land in the consumer repos and a `qukaizen-harness
run` command respectively.

Apache-2.0 · [qukaizen.com/harness](https://qukaizen.com/harness)
