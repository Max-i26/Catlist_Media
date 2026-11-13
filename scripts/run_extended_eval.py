r"""
MeetingOS Extended Evaluation Harness — 135 Questions
=======================================================
Runs all 135 questions against the production stack, validates:
  1. Citation determinism (verbatim ≥6 words, meeting_id exists in DB)
  2. Abstention correctness (IS1002 'a' and IS1005 'd' questions)
  3. Consistency across repeated calls (optional second-pass flag)
  4. Answer quality dimensions (material named, feature named, etc.)
  5. Per-category pass rate summary

Usage:
  cd D:\Catalist_Media\meetingos
  python scripts/run_extended_eval.py [--second-pass] [--limit N] [--category CATEGORY]
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path
from typing import Optional

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# ── path bootstrap ──────────────────────────────────────────────
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from meetingos.config import DB_PATH, FAISS_DIR
from meetingos.memory.schema import get_connection
from meetingos.memory.source import SourceMemory
from meetingos.processing.indexer import LexicalIndexer, TeamVectorIndexer
from meetingos.processing.embedder import TextEmbedder
from meetingos.retrieval.hybrid import HybridRetriever
from meetingos.agent.orchestrator import AgentOrchestrator
from meetingos.agent.tools import AgentTools
from meetingos.validation.citation_validator import validate_citation, CitationResult

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("extended_eval")

BANK_PATH = Path(__file__).parent.parent / "outputs" / "extended_eval_bank.json"
RESULTS_PATH = Path(__file__).parent.parent / "outputs" / "extended_eval_results.json"
REPORT_PATH = Path(__file__).parent.parent / "outputs" / "extended_eval_report.md"

# ── quality checkers ────────────────────────────────────────────

MATERIAL_TERMS = ["plastic", "rubber", "titanium", "wood", "latex", "metal", "aluminium", "aluminum"]
ENERGY_TERMS = ["battery", "kinetic", "solar", "dynamo", "rechargeable", "power source", "energy"]


def check_names_material(answer: str) -> bool:
    al = answer.lower()
    return any(t in al for t in MATERIAL_TERMS)


def check_names_energy(answer: str) -> bool:
    al = answer.lower()
    return any(t in al for t in ENERGY_TERMS)


def check_citation_valid(cit: dict, conn) -> tuple[bool, str]:
    """Returns (is_valid, reason)."""
    quote = cit.get("quote", "")
    meeting_id = cit.get("meeting_id", "")
    if not quote or not meeting_id:
        return False, "Missing quote or meeting_id"
    if len(quote.split()) < 6:
        return False, f"Quote too short ({len(quote.split())} words < 6)"
    result = validate_citation(meeting_id, quote, conn)
    if result.result == CitationResult.VALID:
        return True, "VALID"
    return False, f"{result.result.value}: {result.message}"


def evaluate_question(q: dict, answer: dict, conn) -> dict:
    """Score one question-answer pair."""
    ev = {
        "question_id": q["question_id"],
        "team_id": q["team_id"],
        "category": q["category"],
        "question": q["question"],
        "expected_abstain": q.get("expected_abstain", False),
        "did_abstain": answer.get("abstained", False),
        "answer": answer.get("answer", ""),
        "citations": answer.get("citations", []),
        "issues": [],
        "passed": True,
    }

    # 1. Abstention correctness
    if ev["expected_abstain"] and not ev["did_abstain"]:
        ev["issues"].append("FAIL: Expected abstention but answer was produced")
        ev["passed"] = False
    elif not ev["expected_abstain"] and ev["did_abstain"]:
        ev["issues"].append("FAIL: Abstained but evidence should exist")
        ev["passed"] = False

    # 2. Citation validation
    if not ev["did_abstain"]:
        if not ev["citations"]:
            ev["issues"].append("FAIL: No citations returned for non-abstained answer")
            ev["passed"] = False
        else:
            citation_pass = True
            for idx, cit in enumerate(ev["citations"]):
                valid, reason = check_citation_valid(cit, conn)
                if not valid:
                    ev["issues"].append(f"FAIL: Citation {idx+1} invalid — {reason}")
                    citation_pass = False
                    ev["passed"] = False
            if citation_pass:
                ev["issues"].append(f"OK: All {len(ev['citations'])} citation(s) pass deterministic validation")

        # 3. Category-specific answer quality
        if ev["category"] == "casing_material":
            if not check_names_material(ev["answer"]):
                ev["issues"].append("WARN: Answer does not name a specific material (plastic/rubber/wood/titanium etc.)")
                # Downgrade but don't fail (may be a valid abstain-ish edge case)
        elif ev["category"] == "energy_source":
            if not check_names_energy(ev["answer"]):
                ev["issues"].append("WARN: Answer does not name a specific energy source (battery/kinetic/solar etc.)")

        # 4. Broken sentence / truncation check
        answer_text = ev["answer"]
        if answer_text.endswith(("so we", "that we", "so the", "and the", "in the")):
            ev["issues"].append("WARN: Answer ends mid-sentence — possible truncation")

        # 5. Speaker attribution present
        if ev["citations"] and all("speaker" not in ev["answer"].lower() and "Speaker" not in ev["answer"] for _ in [1]):
            ev["issues"].append("NOTE: Answer does not attribute any citation to a named speaker")

    # 6. Citation count contract
    cit_count = len(ev["citations"])
    if not ev["did_abstain"]:
        if cit_count < 1:
            ev["issues"].append("FAIL: Zero citations on non-abstained answer")
            ev["passed"] = False
        elif cit_count > 3:
            ev["issues"].append(f"FAIL: {cit_count} citations exceeds contract max of 3")
            ev["passed"] = False

    return ev


def run_question(orch: AgentOrchestrator, q: dict) -> dict:
    """Run one question through the orchestrator; return dict."""
    t0 = time.monotonic()
    try:
        answer = orch.run_question(
            question_id=q["question_id"],
            question_text=q["question"],
            team_id=q.get("team_id"),
        )
        elapsed = time.monotonic() - t0
        return {
            "question_id": answer.question_id,
            "answer": answer.answer,
            "citations": [{"meeting_id": c.meeting_id, "quote": c.quote} for c in answer.citations],
            "abstained": answer.abstained,
            "elapsed_s": round(elapsed, 2),
        }
    except Exception as exc:
        elapsed = time.monotonic() - t0
        logger.error(f"Question {q['question_id']} failed: {exc}")
        return {
            "question_id": q["question_id"],
            "answer": f"[ERROR: {type(exc).__name__}: {exc}]",
            "citations": [],
            "abstained": True,
            "error": str(exc),
            "elapsed_s": round(elapsed, 2),
        }


def generate_report(results: list[dict], meta: dict) -> str:
    total = len(results)
    passed = sum(1 for r in results if r["passed"])
    abstained_correctly = sum(1 for r in results if r["expected_abstain"] and r["did_abstain"])
    abstained_incorrectly = sum(1 for r in results if not r["expected_abstain"] and r["did_abstain"])
    total_cits = sum(len(r["citations"]) for r in results)
    valid_cits = sum(
        1 for r in results for issue in r["issues"]
        if issue.startswith("OK: All") and "citation" in issue
    )

    # By category
    cat_stats: dict[str, dict] = {}
    for r in results:
        c = r["category"]
        if c not in cat_stats:
            cat_stats[c] = {"total": 0, "passed": 0, "warns": 0, "fails": 0}
        cat_stats[c]["total"] += 1
        if r["passed"]:
            cat_stats[c]["passed"] += 1
        for issue in r["issues"]:
            if issue.startswith("FAIL"):
                cat_stats[c]["fails"] += 1
            elif issue.startswith("WARN"):
                cat_stats[c]["warns"] += 1

    lines = [
        "# MeetingOS Extended Evaluation Report",
        "",
        f"> Generated over **{total} questions** across all 35 teams",
        "",
        "## Executive Summary",
        "",
        f"| Metric | Value |",
        f"|--------|-------|",
        f"| Total Questions | {total} |",
        f"| **Passed** | **{passed}** ({100*passed//total}%) |",
        f"| Failed | {total-passed} |",
        f"| Correctly Abstained | {abstained_correctly} |",
        f"| Incorrectly Abstained | {abstained_incorrectly} |",
        f"| Total Citations | {total_cits} |",
        f"| Avg Citations / Answer | {total_cits/(total - sum(1 for r in results if r['did_abstain']) or 1):.2f} |",
        "",
        "## Results by Category",
        "",
        "| Category | Questions | Passed | Pass% | Warns | Fails |",
        "|----------|-----------|--------|-------|-------|-------|",
    ]
    for cat, s in sorted(cat_stats.items()):
        pct = 100 * s["passed"] // s["total"] if s["total"] > 0 else 0
        lines.append(f"| {cat} | {s['total']} | {s['passed']} | {pct}% | {s['warns']} | {s['fails']} |")

    lines += [
        "",
        "## Detailed Results",
        "",
    ]

    for r in results:
        status = "✅ PASS" if r["passed"] else "❌ FAIL"
        abst = " (abstained)" if r["did_abstain"] else ""
        lines.append(f"### {r['question_id']} [{r['category']}] — {r['team_id']} {status}{abst}")
        lines.append(f"**Q:** {r['question']}")
        lines.append("")
        if r["did_abstain"]:
            lines.append("*System abstained (no verifiable evidence)*")
        else:
            lines.append(f"**A:** {r['answer']}")
            lines.append("")
            if r["citations"]:
                lines.append("**Citations:**")
                for i, c in enumerate(r["citations"], 1):
                    lines.append(f"{i}. `{c['meeting_id']}` — \"{c['quote']}\"")
        lines.append("")
        if r["issues"]:
            lines.append("**Evaluation notes:**")
            for issue in r["issues"]:
                prefix = "- ⚠️ " if "WARN" in issue else ("- ❌ " if "FAIL" in issue else "- ✅ ")
                lines.append(f"{prefix}{issue}")
        lines.append("")
        lines.append("---")
        lines.append("")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="MeetingOS Extended Evaluation Harness")
    parser.add_argument("--limit", type=int, default=None, help="Max questions to run (for quick smoke tests)")
    parser.add_argument("--category", type=str, default=None, help="Run only this category")
    parser.add_argument("--question-id", type=str, default=None, help="Run only this question ID")
    parser.add_argument("--second-pass", action="store_true", help="Run all questions twice to check consistency")
    parser.add_argument("--use-mock", action="store_true", help="Use mock embedder for rapid testing")
    parser.add_argument("--verbose", "-v", action="store_true", help="Show per-question output")
    args = parser.parse_args()

    # Load question bank
    with open(BANK_PATH, encoding="utf-8") as f:
        bank = json.load(f)

    questions = bank["questions"]

    # Filters
    if args.question_id:
        questions = [q for q in questions if q["question_id"] == args.question_id]
    if args.category:
        questions = [q for q in questions if q["category"] == args.category]
    if args.limit:
        questions = questions[: args.limit]

    print(f"Running {len(questions)} questions...\n")

    # Setup agent
    conn = get_connection(DB_PATH, readonly=False)
    memory = SourceMemory(conn)
    lexical = LexicalIndexer(conn)
    embedder = TextEmbedder(lazy_load=False, use_mock=args.use_mock)
    vector = TeamVectorIndexer(conn, embedder, index_dir=FAISS_DIR)
    retriever = HybridRetriever(lexical, vector, memory)
    tools = AgentTools(conn, retriever, source_memory=memory)
    orch = AgentOrchestrator(conn, tools)

    raw_answers: list[dict] = []
    eval_results: list[dict] = []

    for i, q in enumerate(questions, 1):
        if args.verbose:
            print(f"[{i:3d}/{len(questions)}] {q['question_id']} ({q['category']}) — {q['team_id']}")
        else:
            print(f"\r[{i:3d}/{len(questions)}] {q['question_id']}...", end="", flush=True)

        answer = run_question(orch, q)
        raw_answers.append(answer)
        ev = evaluate_question(q, answer, conn)
        eval_results.append(ev)

        if args.verbose:
            status = "[PASS]" if ev["passed"] else "[FAIL]"
            issue_str = ev['issues'][0] if ev['issues'] else 'OK'
            print(f"  {status} {issue_str}")

    print(f"\n\nCompleted {len(questions)} questions.")

    # Consistency second pass
    if args.second_pass:
        print("\nRunning second pass for consistency check...")
        consistency_issues = []
        for i, q in enumerate(questions, 1):
            answer2 = run_question(orch, q)
            a1_text = raw_answers[i-1].get("answer", "")
            a2_text = answer2.get("answer", "")
            if a1_text.strip() != a2_text.strip():
                consistency_issues.append({
                    "question_id": q["question_id"],
                    "pass1": a1_text,
                    "pass2": a2_text,
                })
                print(f"  ⚠️  Inconsistency in {q['question_id']}")
        print(f"Consistency issues: {len(consistency_issues)} / {len(questions)}")

    # Save raw results
    output = {
        "metadata": bank["metadata"],
        "run_info": {
            "questions_run": len(questions),
            "passed": sum(1 for r in eval_results if r["passed"]),
            "failed": sum(1 for r in eval_results if not r["passed"]),
            "abstained": sum(1 for r in eval_results if r["did_abstain"]),
        },
        "answers": raw_answers,
        "evaluation": eval_results,
    }
    with open(RESULTS_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    print(f"Results saved to {RESULTS_PATH}")

    # Generate report
    report_md = generate_report(eval_results, bank["metadata"])
    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        f.write(report_md)
    print(f"Report saved to {REPORT_PATH}")

    # Summary
    total = len(eval_results)
    passed = sum(1 for r in eval_results if r["passed"])
    print(f"\n{'='*50}")
    print(f"PASS: {passed}/{total} ({100*passed//total}%)")
    print(f"FAIL: {total-passed}/{total}")
    abstained_correctly = sum(1 for r in eval_results if r["expected_abstain"] and r["did_abstain"])
    print(f"Correct abstentions: {abstained_correctly}/{sum(1 for q in questions if q.get('expected_abstain'))}")

    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
