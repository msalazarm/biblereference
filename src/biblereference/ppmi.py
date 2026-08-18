"""PPMI lemma vectors: the count-based distributional backoff, and nothing neural.

quotes.md §7's retrieval component (c). The entity pass sees Ἀβραάμ; the shared-lemma
term sees exact lemma overlap; what neither sees is a father writing σκάφος where the
verse wrote πλοῖον. The classical remedy predating every embedding: two words are
similar when they keep the same company, counted openly — Positive Pointwise Mutual
Information over sentence-window co-occurrence (Levy, Goldberg & Dagan 2015's
count-based baseline), from the **Diorisis Ancient Greek Corpus** (10.2M words,
Vatri & McGillivray, CC BY 4.0, pinned figshare snapshot). Bit-reproducible from the
snapshot plus `tools/ppmi_vectors.py`: same input, same artifact, same digest —
the deterministic line the design refuses to cross stays uncrossed.

The reader serves one question: how alike do two lemmas keep company. `allusions()`
uses the answer as a **reranking term inside the tie window only** -- it can reorder
near-equals, it never adds a bit of evidence, and :attr:`Match.bits` stays the
entity-plus-lemma sum it always was.
"""

from __future__ import annotations

import math
import sqlite3
from pathlib import Path
from typing import Final

from .licences import get
from .sources import BuiltCorpus, RemoteFile, Source

__all__ = ["DIORISIS", "PpmiVectors"]


def _refuse(archive: Path) -> list[BuiltCorpus]:
    raise RuntimeError(
        "Diorisis is a lexical corpus, not scripture; build vectors with tools/ppmi_vectors.py"
    )


DIORISIS: Final = Source(
    id="diorisis",
    label="The Diorisis Ancient Greek Corpus (Vatri & McGillivray)",
    homepage="https://doi.org/10.6084/m9.figshare.6187256",
    license="CC BY 4.0, per the figshare record.",
    terms=get("cc-by-4.0"),
    attribution="The Diorisis Ancient Greek Corpus, A. Vatri & B. McGillivray, "
    "used under CC BY 4.0.",
    files=(
        RemoteFile(
            url="https://ndownloader.figshare.com/files/11296247",
            name="Diorisis.zip",
        ),
    ),
    build=_refuse,
    note="10.2M words of lemmatised ancient Greek; the PPMI vectors' only input. The "
    "figshare file id pins the snapshot.",
)


class PpmiVectors:
    """Sparse PPMI vectors from the artifact `tools/ppmi_vectors.py` writes."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._db: sqlite3.Connection | None = None
        if self.path.exists():
            self._db = sqlite3.connect(f"file:{self.path}?mode=ro", uri=True)
            self.meta: dict[str, str] = {
                str(k): str(v) for k, v in self._db.execute("SELECT key, value FROM meta")
            }
        else:
            self.meta = {}
        self._held_vectors: dict[str, dict[int, float]] = {}

    @property
    def held(self) -> bool:
        return self._db is not None

    def _vector(self, lemma: str) -> dict[int, float]:
        if self._db is None:
            return {}
        cached = self._held_vectors.get(lemma)
        if cached is None:
            if len(self._held_vectors) > 50_000:
                self._held_vectors.clear()
            cached = self._held_vectors[lemma] = {
                int(dim): float(weight)
                for dim, weight in self._db.execute(
                    "SELECT dim, weight FROM vector WHERE lemma = ?", (lemma,)
                )
            }
        return cached

    def similarity(self, ours: str, theirs: str) -> float:
        """Cosine over the sparse PPMI rows: 0 where either lemma is unknown. Folded
        lemmas in, the same fold the lexicon speaks."""
        if ours == theirs:
            return 1.0
        a = self._vector(ours)
        b = self._vector(theirs)
        if not a or not b:
            return 0.0
        if len(b) < len(a):
            a, b = b, a
        dot = sum(weight * b.get(dim, 0.0) for dim, weight in a.items())
        if not dot:
            return 0.0
        return dot / math.sqrt(
            sum(w * w for w in a.values()) * sum(w * w for w in b.values())
        )
