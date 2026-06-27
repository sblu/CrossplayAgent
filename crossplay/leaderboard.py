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
class MatchupRecord:
    """Head-to-head tally for one *unordered* pair of agents.

    `a_wins`/`b_wins` are wins for the alphabetically-first / -second name in the
    pair (the canonical order), so the same record serves a query from either side.
    """
    games: int = 0
    a_wins: int = 0
    b_wins: int = 0
    ties: int = 0


@dataclass
class Leaderboard:
    k_factor: float = DEFAULT_K
    agents: dict[str, AgentRecord] = field(default_factory=dict)
    history: list[dict] = field(default_factory=list)
    matchups: dict[str, MatchupRecord] = field(default_factory=dict)

    # ── Persistence ───────────────────────────────────────────────────────────

    @classmethod
    def load(cls, path: str = DEFAULT_PATH) -> "Leaderboard":
        p = Path(path)
        if not p.exists():
            return cls()
        raw = json.loads(p.read_text())
        agents = {name: AgentRecord(**rec) for name, rec in raw.get("agents", {}).items()}
        matchups = {key: MatchupRecord(**rec)
                    for key, rec in raw.get("matchups", {}).items()}
        return cls(
            k_factor=raw.get("k_factor", DEFAULT_K),
            agents=agents,
            history=raw.get("history", []),
            matchups=matchups,
        )

    def save(self, path: str = DEFAULT_PATH) -> None:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({
            "k_factor": self.k_factor,
            "agents": {name: vars(rec) for name, rec in self.agents.items()},
            "history": self.history,
            "matchups": {key: vars(rec) for key, rec in self.matchups.items()},
        }, indent=2))

    # ── Updates ─────────────────────────────────────────────────────────────────

    def _agent(self, name: str) -> AgentRecord:
        return self.agents.setdefault(name, AgentRecord())

    @staticmethod
    def _matchup_key(name_a: str, name_b: str) -> str:
        lo, hi = sorted((name_a, name_b))
        return f"{lo}\x1f{hi}"

    def matchup(self, name_a: str, name_b: str) -> dict:
        """Head-to-head record between two agents, from `name_a`'s perspective."""
        rec = self.matchups.get(self._matchup_key(name_a, name_b))
        if rec is None:
            return {"games": 0, "wins": 0, "losses": 0, "ties": 0}
        lo, _ = sorted((name_a, name_b))
        a_is_lo = name_a == lo
        return {
            "games": rec.games,
            "wins": rec.a_wins if a_is_lo else rec.b_wins,
            "losses": rec.b_wins if a_is_lo else rec.a_wins,
            "ties": rec.ties,
        }

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
            self._record_matchup(name_a, name_b, outcome_a)

        for rec, sf, sa, res in ((a, score_a, score_b, ra), (b, score_b, score_a, rb)):
            rec.games += 1
            rec.score_for += sf
            rec.score_against += sa
            setattr(rec, res, getattr(rec, res) + 1)

    def _record_matchup(self, name_a: str, name_b: str, outcome_a: float) -> None:
        """Tally one game into the unordered head-to-head record. `outcome_a` is
        1.0 (a won), 0.0 (b won) or 0.5 (tie)."""
        rec = self.matchups.setdefault(self._matchup_key(name_a, name_b), MatchupRecord())
        rec.games += 1
        lo, _ = sorted((name_a, name_b))
        if outcome_a == 0.5:
            rec.ties += 1
        elif (outcome_a == 1.0) == (name_a == lo):
            rec.a_wins += 1
        else:
            rec.b_wins += 1

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
