"""Coverage-aware question decomposition and execution planning.

Decomposes complex temporal and multi-meeting questions into focused
sub-questions and search directives, with strict coverage awareness.
"""
from __future__ import annotations

import re
from typing import Optional
from pydantic import BaseModel, Field

from meetingos.agent.tools import AgentTools
from meetingos.config import MAX_SUB_QUESTIONS
from meetingos.models import TeamCoverage


class SubQuestion(BaseModel):
    """A decomposed sub-goal within a question's investigation plan."""
    id: str
    query_text: str
    keywords: list[str] = Field(default_factory=list)
    target_sequence: Optional[str] = None   # 'a', 'b', 'c', 'd', or None (any)
    aspect: str = "general"                 # "initial_proposal", "change", "final_decision", "attribution", "numeric"


class ExecutionPlan(BaseModel):
    """The complete execution plan for answering a question."""
    question_id: str
    original_question: str
    team_id: str
    coverage: TeamCoverage
    coverage_warning: Optional[str] = None
    sub_questions: list[SubQuestion] = Field(max_length=MAX_SUB_QUESTIONS)
    team_meetings: list[str]
    target_sequence: Optional[str] = None
    requires_abstention: bool = False
    abstention_reason: Optional[str] = None


class AgentPlanner:
    """Plans retrieval and synthesis by analyzing questions and corpus coverage."""

    def __init__(self, tools: AgentTools):
        self.tools = tools

    def extract_team_id(self, question_text: str, explicit_team: Optional[str] = None) -> str:
        """Extract or validate the team ID mentioned in the question."""
        if explicit_team:
            return explicit_team.strip()
        match = re.search(r"\b(TS\d{4}|ES\d{4}|IS\d{4})\b", question_text)
        if match:
            return match.group(1)
        raise ValueError(f"Could not determine team ID from question: '{question_text}'")

    def create_plan(
        self,
        question_id: str,
        question_text: str,
        team_id: Optional[str] = None,
    ) -> ExecutionPlan:
        """
        Build a coverage-aware execution plan for a question.

        Enforces:
        - Strict coverage awareness: flags missing meetings if team history is partial.
        - Question decomposition: bounded to at most MAX_SUB_QUESTIONS (6).
        - Temporal separation: plans distinct queries across early and late meeting sequences.
        """
        tid = self.extract_team_id(question_text, team_id)
        coverage = self.tools.get_team_coverage(tid)
        if not coverage:
            raise ValueError(f"No coverage registry record for team {tid}")

        coverage_warning = None
        requires_abstention = False
        abstention_reason = None
        q_lower = question_text.lower()

        if not coverage.is_complete:
            missing = ", ".join(coverage.missing_sequences)
            coverage_warning = (
                f"Team {tid} corpus is incomplete (missing meeting {missing}). "
                f"Earliest available is {coverage.earliest_available}, "
                f"latest available is {coverage.latest_available}."
            )
            # Check if query targets a missing meeting phase
            missing_seqs = coverage.missing_sequences
            if "a" in missing_seqs and any(
                w in q_lower for w in ["kickoff", "kick-off", "meeting a", "first meeting", "initial meeting"]
            ):
                requires_abstention = True
                abstention_reason = (
                    f"The actual kickoff meeting ({tid}a) is missing from the available corpus. "
                    f"The earliest available meeting is {tid}{coverage.earliest_available}, "
                    f"so MeetingOS cannot reliably establish what was decided during the kickoff."
                )
            elif "d" in missing_seqs and any(
                w in q_lower for w in ["detailed design", "final meeting", "meeting d", "last meeting", "final design", "ultimate", "final conclusion"]
            ):
                requires_abstention = True
                abstention_reason = (
                    f"The actual detailed design meeting ({tid}d) is missing from the available corpus. "
                    f"The latest available meeting is {tid}{coverage.latest_available}, "
                    f"so MeetingOS cannot reliably establish what was decided during the final meeting."
                )

        # Detect targeted meeting phase
        target_seq = None
        if any(w in q_lower for w in ["final meeting", "meeting d", "last meeting", "final design", "decide on in their final"]):
            target_seq = "d"
        elif any(w in q_lower for w in ["kickoff", "kick-off", "meeting a", "first meeting", "initial meeting"]):
            target_seq = "a"

        team_meetings = self.tools.get_all_meetings_for_team(tid)
        sub_questions = self._decompose_question(question_text, tid, team_meetings, target_seq)

        return ExecutionPlan(
            question_id=question_id,
            original_question=question_text,
            team_id=tid,
            coverage=coverage,
            coverage_warning=coverage_warning,
            sub_questions=sub_questions[:MAX_SUB_QUESTIONS],
            team_meetings=team_meetings,
            target_sequence=target_seq,
            requires_abstention=requires_abstention,
            abstention_reason=abstention_reason,
        )

    def _decompose_question(
        self,
        question_text: str,
        team_id: str,
        team_meetings: list[str],
        target_sequence: Optional[str] = None,
    ) -> list[SubQuestion]:
        """
        Decompose the question into structured sub-goals based on linguistic patterns.
        """
        q_lower = question_text.lower()
        sub_questions: list[SubQuestion] = []
        sq_idx = 1

        # Extract salient entities/topics from question
        # Stopwords to remove from core entity extraction
        stopwords = {
            "team", team_id.lower(), "remote", "control", "the", "a", "an", "what", "which",
            "who", "when", "why", "how", "did", "they", "their", "its", "was", "were", "is",
            "are", "to", "in", "of", "for", "and", "or", "on", "with", "at", "by", "from",
            "first", "later", "final", "end", "meeting", "meetings", "design", "decide",
            "settle", "change", "changed", "switch", "switched", "cost", "costs", "budget"
        }
        words = re.findall(r"\b[a-zA-Z]{3,}\b", q_lower)
        topic_keywords = [w for w in words if w not in stopwords]

        domain_synonyms = {
            "casing": ["plastic", "rubber", "titanium", "wood", "latex", "case", "material"],
            "material": ["plastic", "rubber", "titanium", "wood", "latex", "case", "casing"],
            "materials": ["plastic", "rubber", "titanium", "wood", "latex", "case", "casing"],
            "power": ["battery", "kinetic", "solar", "dynamo", "energy", "supply"],
            "energy": ["battery", "kinetic", "solar", "dynamo", "power", "supply"],
            "feature": ["speech", "voice", "recognition", "screen", "lcd", "display", "locator"],
            "drop": ["speech", "voice", "recognition", "cut", "scrap", "screen", "lcd"],
            "budget": ["price", "cost", "euros", "euro", "expensive", "production"],
            "price": ["cost", "budget", "euros", "euro", "selling", "production"],
        }
        domain_additions = []
        for term, syns in domain_synonyms.items():
            if term in q_lower:
                for s in syns:
                    if s not in topic_keywords and s not in domain_additions:
                        domain_additions.append(s)
        topic_keywords = topic_keywords + domain_additions

        # 1. Early stage / initial proposal or baseline
        early_target = "a" if "a" in [m[-1] for m in team_meetings] else "b"
        sub_questions.append(
            SubQuestion(
                id=f"SQ{sq_idx}",
                query_text=f"{' '.join(topic_keywords[:8])} initial proposal discuss",
                keywords=topic_keywords[:6],
                target_sequence=early_target,
                aspect="initial_proposal",
            )
        )
        sq_idx += 1

        # 2. Intermediate change / debate / objection / cost pressure
        if any(w in q_lower for w in ["cost", "budget", "cut", "price", "expensive"]):
            sub_questions.append(
                SubQuestion(
                    id=f"SQ{sq_idx}",
                    query_text=f"{' '.join(topic_keywords[:8])} cost budget price cut limit",
                    keywords=["cost", "budget", "price"] + topic_keywords[:4],
                    target_sequence=None,
                    aspect="numeric",
                )
            )
            sq_idx += 1

        if any(w in q_lower for w in ["change", "switch", "drop", "keep", "replace", "objection", "disagree"]):
            sub_questions.append(
                SubQuestion(
                    id=f"SQ{sq_idx}",
                    query_text=f"{' '.join(topic_keywords[:8])} change switch replace drop objection instead",
                    keywords=["change", "switch", "replace", "drop"] + topic_keywords[:4],
                    target_sequence=None,
                    aspect="change",
                )
            )
            sq_idx += 1

        # 3. Attribution / who proposed or checked
        if any(w in q_lower for w in ["who", "speaker", "project manager", "member"]):
            sub_questions.append(
                SubQuestion(
                    id=f"SQ{sq_idx}",
                    query_text=f"{' '.join(topic_keywords[:8])} I think suggest agree check look into",
                    keywords=["suggest", "propose", "check"] + topic_keywords[:4],
                    target_sequence=None,
                    aspect="attribution",
                )
            )
            sq_idx += 1

        # 4. Final outcome / final decision in latest meeting
        late_target = "d" if "d" in [m[-1] for m in team_meetings] else "c"
        sub_questions.append(
            SubQuestion(
                id=f"SQ{sq_idx}",
                query_text=f"{' '.join(topic_keywords[:8])} final design decide conclusion end",
                keywords=["final", "decide", "conclusion"] + topic_keywords[:4],
                target_sequence=late_target,
                aspect="final_decision",
            )
        )
        sq_idx += 1

        # 4B. Conceptual design (c) if 4 meetings exist and no specific sequence targeted
        if not target_sequence and "c" in [m[-1] for m in team_meetings] and late_target != "c":
            sub_questions.append(
                SubQuestion(
                    id=f"SQ{sq_idx}",
                    query_text=f"{' '.join(topic_keywords[:8])} options components evaluate",
                    keywords=topic_keywords[:4],
                    target_sequence="c",
                    aspect="conceptual_design",
                )
            )
            sq_idx += 1

        # 5. Core direct query from the full question text
        sub_questions.append(
            SubQuestion(
                id=f"SQ{sq_idx}",
                query_text=f"{' '.join(topic_keywords[:8])}",
                keywords=topic_keywords[:4],
                target_sequence=None,
                aspect="general",
            )
        )

        if target_sequence == "d":
            sub_questions.sort(key=lambda sq: 0 if sq.aspect == "final_decision" else (1 if sq.target_sequence == "d" else 2))
        elif target_sequence == "a":
            sub_questions.sort(key=lambda sq: 0 if sq.aspect == "initial_proposal" else (1 if sq.target_sequence == "a" else 2))

        return sub_questions
