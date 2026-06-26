"""Single source of truth for selectable agents.

Add a new strategy here once and it becomes available everywhere that picks agents
by name — selfplay.py (--agent-a/--agent-b), the live spectator, and the dashboard.
Each entry is a constructor taking a Dictionary and returning an Agent.
"""
from crossplay.engine.dictionary import Dictionary
from crossplay.strategy.base import Agent
from crossplay.strategy.baseline import WeakAgent
from crossplay.strategy.greedy import GreedyAgent
from crossplay.strategy.heuristic import HeuristicAgent

AGENTS: dict[str, type[Agent]] = {
    "greedy": GreedyAgent,
    "heuristic": HeuristicAgent,
    "weak": WeakAgent,
}


def build_agent(name: str, dictionary: Dictionary) -> Agent:
    if name not in AGENTS:
        raise ValueError(f"unknown agent {name!r}; choices: {', '.join(AGENTS)}")
    return AGENTS[name](dictionary)
