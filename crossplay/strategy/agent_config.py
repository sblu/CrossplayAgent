"""Named algorithm configurations — the `data/agents.json` profile file.

The registry (registry.py) maps a *type* name to an Agent class. This adds a thin
layer on top: a JSON file of named **configurations**, each selecting a type plus
optional constructor params (e.g. HeuristicAgent's `leave_weight`). It is the
single file the dashboard surfaces so users can see and tune which algorithms the
live device bot and the simulator arena use, without editing code.

Shape of data/agents.json:
    {
      "greedy":    {"type": "greedy",    "description": "..."},
      "heuristic": {"type": "heuristic", "params": {"leave_weight": 1.0},
                    "description": "..."},
      "weak":      {"type": "weak",      "description": "..."}
    }
"""
import json
from pathlib import Path

from crossplay.engine.dictionary import Dictionary
from crossplay.strategy.base import Agent
from crossplay.strategy.registry import AGENTS

AGENT_CONFIG_PATH = "data/agents.json"

# Seed profiles written on first use — one per built-in type. Editing/extending
# this file (e.g. adding a second heuristic with a different leave_weight) makes
# the new profile selectable everywhere without code changes.
DEFAULT_AGENT_CONFIGS: dict[str, dict] = {
    "greedy": {
        "type": "greedy",
        "description": "Always plays the highest-scoring legal move.",
    },
    "heuristic": {
        "type": "heuristic",
        "params": {"leave_weight": 1.0},
        "description": "Balances immediate score against rack-leave quality.",
    },
    "weak": {
        "type": "weak",
        "description": "Plays the lowest-scoring move — a deliberately weak sparring partner.",
    },
}


def load_agent_configs(path: str | Path = AGENT_CONFIG_PATH,
                       *, create: bool = True) -> dict[str, dict]:
    """Return the named-config dict, creating the file with defaults if missing."""
    p = Path(path)
    if not p.exists():
        if create:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(DEFAULT_AGENT_CONFIGS, indent=2))
        return {k: dict(v) for k, v in DEFAULT_AGENT_CONFIGS.items()}
    data = json.loads(p.read_text())
    return data if isinstance(data, dict) else dict(DEFAULT_AGENT_CONFIGS)


def build_configured_agent(name: str, dictionary: Dictionary,
                           configs: dict | None = None,
                           path: str | Path = AGENT_CONFIG_PATH) -> Agent:
    """Construct the agent for profile `name` (type + params) from agents.json.

    Falls back to a bare registry type if `name` is a known type but not a named
    profile, so existing callers passing "greedy"/"weak"/"heuristic" keep working.
    """
    configs = configs if configs is not None else load_agent_configs(path)
    cfg = configs.get(name)
    if cfg is None:
        if name in AGENTS:
            return AGENTS[name](dictionary)
        raise ValueError(f"unknown agent profile {name!r}; "
                         f"choices: {', '.join(configs) or ', '.join(AGENTS)}")
    agent_type = cfg.get("type", name)
    if agent_type not in AGENTS:
        raise ValueError(f"profile {name!r} has unknown type {agent_type!r}; "
                         f"types: {', '.join(AGENTS)}")
    return AGENTS[agent_type](dictionary, **(cfg.get("params") or {}))
