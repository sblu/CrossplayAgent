from pathlib import Path


class Dictionary:
    def __init__(self, words: set[str], prefixes: set[str]):
        self._words = words
        self._prefixes = prefixes

    @classmethod
    def load(cls, path: str) -> "Dictionary":
        words: set[str] = set()
        prefixes: set[str] = set()
        for line in Path(path).read_text().splitlines():
            parts = line.split()
            if not parts:
                continue
            word = parts[0].strip().upper()
            if len(word) >= 2:
                words.add(word)
                for i in range(1, len(word)):
                    prefixes.add(word[:i])
        return cls(words, prefixes)

    def is_word(self, word: str) -> bool:
        return word in self._words

    def is_prefix(self, prefix: str) -> bool:
        return prefix in self._prefixes
