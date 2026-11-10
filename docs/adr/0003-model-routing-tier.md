# ADR-0003 — Model routing tier: chat stays small, agents may use both, code decides first

- **Status:** proposed · 2026-11-10
- **Deciders:** Charlie Darnell (the reading in "Relation to ADR-0002" needs his decision before this can be accepted)

## Context

Two model lanes exist and nothing decides between them per request.

- The resident model (ADR-0002) is loaded first, pinned, and never evicted.
- QueueLLM is the larger lane: a runtime that runs models without full GPU
  residency. In ARAIL it is the deep backend of the highest tier.
- ARAIL's `deep_policy` chooses fast versus deep by availability (tier,
  foreground or background, the work window, operator presence, memory
  pressure). It never reads the request. `AgentCall.brain` and
  `deep_reason_code` exist as fields; every row recorded on the owner's machine
  has them unset.

The owner's statement of 2026-11-10: a person typing in ARAIL's chat box gets
the small in-memory model by default, for speed; agents doing anything use both
models. The per-request choice therefore lives inside the agent lane, and chat
is not part of it.

Nobody has measured whether sending an agent request to the larger model pays,
nor how often the larger model is the worse of the two, nor whether anything
can find the requests on which it pays. A gate designed before that number
exists has an unknown ceiling that may be near zero. A decision model (Laya was
the candidate named in the brief) has been measured only as a grader, on a
nearby task, and did not pass its own entrance exam there (`qukaizen-3d-eval`
at `dc38761`, `judge-runs/20261011T015558Z-laya-acceptance/` and its ADR-0003);
it holds no certificate for any population.

The sprint that produced this record
(`qukaizen-site/sprints/2026-11-10-model-routing-tier/`, architecture at
`aed1866`, owner acceptance recorded at `7fb6002`) therefore built an offline
measurement and wrote this ADR as a proposal that fixes only what the
measurement cannot overturn.

## Decision

- Chat is not routed by this tier. A person typing in the chat box is answered
  by the small model that is already in memory. The person's own choice of
  compute source stays the only way chat reaches the deep lane.
- The per-request choice between the small model and the deep lane exists only
  for agent calls.
- Code decides first. An abstention, template debris, a truncated or looping
  answer, a schema failure, a World lookup with no warrant, and a person's
  explicit "ask deep" are decided by code, before any model is asked.
- A model gate decides only under a certificate for a named triple: the gate's
  identity, its question template, and the population it was certified on. This
  ADR names no gate.
- A gate without a certificate runs in shadow. Its opinion is recorded beside
  the decision that code or a person made, and it is never obeyed.
- The existing availability policy is extended with new reasons. It is not
  replaced and no second router is added.
- No model is ever loaded twice, and the resident is never evicted, as the
  resident-model ADR already says.
- Cloud is never an automatic tier. The airgap switch is the cloud policy, and
  a prompt the resident has seen leaves the machine only through a per-request
  action by the person.
- Every routing decision leaves a trace line that names the gate that decided
  and the thresholds in force.
- Manual before scheduled: an "ask deep" action on a resident answer comes
  first, with a gate's opinion recorded beside the person's choice. Automatic
  escalation waits for a certificate.
- Escalations for an unattended caller are queued, not made inline. The deep
  answer attaches to the agent's record and is labelled as the deep answer.

## Relation to ADR-0002

This ADR does not amend ADR-0002.

ADR-0002 pins one resident model, sized 8 to 14B by default, as the agent's
brain, and says that sub-8B drafters and interactive chat are "tools or
streamable lanes, not the brain". The owner's 2026-11-10 statement makes a
1B-class model ARAIL's chat default and gives agents both models.

Those two statements describe different pairs. They are reconciled only by an
owner decision. The reading this sprint worked under, and that needs the
owner's confirmation, is: the small model is the chat default and may draft for
an agent; the larger QueueLLM model is the agent's deeper lane. If that is
right, ADR-0002's size band, and the sentence on qukaizen.com/harness that
repeats it, need their own decision, and this ADR does not make it. Until that
decision exists this ADR stays Proposed, for that reason among others.

## What was measured

The pair measured is this sprint's pins, and is not named here as the small or
the large model of the product:

- small: `llama3.2:1b` through Ollama (the weights behind ARAIL's shipped
  default tag, without its persona layer, so both arms see the same bytes);
- large: `Qwen3-30B-A3B-Instruct-2507-4bit` resident through QueueLLM, on the
  engine build 3DEval pins.

The population is: closed-vocabulary term questions over the DDaC `ai` and
`ml-engineering` Worlds at DDaC `6ef15e6c`, generated by `world-flat/v1` seed
`20261021`. It is a proxy for the grounded lookup steps an agent performs. It is
not a sample of agent requests, and no result of it is a claim about any other
population.

| Question | Result | Receipt |
|---|---|---|
| Headroom: how often the larger model is right where the small one is wrong, and the reverse | not measured | none |
| Gate comparison: a code-only gate against candidate decision models, held-out | not measured | none |

The measurement surface (the pairing, the verdict table, the code-only gate,
the held-out comparison and an independent recompute) is built in
`qukaizen-3d-eval` on branch `qukaizen/3d-eval-routing-surface` at `17490b6`
(not merged at the time of writing). Only a five-case timing probe of the large
arm has run; it is not an input to either question above. When the measurement
runs, this section is replaced by the 3DEval commit and the digests of
`headroom.json` and `gate.json`.

## Not decided here

- Which decision model gates escalation, or whether any does.
- Any threshold.
- Any latency, throughput or quality claim.
- Which model is "the" small model or "the" large model.
- Whether a streamed model, as opposed to a resident one, is the deep lane. The
  pair above fits in memory, so the measurement says nothing about streaming.

## Consequences

- The routing tier is a set of constraints today, not a feature. Nothing routes
  live, and no harness change accompanies this ADR.
- The harness has no `Runtime` adapter for QueueLLM yet (README status). That is
  a hard prerequisite for routing through the harness and is not built here.
- ARAIL, QueueLLM and DDaC are unchanged. `deep_policy`, `ModelRouter` and the
  chat path stay as they are.
- If the headroom measurement does not clear its pre-registered bar, the tier is
  shelved on this pair and the record keeps the figure. If a code-only gate
  catches most of what a model could, the decision-model work ends there.
- A routing certificate is a second queue of owner labels beside the grader's.
  This sprint spends none of them; a later one will.

## Alternatives considered

- **A fixed assignment per agent or call site, with no draft.** A reading of
  "agents use both" that needs no gate. Not measured; this ADR's gate work
  measures the cascade reading, and the owner picked it.
- **An automatic cloud tier.** Rejected: the airgap switch already is the cloud
  policy, and an automatic tier would send prompts the resident has seen off the
  machine without a person's action.
- **A decision model as the gate by premise.** Rejected: it is a candidate that
  has to beat a code-only gate on held-out items, under a certificate.
- **Live per-request routing now.** Deferred until the measurement and a
  QueueLLM adapter exist; the cost of a deep answer is also not a chat latency.
