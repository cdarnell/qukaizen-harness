# ADR-0002 — The resident model is never evicted

- **Status:** accepted · 2026-10-20
- **Deciders:** Charlie Darnell

## Context

Always-on means the agent's brain must be there when it wakes at 01:00, not
paged out because QueueLLM streamed a frontier model overnight or Nucleus ran a
bake. ARAIL 2.0 already set a hard parameter ceiling (no model ≥ 8B as the
answering model in the lab; 8–14B dense as Buddy's brain in the Embodied brief)
and a residency-protection rule: Buddy's SLM must never be evicted by a frontier
model load. Both lived in documents, enforced by nobody.

## Decision

The policy is a file (`model-policy.json`), loaded into `ModelPolicy` and
enforced at load by `ModelManager`:

- One `resident` model, loaded first and pinned. Its size must fall inside
  `[resident_min_params_b, resident_max_params_b]`, default 8–14B.
- Any other model is streamed only if the policy names it in `streamable`, only
  after the resident is loaded, and the resident is re-checked afterwards.
  Eviction is a `PolicyError`, raised — not logged.
- `protect_resident` exists to be read, not toggled. A deployment that sets it
  false is choosing to be a batch lane, not an always-on agent.

## Consequences

- The runtime (`Runtime` Protocol) must report residency honestly in `loaded()`.
  QueueLLM's adapter owns that; the harness only asks.
- The loop asserts residency after every tool call, since a tool may stream a
  candidate (3DEval does). A violation surfaces as an `error` ledger line.
- Interactive chat and sub-8B drafters are out of scope for the resident; they
  are tools or streamable lanes, not the brain.
