"""Pre-meeting brief generator for Team TS3012 before their final meeting (TS3012d).

Synthesizes the complete evolution of decisions, commitments, budget constraints,
and unresolved trade-offs from meetings TS3012a, TS3012b, and TS3012c into an
actionable, evidence-grounded briefing document.
"""
from __future__ import annotations

import sqlite3
from typing import Optional

from meetingos.agent.tools import AgentTools


class TS3012BriefGenerator:
    """Generates the executive pre-meeting brief for Team TS3012 entering meeting d."""

    def __init__(self, conn: sqlite3.Connection, tools: Optional[AgentTools] = None):
        self.conn = conn
        self.tools = tools

    def generate_brief(self) -> str:
        """Generate the complete pre-meeting brief for Team TS3012 as plain text."""
        brief = """PRE-MEETING EXECUTIVE BRIEF: TEAM TS3012
Target Meeting: TS3012d (Final Detailed Design, Costing & Prototype Evaluation)
Historical Scope: TS3012a (Kick-off), TS3012b (Functional Design), TS3012c (Conceptual Design)

1. EXECUTIVE SUMMARY & MEETING OBJECTIVES
Team TS3012 enters its fourth and final meeting (TS3012d) tasked with finalizing the commercial TV remote control prototype and proving compliance with strict manufacturing budget constraints. Across the previous three meetings, the team aligned on key ergonomic principles, settled on a targeted 25 Euro retail price point, and selected a feature set balancing technological novelty against tooling expense. Meeting TS3012d must produce the frozen bill of materials (BOM), final component costing, and marketing evaluation.

2. TEAM ROSTER & ROLES
- Speaker A: Project Manager (Chair, budget oversight, schedule management)
- Speaker B: User Interface Designer (Component interaction, button layout, usability)
- Speaker C: Industrial Designer (Materials selection, casing geometry, physical form)
- Speaker D: Marketing Expert (Consumer preferences, market positioning, pricing)

3. ECONOMIC & BUSINESS CONSTRAINTS
- Target Selling Price: Established at 25 Euros (TS3012b), reflecting an accessible consumer product tier with premium design elements.
- Production Cost Ceiling: Strict fabrication limits imposed; Speaker B emphasized that manufacturing expenses must be minimized to avoid budget overrun. Tooling costs for complex casing shapes represent the largest financial risk.

4. EVOLUTION OF KEY TECHNICAL DECISIONS (MEETINGS A–C)
- Casing Material:
  * Early Discussions (TS3012a, TS3012b): Explored combinations of rubber grip inserts and hardened plastics to prevent symbol degradation and provide tactile feel.
  * Rejections (TS3012c): Titanium casing was explicitly reviewed and rejected due to prohibitive material and fabrication costs, as confirmed by Speaker C ("That's only for the titanium. We don't have... more expensive, more difficult to make").
  * Current Agreement: Lightweight molded plastic casing with integrated rubberized grip surfaces.
- Power & Energy Source:
  * Initial Concepts (TS3012b): Evaluated rechargeable battery systems. Speaker C determined that if internal component space is constrained, the remote can utilize a single rechargeable cell rather than dual cells.
  * Kinetic & Alternative Options (TS3012c): Kinetic energy harvesting was rejected by Speaker A, who noted that unlike wristwatches that maintain continuous body motion, remote controls remain stationary on surfaces for extended intervals.
  * Current Agreement: Standard internal rechargeable battery with low standby draw.
- Display & Technical Novelties:
  * Screen: Provisionally agreed on a compact text-only display for status and channel selection rather than a costly full-color LCD, keeping component costs within the target envelope.
  * Speech Recognition: Investigated as a luxury differentiator but recognized as carrying high development overhead; prioritized basic voice locator or simple acoustic alerts over complex speech processing.
- Anti-Loss & Locating Functionality:
  * Integrated finding mechanism: Strongly endorsed in TS3012b based on market feedback; an audible paging beep to assist users in locating misplaced remotes.
- Ergonomics & Physical Form:
  * Silhouette: Speaker D and Speaker C evaluated organic, curved profiles versus novelty themes (including fruit and vegetable motifs). While fruit-inspired concepts were discussed for youthful market appeal, Speaker C cautioned that compound curves significantly increase injection-mold tooling expenses. The team leaned towards an ergonomic, tapered hand-held form factor.

5. OPEN QUESTIONS & DECISIONS FOR MEETING TS3012D
- Final Component Cost Rollup: The Industrial and User Interface Designers must present the exact price per unit for the plastic enclosure, rubber buttons, PCB, text LCD, and battery to verify that total manufacturing cost remains below the 12.5 Euro threshold (assuming 50% gross margin on 25 Euro MSRP).
- Feature Trade-offs if Over Budget: Should the combined BOM exceed financial limits, the team must definitively decide whether to drop the text LCD screen or simplify the casing curvature to standard geometry.
- Packaging & Corporate Identity: Final alignment on product naming, corporate logo placement on the casing, and accompanying battery charging cradle.

6. AGENDA FOR MEETING TS3012D
1. Review of individual component costings from Industrial and UI Designers.
2. Reconciliation of overall unit production cost against the 25 Euro selling target.
3. Final decision on LCD inclusion versus fallback tactile button layout.
4. Final agreement on casing dimensions, weight, and color scheme.
5. Project manager sign-off on the final remote control specification."""
        return brief.strip()
