# ADR-006: Orchestration Approach — Custom Python vs. LangGraph

**Date:** 2026-11-13
**Status:** Accepted
**Decision made by:** Architecture review

## Context

MeetingOS requires a bounded agent loop that:
- Decomposes questions into sub-questions
- Calls retrieval tools iteratively (max 4 iterations)
- Enforces hard limits on iterations, model calls and timeouts
- Records a complete execution trace (tool calls, evidence selected, citations)
- Supports checkpoint-based recovery after failures
- Is inspectable — every retrieval decision must be auditable

## Decision

**Custom Python orchestrator** implemented in `src/meetingos/agent/orchestrator.py`.

No LangChain, LangGraph or similar framework is introduced.

## Rationale

The agent workflow for this assignment is a **bounded, linear state machine** with deterministic tool dispatch:

```
plan → retrieve → inspect → (loop if needed) → synthesize → validate → return
```

A custom orchestrator:
- Makes every retrieval decision visible in the code and execution trace
- Requires no additional abstractions or hidden state
- Makes timeout, retry and checkpoint logic explicit and testable
- Avoids adding a dependency whose abstractions we would need to debug during the interview

## Alternatives Considered

| Alternative | Why Not Now |
|---|---|
| LangGraph | Useful for persistent multi-step workflows with human approval, complex branching across sessions. Our workflow fits in a single function. Adds an abstraction layer that makes debugging harder during a time-constrained assignment. |
| LangChain | Chain abstractions obscure retrieval decisions. Difficult to control exact tool dispatch and execution trace format. |
| DSPy | Optimizes prompts programmatically — valuable, but adds complexity we don't need for a bounded workflow. |

## When to Reconsider

LangGraph would become appropriate if MeetingOS needs:
- Persistent multi-session workflow state
- Human-in-the-loop approval steps
- Complex branching graphs that don't fit a linear loop
- Multi-agent collaboration

None of these are required by this assignment.

## Consequences

- **Good:** Full control, auditability, testability of every agent decision
- **Good:** No hidden framework state to debug
- **Watch:** We implement checkpointing ourselves — `agent_runs` table in SQLite
- **Watch:** If the workflow grows significantly more complex, refactoring to LangGraph is straightforward because our tool registry and state model are already well-defined
