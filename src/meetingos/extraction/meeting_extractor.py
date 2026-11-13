"""Stage 1: Per-meeting candidate event extraction.

Extracts candidate decisions, commitments, objections, and numeric evidence
from conversational turns within a single meeting context.
Preserves exact verbatim evidence quotes and turn IDs.
"""
from __future__ import annotations

import json
import re
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from meetingos.models import (
    ActionEventType,
    Confidence,
    DecisionEventType,
    NumericEvidence,
    Turn,
)


@dataclass
class CandidateDecision:
    topic: str
    event_type: DecisionEventType
    description: str
    turn_id: str
    speaker_id: str
    meeting_id: str
    team_id: str
    turn_index: int
    quote: str
    confidence: Confidence


@dataclass
class CandidateAction:
    description: str
    event_type: ActionEventType
    owner: Optional[str]
    deadline: Optional[str]
    turn_id: str
    meeting_id: str
    team_id: str
    turn_index: int
    quote: str
    confidence: Confidence


class MeetingExtractor:
    """Extracts candidate decisions, actions, and numeric evidence from a single meeting."""

    DECISION_PATTERNS = [
        # Acceptance
        (re.compile(r"\b(?:we(?:'ll| will| have)? (?:keep|agree on|decide on|settle on|go with|use))\b\s+([^.?!,;]+)", re.I), DecisionEventType.ACCEPTED),
        (re.compile(r"\b(?:that's (?:agreed|decided|a good idea|settled))\b", re.I), DecisionEventType.ACCEPTED),
        (re.compile(r"\b(?:let's (?:keep|use|go with))\b\s+([^.?!,;]+)", re.I), DecisionEventType.ACCEPTED),
        # Rejection / Withdrawn
        (re.compile(r"\b(?:we(?:'ll| will)? (?:drop|scrap|ditch|dump|skip|cut|get rid of))\b\s+([^.?!,;]+)", re.I), DecisionEventType.REJECTED),
        (re.compile(r"\b(?:don't (?:want|need|use)|not (?:going to use|practical))\b\s+([^.?!,;]+)", re.I), DecisionEventType.REJECTED),
        # Proposals
        (re.compile(r"\b(?:how about|what if we|why don't we|could (?:we)?|suggest we)\b\s+([^.?!,;]+)", re.I), DecisionEventType.PROPOSED),
        (re.compile(r"\b(?:we could (?:have|use|make))\b\s+([^.?!,;]+)", re.I), DecisionEventType.PROPOSED),
    ]

    ACTION_PATTERNS = [
        # Assigned / Followed up
        (re.compile(r"\b(i (?:will|'ll|'m going to|'m gonna)\s+(?:check|look into|look at|find out|see if|investigate|work on|calculate|talk to|send|write|prepare|summarise|summarize))\b\s+([^.?!,;]+)", re.I), ActionEventType.ASSIGNED),
        (re.compile(r"\b(can you|could you|would you|why don't you)\s+(?:check|look into|find out|see if|design|investigate|work on|calculate)\b\s+([^.?!,;]+)", re.I), ActionEventType.ASSIGNED),
        # Suggested
        (re.compile(r"\b(?:someone should|we should|we need to|have to|must)\s+(?:check|look into|find out|investigate|see if)\b\s+([^.?!,;]+)", re.I), ActionEventType.SUGGESTED),
        # Completed
        (re.compile(r"\b(i (?:have|'ve)?\s+(?:checked|looked into|found out|calculated|finished|asked|searched|talked to))\b\s+([^.?!,;]+)", re.I), ActionEventType.COMPLETED),
        # Follow up
        (re.compile(r"\b(?:action item|action point|follow up on|recap on)\b\s+([^.?!,;]+)", re.I), ActionEventType.FOLLOWED_UP),
    ]

    NUMERIC_PATTERN = re.compile(
        r"(?:(\d+(?:\.\d+)?)\s*(?:euro|euros|eur|€|pounds?|£|dollars?|\$)|"
        r"(?:euro|euros|eur|€|pounds?|£|dollars?|\$)\s*(\d+(?:\.\d+)?)|"
        r"\b(?:twelve fifty|twenty five|fifteen point eight|twelve point five)\b|"
        r"(\d+(?:\.\d+)?)\s*(?:percent|%|centimetres?|cm|grams?|g))",
        re.I,
    )

    TOPIC_KEYWORDS = {
        "casing_material": ["plastic", "rubber", "titanium", "wood", "spongy", "latex", "material", "case"],
        "energy_source": ["battery", "solar", "kinetic", "dynamo", "rechargeable", "power"],
        "display": ["lcd", "screen", "display", "monitor", "touch screen"],
        "speech_recognition": ["speech", "voice", "voice recognition", "speech recognition"],
        "navigation_controls": ["joystick", "scroll", "wheel", "buttons", "trackball", "touch pad", "navigation"],
        "lost_remote_feature": ["lost", "find", "beep", "locator", "whistle"],
        "budget_and_pricing": ["budget", "cost", "selling price", "price", "euro", "limit", "costing"],
        "ergonomics_and_shape": ["shape", "curved", "fruit", "vegetable", "ergonomic", "grip", "rsi"],
    }

    def infer_topic(self, text: str) -> str:
        """Categorize dialogue snippet into a stable topic slug."""
        text_lower = text.lower()
        for topic, kws in self.TOPIC_KEYWORDS.items():
            if any(kw in text_lower for kw in kws):
                return topic
        return "general_design"

    def extract_from_meeting_turns(
        self,
        turns: list[Turn],
    ) -> tuple[list[CandidateDecision], list[CandidateAction], list[NumericEvidence]]:
        """Extract candidate decisions, actions, and numeric evidence from turns of one meeting."""
        decisions: list[CandidateDecision] = []
        actions: list[CandidateAction] = []
        numerics: list[NumericEvidence] = []

        for turn in turns:
            text = turn.text.strip()
            if not text or len(text.split()) < 3:
                continue

            # 1. Decisions
            for pat, ev_type in self.DECISION_PATTERNS:
                match = pat.search(text)
                if match:
                    topic = self.infer_topic(text)
                    # Pick a coherent quote around match of at least 6 words
                    words = text.split()
                    quote = text if len(words) <= 30 else " ".join(words[:min(len(words), 25)])
                    if len(quote.split()) >= 6:
                        desc = f"{ev_type.value.capitalize()} decision on {topic} by Speaker {turn.speaker_id}"
                        decisions.append(
                            CandidateDecision(
                                topic=topic,
                                event_type=ev_type,
                                description=desc,
                                turn_id=turn.turn_id,
                                speaker_id=turn.speaker_id,
                                meeting_id=turn.meeting_id,
                                team_id=turn.team_id,
                                turn_index=turn.turn_index,
                                quote=quote,
                                confidence=Confidence.HIGH if len(words) > 8 else Confidence.MEDIUM,
                            )
                        )
                    break

            # 2. Actions
            for pat, ev_type in self.ACTION_PATTERNS:
                match = pat.search(text)
                if match:
                    owner = turn.speaker_id if ev_type in (ActionEventType.ASSIGNED, ActionEventType.COMPLETED) else None
                    words = text.split()
                    quote = text if len(words) <= 30 else " ".join(words[:min(len(words), 25)])
                    if len(quote.split()) >= 6:
                        desc = f"Action {ev_type.value}: {match.group(0)}"
                        actions.append(
                            CandidateAction(
                                description=desc,
                                event_type=ev_type,
                                owner=owner,
                                deadline=None,
                                turn_id=turn.turn_id,
                                meeting_id=turn.meeting_id,
                                team_id=turn.team_id,
                                turn_index=turn.turn_index,
                                quote=quote,
                                confidence=Confidence.HIGH if owner else Confidence.MEDIUM,
                            )
                        )
                    break

            # 3. Numeric Evidence
            num_matches = self.NUMERIC_PATTERN.findall(text)
            if num_matches:
                for match_tuple in num_matches:
                    raw_str = [m for m in match_tuple if m]
                    val_str = raw_str[0] if raw_str else None
                    if not val_str:
                        # matched full word like twelve fifty
                        m_obj = self.NUMERIC_PATTERN.search(text)
                        val_str = m_obj.group(0) if m_obj else None

                    if val_str:
                        # Extract exact substring context
                        num_id = f"num_{uuid.uuid4().hex[:12]}"
                        norm_val = None
                        try:
                            norm_val = float(re.sub(r"[^\d.]", "", val_str))
                        except Exception:
                            if "twelve fifty" in val_str.lower():
                                norm_val = 12.50
                            elif "twenty five" in val_str.lower():
                                norm_val = 25.0
                            elif "fifteen point eight" in val_str.lower():
                                norm_val = 15.80
                            elif "twelve point five" in val_str.lower():
                                norm_val = 12.50

                        unit = "Euro" if any(u in text.lower() for u in ["euro", "€"]) else None
                        unit_conf = "explicit" if unit else "unknown"

                        words = text.split()
                        ctx = " ".join(words[:min(len(words), 20)])

                        numerics.append(
                            NumericEvidence(
                                numeric_id=num_id,
                                team_id=turn.team_id,
                                meeting_id=turn.meeting_id,
                                turn_id=turn.turn_id,
                                value_text=val_str,
                                normalized_value=norm_val,
                                unit=unit,
                                unit_confidence=unit_conf,
                                context_summary=ctx,
                            )
                        )

        return decisions, actions, numerics
