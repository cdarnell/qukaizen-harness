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

## Measurement

The headroom measurement has been scored once, on the pair below. Nothing else
has been scored, and the pair is not named here as the small or the large model
of the product. (An earlier, smaller population was run and never scored; see
the end of this section.)

- small: `llama3.2:1b` as served by Ollama 0.40.11 (the weights behind ARAIL's
  shipped default tag, without its persona layer, so both arms see the same
  bytes);
- large: `Qwen3-30B-A3B-Instruct-2507-4bit` resident through QueueLLM, on the
  engine build 3DEval pins.

The population is: closed-vocabulary term identification over every in-domain
card of the DDaC `ai` World at DDaC `6ef15e6c` (294 subjects; the `qukaizen`
category excluded by the frozen held-out file), generated by `world-flat/v1`
seed `20261021`. It is a proxy for the grounded lookup steps an agent performs.
It is not a sample of agent requests, and no result of it is a claim about any
other population.

The receipt's own sentence: "Escalation pays on this population (...): H =
105/294 (35.7%, 95% lower bound 30.2%), R = 4/294 (1.4%). The gate comparison
may run; nothing is certified." (The parenthesis, cut here, restates the
population above.) Answers were graded strict-correct under cut/v2. H is the
share of subjects the large model answers right and the small one wrong, R the
reverse. Both models right on 22 subjects, neither on 163 ("neither" includes
answers the strict grader rejects for format, such as an expanded acronym or a
plural). All 294 subjects were paired, none excluded, and the large arm was
clean (588 rows checked). Under cut/v2, one correct large-model answer is graded
non-committal because of a known deferred defect (TD-101 in the 3DEval
register), so H is a lower bound by at least one subject; strictness pushes H
down and R up, never the other way.

Context does not cover it. A retrieved context slice fixes 53 of the 105
subjects on which escalation pays (50.5%), below the 80% line frozen before the
run. This is the receipt's line "context does not cover it", and it limits the
population above, not the product.

Each QueueLLM answer was a fresh `queuellm generate` process: the model is
loaded for every request and nothing is reused between requests, so these runs
are pessimistic against a warm session. The large model was resident, so disk
streaming was not tested, and nothing here says anything about it.

| Question | Result | Receipt |
|---|---|---|
| Headroom: how often the larger model is right where the small one is wrong, and the reverse | H = 105/294 (35.7%, lower bound 30.2%), R = 4/294 (1.4%); verdict pass; context does not cover it | `routing/w1b-primary/headroom.json`, `sha256:fca7dc92e63700f3583bcde33b22b8b5d231435993ebfb0088d5dfcf9bbed9fa` |
| Gate comparison: a code-only gate against candidate decision models, held-out | not run (the gate has not been run; nothing is certified) | none |

The receipt is in `qukaizen-3d-eval`, branch `qukaizen/3d-eval-routing-surface`
(not merged at the time of writing): committed at `fcec899`, scored by code at
`0bbee0a`, from two runs made at `b6dc99d`. Its figures were rebuilt from the
run rows by an independent recompute before this section cited them, and every
compared figure matched. An earlier population of 101 subjects fell short of the
frozen floor of 105 and was void; it was never scored and is not an input to
anything here. This ADR remains Proposed. Live routing is not built.

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
