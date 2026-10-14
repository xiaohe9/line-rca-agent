"""Working memory: in-process, zero-dependency, deliberately simple.

Recall scores by shared character bigrams rather than whitespace tokens, because the
corpus is Chinese-first and whitespace tokenisation would reduce it to noise. This is a
placeholder for the pgvector-backed episodic store — the `Memory` Protocol is the seam,
so swapping it touches nothing else.
"""

from __future__ import annotations

from line_rca_agent.contracts import MemoryItem


def _bigrams(text: str) -> set[str]:
    normalised = "".join(ch for ch in text.lower() if not ch.isspace())
    if len(normalised) < 2:
        return {normalised} if normalised else set()
    return {normalised[i : i + 2] for i in range(len(normalised) - 1)}


class WorkingMemory:
    def __init__(self, *, max_items: int = 200) -> None:
        self._items: list[MemoryItem] = []
        self._max_items = max_items

    async def write(self, item: MemoryItem) -> None:
        self._items.append(item)
        if len(self._items) > self._max_items:
            del self._items[: len(self._items) - self._max_items]

    async def recall(self, query: str, *, limit: int = 5) -> list[MemoryItem]:
        query_grams = _bigrams(query)
        if not query_grams:
            return []
        scored: list[tuple[float, MemoryItem]] = []
        for item in self._items:
            overlap = len(query_grams & _bigrams(item.content))
            if overlap:
                scored.append((overlap / len(query_grams), item))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [item for _, item in scored[:limit]]

    def __len__(self) -> int:
        return len(self._items)
