"""Stage 2: Cross-meeting temporal reconciliation.

Groups candidate events by team and topic, creates stable entities,
establishes supersession/contradiction relationships, and populates
the event-sourced persistent memory tables in SQLite.
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Optional

from meetingos.extraction.meeting_extractor import CandidateAction, CandidateDecision
from meetingos.models import NumericEvidence


class TemporalReconciler:
    """Reconciles candidate events into event-sourced persistent memory tables."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def reconcile_team_events(
        self,
        team_id: str,
        candidates_decisions: list[CandidateDecision],
        candidates_actions: list[CandidateAction],
        candidates_numerics: list[NumericEvidence],
    ) -> tuple[int, int, int]:
        """
        Reconcile and persist structured events for a single team.

        Returns: (decisions_saved, actions_saved, numerics_saved)
        """
        now = datetime.now(timezone.utc).isoformat()

        # 1. Reconcile Decisions by Topic
        decisions_by_topic: dict[str, list[CandidateDecision]] = {}
        for cd in candidates_decisions:
            if cd.topic not in decisions_by_topic:
                decisions_by_topic[cd.topic] = []
            decisions_by_topic[cd.topic].append(cd)

        decisions_count = 0
        for topic, d_list in decisions_by_topic.items():
            # Sort chronologically by turn_index
            d_list.sort(key=lambda x: x.turn_index)
            entity_id = f"{team_id}_DE_{topic}"

            # Create decision entity
            self.conn.execute(
                """
                INSERT OR IGNORE INTO decision_entities (decision_entity_id, team_id, topic, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (entity_id, team_id, topic, now),
            )

            last_accepted_evt_id = None
            for idx, d in enumerate(d_list, start=1):
                evt_id = f"{entity_id}_evt_{d.turn_index}"
                self.conn.execute(
                    """
                    INSERT OR REPLACE INTO decision_events (
                        event_id, decision_entity_id, team_id, meeting_id, turn_index,
                        event_type, description, evidence_turn_ids, evidence_quotes,
                        confidence, extracted_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        evt_id,
                        entity_id,
                        team_id,
                        d.meeting_id,
                        d.turn_index,
                        d.event_type.value,
                        d.description,
                        json.dumps([d.turn_id]),
                        json.dumps([d.quote]),
                        d.confidence.value,
                        now,
                    ),
                )
                decisions_count += 1

                # Reconcile relations (supersedes / contradicts)
                if d.event_type.value in ("accepted", "rejected", "withdrawn") and last_accepted_evt_id:
                    rel_id = f"rel_{uuid.uuid4().hex[:12]}"
                    rel_type = "supersedes" if d.event_type.value == "accepted" else "contradicts"
                    self.conn.execute(
                        """
                        INSERT OR IGNORE INTO decision_relations (
                            relation_id, source_entity_id, target_entity_id,
                            relation_type, established_in_meeting, evidence_turn_ids
                        ) VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (
                            rel_id,
                            entity_id,
                            entity_id,
                            rel_type,
                            d.meeting_id,
                            json.dumps([d.turn_id]),
                        ),
                    )

                if d.event_type.value == "accepted":
                    last_accepted_evt_id = evt_id

        # 2. Reconcile Actions
        actions_count = 0
        for idx, act in enumerate(candidates_actions, start=1):
            act_entity_id = f"{team_id}_ACT_{idx:03d}"
            self.conn.execute(
                """
                INSERT OR IGNORE INTO action_entities (action_entity_id, team_id, description, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (act_entity_id, team_id, act.description, now),
            )

            act_evt_id = f"{act_entity_id}_evt_{act.turn_index}"
            self.conn.execute(
                """
                INSERT OR REPLACE INTO action_events (
                    event_id, action_entity_id, team_id, meeting_id, turn_index,
                    event_type, owner, deadline, evidence_turn_ids, evidence_quotes,
                    confidence, extracted_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    act_evt_id,
                    act_entity_id,
                    team_id,
                    act.meeting_id,
                    act.turn_index,
                    act.event_type.value,
                    act.owner,
                    act.deadline,
                    json.dumps([act.turn_id]),
                    json.dumps([act.quote]),
                    act.confidence.value,
                    now,
                ),
            )
            actions_count += 1

        # 3. Save Numeric Evidence
        numerics_count = 0
        for num in candidates_numerics:
            self.conn.execute(
                """
                INSERT OR REPLACE INTO numeric_evidence (
                    numeric_id, team_id, meeting_id, turn_id, value_text,
                    normalized_value, unit, unit_confidence, context_summary
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    num.numeric_id,
                    num.team_id,
                    num.meeting_id,
                    num.turn_id,
                    num.value_text,
                    num.normalized_value,
                    num.unit,
                    num.unit_confidence,
                    num.context_summary,
                ),
            )
            numerics_count += 1

        self.conn.commit()
        return decisions_count, actions_count, numerics_count
