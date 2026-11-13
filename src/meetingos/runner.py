"""MeetingOS Deliverables Generator.

Executes the agent pipeline across all 25 benchmark questions, validates
citations against source memory, generates the TS3012 pre-meeting brief,
and serializes outputs/answers.json matching the exact submission schema.
"""
from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path
from typing import Optional

from meetingos.agent.brief_generator import TS3012BriefGenerator
from meetingos.agent.checkpoint import CheckpointManager
from meetingos.agent.orchestrator import AgentOrchestrator
from meetingos.agent.planner import AgentPlanner
from meetingos.agent.synthesizer import EvidenceSynthesizer
from meetingos.agent.tools import AgentTools
from meetingos.config import (
    DB_PATH,
    FAISS_DIR,
    OUTPUTS_DIR,
    QUESTIONS_FILE,
)
from meetingos.memory.schema import get_connection
from meetingos.memory.source import SourceMemory
from meetingos.models import Answer, AnswersFile, Citation, CitationResult
from meetingos.processing.embedder import TextEmbedder
from meetingos.processing.indexer import LexicalIndexer, TeamVectorIndexer
from meetingos.retrieval.hybrid import HybridRetriever
from meetingos.validation.citation_validator import validate_citation

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def generate_answers_and_brief(
    questions_file: Path = QUESTIONS_FILE,
    output_path: Path = OUTPUTS_DIR / "answers.json",
    db_path: Path = DB_PATH,
    faiss_dir: Path = FAISS_DIR,
    use_mock_embedder: bool = False,
) -> AnswersFile:
    """
    Run agent orchestration over all 25 questions and generate answers.json.
    """
    logger.info("Initializing Agent and Retrieval subsystems...")
    conn = get_connection(db_path, readonly=False)
    memory = SourceMemory(conn)
    lexical = LexicalIndexer(conn)
    embedder = TextEmbedder(lazy_load=False, use_mock=use_mock_embedder)
    vector = TeamVectorIndexer(conn, embedder, index_dir=faiss_dir)
    retriever = HybridRetriever(lexical, vector, memory)
    tools = AgentTools(conn, retriever, source_memory=memory)
    planner = AgentPlanner(tools)
    synthesizer = EvidenceSynthesizer(conn)
    checkpoint_mgr = CheckpointManager(conn)

    orchestrator = AgentOrchestrator(
        conn=conn,
        tools=tools,
        planner=planner,
        synthesizer=synthesizer,
        checkpoint_mgr=checkpoint_mgr,
    )

    with open(questions_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    questions_list = data["questions"]
    logger.info(f"Loaded {len(questions_list)} questions from {questions_file}")

    answers: list[Answer] = []

    for i, q in enumerate(questions_list, start=1):
        qid = q["question_id"]
        qtext = q["question"]
        team = q.get("team")
        logger.info(f"[{i}/{len(questions_list)}] Processing {qid} (Team: {team})...")

        ans = orchestrator.run_question(qid, qtext, team)

        # Audit citations
        valid_citations = []
        for cit in ans.citations:
            v_res = validate_citation(cit.meeting_id, cit.quote, conn)
            if v_res.result == CitationResult.VALID:
                valid_citations.append(cit)
            else:
                logger.warning(
                    f"[{qid}] Citation failed validation: {v_res.result.value} ({cit.meeting_id}: '{cit.quote}')"
                )

        final_ans = Answer(
            question_id=ans.question_id,
            answer=ans.answer,
            citations=valid_citations,
            abstained=ans.abstained or (len(valid_citations) == 0 and not ans.abstained),
        )
        answers.append(final_ans)
        logger.info(
            f"[{qid}] Complete. Citations: {len(final_ans.citations)}, Abstained: {final_ans.abstained}"
        )

    # Generate TS3012 brief
    logger.info("Generating pre-meeting brief for Team TS3012...")
    brief_generator = TS3012BriefGenerator(conn, tools)
    brief_text = brief_generator.generate_brief()

    # Build validated AnswersFile payload
    answers_file_obj = AnswersFile(
        answers=answers,
        brief=brief_text,
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(answers_file_obj.model_dump_json(indent=2))

    logger.info(f"Successfully generated and wrote {output_path}")
    conn.close()
    return answers_file_obj


if __name__ == "__main__":
    generate_answers_and_brief()
