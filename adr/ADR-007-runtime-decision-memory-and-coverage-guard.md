# ADR-007: Dual-Path Retrieval, Decision Memory Wiring, and Coverage Abstention Guard

**Date:** 2026-11-13  
**Status:** Accepted (Bug Fix & Alignment to Frozen v1.1 Baseline)  
**Decision made by:** Architecture Review & Audit  

## Context

A production diagnostic audit of live CLI queries revealed three critical failure modes in the runtime agent pipeline:
1. **Decision Memory Disconnect:** In Layer 3, SQLite `decision_events` successfully stored 678 categorized events (e.g., speech recognition cuts, display consensus), but `AgentOrchestrator.run_question()` only queried raw chunk retrieval via `tools.search_hybrid()`. Structured organizational memory was never queried at runtime.
2. **Unsafe Mock Synthesis:** In deterministic mock mode, `orchestrator._synthesize_answer()` slotted arbitrary verbatim quotes into a rigid template (`"The discussions established that {quote}."`), producing grammatically incomplete sentences without identifying actual entities.
3. **Coverage Guard Failure:** When asked about unobserved meeting phases (e.g., kickoff `IS1002a` on team `IS1002`), the planner logged a warning but the orchestrator proceeded to retrieve turns from later meetings (`b` and `d`), falsely presenting subsequent discussion as kickoff decisions.

## Decision

We implement an independent **Dual-Path Evidence Pipeline** within the frozen v1.1 architecture:

```
                    User Question
                         |
                       Planner
                         |
              Coverage / Scope Guard
                         |
              +----------+----------+
              |                     |
         Hybrid Search        Decision Memory
      (tools.search_hybrid) (tools.get_decision_history)
              |                     |
              +----------+----------+
                         |
                Evidence Reconciliation
                         |
                    Synthesis
                         |
               Citation Validation
                         |
                       Answer
```

### Specific Changes
1. **Pre-Retrieval Coverage Scope Guard:** If `plan.coverage_warning` indicates a meeting sequence is absent from the corpus and the question asks about that phase (e.g. "kickoff", "initial meeting", "meeting a"), the orchestrator immediately halts and returns an honest coverage-aware abstention.
2. **Independent Decision Memory Query:** The orchestrator independently queries `tools.get_decision_history(team_id)` to retrieve decision events (event type, entity, meeting ID, turn IDs, and quotes), aligning with the query's topic keywords.
3. **Reconciled Synthesis:** Synthesis fuses both structured decision events and expanded conversational turns. The rigid fill-in-the-blank template is completely removed:
   - If an event is `rejected` / `dropped` and the user asks what was cut, it identifies the dropped feature and cites the source rejection turn.
   - If an event is `accepted` / `finalized` in meeting `d`, it identifies the accepted entity and cites the final meeting decision turn.
   - If evidence cannot support a definitive entity answer, the system abstains honestly with 0 citations.

## Consequences
- **Positive:** Reconciles Layer 3 organizational memory with runtime query answering without adding external dependencies.
- **Positive:** Prevents chronological confusion and eliminates hallucinated answers on missing meeting phases.
- **Positive:** Zero changes to chunking parameters, embedding models, or database schemas; frozen v1.1 architecture preserved.
