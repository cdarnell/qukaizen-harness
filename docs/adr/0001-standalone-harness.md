# ADR-0001 — The agent harness is a standalone repository

- **Status:** accepted · 2026-10-20
- **Deciders:** Charlie Darnell

## Context

QuKaiZen's products each needed the same five things to run an agent unattended:
a tool registry, a model policy, context assembly, guardrails, and a loop. By
October 2026 those lived in pieces — tool definitions in ARAIL's `arail-ops` MCP
server, the residency rule in a Buddy sprint brief, context ordering (E301) in
DDaC's compiler, grammar constraints split between DDaC and QueueLLM, and the
loop itself coupled to Buddy inside ARAIL. TEAM's page already promised "a crew
that runs on a schedule instead of a request" with nothing underneath it.

Three homes were considered: inside DDaC, inside PaperAgents, or standalone.

## Decision

A standalone package, `qukaizen-harness`, with one hard rule: **zero product
imports**. The harness reaches DDaC, QueueLLM, ARAIL, PaperAgents and 3DEval
only through Protocols the consumer implements (`KnowledgeSource`, `Runtime`,
`Gate`). The rule is enforced by ruff's banned-imports lint, not by convention.

Consumers stand in the harness as *residents*: Buddy, the TEAM crew, PaperAgents
team members, 3DEval experiments.

## Why not DDaC

DDaC is a compiler. It produces content-addressed artifacts (PaC contracts,
GBNF grammars, TOON bundles). A harness is a runtime that loads and executes
those artifacts. Putting the loop in the compiler repo blurs the Apache-2.0
compiler / proprietary curation boundary deliberately drawn there.

## Why not PaperAgents (or TEAM)

PaperAgents is orchestration — TOML-declared teams, tier escalation, drift
reconciliation on Paperclip's event bus. It needs *an* agent harness to
instantiate each member, so the harness is a dependency of PaperAgents, not a
feature of it. The same layering logic settled `qukaizen-engine` →
`qukaizen-router` in May 2026. TEAM is a consumer: a crew of agents that mints
decks and keeps the docent current.

## Consequences

- The site's `/harness` page describes the floor, not a frame; it is not on the
  product nav on purpose.
- Buddy migrates onto the harness rather than the loop living in ARAIL; the
  residency rule (ADR-0002) becomes the harness's model policy, not a brief.
- One more repository for a solo founder to keep. Accepted: two consumers and
  one orchestrator exist on day one, which is the usual bar for extraction.
- Nothing here chooses milestone 1 (TEAM crew first vs Buddy first). That is a
  sprint decision, not an architecture one.
