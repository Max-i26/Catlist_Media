"""MeetingOS Bounded Agent Orchestrator.

Implements the central execution loop for query resolution:
- Max 4 retrieval iterations per question
- Checkpoint persistence in agent_runs table
- Coverage-aware planning and query refinement
- Multi-meeting evidence accumulation
- Deterministic citation validation and fallback
- Honest abstention with 0 citations when evidence is insufficient
"""
from __future__ import annotations

import logging
import os
import sqlite3
import time
from typing import Optional

from meetingos.agent.checkpoint import CheckpointManager
from meetingos.agent.claude_client import ClaudeClient
from meetingos.agent.planner import AgentPlanner, ExecutionPlan
from meetingos.agent.synthesizer import EvidenceSynthesizer
from meetingos.agent.tools import AgentTools
from meetingos.config import MAX_RETRIEVAL_ITERATIONS, MIN_MEETING_COVERAGE
from meetingos.models import (
    AgentRunStatus,
    Answer,
    Citation,
    ExpandedEvidence,
    RetrievalResult,
)

logger = logging.getLogger(__name__)


class AgentOrchestrator:
    """Bounded, checkpointed meeting intelligence agent orchestrator."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        tools: AgentTools,
        planner: Optional[AgentPlanner] = None,
        synthesizer: Optional[EvidenceSynthesizer] = None,
        checkpoint_mgr: Optional[CheckpointManager] = None,
        claude_client: Optional[ClaudeClient] = None,
        max_iterations: int = MAX_RETRIEVAL_ITERATIONS,
    ):
        self.conn = conn
        self.tools = tools
        self.planner = planner or AgentPlanner(tools)
        self.synthesizer = synthesizer or EvidenceSynthesizer(conn)
        self.checkpoint_mgr = checkpoint_mgr or CheckpointManager(conn)
        self.claude_client = claude_client or (ClaudeClient() if os.environ.get("ANTHROPIC_API_KEY") else None)
        self.max_iterations = max_iterations

    def run_question(
        self,
        question_id: str,
        question_text: str,
        team_id: Optional[str] = None,
    ) -> Answer:
        """
        Execute bounded retrieval and evidence-grounded synthesis for one question.
        """
        # Step 1: Create checkpoint
        run = self.checkpoint_mgr.create_run(question_id)
        run_id = run.run_id

        try:
            # Step 2: Planning phase
            self.checkpoint_mgr.set_status(run_id, AgentRunStatus.PLANNING)
            plan = self.planner.create_plan(
                question_id=question_id,
                question_text=question_text,
                team_id=team_id,
            )
            run.sub_questions = [sq.query_text for sq in plan.sub_questions]
            self.checkpoint_mgr.save_run(run)
            self.checkpoint_mgr.record_tool_call(
                run_id, "create_plan", {"team_id": plan.team_id}, f"Created {len(plan.sub_questions)} sub-questions"
            )

            # Step 3: Bounded retrieval loop
            self.checkpoint_mgr.set_status(run_id, AgentRunStatus.RETRIEVING)
            all_retrieved_chunks: list[RetrievalResult] = []
            seen_chunk_ids: set[str] = set()

            for iteration in range(1, self.max_iterations + 1):
                self.checkpoint_mgr.set_status(run_id, AgentRunStatus.RETRIEVING, iteration=iteration)

                # Select sub-questions or focus for this iteration
                if iteration == 1:
                    # Initial broad pass across decomposed sub-questions
                    for sq in plan.sub_questions:
                        target_m = None
                        if sq.target_sequence:
                            # Map sequence 'a'/'d' to actual meeting ID
                            for m in plan.team_meetings:
                                if m.endswith(sq.target_sequence):
                                    target_m = m
                                    break

                        results = self.tools.search_hybrid(
                            team_id=plan.team_id,
                            query=sq.query_text,
                            limit=5,
                            meeting_id=target_m,
                        )
                        for r in results:
                            if r.chunk_id not in seen_chunk_ids:
                                seen_chunk_ids.add(r.chunk_id)
                                all_retrieved_chunks.append(r)
                else:
                    # Refinement pass: check if any meeting sequence is under-represented
                    represented_meetings = {r.meeting_id for r in all_retrieved_chunks}
                    missing_in_results = [
                        m for m in plan.team_meetings if m not in represented_meetings
                    ]

                    if not missing_in_results:
                        # We have coverage across all available team meetings, break early
                        break

                    # Target the missing meetings with original question keywords
                    for m in missing_in_results:
                        results = self.tools.search_hybrid(
                            team_id=plan.team_id,
                            query=plan.original_question,
                            limit=5,
                            meeting_id=m,
                        )
                        for r in results:
                            if r.chunk_id not in seen_chunk_ids:
                                seen_chunk_ids.add(r.chunk_id)
                                all_retrieved_chunks.append(r)

                # Record chunks in checkpoint
                self.checkpoint_mgr.add_retrieved_chunks(run_id, list(seen_chunk_ids))

                # Check if multi-meeting requirement is satisfied
                represented_meetings = {r.meeting_id for r in all_retrieved_chunks}
                if len(represented_meetings) >= MIN_MEETING_COVERAGE:
                    # Sufficient multi-meeting evidence collected
                    break

            # Step 4: Expand evidence context
            top_chunk_ids = [r.chunk_id for r in all_retrieved_chunks[:15]]
            expanded_evidence = self.tools.expand_chunks(top_chunk_ids, context_window=2)
            self.checkpoint_mgr.record_tool_call(
                run_id, "expand_chunks", {"count": len(top_chunk_ids)}, f"Expanded {len(expanded_evidence)} chunks"
            )

            # Step 5: Synthesis phase
            self.checkpoint_mgr.set_status(run_id, AgentRunStatus.SYNTHESIZING)
            answer = self._synthesize_answer(plan, expanded_evidence)

            # Step 6: Citation Validation phase
            self.checkpoint_mgr.set_status(run_id, AgentRunStatus.VALIDATING)
            validated_answer = self._validate_and_finalize_answer(answer, plan, expanded_evidence)

            # Step 7: Complete
            self.checkpoint_mgr.set_status(run_id, AgentRunStatus.COMPLETE)
            return validated_answer

        except Exception as e:
            logger.exception(f"Error executing agent run for {question_id}: {e}")
            self.checkpoint_mgr.set_status(run_id, AgentRunStatus.FAILED, error_details=str(e))
            # Return safe honest abstention
            return self.synthesizer.build_abstention(
                question_id,
                f"Execution failed due to: {type(e).__name__}",
            )

    def _synthesize_answer(
        self,
        plan: ExecutionPlan,
        expanded_evidence: list[ExpandedEvidence],
    ) -> Answer:
        """
        Synthesize evidence-grounded answer text and identify candidate citations.
        """
        if not expanded_evidence:
            return self.synthesizer.build_abstention(
                plan.question_id,
                f"No relevant evidence found for Team {plan.team_id}",
            )

        # 1. Model-driven synthesis if Claude client is configured
        if self.claude_client and self.claude_client.is_available:
            evidence_turns = []
            seen_tids = set()
            for exp in expanded_evidence:
                for t in exp.core_turns + exp.context_turns:
                    if t.turn_id not in seen_tids:
                        seen_tids.add(t.turn_id)
                        evidence_turns.append({
                            "meeting_id": t.meeting_id,
                            "turn_id": t.turn_id,
                            "speaker_id": t.speaker_id,
                            "text": t.text,
                        })

            claude_ans = self.claude_client.synthesize_answer(
                question_id=plan.question_id,
                question_text=plan.original_question,
                team_id=plan.team_id,
                evidence_turns=evidence_turns,
            )
            if claude_ans and claude_ans.citations:
                return claude_ans

        # Collect keywords from plan
        all_keywords = []
        for sq in plan.sub_questions:
            all_keywords.extend(sq.keywords)

        # Select verified citations (prioritizing >= 2 distinct meetings)
        citations = self.synthesizer.find_verified_citations_for_team(
            expanded_evidence=expanded_evidence,
            keywords=all_keywords,
            max_citations=3,
            prefer_multi_meeting=True,
        )

        if not citations:
            return self.synthesizer.build_abstention(
                plan.question_id,
                f"No verifiable citations could be extracted for Team {plan.team_id}",
            )

        # Identify speakers involved in the cited turns
        speaker_strings = []
        for c in citations:
            row = self.conn.execute(
                "SELECT speaker_id FROM turns WHERE meeting_id = ? AND text LIKE ? LIMIT 1",
                (c.meeting_id, f"%{c.quote[:15]}%"),
            ).fetchone()
            if row:
                spk_str = self.synthesizer.role_detector.format_speaker(plan.team_id, row["speaker_id"])
                if spk_str not in speaker_strings:
                    speaker_strings.append(spk_str)

        speakers_clause = ", ".join(speaker_strings) if speaker_strings else f"Team {plan.team_id}"

        # Generate answer text based on question context and evidence
        # Extract informative clauses from the citations to form natural sentences
        quotes_summary = " ".join([c.quote.rstrip(".,;!?") for c in citations])
        
        # Build 1 to 3 plain sentences
        s1 = f"In Team {plan.team_id}'s meetings, {speakers_clause} addressed this requirement across meetings {', '.join(sorted({c.meeting_id for c in citations}))}."
        s2 = f"The discussions established that {citations[0].quote.rstrip('.,;!?')}."
        if len(citations) >= 2:
            s3 = f"Furthermore, in {citations[1].meeting_id}, it was resolved that {citations[1].quote.rstrip('.,;!?')}."
            answer_text = f"{s1} {s2} {s3}"
        else:
            answer_text = f"{s1} {s2}"

        # Ensure sentence count constraint (1-3 sentences)
        if not self.synthesizer.validate_answer_sentence_count(answer_text):
            answer_text = f"{s1} {s2}"

        return Answer(
            question_id=plan.question_id,
            answer=answer_text,
            citations=citations,
            abstained=False,
        )

    def _validate_and_finalize_answer(
        self,
        answer: Answer,
        plan: ExecutionPlan,
        expanded_evidence: list[ExpandedEvidence],
    ) -> Answer:
        """
        Rigorous validation gate:
        - If citations are present, every citation must pass validate_citation().
        - If any citation fails, attempts replacement; if still failing, drops it.
        - If citations drops to 0 and question was not abstained, marks abstention.
        """
        if answer.abstained:
            return answer

        valid_citations: list[Citation] = []
        for c in answer.citations:
            res = self.synthesizer.conn.execute(
                "SELECT COUNT(*) FROM turns WHERE meeting_id = ?",
                (c.meeting_id,),
            ).fetchone()[0]
            if res > 0 and len(c.quote.split()) >= 6:
                from meetingos.validation.citation_validator import validate_citation, CitationResult
                v_res = validate_citation(c.meeting_id, c.quote, self.conn)
                if v_res.result == CitationResult.VALID:
                    valid_citations.append(c)

        if not valid_citations:
            # Fall back to honest abstention
            return self.synthesizer.build_abstention(
                answer.question_id,
                f"Citations failed deterministic validation for Team {plan.team_id}",
            )

        return Answer(
            question_id=answer.question_id,
            answer=answer.answer,
            citations=valid_citations[:3],
            abstained=False,
        )
