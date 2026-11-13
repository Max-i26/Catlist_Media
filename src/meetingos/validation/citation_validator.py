"""Deterministic citation validator.

This is NOT an LLM component. Every decision here is a pure Python function.

Two operations are strictly separated:
1. normalize_for_matching() — used ONLY for validation comparison
2. Output in answers.json — always the original quote, never normalized

The validator proves a quote EXISTS in the source. It does NOT prove
the quote SUPPORTS the answer. That is a separate human/LLM check.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from enum import Enum

from meetingos.models import CitationResult


def normalize_for_matching(text: str) -> str:
    """
    Normalize text for citation matching ONLY.

    Rules (from questions.json: "case and spacing are ignored"):
    - Collapse all whitespace (spaces, tabs, newlines) to single space
    - Convert to lowercase (casefold for Unicode correctness)

    This function is NEVER applied to output. The original quote is
    always preserved exactly in answers.json.
    """
    return " ".join(text.split()).casefold()


@dataclass(frozen=True)
class CitationValidationResult:
    result:     CitationResult
    meeting_id: str
    quote:      str
    # On success, the matched turn_id for auditability
    matched_turn_id: str | None = None
    matched_in_text: str | None = None


def validate_citation(
    meeting_id: str,
    quote: str,
    conn: sqlite3.Connection,
) -> CitationValidationResult:
    """
    Deterministically validate one citation against source memory.

    Returns CitationValidationResult. Never raises on bad input.

    Steps:
    1. Meeting ID must exist in source DB
    2. Quote must be ≥ 6 words
    3. Normalized quote must be found as substring in a turn from that meeting
    4. Attribution: the matching turn must belong to the stated meeting_id

    Does NOT check whether the quote supports the answer (separate concern).
    """
    # Step 1: meeting exists
    row = conn.execute(
        "SELECT COUNT(*) AS cnt FROM turns WHERE meeting_id = ?",
        (meeting_id,),
    ).fetchone()
    if row["cnt"] == 0:
        return CitationValidationResult(
            result=CitationResult.MEETING_NOT_FOUND,
            meeting_id=meeting_id,
            quote=quote,
        )

    # Step 2: quote length
    if len(quote.split()) < 6:
        return CitationValidationResult(
            result=CitationResult.QUOTE_TOO_SHORT,
            meeting_id=meeting_id,
            quote=quote,
        )

    # Step 3+4: normalized substring match in a turn from this meeting
    norm_quote = normalize_for_matching(quote)

    turns = conn.execute(
        "SELECT turn_id, text FROM turns WHERE meeting_id = ?",
        (meeting_id,),
    ).fetchall()

    for turn in turns:
        norm_turn = normalize_for_matching(turn["text"])
        if norm_quote in norm_turn:
            return CitationValidationResult(
                result=CitationResult.VALID,
                meeting_id=meeting_id,
                quote=quote,                        # original preserved
                matched_turn_id=turn["turn_id"],
                matched_in_text=turn["text"],       # original source text
            )

    return CitationValidationResult(
        result=CitationResult.QUOTE_NOT_FOUND,
        meeting_id=meeting_id,
        quote=quote,
    )


def validate_all_citations(
    answers: list[dict],
    conn: sqlite3.Connection,
) -> dict[str, list[CitationValidationResult]]:
    """
    Validate all citations across all answers.

    Returns mapping of question_id → list of validation results.
    Gate 5 fails if any result is not VALID (unless the answer is an abstention).
    """
    results: dict[str, list[CitationValidationResult]] = {}
    for answer in answers:
        qid = answer["question_id"]
        results[qid] = []
        for citation in answer.get("citations", []):
            result = validate_citation(
                meeting_id=citation["meeting_id"],
                quote=citation["quote"],
                conn=conn,
            )
            results[qid].append(result)
    return results


def citation_validity_rate(
    validation_results: dict[str, list[CitationValidationResult]],
) -> float:
    """
    Citation Validity = (Valid citations / Total citations) × 100

    Abstentions (empty citation lists) are excluded from the denominator.
    """
    total = sum(len(v) for v in validation_results.values())
    if total == 0:
        return 0.0
    valid = sum(
        1 for results in validation_results.values()
        for r in results
        if r.result == CitationResult.VALID
    )
    return (valid / total) * 100.0
