"""Unit tests for event-sourced DecisionMemory and ActionMemory."""
from __future__ import annotations

import tempfile
from pathlib import Path
import pytest

from meetingos.memory.actions import ActionMemory
from meetingos.memory.decisions import DecisionMemory
from meetingos.memory.schema import initialise_db
from meetingos.models import (
    ActionEventType,
    Confidence,
    DecisionEventType,
    EvidenceItem,
)


@pytest.fixture
def db_conn():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "evt_mem.db"
        conn = initialise_db(db_path)
        try:
            yield conn
        finally:
            conn.close()


class TestDecisionMemory:

    def test_entity_creation_and_history(self, db_conn) -> None:
        dm = DecisionMemory(db_conn)
        entity = dm.create_entity("TS3006", "Remote Casing Material")
        assert entity.team_id == "TS3006"
        assert "remote_casing" in entity.decision_entity_id

        # Record proposed event in meeting a
        e1 = dm.record_event(
            decision_entity_id=entity.decision_entity_id,
            team_id="TS3006",
            meeting_id="TS3006a",
            turn_index=10,
            event_type=DecisionEventType.PROPOSED,
            description="Speaker A proposed titanium case.",
            evidence=[EvidenceItem(turn_id="TS3006a_A_0005", quote="we could use titanium")],
        )

        # Record accepted event in meeting b
        e2 = dm.record_event(
            decision_entity_id=entity.decision_entity_id,
            team_id="TS3006",
            meeting_id="TS3006b",
            turn_index=150,
            event_type=DecisionEventType.ACCEPTED,
            description="Team approved titanium case.",
            evidence=[EvidenceItem(turn_id="TS3006b_A_0020", quote="okay titanium is agreed")],
        )

        history = dm.get_entity_history(entity.decision_entity_id)
        assert len(history) == 2
        assert history[0].turn_index == 10
        assert history[1].turn_index == 150

        state = dm.derive_current_state(entity.decision_entity_id)
        assert state.current_status == "accepted"
        assert state.last_accepted_in == "TS3006b"
        assert state.post_acceptance_revocations == 0

    def test_revocation_after_acceptance(self, db_conn) -> None:
        """The critical review case: acceptance followed by subsequent withdrawal."""
        dm = DecisionMemory(db_conn)
        entity = dm.create_entity("TS3006", "Speech Recognition Feature")

        # Accepted in meeting b
        dm.record_event(
            decision_entity_id=entity.decision_entity_id,
            team_id="TS3006",
            meeting_id="TS3006b",
            turn_index=50,
            event_type=DecisionEventType.ACCEPTED,
            description="Speech recognition approved.",
            evidence=[EvidenceItem(turn_id="T1", quote="let's keep speech recognition")],
        )

        # Proposed alternative in meeting c
        dm.record_event(
            decision_entity_id=entity.decision_entity_id,
            team_id="TS3006",
            meeting_id="TS3006c",
            turn_index=120,
            event_type=DecisionEventType.PROPOSED,
            description="Speaker B suggested cutting speech recognition to save cost.",
            evidence=[EvidenceItem(turn_id="T2", quote="speech recognition might be too expensive")],
        )

        # Explicitly withdrawn / rejected in meeting d
        dm.record_event(
            decision_entity_id=entity.decision_entity_id,
            team_id="TS3006",
            meeting_id="TS3006d",
            turn_index=200,
            event_type=DecisionEventType.WITHDRAWN,
            description="Speech recognition dropped due to budget constraints.",
            evidence=[EvidenceItem(turn_id="T3", quote="we have to drop speech recognition")],
        )

        state = dm.derive_current_state(entity.decision_entity_id)
        # Must NOT show as accepted!
        assert state.current_status == "withdrawn"
        assert state.last_accepted_in == "TS3006b"
        assert state.post_acceptance_revocations == 1

    def test_proposed_after_accepted_does_not_override(self, db_conn) -> None:
        dm = DecisionMemory(db_conn)
        entity = dm.create_entity("ES2008", "Battery Type")

        dm.record_event(
            decision_entity_id=entity.decision_entity_id,
            team_id="ES2008",
            meeting_id="ES2008b",
            turn_index=30,
            event_type=DecisionEventType.ACCEPTED,
            description="Standard AA batteries accepted.",
            evidence=[EvidenceItem(turn_id="T1", quote="standard batteries are fine")],
        )

        # Someone proposes solar in meeting c without approval
        dm.record_event(
            decision_entity_id=entity.decision_entity_id,
            team_id="ES2008",
            meeting_id="ES2008c",
            turn_index=90,
            event_type=DecisionEventType.PROPOSED,
            description="Speaker C asked about solar cells.",
            evidence=[EvidenceItem(turn_id="T2", quote="what about solar cells")],
        )

        state = dm.derive_current_state(entity.decision_entity_id)
        # Still accepted from meeting b
        assert state.current_status == "accepted"
        assert state.last_accepted_in == "ES2008b"

    def test_contradiction_preserved(self, db_conn) -> None:
        dm = DecisionMemory(db_conn)
        entity = dm.create_entity("IS1008", "Display Feature")

        dm.record_event(
            decision_entity_id=entity.decision_entity_id,
            team_id="IS1008",
            meeting_id="IS1008b",
            turn_index=20,
            event_type=DecisionEventType.ACCEPTED,
            description="Display agreed.",
            evidence=[EvidenceItem(turn_id="T1", quote="yes display is good")],
        )
        dm.record_event(
            decision_entity_id=entity.decision_entity_id,
            team_id="IS1008",
            meeting_id="IS1008c",
            turn_index=80,
            event_type=DecisionEventType.CONTRADICTED,
            description="Conflicting decision made on no display.",
            evidence=[EvidenceItem(turn_id="T2", quote="we cannot afford display")],
        )

        state = dm.derive_current_state(entity.decision_entity_id)
        assert state.current_status == "contradicted"


class TestActionMemory:

    def test_action_lifecycle_and_owner_nullability(self, db_conn) -> None:
        am = ActionMemory(db_conn)
        entity = am.create_entity("TS3011", "Research component pricing")

        # 1. Suggested without owner
        am.record_event(
            action_entity_id=entity.action_entity_id,
            team_id="TS3011",
            meeting_id="TS3011a",
            turn_index=15,
            event_type=ActionEventType.SUGGESTED,
            owner=None,
            deadline=None,
        )
        s1 = am.derive_current_status(entity.action_entity_id)
        assert s1.current_status == "suggested"
        assert s1.current_owner is None
        assert s1.current_deadline is None

        # 2. Assigned to Speaker B in meeting b
        am.record_event(
            action_entity_id=entity.action_entity_id,
            team_id="TS3011",
            meeting_id="TS3011b",
            turn_index=60,
            event_type=ActionEventType.ASSIGNED,
            owner="B",
            deadline="next meeting",
        )
        s2 = am.derive_current_status(entity.action_entity_id)
        assert s2.current_status == "assigned"
        assert s2.current_owner == "B"
        assert s2.current_deadline == "next meeting"

        # 3. Completed in meeting c
        am.record_event(
            action_entity_id=entity.action_entity_id,
            team_id="TS3011",
            meeting_id="TS3011c",
            turn_index=120,
            event_type=ActionEventType.COMPLETED,
            owner="B",
        )
        s3 = am.derive_current_status(entity.action_entity_id)
        assert s3.current_status == "completed"
        assert s3.current_owner == "B"
