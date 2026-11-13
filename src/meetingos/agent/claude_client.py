"""Claude API Client for MeetingOS.

Provides structured integration with Anthropic Claude models (e.g. claude-haiku-5-5,
claude-sonnet-5-5) for evidence-grounded answer synthesis and extraction.
"""
from __future__ import annotations

import json
import logging
import os
import re
from typing import Optional

import requests

from meetingos.models import Answer, Citation

logger = logging.getLogger(__name__)

DEFAULT_CLAUDE_MODEL = "claude-haiku-5-5"
ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"


class ClaudeClient:
    """Client for generating evidence-grounded answers using Anthropic Claude."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = DEFAULT_CLAUDE_MODEL,
        timeout: int = 45,
    ):
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        self.model = model
        self.timeout = timeout
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.total_requests = 0

    @property
    def is_available(self) -> bool:
        return bool(self.api_key and len(self.api_key) > 10)

    def get_usage_summary(self) -> dict:
        """Return cumulative API usage statistics."""
        return {
            "requests": self.total_requests,
            "input_tokens": self.total_input_tokens,
            "output_tokens": self.total_output_tokens,
            "model": self.model,
            "estimated_cost_usd": (self.total_input_tokens * 0.00000010) + (self.total_output_tokens * 0.00000050),
        }

    def synthesize_answer(
        self,
        question_id: str,
        question_text: str,
        team_id: str,
        evidence_turns: list[dict],
    ) -> Optional[Answer]:
        """
        Send retrieved evidence turns to Claude to generate an answer and citations.
        """
        if not self.is_available:
            return None

        # Group turns by meeting to preserve multi-meeting coverage
        by_meeting: dict[str, list[dict]] = {}
        for t in evidence_turns:
            mid = t.get("meeting_id", "unknown")
            by_meeting.setdefault(mid, []).append(t)

        selected_turns = []
        # Take up to 10 turns per meeting across all available meetings
        for mid, turns in sorted(by_meeting.items()):
            selected_turns.extend(turns[:10])

        formatted_evidence = []
        for t in selected_turns[:35]:
            mid = t.get("meeting_id", "")
            tid = t.get("turn_id", "")
            spk = t.get("speaker_id", "")
            txt = t.get("text", "")
            formatted_evidence.append(f"[{mid} Turn {tid}] Speaker {spk}: {txt}")

        evidence_str = "\n".join(formatted_evidence)

        prompt = f"""You are an evidence-grounded meeting intelligence engine answering questions about Team {team_id}'s design meetings.

QUESTION:
{question_text}

EVIDENCE FROM TRANSCRIPTS:
{evidence_str}

CONSTRAINTS:
1. Provide a direct, factually accurate answer in strictly 1 to 3 plain sentences.
2. Select 1 to 3 citations from the evidence turns supporting your answer.
3. Every citation MUST be an exact verbatim substring of at least 6 consecutive words taken directly from within one speaker turn in the evidence. Do not paraphrase or alter punctuation.
4. If the question spans multiple meetings, provide citations from at least 2 distinct meetings.
5. Return your response in valid JSON matching this schema:
{{
  "answer": "1 to 3 sentences answering the question directly",
  "citations": [
    {{"meeting_id": "TS3006d", "quote": "exact verbatim quote of 6 or more words"}}
  ]
}}
"""
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": ANTHROPIC_VERSION,
            "content-type": "application/json",
        }
        payload = {
            "model": self.model,
            "max_tokens": 800,
            "thinking": {"type": "disabled"},
            "messages": [{"role": "user", "content": prompt}],
        }

        try:
            resp = requests.post(
                ANTHROPIC_API_URL,
                headers=headers,
                json=payload,
                timeout=self.timeout,
            )
            if resp.status_code != 200:
                logger.warning(f"Claude API returned status {resp.status_code}: {resp.text[:150]}")
                return None

            data = resp.json()
            usage = data.get("usage", {})
            in_tok = usage.get("input_tokens", 0)
            out_tok = usage.get("output_tokens", 0)
            self.total_input_tokens += in_tok
            self.total_output_tokens += out_tok
            self.total_requests += 1
            logger.info(f"[{question_id}] Claude call succeeded (tokens: in={in_tok}, out={out_tok})")

            content_blocks = data.get("content", [])
            text = ""
            for block in content_blocks:
                if block.get("type") == "text":
                    text = block.get("text", "")
                    break

            # Parse JSON
            match = re.search(r"\{.*\}", text, re.DOTALL)
            if not match:
                logger.warning(f"No JSON found in Claude response: {text[:100]}")
                return None

            parsed = json.loads(match.group(0))
            ans_text = parsed.get("answer", "")
            cits_data = parsed.get("citations", [])

            citations = [
                Citation(meeting_id=c["meeting_id"], quote=c["quote"])
                for c in cits_data
                if "meeting_id" in c and "quote" in c
            ]

            return Answer(
                question_id=question_id,
                answer=ans_text,
                citations=citations,
                abstained=False,
            )

        except Exception as exc:
            logger.warning(f"Failed to call Claude API: {exc}")
            return None
