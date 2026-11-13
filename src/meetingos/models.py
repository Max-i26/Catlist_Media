"""MeetingOS — data models shared across all layers.

These are the canonical Python types for the system.
Every layer boundary uses these types — not raw dicts.
Pydantic v2 enforces the contracts at runtime.
"""
from __future__ import annotations

from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class MeetingSequence(str, Enum):
    A = "a"
    B = "b"
    C = "c"
    D = "d"


class DecisionEventType(str, Enum):
    PROPOSED     = "proposed"
    ACCEPTED     = "accepted"
    REJECTED     = "rejected"
    SUPERSEDED   = "superseded"
    REOPENED     = "reopened"
    WITHDRAWN    = "withdrawn"
    CONTRADICTED = "contradicted"
    NOTED        = "noted"
    UNKNOWN      = "unknown"


class ActionEventType(str, Enum):
    SUGGESTED   = "suggested"
    ASSIGNED    = "assigned"
    REASSIGNED  = "reassigned"
    COMPLETED   = "completed"
    CANCELLED   = "cancelled"
    REOPENED    = "reopened"
    FOLLOWED_UP = "followed_up"
    UNKNOWN     = "unknown"


class Confidence(str, Enum):
    HIGH   = "high"
    MEDIUM = "medium"
    LOW    = "low"


class CoverageStatus(str, Enum):
    COMPLETE = "complete"
    PARTIAL  = "partial"


class CitationResult(str, Enum):
    VALID             = "valid"
    MEETING_NOT_FOUND = "meeting_not_found"
    QUOTE_NOT_FOUND   = "quote_not_found"
    QUOTE_TOO_SHORT   = "quote_too_short"


class AgentRunStatus(str, Enum):
    STARTED      = "started"
    PLANNING     = "planning"
    RETRIEVING   = "retrieving"
    SYNTHESIZING = "synthesizing"
    VALIDATING   = "validating"
    COMPLETE     = "complete"
    FAILED       = "failed"


# ---------------------------------------------------------------------------
# Source memory types
# ---------------------------------------------------------------------------

class Turn(BaseModel):
    """One speaker turn in a transcript — the atomic unit of source truth."""
    turn_id:           str
    turn_index:        int           # global chronological order
    meeting_id:        str
    team_id:           str
    meeting_sequence:  str           # a/b/c/d
    meeting_number:    Optional[int]
    speaker_id:        str           # A/B/C/D
    timestamp:         Optional[str] # HH:MM:SS; None if malformed
    timestamp_valid:   bool = True
    text:              str           # exact original text, never modified
    word_count:        int
    byte_offset_start: int
    byte_offset_end:   int
    source_file:       str
    source_checksum:   str           # SHA-256 of source file
    ingested_at:       str


class TeamCoverage(BaseModel):
    """Coverage registry entry — first-class system concept."""
    team_id:             str
    expected_sequences:  list[str]
    available_sequences: list[str]
    missing_sequences:   list[str]
    coverage_status:     CoverageStatus
    earliest_available:  str
    latest_available:    str
    total_turns:         int

    @property
    def is_complete(self) -> bool:
        return self.coverage_status == CoverageStatus.COMPLETE

    def has_missing_earliest(self) -> bool:
        """True if the first expected meeting (a) is absent."""
        return "a" not in self.available_sequences

    def has_missing_latest(self) -> bool:
        """True if the last expected meeting (d) is absent."""
        return "d" not in self.available_sequences


# ---------------------------------------------------------------------------
# Chunk types
# ---------------------------------------------------------------------------

class EmbeddingConfig(BaseModel):
    config_id:        str    # deterministic hash of fields
    embedding_model:  str
    model_revision:   str
    embedding_dim:    int
    max_seq_length:   int
    normalization:    str
    chunking_version: str
    created_at:       str


class Chunk(BaseModel):
    """A retrieval unit — one or more consecutive turns from one meeting."""
    chunk_id:          str
    meeting_id:        str
    team_id:           str
    meeting_sequence:  str
    turn_ids:          list[str]
    speakers:          list[str]
    start_timestamp:   Optional[str]
    end_timestamp:     Optional[str]
    turn_index_start:  int
    turn_index_end:    int
    token_count:       int
    text:              str
    embedding_config_id: str


# ---------------------------------------------------------------------------
# Decision memory types (event-sourced)
# ---------------------------------------------------------------------------

class DecisionEntity(BaseModel):
    decision_entity_id: str
    team_id:            str
    topic:              str
    created_at:         str


class EvidenceItem(BaseModel):
    turn_id: str
    quote:   str


class DecisionEvent(BaseModel):
    event_id:            str
    decision_entity_id:  str
    team_id:             str
    meeting_id:          str
    turn_index:          int
    event_type:          DecisionEventType
    description:         str
    evidence:            list[EvidenceItem]
    confidence:          Confidence
    extracted_at:        str


class DecisionRelation(BaseModel):
    relation_id:            str
    source_entity_id:       str
    target_entity_id:       str
    relation_type:          str   # supersedes | contradicts | reopens | clarifies
    established_in_meeting: str
    evidence:               list[EvidenceItem]


# ---------------------------------------------------------------------------
# Action memory types (event-sourced)
# ---------------------------------------------------------------------------

class ActionEntity(BaseModel):
    action_entity_id: str
    team_id:          str
    description:      str
    created_at:       str


class ActionEvent(BaseModel):
    event_id:          str
    action_entity_id:  str
    team_id:           str
    meeting_id:        str
    turn_index:        int
    event_type:        ActionEventType
    owner:             Optional[str]  # Speaker letter; None if unidentifiable
    deadline:          Optional[str]  # None if not stated — never invent
    evidence:          list[EvidenceItem]
    confidence:        Confidence
    extracted_at:      str


# ---------------------------------------------------------------------------
# Numeric evidence
# ---------------------------------------------------------------------------

class NumericEvidence(BaseModel):
    numeric_id:      str
    team_id:         str
    meeting_id:      str
    turn_id:         str
    value_text:      str            # exact transcript string: "$250", "twelve euros"
    normalized_value: Optional[float]  # for comparison only; None if ambiguous
    unit:            Optional[str]  # None if not stated
    unit_confidence: str            # explicit | inferred | unknown
    context_summary: Optional[str]


# ---------------------------------------------------------------------------
# Retrieval types
# ---------------------------------------------------------------------------

class RetrievalResult(BaseModel):
    chunk_id:        str
    meeting_id:      str
    team_id:         str
    score:           float          # RRF score (higher = better ranked)
    source:          str            # "bm25" | "vector" | "hybrid"
    rank:            int


class ExpandedEvidence(BaseModel):
    """A retrieval result with surrounding context expanded to full turns."""
    chunk_id:    str
    meeting_id:  str
    team_id:     str
    core_turns:  list[Turn]
    context_turns: list[Turn]      # neighboring turns added for context


# ---------------------------------------------------------------------------
# Output contract (matches questions.json exactly)
# ---------------------------------------------------------------------------

class Citation(BaseModel):
    meeting_id: str
    quote:      str                # exact original text — never normalized

    @field_validator("quote")
    @classmethod
    def quote_min_length(cls, v: str) -> str:
        if len(v.split()) < 6:
            raise ValueError("Citation quote must be at least 6 words")
        return v


class Answer(BaseModel):
    question_id: str = Field(pattern=r"^Q\d{2}$")
    answer:      str
    citations:   list[Citation] = Field(min_length=0, max_length=3)
    # abstained: True when no supporting evidence found
    abstained:   bool = False

    @field_validator("citations")
    @classmethod
    def citations_required_unless_abstained(cls, v: list, info) -> list:
        # Validation of abstention vs citation count happens at the validator layer
        return v


class AnswersFile(BaseModel):
    """The complete output contract — 25 entries + brief."""
    answers: list[Answer] = Field(min_length=25, max_length=25)
    brief:   str


# ---------------------------------------------------------------------------
# Agent execution state
# ---------------------------------------------------------------------------

class AgentRun(BaseModel):
    run_id:               str
    question_id:          str
    status:               AgentRunStatus
    current_iteration:    int = 0
    sub_questions:        list[str] = Field(default_factory=list)
    retrieved_chunk_ids:  list[str] = Field(default_factory=list)
    tool_call_history:    list[dict] = Field(default_factory=list)
    error_details:        Optional[str] = None
    started_at:           str
    updated_at:           str
