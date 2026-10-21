"""qukaizen-harness — a repository, not a product.

The code the products stand in when they run unattended. Five parts:

- :mod:`.registry`   — every tool an agent can reach, declared once and versioned
- :mod:`.model`      — the resident model, pinned; the policy is a file, enforced at load
- :mod:`.context`    — the World, injected; static first, volatile last (E301)
- :mod:`.guardrails` — shape from the registry's schemas, conduct from the standing rules
- :mod:`.loop`       — wake, look, decide, act, record; then sleep
- :mod:`.commands`   — a terminal vocabulary, declared: typed commands, classes, rulings

Zero product imports. DDaC, QueueLLM, ARAIL, PaperAgents and 3DEval reach the
harness through the Protocols in each module, never the other way round.
"""

from .commands import (
    CommandSpec,
    DisruptiveNeedsRuling,
    Operator,
    Rulings,
    RunResult,
    SubprocessOperator,
    TmuxOperator,
    declare_commands,
)
from .context import AssembledContext, ContextAssembler, KnowledgeSource, Mutation, Segment
from .guardrails import (
    DescribeNeverPrescribe,
    Gate,
    Guardrails,
    NothingLeavesTheMachine,
    PassesTheGate,
    Proposed,
    Rule,
    Verdict,
    gbnf_for_tool_calls,
)
from .ledger import Entry, Ledger
from .loop import Harness, OnChange, OnSchedule, Resident, Tick, Trigger, Wake
from .model import Completion, ModelInfo, ModelManager, ModelPolicy, PolicyError, Runtime
from .registry import RegistryError, ToolRegistry, ToolSpec

__version__ = "0.2.0"

__all__ = [
    "CommandSpec",
    "DisruptiveNeedsRuling",
    "Operator",
    "Rulings",
    "RunResult",
    "SubprocessOperator",
    "TmuxOperator",
    "declare_commands",
    "AssembledContext",
    "ContextAssembler",
    "KnowledgeSource",
    "Mutation",
    "Segment",
    "DescribeNeverPrescribe",
    "Gate",
    "Guardrails",
    "NothingLeavesTheMachine",
    "PassesTheGate",
    "Proposed",
    "Rule",
    "Verdict",
    "gbnf_for_tool_calls",
    "Entry",
    "Ledger",
    "Harness",
    "OnChange",
    "OnSchedule",
    "Resident",
    "Tick",
    "Trigger",
    "Wake",
    "Completion",
    "ModelInfo",
    "ModelManager",
    "ModelPolicy",
    "PolicyError",
    "Runtime",
    "RegistryError",
    "ToolRegistry",
    "ToolSpec",
]
