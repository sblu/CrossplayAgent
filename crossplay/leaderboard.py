"""Persistent ratings store for self-play results.

Accumulates per-agent (per-version) stats across self-play batches and maintains an
Elo rating so different strategy versions can be ranked against each other over
time. Also records a `history` of snapshots so progress can be charted.

Pure stdlib (JSON on disk); no external dependencies.
"""
import json
import time
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_PATH = "data/leaderboard.json"
DEFAULT_RATING = 1500.0
DEFAULT_K = 32.0


@dataclass
class AgentRecord:
    rating: float = DEFAULT_RATING
    games: int = 0
    wins: int = 0
    losses: int = 0
    ties: int = 0
    score_for: int = 0
    score_against: int = 0

    @property
    def winrate(self) -> float:
        return (self.wins + 0.5 * self.ties) / self.games if self.games else 0.0

    @property
    def avg_score(self) -> float:
        return self.score_for / self.games if self.games else 0.0

    @property
    def avg_margin(self) -> float:
        return (self.score_for - self.score_against) / self.games if self.games else 0.0


@dataclass
class Leaderboard:
    k_factor: float = DEFAULT_K
    agents: dict[str, AgentRecord] = field(default_factory=dict)
    history: list[dict] = field(default_factory=list)

    # ── Persistence ───────────────────────────────────────────────────────────

    @classmethod
    def load(cls, path: str = DEFAULT_PATH) -> "Leaderboard":
        p = Path(path)
        if not p.exists():
            return cls()
        raw = json.loads(p.read_text())
        agents = {name: AgentRecord(**rec) for name, rec in raw.get("agents", {}).items()}
        return cls(
            k_factor=raw.get("k_factor", DEFAULT_K),
            agents=agents,
            history=raw.get("history", []),
        )

    def save(self, path: str = DEFAULT_PATH) -> None:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({
            "k_factor": self.k_factor,
            "agents": {name: vars(rec) for name, rec in self.agents.items()},
            "history": self.history,
        }, indent=2))

    # ── Updates ─────────────────────────────────────────────────────────────────

    def _agent(self, name: str) -> AgentRecord:
        return self.agents.setdefault(name, AgentRecord())

    @staticmethod
    def _expected(rating: float, opp_rating: float) -> float:
        return 1.0 / (1.0 + 10 ** ((opp_rating - rating) / 400.0))

    def record_game(self, name_a: str, name_b: str, score_a: int, score_b: int) -> None:
        """Update both agents' Elo + tallies from one finished game.

        A self-game (name_a == name_b) still records counts but skips the Elo
        update, which would be meaningless against oneself.
        """
        a, b = self._agent(name_a), self._agent(name_b)

        if score_a > score_b:
            outcome_a, ra, rb = 1.0, "wins", "losses"
        elif score_b > score_a:
            outcome_a, ra, rb = 0.0, "losses", "wins"
        else:
            outcome_a, ra, rb = 0.5, "ties", "ties"

        if name_a != name_b:
            exp_a = self._expected(a.rating, b.rating)
            exp_b = 1.0 - exp_a
            a.rating += self.k_factor * (outcome_a - exp_a)
            b.rating += self.k_factor * ((1.0 - outcome_a) - exp_b)

        for rec, sf, sa, res in ((a, score_a, score_b, ra), (b, score_b, score_a, rb)):
            rec.games += 1
            rec.score_for += sf
            rec.score_against += sa
            setattr(rec, res, getattr(rec, res) + 1)

    def snapshot(self, run: str | None = None) -> None:
        """Append a history point per agent (call once per self-play batch)."""
        ts = time.strftime("%Y-%m-%dT%H:%M:%S")
        for name, rec in self.agents.items():
            self.history.append({
                "ts": ts, "run": run, "agent": name,
                "rating": round(rec.rating, 1), "games": rec.games,
                "winrate": round(rec.winrate, 4), "avg_score": round(rec.avg_score, 1),
            })

    # ── Views ─────────────────────────────────────────────────────────────────

    def standings(self) -> list[tuple[str, AgentRecord]]:
        """Agents ranked by rating, highest first."""
        return sorted(self.agents.items(), key=lambda kv: kv[1].rating, reverse=True)
