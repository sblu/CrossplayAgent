"""Crossplay bot entry point (backend-agnostic).

The same loop drives a real device or the headless simulator — pick with the
CROSSPLAY_BACKEND env var (default "ios").

iOS prerequisites:
1. Start Appium:  appium
2. In Xcode, run WebDriverAgent on the iPhone (Product > Test, WebDriverAgentRunner)
3. Confirm .env has APPIUM_HOST, APPIUM_PORT, DEVICE_UDID, BUNDLE_ID, WDA_URL

Usage:
    python main.py                         # real iPhone
    CROSSPLAY_BACKEND=sim python main.py   # headless self-play smoke test
"""
import os

from dotenv import load_dotenv

from crossplay.client.factory import build_client
from crossplay.engine.dictionary import Dictionary
from crossplay.runner import run
from crossplay.strategy.greedy import GreedyAgent

DICT_PATH = "data/dictionary/nwl23.txt"
FALLBACK_DICT = "data/sample_words.txt"


def _load_dictionary(path: str) -> Dictionary:
    try:
        return Dictionary.load(path)
    except FileNotFoundError:
        print(f"[!] {path} not found — falling back to {FALLBACK_DICT}")
        return Dictionary.load(FALLBACK_DICT)


def main():
    load_dotenv()
    backend = os.environ.get("CROSSPLAY_BACKEND", "ios")
    dictionary = _load_dictionary(DICT_PATH)
    agent = GreedyAgent(dictionary)
    print(f"Backend: {backend}   Agent: Greedy")

    client = build_client(backend, dictionary=dictionary)
    run(client, agent)


if __name__ == "__main__":
    main()
