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

import json
from contextlib import contextmanager
from typing import Any
from unittest.mock import patch

from biblereference.judge import DEFAULT_TEMPERATURE, Judge, Judgement, Verdict
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


# --------------------------------------------------------------------------------------
# How the question is asked, which was calibrated rather than chosen
# --------------------------------------------------------------------------------------


class FakeResponse:
    def __init__(self, answer: str) -> None:
        self._answer = answer

    def read(self) -> bytes:
        return json.dumps({"choices": [{"message": {"content": self._answer}}]}).encode()

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *exc: object) -> None:
        return None


@contextmanager
def recording(answers: list[str]) -> Any:
    """Capture every request the judge makes, answering from a script."""
    sent: list[dict[str, Any]] = []
    replies = list(answers)

    def fake_urlopen(request: Any, timeout: float | None = None) -> FakeResponse:
        sent.append({"url": request.full_url, "body": json.loads(request.data)})
        return FakeResponse(replies.pop(0) if replies else "NO")

    with patch("biblereference.judge.urllib.request.urlopen", fake_urlopen):
        yield sent


def test_the_question_goes_to_the_chat_endpoint() -> None:
    """Not ``/completion``. Handed a raw completion prompt, an instruction-tuned model
    rejected nearly every pair put to it including unquestionably correct ones -- a failure
    that looks exactly like a corpus full of faults, and which invalidated an entire earlier
    dismissal of this approach."""
    with recording(["YES", "YES"]) as sent:
        Judge(["http://x"]).same_verse("a", "b")

    assert sent, "no request was made"
    for call in sent:
        assert call["url"].endswith("/v1/chat/completions")
        assert "messages" in call["body"], "must be a chat request, not a raw prompt"


def test_the_votes_are_not_one_computation_repeated() -> None:
    """Distinct seeds and a non-zero temperature. At temperature 0 a best-of-three is the
    same computation three times and the vote is theatre.

    The two votes also swap the verses, so a positional bias shows up as disagreement --
    and therefore as a third question -- rather than as a confident wrong answer.
    """
    assert DEFAULT_TEMPERATURE > 0

    with recording(["YES", "NO", "YES"]) as sent:
        Judge(["http://x"]).same_verse("alpha", "beta")

    assert len(sent) == 3, "a split vote must be broken by a third question"
    assert {call["body"]["seed"] for call in sent} == {1, 2, 3}
    assert all(call["body"]["temperature"] > 0 for call in sent)

    first, second = (call["body"]["messages"][1]["content"] for call in sent[:2])
    assert first.index("alpha") < first.index("beta")
    assert second.index("beta") < second.index("alpha"), "the second vote must swap them"


def test_an_agreed_vote_costs_only_two_questions() -> None:
    """Escalation is what makes an exhaustive pass affordable."""
    with recording(["YES", "YES"]) as sent:
        assert Judge(["http://x"]).same_verse("a", "b") is True
    assert len(sent) == 2


def test_the_inverse_framing_can_only_confirm_a_rejection() -> None:
    """Alone it is 36-78% accurate, barely better than guessing; in agreement with the
    positive framing it is 98.4% and up. So it is wired as a veto.

    Here the positive prompt rejects the mapping and the inverse framing refuses to confirm
    it. The result must be uninformative -- never a contradiction, which is the only verdict
    that counts against a mapping.
    """
    ref = VerseRef("GEN", 1, 1, vrs="org")

    # The sign of this is worth pinning, because getting it backwards silently inverts the
    # whole escalation and nothing crashes. The inverse question is "are these DIFFERENT
    # verses?", so YES confirms the rejection and NO withdraws it.
    judge = Judge(["http://x"])
    with recording(["YES", "YES"]):
        assert judge.confirms_rejection("a", "b") is True
    with recording(["NO", "NO"]):
        assert judge.confirms_rejection("a", "b") is False

    # Positive prompt rejects; inverse framing declines to confirm. Uninformative, never a
    # contradiction -- a contradiction is the only verdict that counts against a mapping.
    with recording(["NO", "NO", "NO", "NO", "YES", "YES"]):
        result = judge.judge(ref, ref, "a", "b", "c")
    assert result.verdict == Verdict.UNINFORMATIVE

    # Positive rejects, inverse confirms it, and the control verse is accepted instead.
    # That is the one shape that is evidence against a mapping.
    with recording(["NO", "NO", "YES", "YES", "YES", "YES"]):
        result = judge.judge(ref, ref, "a", "b", "c")
    assert result.verdict == Verdict.CONTRADICTED


def test_work_is_shared_between_servers_by_a_counter() -> None:
    """Round-robin under a lock. Hashing the thread name looked equivalent and was not: a
    fresh pool per batch reuses thread names, so both workers landed on one server while the
    second sat idle."""
    with recording(["YES", "YES", "YES", "YES"]) as sent:
        judge = Judge(["http://one", "http://two"])
        judge.same_verse("a", "b")
        judge.same_verse("c", "d")

    hosts = [call["url"].split("/v1/")[0] for call in sent]
    assert hosts.count("http://one") == hosts.count("http://two") == 2
