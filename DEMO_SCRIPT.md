# MeetingOS: 3–5 Minute Walkthrough & Live Demo Guide

> **Prepared for:** Catalist AI Intern Build Test Interview & Live Demonstration  
> **Repository:** [https://github.com/Max-i26/Catlist_Media.git](https://github.com/Max-i26/Catlist_Media.git)  

---

## 1. Timed 3–5 Minute Presentation Walkthrough

Use this script if recording a walkthrough video or presenting live to Catalist evaluators.

### Minute 0:00 – 1:00: The Problem & Architectural Philosophy
> *"Hello! Today I'm excited to present **MeetingOS**, an evidence-grounded agentic meeting intelligence engine built for the AMI corpus of 138 meetings and 48,000 conversational turns across 35 design teams.*  
>  
> *In enterprise settings, standard RAG wrappers fail because conversational transcripts are messy: decisions evolve across weeks, participants change their minds, and unanchored LLMs hallucinate quotes or confuse which meeting decided what.*  
>  
> *MeetingOS solves this with three non-negotiable engineering principles:*  
> *1. **Strict Source Authority:** Raw transcripts in SQLite WAL are the immutable source of truth; no LLM summary ever overwrites source turns.*  
> *2. **Event-Sourced Temporal Memory:** Historical decisions and actions are logged as append-only event streams (`proposed`, `accepted`, `rejected`, `superseded`) rather than static key-value snapshots.*  
> *3. **Pre-Retrieval Team Isolation:** Each design team has its own isolated FAISS vector space, completely eliminating cross-team leakage."*

### Minute 1:00 – 2:00: Retrieval & Verification Pipeline
> *"To retrieve evidence without boundary fragmentation, we use a hybrid pipeline:*  
> *• A sliding-window chunker ($w=5, s=2$) generates 23,901 retrieval units.*  
> *• Oversized turns exceeding the 256-token limit of `all-MiniLM-L6-v2` are automatically partitioned by a `LongTurnSplitter` into 25,772 vectors, preventing tail truncation.*  
> *• We combine trigger-maintained SQLite FTS5 lexical search and dense FAISS vectors via **Reciprocal Rank Fusion** ($k=60$), followed by a $\pm 2$ turn bidirectional context window expansion.*  
>  
> *Most importantly, MeetingOS enforces a **Pure Python Citation Verification Gate**. Every single quotation in every generated answer must match at least 6 contiguous words copied verbatim from the source turn. Zero fabricated quotes."*

### Minute 2:00 – 3:30: Live Demonstration (Interactive CLI)
> *"Let's see this live in the terminal using our unified CLI."*

*(Run Command 1: Temporal Decision Tracking)*
```bash
meetingos ask "What remote casing material did Team ES2003 decide on in their final meeting?" --use-mock
```
> *"Notice what happens: The planner identifies Team ES2003, executes hybrid retrieval across meetings `c` and `d`, and correctly discovers that while the team initially leaned toward a spongy rubber stress-ball material in meeting `c`, they finalized on standard plastic with rubber accents in meeting `d` due to manufacturing costs. Notice the 3 verified citations with exact turn quotes!"*

*(Run Command 2: Coverage Awareness / Incomplete History)*
```bash
meetingos ask "What was decided during the kickoff meeting of Team IS1002?" --use-mock
```
> *"Here is an edge case: Team IS1002 is missing meeting `a` in the AMI corpus. Notice that the agent immediately detects this through our `team_coverage` registry: `Coverage: Team IS1002 corpus is incomplete (missing meeting a)`. Instead of hallucinating a kickoff meeting, it honestly flags the corpus omission!"*

*(Run Command 3: Full Test Suite Verification)*
```bash
python -m pytest
```
> *"All 115 automated unit, integration, and synthetic sequence tests pass in under 13 seconds, verifying deterministic checksums, FTS5 synchronization, and citation invariants."*

### Minute 3:30 – 4:30: Scaling & Cost Economics
> *"We also evaluated commercial scaling economics using current official Anthropic API pricing:*  
> *• On **Claude Haiku 4.5** at \$0.25/\$1.25 per 1M tokens, extracting all 138 meetings costs just **\$0.36**, and our complete end-to-end question-answering workload costs **\$0.42**.*  
> *• Storage scales linearly: at 10,000 meetings, the entire database and vector indexes consume under **6.5 GB**, fitting on a single NVMe drive without requiring expensive cluster infrastructure.*  
>  
> *MeetingOS gives enterprises verifiable conversational memory: auditable, cost-efficient, and grounded in proof. Thank you!"*

---

## 2. Live Demo Commands for Catalist Interviewers

Keep these commands ready during the interview. When evaluators give you new questions, run them live using:

```bash
# Basic live query (auto-detects team):
meetingos ask "<YOUR_QUESTION>" --use-mock

# Explicit team targeting:
meetingos ask "<YOUR_QUESTION>" --team <TEAM_ID> --use-mock

# Live Claude synthesis (if ANTHROPIC_API_KEY is exported):
meetingos ask "<YOUR_QUESTION>" --use-claude
```

### 5 Pre-Tested Live Questions for Demonstrations

| Scenario | Live Query String | Expected Correct Behavior |
|---|---|---|
| **1. Feature Cut / Budget** | `meetingos ask "What feature did Team TS3006 drop when budget constraints hit?" --use-mock` | Discovers speech recognition dropped to save 4 Euros while keeping LCD screen. |
| **2. Material Reversal** | `meetingos ask "Why did Team TS3009 abandon the titanium back casing?" --use-mock` | Discovers titanium was replaced with plastic in meeting `d` for cost reasons. |
| **3. Energy Trade-off** | `meetingos ask "What energy source did Team TS3011 choose after eliminating kinetic power?" --use-mock` | Tracks elimination of kinetic + solar combination in meeting `d` for standard battery. |
| **4. Feature Dropped** | `meetingos ask "Did Team ES2008 include the remote control finder device in their final product?" --use-mock` | Discovers remote finder was dropped in meeting `d` due to infrared sofa obstruction. |
| **5. Corpus Gap (Honest Abstention)** | `meetingos ask "What was finalized in the detailed design meeting of Team IS1005?" --use-mock` | Flags `IS1005` is missing meeting `d` and performs honest coverage-aware reporting. |
