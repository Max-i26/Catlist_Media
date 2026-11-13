"""Event-sourced Decision Memory.

Maintains immutable decision event history and computes derived current state.
Never silently overwrites historical decisions.
"""
from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from meetingos.models import (
    Confidence,
    DecisionEntity,
    DecisionEvent,
    DecisionEventType,
    DecisionRelation,
    EvidenceItem,
)


@dataclass
class DerivedDecisionState:
    decision_entity_id:           str
    team_id:                      str
    topic:                        str
    current_status:               str  # 'accepted' | 'withdrawn' | 'rejected' | 'contradicted' | 'proposed' | 'unknown'
    last_accepted_in:             Optional[str]
    post_acceptance_revocations:  int
    total_events:                 int
    latest_event_type:            str
    events:                       list[DecisionEvent]


class DecisionMemory:
    """Manages immutable decision entities, events, and relations."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def create_entity(
        self,
        team_id: str,
        topic: str,
        created_at: Optional[str] = None,
    ) -> DecisionEntity:
        """Register a new decision entity (stable topic/direction identity)."""
        slug = re.sub(r"[^a-z0-9]+", "_", topic.lower()).strip("_")[:20]
        row = self.conn.execute(
            "SELECT COUNT(*) AS cnt FROM decision_entities WHERE team_id = ?",
            (team_id,),
        ).fetchone()
        seq = row["cnt"] + 1
        entity_id = f"{team_id}_DE_{slug}_{seq:03d}"
        now = created_at or datetime.now(timezone.utc).isoformat()

        with self.conn:
            self.conn.execute(
                """
                INSERT INTO decision_entities (decision_entity_id, team_id, topic, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (entity_id, team_id, topic, now),
            )

        return DecisionEntity(
            decision_entity_id=entity_id,
            team_id=team_id,
            topic=topic,
            created_at=now,
        )

    def record_event(
        self,
        decision_entity_id: str,
        team_id: str,
        meeting_id: str,
        turn_index: int,
        event_type: DecisionEventType,
        description: str,
        evidence: list[EvidenceItem],
        confidence: Confidence = Confidence.HIGH,
        extracted_at: Optional[str] = None,
    ) -> DecisionEvent:
        """Append an immutable decision event."""
        row = self.conn.execute(
            "SELECT COUNT(*) AS cnt FROM decision_events WHERE decision_entity_id = ?",
            (decision_entity_id,),
        ).fetchone()
        evt_seq = row["cnt"] + 1
        event_id = f"{decision_entity_id}_EVT_{evt_seq:03d}"
        now = extracted_at or datetime.now(timezone.utc).isoformat()

        evidence_turn_ids = [e.turn_id for e in evidence]
        evidence_quotes = [e.quote for e in evidence]

        with self.conn:
            self.conn.execute(
                """
                INSERT INTO decision_events (
                    event_id, decision_entity_id, team_id, meeting_id, turn_index,
                    event_type, description, evidence_turn_ids, evidence_quotes,
                    confidence, extracted_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_id,
                    decision_entity_id,
                    team_id,
                    meeting_id,
                    turn_index,
                    event_type.value,
                    description,
                    json.dumps(evidence_turn_ids),
                    json.dumps(evidence_quotes),
                    confidence.value,
                    now,
                ),
            )

        return DecisionEvent(
            event_id=event_id,
            decision_entity_id=decision_entity_id,
            team_id=team_id,
            meeting_id=meeting_id,
            turn_index=turn_index,
            event_type=event_type,
            description=description,
            evidence=evidence,
            confidence=confidence,
            extracted_at=now,
        )

    def record_relation(
        self,
        source_entity_id: str,
        target_entity_id: str,
        relation_type: str,
        established_in_meeting: str,
        evidence: list[EvidenceItem],
    ) -> DecisionRelation:
        """Record relation between decision entities (supersedes, contradicts, reopens)."""
        rel_id = f"REL_{source_entity_id}_TO_{target_entity_id}_{relation_type}"
        evidence_turn_ids = [e.turn_id for e in evidence]

        with self.conn:
            self.conn.execute(
                """
                INSERT OR REPLACE INTO decision_relations (
                    relation_id, source_entity_id, target_entity_id,
                    relation_type, established_in_meeting, evidence_turn_ids
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    rel_id,
                    source_entity_id,
                    target_entity_id,
                    relation_type,
                    established_in_meeting,
                    json.dumps(evidence_turn_ids),
                ),
            )

        return DecisionRelation(
            relation_id=rel_id,
            source_entity_id=source_entity_id,
            target_entity_id=target_entity_id,
            relation_type=relation_type,
            established_in_meeting=established_in_meeting,
            evidence=evidence,
        )

    def get_entity_history(self, decision_entity_id: str) -> list[DecisionEvent]:
        """Fetch all events for a decision entity in chronological order."""
        rows = self.conn.execute(
            """
            SELECT * FROM decision_events
            WHERE decision_entity_id = ?
            ORDER BY turn_index ASC
            """,
            (decision_entity_id,),
        ).fetchall()

        events = []
        for r in rows:
            turn_ids = json.loads(r["evidence_turn_ids"])
            quotes = json.loads(r["evidence_quotes"])
            evidence_items = [
                EvidenceItem(turn_id=tid, quote=q)
                for tid, q in zip(turn_ids, quotes)
            ]
            events.append(DecisionEvent(
                event_id=r["event_id"],
                decision_entity_id=r["decision_entity_id"],
                team_id=r["team_id"],
                meeting_id=r["meeting_id"],
                turn_index=r["turn_index"],
                event_type=DecisionEventType(r["event_type"]),
                description=r["description"],
                evidence=evidence_items,
                confidence=Confidence(r["confidence"]),
                extracted_at=r["extracted_at"],
            ))
        return events

    def derive_current_state(self, decision_entity_id: str) -> DerivedDecisionState:
        """
        Derive the current active status from the immutable event log.

        Execution of the validated temporal state derivation rule:
        - Never simply takes the latest event type as current state.
        - Identifies last acceptance and checks for post-acceptance revocations (withdrawn, rejected).
        - Flags unresolved contradictions.
        - Keeps uncertain states uncertain.
        """
        entity_row = self.conn.execute(
            "SELECT * FROM decision_entities WHERE decision_entity_id = ?",
            (decision_entity_id,),
        ).fetchone()
        if not entity_row:
            raise ValueError(f"Decision entity not found: {decision_entity_id}")

        events = self.get_entity_history(decision_entity_id)
        if not events:
            return DerivedDecisionState(
                decision_entity_id=decision_entity_id,
                team_id=entity_row["team_id"],
                topic=entity_row["topic"],
                current_status="unknown",
                last_accepted_in=None,
                post_acceptance_revocations=0,
                total_events=0,
                latest_event_type="none",
                events=[],
            )

        event_types = [e.event_type for e in events]
        latest_event = event_types[-1]

        # Find last accepted event
        last_accepted_idx = None
        last_accepted_in = None
        for i, e in enumerate(events):
            if e.event_type == DecisionEventType.ACCEPTED:
                last_accepted_idx = i
                last_accepted_in = e.meeting_id

        # Count revocations occurring after the last acceptance
        post_acceptance_revocations = 0
        latest_revocation_type = None
        if last_accepted_idx is not None:
            for e in events[last_accepted_idx + 1:]:
                if e.event_type in (DecisionEventType.WITHDRAWN, DecisionEventType.REJECTED):
                    post_acceptance_revocations += 1
                    latest_revocation_type = e.event_type

        # Derive state
        if latest_event == DecisionEventType.CONTRADICTED:
            current_status = "contradicted"
        elif latest_revocation_type is not None:
            current_status = latest_revocation_type.value
        elif last_accepted_idx is not None and post_acceptance_revocations == 0:
            current_status = "accepted"
        elif latest_event == DecisionEventType.REJECTED and last_accepted_idx is None:
            current_status = "rejected"
        elif latest_event == DecisionEventType.PROPOSED and last_accepted_idx is None:
            current_status = "proposed"
        elif latest_event == DecisionEventType.NOTED:
            current_status = "unknown"
        else:
            current_status = "unknown"

        return DerivedDecisionState(
            decision_entity_id=decision_entity_id,
            team_id=entity_row["team_id"],
            topic=entity_row["topic"],
            current_status=current_status,
            last_accepted_in=last_accepted_in,
            post_acceptance_revocations=post_acceptance_revocations,
            total_events=len(events),
            latest_event_type=latest_event.value,
            events=events,
        )
