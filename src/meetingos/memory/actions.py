"""Event-sourced Action Memory.

Maintains immutable action commitment events and computes derived current status.
Guarantees:
- Distinguishes suggestions from formal assignments.
- Never guesses unidentifiable owners (owner=None).
- Never invents unstated deadlines (deadline=None).
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from meetingos.models import (
    ActionEvent,
    ActionEventType,
    ActionEntity,
    Confidence,
    EvidenceItem,
)


@dataclass
class DerivedActionStatus:
    action_entity_id: str
    team_id:          str
    description:      str
    current_status:   str  # 'assigned' | 'completed' | 'cancelled' | 'reopened' | 'suggested' | 'unknown'
    current_owner:    Optional[str]
    current_deadline: Optional[str]
    total_events:     int
    latest_event_type:str
    events:           list[ActionEvent]


class ActionMemory:
    """Manages immutable action entities and chronological events."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def create_entity(
        self,
        team_id: str,
        description: str,
        created_at: Optional[str] = None,
    ) -> ActionEntity:
        """Register a new action task entity."""
        row = self.conn.execute(
            "SELECT COUNT(*) AS cnt FROM action_entities WHERE team_id = ?",
            (team_id,),
        ).fetchone()
        seq = row["cnt"] + 1
        entity_id = f"{team_id}_ACT_{seq:03d}"
        now = created_at or datetime.now(timezone.utc).isoformat()

        with self.conn:
            self.conn.execute(
                """
                INSERT INTO action_entities (action_entity_id, team_id, description, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (entity_id, team_id, description, now),
            )

        return ActionEntity(
            action_entity_id=entity_id,
            team_id=team_id,
            description=description,
            created_at=now,
        )

    def record_event(
        self,
        action_entity_id: str,
        team_id: str,
        meeting_id: str,
        turn_index: int,
        event_type: ActionEventType,
        owner: Optional[str] = None,
        deadline: Optional[str] = None,
        evidence: Optional[list[EvidenceItem]] = None,
        confidence: Confidence = Confidence.HIGH,
        extracted_at: Optional[str] = None,
    ) -> ActionEvent:
        """Append an immutable action event."""
        row = self.conn.execute(
            "SELECT COUNT(*) AS cnt FROM action_events WHERE action_entity_id = ?",
            (action_entity_id,),
        ).fetchone()
        evt_seq = row["cnt"] + 1
        event_id = f"{action_entity_id}_EVT_{evt_seq:03d}"
        now = extracted_at or datetime.now(timezone.utc).isoformat()

        ev_list = evidence or []
        evidence_turn_ids = [e.turn_id for e in ev_list]
        evidence_quotes = [e.quote for e in ev_list]

        with self.conn:
            self.conn.execute(
                """
                INSERT INTO action_events (
                    event_id, action_entity_id, team_id, meeting_id, turn_index,
                    event_type, owner, deadline, evidence_turn_ids, evidence_quotes,
                    confidence, extracted_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_id,
                    action_entity_id,
                    team_id,
                    meeting_id,
                    turn_index,
                    event_type.value,
                    owner,
                    deadline,
                    json.dumps(evidence_turn_ids),
                    json.dumps(evidence_quotes),
                    confidence.value,
                    now,
                ),
            )

        return ActionEvent(
            event_id=event_id,
            action_entity_id=action_entity_id,
            team_id=team_id,
            meeting_id=meeting_id,
            turn_index=turn_index,
            event_type=event_type,
            owner=owner,
            deadline=deadline,
            evidence=ev_list,
            confidence=confidence,
            extracted_at=now,
        )

    def get_action_history(self, action_entity_id: str) -> list[ActionEvent]:
        """Fetch all chronological events for an action entity."""
        rows = self.conn.execute(
            """
            SELECT * FROM action_events
            WHERE action_entity_id = ?
            ORDER BY turn_index ASC
            """,
            (action_entity_id,),
        ).fetchall()

        events = []
        for r in rows:
            turn_ids = json.loads(r["evidence_turn_ids"])
            quotes = json.loads(r["evidence_quotes"])
            evidence_items = [
                EvidenceItem(turn_id=tid, quote=q)
                for tid, q in zip(turn_ids, quotes)
            ]
            events.append(ActionEvent(
                event_id=r["event_id"],
                action_entity_id=r["action_entity_id"],
                team_id=r["team_id"],
                meeting_id=r["meeting_id"],
                turn_index=r["turn_index"],
                event_type=ActionEventType(r["event_type"]),
                owner=r["owner"],
                deadline=r["deadline"],
                evidence=evidence_items,
                confidence=Confidence(r["confidence"]),
                extracted_at=r["extracted_at"],
            ))
        return events

    def derive_current_status(self, action_entity_id: str) -> DerivedActionStatus:
        """
        Derive current status, active owner, and active deadline from chronological events.
        """
        entity_row = self.conn.execute(
            "SELECT * FROM action_entities WHERE action_entity_id = ?",
            (action_entity_id,),
        ).fetchone()
        if not entity_row:
            raise ValueError(f"Action entity not found: {action_entity_id}")

        events = self.get_action_history(action_entity_id)
        if not events:
            return DerivedActionStatus(
                action_entity_id=action_entity_id,
                team_id=entity_row["team_id"],
                description=entity_row["description"],
                current_status="unknown",
                current_owner=None,
                current_deadline=None,
                total_events=0,
                latest_event_type="none",
                events=[],
            )

        latest_event = events[-1]

        # Determine latest non-null owner and deadline
        active_owner = None
        active_deadline = None
        for e in events:
            if e.owner is not None:
                active_owner = e.owner
            if e.deadline is not None:
                active_deadline = e.deadline

        # Determine current status from latest event
        if latest_event.event_type == ActionEventType.COMPLETED:
            status = "completed"
        elif latest_event.event_type == ActionEventType.CANCELLED:
            status = "cancelled"
        elif latest_event.event_type == ActionEventType.REOPENED:
            status = "reopened"
        elif latest_event.event_type in (ActionEventType.ASSIGNED, ActionEventType.REASSIGNED):
            status = "assigned"
        elif latest_event.event_type == ActionEventType.SUGGESTED:
            status = "suggested"
        else:
            status = "unknown"

        return DerivedActionStatus(
            action_entity_id=action_entity_id,
            team_id=entity_row["team_id"],
            description=entity_row["description"],
            current_status=status,
            current_owner=active_owner,
            current_deadline=active_deadline,
            total_events=len(events),
            latest_event_type=latest_event.event_type.value,
            events=events,
        )
