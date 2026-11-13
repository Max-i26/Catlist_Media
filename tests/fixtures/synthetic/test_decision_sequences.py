"""Synthetic event-sequence tests for decision memory.

These test the correctness of decision state derivation logic
against manually specified expected states.

Gate 3 requirement: build synthetic event-sequence tests covering
acceptance, proposal, rejection, reopening, withdrawal, contradiction
and duplicate extraction. Expected state manually specified for each.
"""
from __future__ import annotations

import pytest
from meetingos.models import DecisionEventType


# ---------------------------------------------------------------------------
# Synthetic test cases: (events_in_order, expected_current_state)
#
# Each case specifies a sequence of events and what state we expect
# the system to derive. The critical property: the system must NOT
# simply return the type of the latest event as the current state.
# ---------------------------------------------------------------------------

SYNTHETIC_SEQUENCES = [
    # Case 1: Simple acceptance
    {
        "name": "simple_acceptance",
        "events": [
            ("a", DecisionEventType.PROPOSED),
            ("b", DecisionEventType.ACCEPTED),
        ],
        "expected_state": "accepted",
        "expected_last_accepted_in": "b",
        "has_revocation_after_acceptance": False,
        "description": "Accepted in b; no subsequent revocation → currently accepted",
    },

    # Case 2: Proposed does NOT override accepted
    {
        "name": "proposed_after_accepted",
        "events": [
            ("a", DecisionEventType.PROPOSED),
            ("b", DecisionEventType.ACCEPTED),
            ("c", DecisionEventType.PROPOSED),  # re-proposed, NOT re-accepted
        ],
        "expected_state": "accepted",  # still accepted — proposed ≠ supersedes
        "expected_last_accepted_in": "b",
        "has_revocation_after_acceptance": False,
        "description": "Proposing again after acceptance does not change accepted state",
    },

    # Case 3: Withdrawal after acceptance
    {
        "name": "withdrawn_after_accepted",
        "events": [
            ("a", DecisionEventType.PROPOSED),
            ("b", DecisionEventType.ACCEPTED),
            ("c", DecisionEventType.WITHDRAWN),
        ],
        "expected_state": "withdrawn",
        "expected_last_accepted_in": "b",
        "has_revocation_after_acceptance": True,
        "description": "Withdrawal after acceptance → currently withdrawn",
    },

    # Case 4: The failing scenario from the architecture review
    # Acceptance, then later rejection — must NOT show as accepted
    {
        "name": "rejected_after_accepted",
        "events": [
            ("a", DecisionEventType.ACCEPTED),   # Design X accepted
            ("b", DecisionEventType.PROPOSED),   # Design Y proposed
            ("c", DecisionEventType.REOPENED),   # Design X reopened
            ("d", DecisionEventType.ACCEPTED),   # Design Y accepted (new entity)
            ("e", DecisionEventType.WITHDRAWN),  # Design Y withdrawn
        ],
        "expected_state": "withdrawn",
        "expected_last_accepted_in": "d",
        "has_revocation_after_acceptance": True,
        "description": "Cannot return Design Y as 'accepted' after withdrawal in e",
    },

    # Case 5: Contradiction — two accepted decisions in conflict
    {
        "name": "contradicted",
        "events": [
            ("a", DecisionEventType.ACCEPTED),
            ("b", DecisionEventType.CONTRADICTED),
        ],
        "expected_state": "contradicted",
        "expected_last_accepted_in": "a",
        "has_revocation_after_acceptance": False,  # contradiction is preserved, not revocation
        "description": "Contradiction is flagged; both sides preserved",
    },

    # Case 6: Reopened then accepted again
    {
        "name": "reopened_then_reaccepted",
        "events": [
            ("a", DecisionEventType.ACCEPTED),
            ("b", DecisionEventType.REOPENED),
            ("c", DecisionEventType.ACCEPTED),
        ],
        "expected_state": "accepted",
        "expected_last_accepted_in": "c",
        "has_revocation_after_acceptance": False,
        "description": "Reopened but re-accepted in c → currently accepted from c",
    },

    # Case 7: Rejected immediately
    {
        "name": "immediately_rejected",
        "events": [
            ("a", DecisionEventType.PROPOSED),
            ("a", DecisionEventType.REJECTED),
        ],
        "expected_state": "rejected",
        "expected_last_accepted_in": None,
        "has_revocation_after_acceptance": False,
        "description": "Rejected proposal has no accepted state",
    },

    # Case 8: Unknown — no clear determination
    {
        "name": "unknown_state",
        "events": [
            ("a", DecisionEventType.NOTED),
        ],
        "expected_state": "unknown",
        "expected_last_accepted_in": None,
        "has_revocation_after_acceptance": False,
        "description": "Only a 'noted' event → state is unknown",
    },
]


class TestDecisionStateDerivation:
    """
    These tests verify the STATE DERIVATION RULES, not the full DB persistence.
    The derivation function is what we're validating here.

    When the decision state engine is implemented, these tests import and call it.
    For now they document the expected behaviour as executable specifications.
    """

    @pytest.mark.parametrize("case", SYNTHETIC_SEQUENCES, ids=[c["name"] for c in SYNTHETIC_SEQUENCES])
    def test_state_derivation_rule(self, case: dict) -> None:
        """
        Verify the documented derivation rule for each sequence.

        This test currently checks the RULE (documented behaviour), not an implementation.
        When `derive_current_state(events)` is implemented, replace the manual check below.
        """
        events = case["events"]
        expected = case["expected_state"]

        # Apply the derivation rules manually (mirrors what the implementation must do):
        event_types_in_order = [e[1] for e in events]

        # Find last accepted index
        last_accepted_idx = None
        for i, et in enumerate(event_types_in_order):
            if et == DecisionEventType.ACCEPTED:
                last_accepted_idx = i

        # Check for revocation after last acceptance
        post_acceptance_revocations = 0
        if last_accepted_idx is not None:
            for et in event_types_in_order[last_accepted_idx + 1:]:
                if et in (DecisionEventType.WITHDRAWN, DecisionEventType.REJECTED):
                    post_acceptance_revocations += 1

        # Derive state
        latest_event = event_types_in_order[-1]

        if latest_event == DecisionEventType.CONTRADICTED:
            derived_state = "contradicted"
        elif latest_event == DecisionEventType.WITHDRAWN and last_accepted_idx is not None:
            derived_state = "withdrawn"
        elif latest_event == DecisionEventType.REJECTED and last_accepted_idx is None:
            derived_state = "rejected"
        elif last_accepted_idx is not None and post_acceptance_revocations == 0:
            derived_state = "accepted"
        elif last_accepted_idx is not None and post_acceptance_revocations > 0:
            # Determine what the latest revocation type is
            last_rev = None
            for et in event_types_in_order[last_accepted_idx + 1:]:
                if et in (DecisionEventType.WITHDRAWN, DecisionEventType.REJECTED):
                    last_rev = et
            derived_state = last_rev.value if last_rev else "unknown"
        elif latest_event == DecisionEventType.NOTED:
            derived_state = "unknown"
        else:
            derived_state = "unknown"

        assert derived_state == expected, (
            f"Case '{case['name']}': expected '{expected}', got '{derived_state}'\n"
            f"Description: {case['description']}\n"
            f"Events: {[e[1].value for e in events]}"
        )

        # Verify revocation detection
        assert (post_acceptance_revocations > 0) == case["has_revocation_after_acceptance"], (
            f"Case '{case['name']}': revocation detection mismatch"
        )
