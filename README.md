# MeetingOS: Evidence-Grounded Agentic Meeting Intelligence

> **Senior Systems Engineering Build for Catalist Agentic AI Intern Assessment**  
> **Dataset:** AMI Meeting Corpus (138 meetings, 35 design teams, CC BY 4.0)  
> **Author:** Antigravity Pair Programming Engineering Team  
> **Date:** November 2026 · Spec Baseline: v1.1  

---

## 1. Executive Summary & System Philosophy

**MeetingOS** is an autonomous, evidence-grounded meeting intelligence engine engineered to retrieve, synthesize, and audit historical organizational knowledge across multi-meeting conversational corpora.

In modern enterprise workflows, hundreds to thousands of meetings contain critical evolving decisions, shifting commitments, budget trade-offs, and subtle disagreements. Unconstrained generative LLM wrappers fail on this task because:
- Monolithic prompt stuffing degrades on large corpora (~880K tokens).
- Unanchored language models hallucinate quotes, misattribute speakers, and make arithmetic errors on spoken currency expressions.
- Vector-only search suffers from cross-team semantic contamination and boundary fragmentation on staccato dialogue.

MeetingOS solves these challenges through a strict **Source of Truth** architecture:
1. **Source Authority:** Original raw transcripts remain the sole authoritative record; no LLM summary ever overwrites raw evidence.
2. **Event-Sourced Temporal Memory:** Immutable append-only event logs for decisions (`decision_events`) and actions (`action_events`), with derived current state views.
3. **Pre-Retrieval Team Isolation:** Per-team FAISS vector indexes paired with trigger-maintained SQLite FTS5 BM25 tables eliminate cross-team leakage by construction ($0.0\%$ measured contamination).
4. **Deterministic Citation Verification:** Every single citation emitted in answers ($\ge 6$ words) is validated by pure Python substring matching against source SQLite turns prior to publication (zero fabricated citations).
5. **Bounded Agent Execution:** Maximum 4 retrieval iterations, coverage-aware planning, and checkpoint recovery in `agent_runs`.

---

## 2. Architectural Layers

```mermaid
flowchart TD
    subgraph L1["Layer 1: Ingestion & Source Authority"]
        Transcripts["138 Raw Transcripts (676K words)"] --> Parser["Deterministic Parser (parser.py)"]
        Parser --> SQLiteTurns["turns (48,148 atomic speaker turns)"]
        Parser --> Checksums["SHA-256 Checksums & Byte Offsets"]
        Parser --> CoverageReg["team_coverage (33 complete, 2 partial)"]
    end

    subgraph L2["Layer 2: Conversation Chunking & Indexing"]
        SQLiteTurns --> Chunker["Hierarchical Chunker (w=5, s=2)"]
        Chunker --> Chunks["chunks (23,901 retrieval units)"]
        Chunks --> FTS5["FTS5 chunks_fts (BM25 with maintenance triggers)"]
        Chunks --> Splitter["Long-Turn Splitter (>256 tokens)"]
        Splitter --> Embedder["all-MiniLM-L6-v2 (384-dim, L2-norm)"]
        Embedder --> FAISS["35 Team-Isolated FAISS Indexes (25,772 vectors)"]
    end

    subgraph L3["Layer 3: Event-Sourced Persistent Memory"]
        SQLiteTurns --> DecEntities["decision_entities & decision_events"]
        SQLiteTurns --> ActEntities["action_entities & action_events"]
        SQLiteTurns --> NumEvidence["numeric_evidence (verbatim value_text)"]
        DecEntities --> CurrentState["decision_current_state (derived view)"]
    end

    subgraph L4["Layer 4: Hybrid Retrieval Engine"]
        FTS5 --> RRF["Reciprocal Rank Fusion (k=60)"]
        FAISS --> RRF
        RRF --> Expander["Context Window Expander (+/- 2 turns)"]
    end

    subgraph L5["Layer 5: Bounded Agent Orchestrator"]
        Plan["AgentPlanner (Coverage-Aware Decomposition)"] --> Loop["Bounded Loop (Max 4 iterations)"]
        Loop --> Checkpoint["agent_runs Checkpoints"]
        Expander --> Loop
        Loop --> Synth["EvidenceSynthesizer (1-3 sentences)"]
        Synth --> ValGate["CitationValidator (Pure Python, >= 6 words)"]
        ValGate --> Output["answers.json (25 Qs + TS3012 Brief)"]
    end
```

---

## 3. Key Findings & Corpus Reconciliation

1. **Word Count Discrepancy Resolved:**
   - Conversation turn text: **676,745 words** (~879,768 tokens).
   - Transcript files including headers: **826,709 words** (~1.07M tokens).
   - *Confirmation:* The original brief's "676K words" referred strictly to transcript body dialogue.
2. **Documented Corpus Gaps:**
   - 33 design teams have complete 4-meeting histories (`a`, `b`, `c`, `d`).
   - 2 teams have genuine corpus omissions:
     - `IS1002`: Missing meeting `a` (available: `b`, `c`, `d`).
     - `IS1005`: Missing meeting `d` (available: `a`, `b`, `c`).
   - *Architecture response:* First-class `team_coverage` registry alerts the planner to avoid hallucinating origins or final outcomes on partial histories.
3. **Turn Distribution & MiniLM Context Ceiling:**
   - 48,148 turns; average 14 words per turn.
   - 64 turns exceed 300 words; maximum turn is 736 words (~980 tokens) in `TS3005d`.
   - *Architecture response:* `all-MiniLM-L6-v2` has a hard 256-token limit. The Long-Turn Splitter partitions oversized turns into overlapping sub-segments (25,772 vectors for 23,901 chunks), preventing silent tail-truncation.

---

## 4. Quickstart & CLI Commands

MeetingOS provides a unified CLI built on `click`:

### Prerequisites & Installation

```bash
# Clone the repository
cd D:\Catalist_Media\meetingos

# Install editable package with dev dependencies
pip install -e ".[dev]"
```

### Complete Verification Pipeline

```bash
# 1. Ingest raw corpus into SQLite WAL source memory (Gate 1)
meetingos ingest

# 2. Verify Gate 1 acceptance criteria (checksums, byte offsets, turn continuity)
meetingos validate-gate1

# 3. Process conversation chunks, FTS5 sync, and team-isolated FAISS indexes (Gate 2)
meetingos process

# 4. Verify Gate 2 and Gate 3 acceptance criteria (integrity check, vector-DB map)
meetingos validate-gate2
meetingos validate-gate3

# 5. Execute bounded agent orchestrator on all 25 questions & generate brief (Gate 4-6)
meetingos generate-answers

# 6. Run independent retrieval benchmark, failure analysis & scaling model (Gate 7)
meetingos evaluate

# 7. Inspect memory and coverage statistics
meetingos info
```

### Running Automated Test Suite

```bash
# Run all 112 automated unit, integration, and synthetic sequence tests
python -m pytest
```

---

## 5. Official Deliverables

All generated submission artifacts are stored in `outputs/`:
- **[`outputs/answers.json`](file:///D:/Catalist_Media/meetingos/outputs/answers.json):** Official JSON deliverable containing:
  - 25 answered questions (`Q01` through `Q25`), each in 1–3 plain sentences.
  - 75 verified verbatim citations (exactly 3 per answer, each $\ge 6$ words from a single turn).
  - Pre-meeting executive brief for Team `TS3012` before meeting `TS3012d`.
- **[`outputs/evaluation_report.md`](file:///D:/Catalist_Media/meetingos/outputs/evaluation_report.md):** Formal technical evaluation covering:
  - 10 independently checked retrieval benchmark questions (`E01`–`E10`).
  - Analysis of 3 genuine system failure modes with layer classifications.
  - 1,000 and 10,000 meeting cost, storage, and throughput scaling models.
- **[`outputs/meetingos.db`](file:///D:/Catalist_Media/meetingos/outputs/meetingos.db):** Authoritative SQLite source database (52.8 MB, 48,148 turns, 23,901 chunks, `chunks_fts`, `team_coverage`, `agent_runs`).
- **[`outputs/ingestion_manifest.json`](file:///D:/Catalist_Media/meetingos/outputs/ingestion_manifest.json):** Deterministic Gate 1 audit manifest with SHA-256 hashes.
- **[`outputs/faiss_indexes/`](file:///D:/Catalist_Media/meetingos/outputs/faiss_indexes/):** 35 team-isolated FAISS `IndexFlatIP` vector index files.

---

## 6. Evaluation Benchmark & Performance Summary

| Metric | Target | Measured Result | Status |
|---|---|---|:---:|
| **Recall@5** | $\ge 70\%$ | **80.0%** (8/10) | PASSED |
| **Recall@10** | $\ge 90\%$ | **100.0%** (10/10) | PASSED |
| **Mean Reciprocal Rank (MRR)** | $\ge 0.50$ | **0.698** | PASSED |
| **Cross-Team Leakage** | $0.0\%$ | **0.0%** (0 contamination) | PASSED |
| **Multi-Meeting Coverage** | $\ge 80\%$ | **100.0%** | PASSED |
| **Citation Validity Rate** | $100\%$ | **100.0%** (75/75 valid) | PASSED |
| **Average Meetings Cited / Q** | $\ge 2.0$ | **2.80 meetings** | PASSED |
| **Automated Test Suite** | $100\%$ pass | **112 / 112 passed** | PASSED |

---

## 7. Scaling Model Projections

| Metric | 138 Meetings (Empirical) | 1,000 Meetings (Projected) | 10,000 Meetings (Projected) |
|---|---|---|---|
| **Body Conversation Words** | 676,745 | 4,903,949 | 49,039,492 |
| **Estimated Input Tokens** | 879,768 | 6,375,130 | 63,751,304 |
| **Generated Chunks ($w=5, s=2$)** | 23,901 | 173,195 | 1,731,956 |
| **FAISS Indexed Vectors** | 25,772 | 186,753 | 1,867,536 |
| **Total Storage (DB + FAISS)** | **89.8 MB** | **650.7 MB** | **6.50 GB** |
| **Ingestion Time (8 cores parallel)** | ~15 s | ~1.8 min | ~18.2 min |
| **Extraction API Cost (Flash tier)** | **\$0.25** | **\$1.79** | **\$17.88** |

---

## 8. Failure Honesty: Three Real Failures Analyzed

1. **Boundary Splitting on Staccato Turns (Ranking Layer):**  
   Short back-and-forth agreements (e.g. *"Dump titanium?"* / *"Yeah"*) split across adjacent chunk windows under stride $s=4$. Fixed by adopting stride $s=2$ and bidirectional context expansion ($\pm 2$ neighboring turns).
2. **Colloquial Spoken Number Representation (Reasoning Layer):**  
   Spoken currency phrases (e.g. *"twelve fifty"*, *"fifteen point eight Euros"*) lead unconstrained LLMs to hallucinate arithmetic totals. Fixed by establishing immutable `numeric_evidence` storing exact verbatim transcript strings (`value_text`).
3. **Corpus Coverage Blindness (Orchestration Layer):**  
   Partial histories (`IS1002`, `IS1005`) caused naive agents to mistake meeting `b` for the project kick-off. Fixed by making `team_coverage` a first-class registry and enforcing coverage-aware planning.

---

## 9. Architectural Decision Records (ADRs)

Key architectural decisions and trade-offs are documented in `adr/`:
- [ADR-001: Storage Backend Selection (SQLite WAL)](file:///D:/Catalist_Media/meetingos/adr/ADR-001-storage-backend.md)
- [ADR-002: Embedding Model Selection (all-MiniLM-L6-v2)](file:///D:/Catalist_Media/meetingos/adr/ADR-002-embedding-model.md)
- [ADR-003: Chunking Strategy & Window Sizing](file:///D:/Catalist_Media/meetingos/adr/ADR-003-chunking-strategy.md)
- [ADR-004: Retrieval Fusion (Reciprocal Rank Fusion, k=60)](file:///D:/Catalist_Media/meetingos/adr/ADR-004-retrieval-fusion.md)
- [ADR-005: LLM Selection & Extraction Trade-offs](file:///D:/Catalist_Media/meetingos/adr/ADR-005-llm-selection.md)
- [ADR-006: Orchestration: Custom Python vs Multi-Agent Frameworks](file:///D:/Catalist_Media/meetingos/adr/ADR-006-orchestration-approach.md)

---

*MeetingOS — Grounded Intelligence Built for Real Conversational Memory.*
