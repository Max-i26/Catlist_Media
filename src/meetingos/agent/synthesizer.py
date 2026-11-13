"""Evidence-grounded answer synthesizer and citation extractor.

Enforces:
1. Exact contract: 1 to 3 plain sentences per answer.
2. Speaker identification: speaker letter (Speaker A, B, C, D) and role if evident.
3. Citation discipline: 1 to 3 citations, each >= 6 words copied verbatim from a single speaker turn.
4. Multi-meeting evidence: ensures citations/evidence span at least two meetings when available.
5. Verifiable truth: every citation is deterministically validated before emission; invalid citations are pruned.
6. Honest abstention: when evidence is absent, abstains with 0 citations.
"""
from __future__ import annotations

import re
import sqlite3
from typing import Optional

from meetingos.agent.planner import ExecutionPlan
from meetingos.models import Answer, Citation, CitationResult, ExpandedEvidence, Turn
from meetingos.validation.citation_validator import normalize_for_matching, validate_citation


class SpeakerRoleDetector:
    """Detects speaker roles from meeting introductions and transcript statements."""

    ROLE_PATTERNS = [
        ("Project Manager", re.compile(r"\b(?:project manager|p\.?m\.?)\b", re.I)),
        ("Industrial Designer", re.compile(r"\b(?:industrial design(?:er)?|i\.?d\.?)\b", re.I)),
        ("User Interface Designer", re.compile(r"\b(?:user interface(?: designer)?|u\.?i\.?)\b", re.I)),
        ("Marketing Expert", re.compile(r"\b(?:marketing(?: expert)?)\b", re.I)),
    ]

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self._cache: dict[str, dict[str, str]] = {}

    def get_team_roles(self, team_id: str) -> dict[str, str]:
        """Return map of speaker_id -> role name for the team."""
        if team_id in self._cache:
            return self._cache[team_id]

        roles: dict[str, str] = {}
        # In AMI, Speaker A is consistently Project Manager
        roles["A"] = "Project Manager"

        # Scan first meeting of the team
        rows = self.conn.execute(
            """
            SELECT speaker_id, text
            FROM turns
            WHERE team_id = ?
            ORDER BY turn_index ASC
            LIMIT 300
            """,
            (team_id,),
        ).fetchall()

        for r in rows:
            spk = r["speaker_id"]
            text = r["text"]
            for role_name, pat in self.ROLE_PATTERNS:
                if role_name not in roles.values() and pat.search(text):
                    # Check for self-identification or direct assignment
                    if any(
                        intro in text.lower()
                        for intro in ["i am", "i'm", "my role", "as the", "for the", "you are", "you're"]
                    ):
                        roles[spk] = role_name

        self._cache[team_id] = roles
        return roles

    def format_speaker(self, team_id: str, speaker_id: str) -> str:
        """Format speaker as 'Speaker X (Role)' if known, otherwise 'Speaker X'."""
        roles = self.get_team_roles(team_id)
        role = roles.get(speaker_id)
        if role:
            return f"Speaker {speaker_id} ({role})"
        return f"Speaker {speaker_id}"


class EvidenceSynthesizer:
    """Synthesizes evidence-grounded answers with strictly verified citations."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.role_detector = SpeakerRoleDetector(conn)

    def extract_candidate_quotes(
        self,
        turn: Turn,
        keywords: list[str],
        min_words: int = 6,
        max_words: int = 35,
    ) -> list[str]:
        """
        Extract coherent verbatim substrings (sentences or clauses) >= min_words
        from a turn that contain the relevant keywords.
        """
        text = turn.text.strip()
        if len(text.split()) < min_words:
            return []

        # Split into sentences or clauses
        raw_clauses = re.split(r"(?<=[.!?])\s+", text)
        candidates = []

        for clause in raw_clauses:
            clause = clause.strip()
            word_count = len(clause.split())
            if word_count >= min_words and word_count <= max_words:
                candidates.append(clause)
            elif word_count > max_words:
                # If clause is very long, split into comma/semicolon phrases of >= min_words
                sub_parts = re.split(r"[,;]\s*", clause)
                current_sub = []
                for sp in sub_parts:
                    current_sub.append(sp.strip())
                    joined = " ".join(current_sub)
                    if len(joined.split()) >= min_words:
                        if len(joined.split()) <= max_words:
                            candidates.append(joined)
                        current_sub = []

        # If no clause matched length boundaries but whole turn >= min_words
        if not candidates and len(text.split()) >= min_words:
            words = text.split()
            # Pick first 12-20 words
            take = min(len(words), 20)
            candidates.append(" ".join(words[:take]))

        if not keywords:
            return candidates

        # Sort candidates by keyword presence
        def score_candidate(cand: str) -> int:
            cand_lower = cand.lower()
            return sum(1 for kw in keywords if kw.lower() in cand_lower)

        matching = [c for c in candidates if score_candidate(c) > 0]
        matching.sort(key=score_candidate, reverse=True)
        return matching

    def find_verified_citations_for_team(
        self,
        expanded_evidence: list[ExpandedEvidence],
        keywords: list[str],
        max_citations: int = 3,
        prefer_multi_meeting: bool = True,
        target_meeting_sequence: Optional[str] = None,
        required_entity_terms: Optional[list[str]] = None,
    ) -> list[Citation]:
        """
        Select 1 to 3 valid citations from the evidence set.
        Guarantees that every citation passes validate_citation() and
        prioritizes multi-meeting coverage (>= 2 distinct meetings) or
        the targeted meeting phase if specified.
        If required_entity_terms is provided, enforces that every citation
        directly supports at least one specific factual claim.
        """
        scored_candidates: list[tuple[int, Citation]] = []
        seen_quotes: set[str] = set()

        for ev in expanded_evidence:
            meeting_id = ev.meeting_id
            for turn in ev.core_turns + ev.context_turns:
                quotes = self.extract_candidate_quotes(turn, keywords)
                for quote in quotes:
                    if quote in seen_quotes:
                        continue

                    # Evidence relevance filter: if specific entity terms required, quote must contain at least one
                    if required_entity_terms:
                        if not any(term.lower() in quote.lower() for term in required_entity_terms):
                            continue

                    val_res = validate_citation(meeting_id, quote, self.conn)
                    if val_res.result == CitationResult.VALID:
                        seen_quotes.add(quote)
                        kw_score = sum(3 for kw in keywords if kw.lower() in quote.lower())
                        bonus = 5 if (target_meeting_sequence and meeting_id.endswith(target_meeting_sequence)) else 0
                        total_score = kw_score + bonus
                        scored_candidates.append((total_score, Citation(meeting_id=meeting_id, quote=quote)))

        if not scored_candidates:
            return []

        # Sort candidates by total_score descending
        scored_candidates.sort(key=lambda x: x[0], reverse=True)

        # Evidence quality gate: filter out weak low-scoring quotes if strong evidence exists
        top_score = scored_candidates[0][0]
        quality_candidates = [
            (score, c) for score, c in scored_candidates
            if score >= max(6, top_score * 0.5)
        ]
        if not quality_candidates:
            quality_candidates = scored_candidates

        # 1. If a specific target meeting sequence was requested (e.g. 'd')
        if target_meeting_sequence:
            target_citations = [c for score, c in quality_candidates if c.meeting_id.endswith(target_meeting_sequence)]
            if target_citations:
                return target_citations[:max_citations]

        # 2. Multi-meeting selection if prefer_multi_meeting and >= 2 meetings represented
        if prefer_multi_meeting:
            by_meeting: dict[str, list[Citation]] = {}
            for score, c in quality_candidates:
                if c.meeting_id not in by_meeting:
                    by_meeting[c.meeting_id] = []
                by_meeting[c.meeting_id].append(c)

            if len(by_meeting) >= 2:
                final_citations: list[Citation] = []
                # Take top from each meeting
                for m in list(by_meeting.keys())[:max_citations]:
                    if by_meeting[m]:
                        final_citations.append(by_meeting[m][0])
                # Fill remaining slots from best available
                for score, c in quality_candidates:
                    if len(final_citations) >= max_citations:
                        break
                    if c not in final_citations:
                        final_citations.append(c)
                return final_citations[:max_citations]

        # 3. Default: take top by score (without forcing max_citations)
        return [c for score, c in quality_candidates[:max_citations]]

    def build_abstention(self, question_id: str, reason: str) -> Answer:
        """Create an honest abstention answer with 0 citations."""
        # Ensure 1 to 3 plain sentences
        reason_clean = reason.rstrip(".")
        answer_text = (
            f"The meeting transcripts do not contain sufficient evidence to answer this question. {reason_clean}."
        )
        return Answer(
            question_id=question_id,
            answer=answer_text.strip(),
            citations=[],
            abstained=True,
        )

    def validate_answer_sentence_count(self, answer_text: str) -> bool:
        """Verify that answer has between 1 and 3 plain sentences."""
        sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", answer_text.strip()) if s.strip()]
        return 1 <= len(sentences) <= 3
