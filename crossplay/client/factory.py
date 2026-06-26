"""Select and build a backend from a name (env-driven).

    CROSSPLAY_BACKEND=ios   python main.py     # real iPhone (default)
    CROSSPLAY_BACKEND=sim   python main.py     # headless simulator, greedy opponent
"""
import os

from crossplay.client.base import CrossplayClient


def build_client(backend: str | None = None, *, dictionary=None, **kwargs) -> CrossplayClient:
    backend = (backend or os.environ.get("CROSSPLAY_BACKEND", "ios")).lower()

    if backend == "ios":
        from crossplay.client.ios_client import IOSClient
        return IOSClient(**kwargs)

    if backend == "sim":
        from crossplay.client.sim_client import SimClient
        from crossplay.strategy.greedy import GreedyAgent
        if dictionary is None:
            raise ValueError("sim backend requires a dictionary for the opponent agent")
        opponent = kwargs.pop("opponent", None) or GreedyAgent(dictionary)
        return SimClient(opponent, **kwargs)

    if backend == "android":
        from crossplay.client.android_client import AndroidClient
        return AndroidClient(**kwargs)

    raise ValueError(f"unknown backend {backend!r} (expected ios | android | sim)")
