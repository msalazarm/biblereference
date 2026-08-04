"""What versification families actually exist, derived from the editions rather than assumed.

Every audit in this project used to begin the same wrong way: take the seven systems the
vendored data declares, file each corpus under one of them, and then check the mappings.
The filing step was never verified, and it was wrong often enough to invalidate the
results. The Orthodox Jewish Bible is off from `org` on ten chapters; Brenton is off from
`lxx` on twenty-nine; Swete is off on a hundred and twelve and matches nothing shipped. An
eleven-hour sweep built on those witnesses spent itself measuring the witnesses.

So this module derives the families instead. A corpus belongs to a family only when its
structure is *exact* to every other member -- which is a stricter rule than the vendored
data uses, and it finds that the "English family" is really eleven distinct numberings that
upstream flattened into one.

**The signature is taken over complete chapters only.** A corpus's structure is the map
from chapter to verse count, but only for chapters it holds whole, verses 1..n with no
gaps. Using the highest *printed* verse instead measures how much an edition left out: it
scored a Scripture portion at 42% agreement and read as a catastrophic misfile when the
edition was simply a selection. See :data:`biblereference.corpora.ebible.PORTIONS`.

**There is no canonical partition, and the honest thing is to say so.** Compatibility --
agreeing on every chapter two corpora share -- is reflexive and symmetric but *not
transitive*, so it induces no equivalence classes. The counterexample is concrete and not a
corner case: the King James and the Revised Version differ on exactly two chapters, 2 Esdras
7 (70 verses against 140, the famous missing fragment) and Sirach 23. Any Protestant-canon
Bible has neither book, so it agrees perfectly with both and chains them together. Three
other constructions were tried and all fail:

* **Signature refinement.** Canonical, but it splits the King James from the Cambridge
  Paragraph Bible, which agree on all 1,356 chapters they share -- neither one's coverage
  contains the other's, so neither refines the other.
* **Maximal cliques.** Canonical, but 29 of 55 corpora land in more than one, and the
  largest cliques have no member unique to them. True and useless together.
* **Chain growth in any order.** Produced 15 to 20 families depending on the order, and
  matched the coverage-ordered answer once in 200 random trials.

So this module states a rule rather than pretending to discover a partition: **families are
grown in descending order of coverage**, so that complete Bibles found them and partial
editions join. Under that rule the answer is deterministic -- shuffling corpora of equal
coverage reproduced the identical partition in 200 of 200 trials -- and
:meth:`Derivation.compatibility` then reports, canonically and independent of any ordering,
every family each corpus is compatible with. Where that list holds more than one name, the
partition made a choice and the choice is visible.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

from .store import DataHome

__all__ = [
    "MIN_OVERLAP",
    "Chapter",
    "Derivation",
    "Family",
    "Placement",
    "Signature",
    "derive",
    "disagreements",
    "read_signatures",
    "signature",
]

#: A book code and a chapter number.
Chapter = tuple[str, int]

#: How many verses each chapter holds, for chapters the corpus holds complete.
Signature = dict[Chapter, int]

#: Chapters two corpora must share before their agreement means anything.
#:
#: Set from the shape of the corpus rather than by taste. The New Testament is 260 chapters
#: and is numbered identically by every family here, so any threshold at or below it lets a
#: New Testament agree with every family at once -- which is the correct answer, and the
#: reason placement reports ambiguity rather than resolving it. What this number actually
#: guards against is the opposite mistake: a four-chapter edition of Jonah agreeing with a
#: family on all four and being declared a member on that evidence.
MIN_OVERLAP: Final = 50


def signature(connection: sqlite3.Connection, corpus: str) -> Signature:
    """The chapters this corpus holds complete, and how long each one is.

    Complete means verses 1..n with none missing. A chapter with a hole in it tells us
    what the edition chose to print, not how it numbers scripture.
    """
    rows = connection.execute(
        "SELECT book, chapter, MAX(verse), COUNT(DISTINCT verse), MIN(verse) FROM verse "
        "WHERE corpus = ? AND verse > 0 GROUP BY book, chapter",
        (corpus,),
    )
    return {(str(b), int(ch)): int(top) for b, ch, top, n, low in rows if low == 1 and n == top}


def read_signatures(home: DataHome, corpora: Sequence[str] | None = None) -> dict[str, Signature]:
    """Every corpus's signature, straight from the store."""
    connection = sqlite3.connect(f"file:{home.database}?mode=ro", uri=True)
    try:
        names = corpora or [
            str(row[0]) for row in connection.execute("SELECT corpus FROM source_meta ORDER BY 1")
        ]
        return {name: signature(connection, name) for name in names}
    finally:
        connection.close()


def disagreements(left: Signature, right: Signature) -> list[Chapter]:
    """Chapters both hold complete and give different lengths."""
    return sorted(key for key in left.keys() & right.keys() if left[key] != right[key])


@dataclass
class Family:
    """One exact numbering, and the editions that follow it.

    The signature is the *union* of its members': a family seeded by a Protestant Bible
    learns the deuterocanon when a member carrying it joins. Members never disagree with
    the union, because disagreeing is what keeps a corpus out.
    """

    name: str
    members: list[str] = field(default_factory=list)
    signature: Signature = field(default_factory=dict)

    def conflicts(self, other: Signature) -> list[Chapter]:
        return disagreements(self.signature, other)

    def shared(self, other: Signature) -> int:
        return len(self.signature.keys() & other.keys())


@dataclass(frozen=True, slots=True)
class Placement:
    """Where one corpus landed, and on what evidence."""

    corpus: str
    family: str | None
    """The family joined, or None when the corpus could not be placed."""
    chapters: int
    """How many chapters the corpus holds complete."""
    overlap: int
    """Chapters shared with the family it joined, or with the best candidate."""
    candidates: tuple[str, ...] = ()
    """Families it fits equally well. More than one means it was not placed."""
    verdict: str = "joined"
    """``joined``, ``seeded``, ``ambiguous`` or ``unplaceable``."""

    @property
    def placed(self) -> bool:
        return self.family is not None

    def describe(self) -> str:
        if self.verdict == "ambiguous":
            return (
                f"{self.corpus:13} ambiguous between {', '.join(self.candidates)} "
                f"({self.chapters} chapters, all agree)"
            )
        if self.verdict == "unplaceable":
            return f"{self.corpus:13} unplaceable -- only {self.chapters} complete chapters"
        return f"{self.corpus:13} {self.verdict:8} {self.family} (overlap {self.overlap})"


@dataclass
class Derivation:
    """The whole partition, and everything that would not fit in it."""

    families: list[Family]
    placements: list[Placement]

    def family_of(self, corpus: str) -> str | None:
        for family in self.families:
            if corpus in family.members:
                return family.name
        return None

    @property
    def ambiguous(self) -> list[Placement]:
        return [p for p in self.placements if p.verdict == "ambiguous"]

    @property
    def unplaceable(self) -> list[Placement]:
        return [p for p in self.placements if p.verdict == "unplaceable"]

    def membership(
        self, signatures: Mapping[str, Signature], *, min_overlap: int = MIN_OVERLAP
    ) -> dict[str, list[str]]:
        """Every family each corpus belongs to. Often more than one, and that is the answer.

        The rule is that a corpus belongs to a family when the books they *share* match
        exactly; books one side simply does not carry are no obstacle, since a Protestant
        Bible lacking Tobit and a Catholic one carrying it can still number Genesis
        identically. That rule is right and it does not yield a partition, because it is not
        transitive.

        The concrete case: the King James and the Revised Version both carry 2 Esdras and
        Sirach and disagree there -- 2 Esdras 7 runs to 70 verses in the one and 140 in the
        other, the fragment restored from the Codex Ambianensis -- so they are different
        families. The American Standard Version carries neither book, matches the King James
        exactly on everything they share, and matches the Revised Version exactly too. It
        belongs to both. Nothing is missing and no tie needs breaking: for any purpose the
        ASV has text for, the two numberings are the same.

        So membership is a cover rather than a partition, and a corpus listed under several
        families is fully placed. Only an empty list means genuinely unplaceable -- too few
        complete chapters to compare against anything.
        """
        return self.compatibility(signatures, min_overlap=min_overlap)

    def sole_members(self, signatures: Mapping[str, Signature]) -> dict[str, list[str]]:
        """Per family, the corpora that match it and nothing else."""
        member = self.membership(signatures)
        out: dict[str, list[str]] = {family.name: [] for family in self.families}
        for corpus, families in member.items():
            if len(families) == 1:
                out[families[0]].append(corpus)
        return {name: sorted(corpora) for name, corpora in out.items()}

    def shared_members(self, signatures: Mapping[str, Signature]) -> dict[str, list[str]]:
        """Per family, the corpora that match it *and* at least one other."""
        member = self.membership(signatures)
        out: dict[str, list[str]] = {family.name: [] for family in self.families}
        for corpus, families in member.items():
            if len(families) > 1:
                for name in families:
                    out[name].append(corpus)
        return {name: sorted(corpora) for name, corpora in out.items()}

    def compatibility(
        self, signatures: Mapping[str, Signature], *, min_overlap: int = MIN_OVERLAP
    ) -> dict[str, list[str]]:
        """Every family each corpus could belong to, judged against the finished partition.

        This is the canonical half of the answer and the one to trust: it depends on no
        ordering, and it is computed against the *final* families rather than against
        whichever ones happened to exist when the corpus was reached.

        That distinction matters. During growth a corpus joins when exactly one family fits
        at that moment, but a family founded later may fit it just as well -- so ``joined``
        is not by itself proof of a unique home. A corpus whose list here holds one name is
        determined. A corpus whose list holds several is *exact to all of them*, and they
        differ only outside the chapters it carries.
        """
        out: dict[str, list[str]] = {}
        for corpus, sig in signatures.items():
            if not sig:
                out[corpus] = []
                continue
            out[corpus] = sorted(
                family.name
                for family in self.families
                if not family.conflicts(sig) and family.shared(sig) >= min_overlap
            )
        return out

    def distances(self) -> dict[tuple[str, str], int]:
        """Chapters on which each pair of families differs, over what they both cover.

        This is what makes the partition checkable rather than merely asserted: within a
        family the distance is zero by construction, so the number that matters is how far
        apart the families are. Measured on the built corpus the gap is stark -- neighbouring
        families differ on one to three chapters, distant ones on a hundred and thirty to a
        hundred and ninety, and nothing at all lands in between.
        """
        out: dict[tuple[str, str], int] = {}
        for i, left in enumerate(self.families):
            for right in self.families[i + 1 :]:
                out[(left.name, right.name)] = len(left.conflicts(right.signature))
        return out


def derive(signatures: Mapping[str, Signature], *, min_overlap: int = MIN_OVERLAP) -> Derivation:
    """Grow families from the corpora, largest first.

    Ordering by coverage means full Bibles seed the families and partial editions join
    them, rather than a four-chapter edition founding a family that a complete Bible is
    then measured against.

    A corpus joins a family when it agrees on every chapter they share and shares enough of
    them to mean it. Four outcomes, and only the first two place the corpus:

    ``joined``       agrees with exactly one family, on enough chapters
    ``seeded``       disagrees with every family it meaningfully overlaps -- a new numbering
    ``ambiguous``    agrees with two or more, and nothing here can choose between them
    ``unplaceable``  overlaps nothing enough to say anything at all

    The ambiguous case is deliberately left unresolved. A Greek New Testament really does
    agree with every family, because they all number the New Testament alike; picking one
    would manufacture a fact. Text can often break the tie, and that is a separate step.
    """
    order = sorted(signatures, key=lambda name: (-len(signatures[name]), name))
    families: list[Family] = []
    placements: list[Placement] = []

    for corpus in order:
        sig = signatures[corpus]
        if not sig:
            placements.append(Placement(corpus, None, 0, 0, verdict="unplaceable"))
            continue

        fits: list[Family] = []
        excluded = 0
        untested = 0
        for family in families:
            if family.conflicts(sig):
                # One chapter of disagreement settles it, however little else they share:
                # two editions that number a chapter differently are not one numbering.
                excluded += 1
            elif family.shared(sig) >= min_overlap:
                fits.append(family)
            else:
                # Agrees, but on too little to mean anything.
                untested += 1

        if len(fits) == 1:
            family = fits[0]
            overlap = family.shared(sig)
            family.members.append(corpus)
            family.signature.update(sig)
            placements.append(Placement(corpus, family.name, len(sig), overlap))
        elif len(fits) > 1:
            placements.append(
                Placement(
                    corpus,
                    None,
                    len(sig),
                    max(f.shared(sig) for f in fits),
                    tuple(sorted(f.name for f in fits)),
                    "ambiguous",
                )
            )
        elif (excluded or not families) and not untested and len(sig) >= min_overlap:
            # Different from everything it can be compared against, and large enough to
            # characterise a numbering of its own.
            #
            # All three conditions earn their place. Without `not untested`, a corpus that
            # merely fails to overlap some family is treated as differing from it. Without
            # the size floor, a four-chapter edition of Jonah founds a family on the
            # strength of four chapters -- which is how `glw`, `e2t` and `swete-daniel`
            # first came out of this function as three separate numberings, each of them
            # zero chapters distant from a dozen others.
            family = Family(name=corpus, members=[corpus], signature=dict(sig))
            families.append(family)
            placements.append(Placement(corpus, corpus, len(sig), 0, verdict="seeded"))
        else:
            placements.append(Placement(corpus, None, len(sig), 0, verdict="unplaceable"))

    return Derivation(families, placements)


def to_json(
    derivation: Derivation,
    signatures: Mapping[str, Signature],
    declared: Mapping[str, str] | None = None,
) -> dict[str, object]:
    """The derivation as plain data, for a report or a regression fixture.

    Signatures are not included. They run to a thousand entries per family and the useful
    facts about them -- who belongs, who could not be placed, how far apart the families
    are, and which corpora the partition had to choose a home for -- are all here.
    """
    compatible = derivation.compatibility(signatures)
    return {
        "compatibility": [
            {
                "corpus": corpus,
                "chapters": len(signatures[corpus]),
                "families": families,
                "determined": len(families) == 1,
                "assigned": derivation.family_of(corpus),
            }
            for corpus, families in sorted(compatible.items())
        ],
        "families": [
            {
                "name": family.name,
                "members": sorted(family.members),
                "chapters": len(family.signature),
                "declared": sorted({(declared or {}).get(m, "?") for m in family.members}),
            }
            for family in sorted(derivation.families, key=lambda f: -len(f.members))
        ],
        "unplaced": [
            {
                "corpus": p.corpus,
                "verdict": p.verdict,
                "chapters": p.chapters,
                "candidates": list(p.candidates),
            }
            for p in derivation.placements
            if not p.placed
        ],
        "distances": [
            {"families": [a, b], "chapters_differing": n}
            for (a, b), n in sorted(derivation.distances().items(), key=lambda kv: kv[1])
        ],
    }


def write_json(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def declared_systems(home: DataHome, corpora: Iterable[str] | None = None) -> dict[str, str]:
    """What each corpus *says* its versification is, for comparison against what it is."""
    connection = sqlite3.connect(f"file:{home.database}?mode=ro", uri=True)
    try:
        rows = connection.execute("SELECT corpus, versification FROM source_meta")
        found = {str(c): str(v) for c, v in rows}
    finally:
        connection.close()
    return found if corpora is None else {k: v for k, v in found.items() if k in set(corpora)}
