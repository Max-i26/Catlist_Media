# MeetingOS: Corpus Audit & Guideline Discrepancy Report

> **Author:** Harol Maxilan · **Project:** MeetingOS (Catalist Agentic AI Assessment)  
> **Topic:** Empirical Corpus Audit vs. Original Guideline PDF Claims  
> **Corpus Analyzed:** AMI Meeting Corpus (138 Meetings, 35 Teams, 48,148 Turns)  
> **Date:** November 2026 · **Spec Baseline:** v1.1  

---

## 1. Executive Comparison Table

The table below contrasts the claims, estimates, and assumptions in the original Catalist Build Test guideline PDF against the exact measurements obtained from inspecting the raw transcripts and SQLite source database:

| Item / Metric | Original PDF Said | Empirical Measured Truth | Delta / Discrepancy | Architectural Impact & Engineering Consequence |
|---|---|---|:---:|---|
| **Total Word Count** | *"about 676,000 words in all"* | **826,709 words** (raw files)<br>**676,745 words** (spoken turns) | **+150,064 words**<br>(+22.18% / ~25% more) | Loading raw transcript files into memory or prompt context processes 826.7K words. The PDF's ~676K words applies strictly to dialogue body text after stripping timestamps, file headers, and speaker labels. |
| **Total Token Count** | **~880,000 tokens** (standard $1.3\times$ estimate) | **~1,074,722 tokens** (raw files)<br>**~879,768 tokens** (spoken turns) | **+194,722 tokens**<br>(+22.1% more) | Passing the full raw corpus exceeds 1M-token context windows (1.07M > 1M tokens), causing massive attention dilution ("lost in the middle") and \$1.50+ per-query cost if attempted monolithically. |
| **Team Count** | Implied $35$ teams ($33 \times 4 + 2 \times 3 = 138$) | **35 distinct design teams** | Accurate total, but details omitted | The PDF did not identify which teams are incomplete or which meeting stages are absent. |
| **Incomplete Teams Identity** | *"two teams have only three meetings in the corpus"* | **Team `IS1002`** (missing `a`)<br>**Team `IS1005`** (missing `d`) | Unspecified in PDF | `IS1002` is missing its kickoff meeting (`a`). `IS1005` is missing its final detailed design meeting (`d`). |
| **Question Q09 Solvability** | *"questions.json: 25 questions. Every one needs more than one meeting to answer."* | **Q09 is unanswerable from ground truth** | Factually impossible without abstention | Q09 asks: *"What was the target selling price decided in the kickoff meeting of Team IS1002?"* Because `IS1002a` is absent from the corpus, any system claiming to find the kickoff price is hallucinating or mistaking meeting `b` for kickoff. |
| **Multi-Meeting Assumption** | *"Every one needs more than one meeting to answer."* | **Not all questions require multiple meetings** | Partial inaccuracy | Several questions (e.g. Q02, Q04, Q14) can be answered directly from the final meeting (`d` or `c`) if seeking the final consensus. Q09 cannot be answered from *any* meeting. Cross-meeting retrieval is required to trace *why* and *how* decisions evolved, not for every atomic fact. |
| **Speaker Roles Mapping** | *"Each team of four (project manager, industrial designer, user interface designer, marketing)... Speakers are labelled A to D."* | **Role-to-speaker mapping is dynamic and rotates across teams** | Not a fixed 1:1 mapping | Speaker A is NOT always Project Manager; Speaker B is NOT always Industrial Designer. In Team `ES2002`, Speaker A is Industrial Designer and Speaker D is Project Manager. Assuming fixed roles leads to misattribution. |
| **Conversational Turn Distribution** | Implied standard conversational turns (*"unfinished sentences, um and uh"*) | **48,148 turns**<br>Avg: 14 words/turn<br>Max: **736 words** (IS1005b, Spk D)<br>**64 turns > 300 words** | Extreme long-tail distribution | Embedding models like `all-MiniLM-L6-v2` enforce a hard 256 WordPiece token limit. Naive turn chunking silently truncates the tail 70% of long turns, losing critical technical arguments. |
| **Transcription Formatting Quirks** | Implied standard English text | **Non-standard tokenization** (`L_C_D_`, `R_s`, trailing punctuation) | Parsing edge cases | Transcripts write acronyms with underscores (`L_C_D_` for LCD) and abbreviations like `R_s`. Exact string matching fails unless disfluencies and acronym variations are explicitly handled. |

---

## 2. Deep Dive: Word Count & Token Volume Discrepancy

### The Discrepancy
The guideline PDF explicitly states:
> *"transcripts/: 138 real recorded meetings from the AMI Meeting Corpus, about 676,000 words in all."*

When measured across the dataset files provided in `Catalist_AI_Intern_Build_Test_Data.zip`:
- **Raw `.txt` file word count:** **826,709 words** (whitespace-delimited).
- **Raw `.txt` file character count:** **4,470,090 characters**.
- **Spoken turn text word count (database turns):** **676,745 words**.
- **Discrepancy:** The raw files contain **149,964 additional words** (~22.2% larger than the figure cited in the PDF).

### Why This Happened
The original 676,000-word figure was computed *downstream* after parsing out speaker turn bodies, omitting:
1. File header blocks (`File: ES2002a.txt`, participant lists).
2. Speaker identification tags (`Speaker A:`, `Speaker B:`).
3. Timestamp annotations and audio frame markers (`[00:04:12] - [00:04:18]`).

### Impact on Context Windows & Token Budgets
At standard estimation ratios ($1.30\times$ tokens per English word):
- Spoken dialogue alone: $676,745 \times 1.30 \approx \mathbf{879,768\text{ tokens}}$.
- Full raw transcript files: $826,709 \times 1.30 \approx \mathbf{1,074,722\text{ tokens}}$.

**Consequence:** A developer attempting a "prompt stuffing" approach using a 1,000,000-token context window (e.g. Gemini 1.5 Pro or Claude 2.1) fails on raw files because $1.07\text{M} > 1.00\text{M}$ tokens. Even with modern 2M-token models, unanchored prompt stuffing costs \$1.50+ per query and exhibits severe attention degradation ("lost in the middle").

---

## 3. Deep Dive: The Incomplete Teams & The "Ghost Kickoff" Trap

### The PDF Claim
The guideline PDF notes:
> *"(two teams have only three meetings in the corpus)"*

However, the PDF does not specify:
1. Which teams are incomplete.
2. Which meeting phases are absent.

### Empirical Reality (MeetingOS Coverage Registry)
Through automated schema auditing during Gate 1 ingestion, MeetingOS established:
- **33 Teams:** Complete 4-meeting histories (`a` = Kickoff, `b` = Functional Design, `c` = Conceptual Design, `d` = Detailed Design / Final).
- **Team `IS1002`:** Contains meetings `b`, `c`, `d`. **Meeting `a` is absent.**
- **Team `IS1005`:** Contains meetings `a`, `b`, `c`. **Meeting `d` is absent.**

### The Trap in `questions.json` (Question Q09)
Question `Q09` in the provided evaluation set asks:
> *"What was the target selling price decided in the kickoff meeting of Team IS1002?"*

Because `IS1002a` does not exist in the corpus:
- There is **no recorded kickoff meeting** for Team `IS1002`.
- The earliest meeting in the corpus for `IS1002` is meeting `b`, where Speaker A states *"Twenty-five Euros is the selling price, we really have to innovate here I guess"*.
- **The Failure Mode:** Naive agents retrieve the 25 Euro quote from `IS1002b` and claim it was decided in the kickoff meeting. This is factually false: meeting `b` is the functional design phase, not the kickoff.
- **MeetingOS Mitigation:** The `team_coverage` registry alerts `AgentPlanner` before retrieval begins. Recognizing that kickoff meeting `a` is missing, the system emits an **honest coverage-aware abstention** with 0 citations:
  > *"System abstains: Corpus does not contain the kickoff meeting ('a') for Team IS1002. Earliest available meeting is IS1002b."*

Similarly, for Team `IS1005`, meeting `d` is missing. Any question asking for Team IS1005's "final prototype", "final casing material", or "ultimate conclusion" must trigger an honest abstention.

---

## 4. Deep Dive: The Myth of Static Speaker Roles

### The PDF Claim
> *"Each team of four (project manager, industrial designer, user interface designer, marketing)... Speakers are labelled A to D."*

This phrasing implies a fixed mapping (e.g. Speaker A = Project Manager, Speaker B = Industrial Designer, etc.).

### Empirical Reality
The AMI Meeting Corpus assigns speaker letters A, B, C, D based on **physical seating position around the table**, NOT job role:

| Team ID | Speaker A | Speaker B | Speaker C | Speaker D |
|---|---|---|---|---|
| **`ES2002`** | Industrial Designer | User Interface Designer | Marketing Expert | **Project Manager** |
| **`ES2003`** | **Project Manager** | User Interface Designer | Industrial Designer | Marketing Expert |
| **`ES2008`** | **Project Manager** | Industrial Designer | User Interface Designer | Marketing Expert |
| **`IS1002`** | **Project Manager** | User Interface Designer | Industrial Designer | Marketing Expert |
| **`TS3012`** | **Project Manager** | User Interface Designer | Industrial Designer | Marketing Expert |

### Engineering Consequence
Any heuristic that hard-codes `Speaker A` as the Project Manager causes severe misattribution in teams like `ES2002`, where Speaker D is the Project Manager and Speaker A is the Industrial Designer. MeetingOS solves this via dynamic role extraction in `SpeakerRoleDetector`, scanning introductory turns to extract each participant's actual corporate title.

---

## 5. Deep Dive: "Every Question Needs More Than One Meeting"

### The PDF Claim
> *"questions.json: 25 questions. Every one needs more than one meeting to answer."*

### Empirical Reality
While the design intent of the assessment is cross-meeting reasoning, several questions in `questions.json` do not strictly require multiple meetings to answer the explicit question asked:
1. **`Q02` ("What casing material did Team ES2003 decide on in their final meeting?"):**  
   The final meeting is explicitly `ES2003d`. The binding decision (*plastic casing with rubber grip*) is stated directly in `ES2003d`. While meeting `c` provides historical background on earlier rubber ball concepts, answering the question as phrased only strictly requires `ES2003d`.
2. **`Q04` ("What power source configuration did Team TS3011 settle on?"):**  
   Settled within meeting `TS3011c` (battery power after discussing kinetic/solar).
3. **`Q09` ("Kickoff meeting of Team IS1002"):**  
   Requires zero meetings to answer because the meeting does not exist; the correct response is an honest abstention.

**Engineering Insight:** Temporal multi-meeting retrieval is crucial for questions regarding **feature cuts** (e.g. TS3006 speech drop in meeting `d` after being championed in meetings `b` and `c`), **concept evolution** (e.g. ES2011 iPod touch wheel in `b` evolving to fruit/vegetable theme in `c`), and **pre-meeting executive briefs**. However, treating "multi-meeting" as a rigid retrieval constraint for every question causes agents to force irrelevant citations from earlier meetings.

---

## 6. Deep Dive: Turn Word Distribution & The MiniLM Truncation Ceiling

### The Long-Tail Problem
In conversational speech corpora, the average turn is short (14 words), but formal presentations create massive monologue turns:
- **Corpus Average Turn:** 14 words (~18 tokens).
- **Turns Exceeding 100 Words:** 1,284 turns.
- **Turns Exceeding 300 Words:** **64 turns**.
- **Longest Turn in Corpus:** **736 words (~980 tokens)** (Meeting `IS1005b`, Speaker D, `turn_index` 18,412).

### The Tool Breakage
Most modern dense embedding models (including `sentence-transformers/all-MiniLM-L6-v2`) have a hard context ceiling of **256 WordPiece tokens**:
$$\text{Max Sequence Length} = 256\text{ tokens} \approx 190\text{ words}$$

If a system naively embeds conversational turns:
- Any turn exceeding 190 words is **silently truncated** at token 256.
- The remaining 500+ words of the monologue are discarded without raising an exception.
- In AMI, these monologues are precisely the slides where project managers present budget constraints and industrial designers present component costs!

### MeetingOS Solution: `LongTurnSplitter`
MeetingOS Layer 2 inspects turn length prior to embedding. Any turn exceeding 256 tokens is partitioned into overlapping sub-chunks ($s=128$ token stride), expanding indexed vectors from 23,901 to 25,772 without data loss.

---

## 7. Deep Dive: Citation Verification vs. Spoken Disfluencies

### The PDF Rule
> *"Citations are checked word for word... at least six words."*

### Empirical Speech Challenges
Real conversation includes disfluencies that break naive exact-string matching:
1. **Acronym Transcription:** The AMI corpus uses underscores for acronyms (e.g. `L_C_D_` for LCD, `T_V_` for TV, `D_V_D_` for DVD). If an agent outputs *"LCD screen"*, an exact quote check fails against `"L_C_D_ screen"`.
2. **False Starts and Stuttering:** Transcripts faithfully capture real speech disfluencies (e.g. *"We uh we we haven't really integrated this"* or *"S Fo Four less Euros"*). If an LLM synthesizer cleans up the grammar to *"We haven't really integrated this"*, the citation validator rejects it.
3. **Staccato Multi-Turn Consensus:** A critical consensus is frequently reached in fragments:
   - Speaker A: *"Dump titanium?"* (2 words)
   - Speaker C: *"Yeah, too expensive."* (3 words)
   - Speaker A: *"Plastic it is."* (3 words)  
   None of these individual turns meet the 6-word minimum!

### MeetingOS Solution
MeetingOS enforces strict verbatim substring extraction directly from the immutable `turns` table. Rather than allowing an LLM to generate candidate quotation strings, the synthesizer selects contiguous word spans directly from retrieved SQLite turns, guaranteeing 100% first-pass deterministic validation.

---

## 8. Summary: How MeetingOS Handled Reality Over Assumption

| Guideline PDF Assumption | Reality Discovered | MeetingOS Architecture Solution |
|---|---|---|
| ~676K words total | 826.7K raw words / 676.7K spoken words | Separated raw byte offsets from parsed turn text; indexed both |
| ~880K tokens | 1.07M raw tokens / 879.7K spoken tokens | Bounded hybrid RRF retrieval; eliminated monolithic prompt stuffing |
| Two unspecified incomplete teams | `IS1002` (missing `a`), `IS1005` (missing `d`) | First-class `team_coverage` registry; coverage-aware honest abstentions |
| Static Speaker A–D roles | Dynamic role allocation per team | Dynamic `SpeakerRoleDetector` extracting titles from introductory turns |
| Every question needs multiple meetings | Some questions are atomic / Q09 impossible | Dynamic multi-meeting expansion when warranted; honest abstention for Q09 |
| Standard conversational turns | 64 turns > 300 words (max 736 words) | `LongTurnSplitter` preventing silent 256-token tail truncation |
| Clean verbatim citations | Speech disfluencies (`L_C_D_`, stuttering) | Pure Python deterministic SQLite substring matching against raw turn records |

---

*Report compiled by Harol Maxilan — MeetingOS Engineering Team.*
