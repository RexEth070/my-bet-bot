"""Intelligence package for sports analysis."""
from intelligence.agent_router import AgentRouterClient
from intelligence.prompts import SPORTS_ANALYSIS_SYSTEM_PROMPT, SPORTS_ANALYSIS_USER_PROMPT

__all__ = ["AgentRouterClient", "SPORTS_ANALYSIS_SYSTEM_PROMPT", "SPORTS_ANALYSIS_USER_PROMPT"]
