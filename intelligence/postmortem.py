"""Post-Match Forensic Analysis and Heuristic Self-Calibration Engine.

Analyzes losing selections to extract permanent tactical rules, preventing
the system from repeating the same blind spots in future picks.
"""

import json
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional

from intelligence.prompts import POSTMORTEM_SYSTEM_PROMPT

logger = logging.getLogger(__name__)

RULES_FILE = Path(__file__).resolve().parent.parent / "postmortem_rules.json"


def load_postmortem_rules() -> List[str]:
    """Loads all accumulated failure-avoidance rules."""
    if not RULES_FILE.exists():
        return []
    try:
        with open(RULES_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data.get("rules", [])
    except Exception as e:
        logger.error(f"Failed to load postmortem rules: {e}")
        return []


def save_postmortem_rule(rule_text: str, context: Optional[str] = None):
    """Appends a new heuristic rule to the permanent memory file."""
    rules = load_postmortem_rules()
    if rule_text and rule_text not in rules:
        rules.append(rule_text)
        try:
            with open(RULES_FILE, "w", encoding="utf-8") as f:
                json.dump({"rules": rules}, f, indent=2)
            logger.info(f"Saved new postmortem heuristic rule: {rule_text}")
        except Exception as e:
            logger.error(f"Failed to save postmortem rule: {e}")


async def analyze_loss(agent, event_name: str, selection: str, odds: float) -> str:
    """Invokes LLM to perform a forensic breakdown of a losing bet."""
    user_prompt = f"""The following betting pick resulted in a loss:
- Fixture: {event_name}
- Selection: {selection}
- Odds: {odds}

Perform a forensic analysis:
1. What was the tactical or statistical failure mode (e.g. rotation, red card, heavy rain, underestimating defensive shape)?
2. Formulate 1 concise, permanent heuristic rule for the AI's pre-match filter to prevent this trap.
"""
    try:
        analysis = await agent.run_arbitrary_prompt(
            system_prompt=POSTMORTEM_SYSTEM_PROMPT,
            user_prompt=user_prompt,
        )
        # Attempt to extract rule line if explicitly labeled
        for line in analysis.splitlines():
            clean = line.strip()
            if clean.lower().startswith("rule:") or clean.lower().startswith("permanent rule:"):
                rule = clean.split(":", 1)[1].strip()
                save_postmortem_rule(rule, context=f"{event_name} ({selection})")
                break
        return analysis
    except Exception as e:
        logger.error(f"Error conducting postmortem: {e}")
        fallback_rule = f"Exercise caution on {selection} when fixtures involve high fatigue or rival derbies."
        save_postmortem_rule(fallback_rule)
        return f"• Tactical Failure: Unexpected variance or class underperformance.\n• Heuristic Rule: {fallback_rule}"
