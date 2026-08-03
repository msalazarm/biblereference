"""What counts as evidence when a language model is the instrument.

The model is asked whether two verses are the same passage. On its own that answer is
worth very little: a model inclined to agree confirms everything, and a model that cannot
read one of the texts rejects everything. Either way the output looks like data.

The control probe is what turns it into evidence. Every verse is asked twice -- once about
the mapping, once about a verse known to be wrong -- and only an answer that *distinguishes*
the two counts, in either direction. These tests pin that rule, because getting it wrong is
not a crash: it is a plausible-looking pile of findings that are not findings.
"""

from __future__ import annotations

from biblereference.judge import Judgement, Verdict
from biblereference.refs import VerseRef


def judged(mapping: bool, control: bool) -> Judgement:
    return Judgement(
        VerseRef("GEN", 1, 1, vrs="nvl"),
        VerseRef("GEN", 1, 1, vrs="org"),
        mapping_answer=mapping,
        control_answer=control,
    )


def test_yes_to_the_mapping_and_no_to_its_neighbour_confirms_it() -> None:
    """The only shape of answer that supports a mapping: the model told them apart and
    chose the one the data claims."""
    assert judged(mapping=True, control=False).verdict == Verdict.CONFIRMED


def test_no_to_the_mapping_and_yes_to_its_neighbour_contradicts_it() -> None:
    """And the only shape that counts against one. The model told them apart and preferred
    the other."""
    assert judged(mapping=False, control=True).verdict == Verdict.CONTRADICTED


def test_yes_to_both_is_not_confirmation() -> None:
    """The failure this was built for. A model agreeable enough to accept a verse known to
    be wrong would otherwise hand back a clean bill of health for a corpus full of errors,
    and it would look exactly like evidence."""
    assert judged(mapping=True, control=True).verdict == Verdict.UNINFORMATIVE


def test_no_to_both_is_not_a_contradiction() -> None:
    """The mirror failure, and the one this module originally got wrong.

    A model that rejects the mapping *and* rejects a verse it was supposed to reject has
    said nothing about the mapping -- it has said it cannot read this pair of texts. Scored
    as a contradiction, it inflated the count twenty-two fold: 247 apparent contradictions
    across 3,500 verses of the Nova Vulgata against the Orthodox Jewish Bible, of which 11
    survived this rule. The Orthodox Jewish Bible transliterates its Hebrew heavily --
    *achim*, *meyalledot*, *nogesim* -- and a small quantised model reads that as a foreign
    language and says no to everything.
    """
    assert judged(mapping=False, control=False).verdict == Verdict.UNINFORMATIVE


def test_only_discriminating_answers_are_evidence() -> None:
    """Stated once as the invariant, so the rule survives a rewrite of the branches."""
    for mapping in (True, False):
        for control in (True, False):
            verdict = judged(mapping, control).verdict
            discriminated = mapping != control
            assert (verdict != Verdict.UNINFORMATIVE) == discriminated
