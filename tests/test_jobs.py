"""Sharding oversized batch documents: spans rebased, seams deduped, failures whole.

The consumer measured one 7,859-passage witness holding one worker while twenty-nine
idled -- because the unit of parallelism is the item, and one enormous text is one item.
Sharding splits it with overlap; what is tested here is the arithmetic that must not
lie: offsets rebased so spans point at the caller's own document, duplicates at the
seams dropped, a document with a failed part failing whole, and small documents passing
through untouched.
"""

from __future__ import annotations

from biblereference.web.jobs import _SHARD_OVERLAP, _SHARD_TOKENS, _assemble, _sharded


def test_small_documents_pass_through_untouched() -> None:
    work = [{"id": "a", "text": "few words only"}, {"id": "b", "text": None}]
    items, parts = _sharded(work)
    assert items == work and parts == {}


def test_an_oversized_document_shards_with_overlap_and_true_offsets() -> None:
    words = [f"w{i}" for i in range(_SHARD_TOKENS + 500)]
    text = " ".join(words)
    items, parts = _sharded([{"id": "big", "text": text}])
    assert parts == {"big": 2}
    first, second = items
    assert first["__offset"] == 0 and first["__part"] == 0
    assert second["__part"] == 1
    # The second shard begins exactly at the step boundary in the original text.
    step = _SHARD_TOKENS - _SHARD_OVERLAP
    assert text[second["__offset"] :].startswith(f"w{step} ")
    # And the shards overlap by the promised margin.
    assert first["text"].split()[-_SHARD_OVERLAP] == second["text"].split()[0]


def test_every_token_is_covered_by_some_shard() -> None:
    words = [f"w{i}" for i in range(3 * _SHARD_TOKENS)]
    items, parts = _sharded([{"id": "big", "text": " ".join(words)}])
    covered: set[str] = set()
    for item in items:
        covered.update(item["text"].split())
    assert covered == set(words)
    assert parts["big"] == len(items)


def test_assembly_dedupes_seams_and_keeps_the_larger_claim() -> None:
    merged = {
        "found": {
            ("big", 0): [
                {"passage": "MAT 5:7", "span": [100, 150]},
                {"passage": "JHN 1:1", "span": [800, 840]},
            ],
            ("big", 1): [
                # The same match seen from the other side of the seam: exact duplicate.
                {"passage": "JHN 1:1", "span": [800, 840]},
                # And a truncated sighting of it: contained, dropped.
                {"passage": "JHN 1:1", "span": [810, 840]},
                {"passage": "ROM 1:1", "span": [1200, 1260]},
            ],
            ("small", None): [{"passage": "PSA 22:1", "span": [3, 30]}],
        },
        "failed": {},
    }
    out = _assemble(merged, {"big": 2})
    assert [m["passage"] for m in out["found"]["big"]] == ["MAT 5:7", "JHN 1:1", "ROM 1:1"]
    assert out["found"]["small"] == [{"passage": "PSA 22:1", "span": [3, 30]}]
    assert out["failed"] == {}


def test_a_failed_part_fails_the_whole_document() -> None:
    """A silently partial answer is the one thing worse than no answer."""
    merged = {
        "found": {("big", 0): [{"passage": "MAT 5:7", "span": [1, 9]}]},
        "failed": {("big", 1): "TypeError: text must be a string"},
    }
    out = _assemble(merged, {"big": 2})
    assert "big" not in out["found"]
    assert out["failed"] == {"big": "TypeError: text must be a string"}


def test_a_control_character_in_a_document_id_cannot_stall_the_merge() -> None:
    """The consumer's afternoon, pinned.

    The shard key used to be `f"{name}\\x00{part}"`. A caller whose own document id
    contained that byte was therefore parsed as *a shard of a document that did not
    exist*: its parts never completed, `documents_done` never reached the total, and the
    job sat `running` with `done` frozen and nothing logged -- deterministically, at the
    same count every time. `/api/scan` was unaffected, which is what made it baffling.

    The key is a tuple now, so no id can collide with it whatever bytes it holds. These
    ids are the exact shape that hung: `work\\x00locus`.
    """
    from biblereference.web.jobs import _assemble, _sharded

    nasty = "clement-of-rome.1-clement\x0020.11"
    work = [{"id": nasty, "text": "short enough not to shard"}]
    items, parts = _sharded(work)
    assert len(items) == 1 and parts.get(nasty, 1) == 1

    merged = {
        "found": {(nasty, None): [{"passage": "ROM 5:1", "span": [0, 9]}]},
        "failed": {},
    }
    out = _assemble(merged, parts)
    assert nasty in out["found"], "the document comes back under its own id, NUL and all"
    assert out["failed"] == {}


def test_a_document_whose_shards_never_arrive_is_failed_not_forgotten() -> None:
    """The stall's other half: a document that vanishes between submission and result is
    the one outcome a caller cannot detect for themselves, so it is reported failed rather
    than silently absent or quietly partial."""
    from biblereference.web.jobs import _assemble

    merged = {"found": {("big", 0): [{"passage": "MAT 5:7", "span": [1, 9]}]}, "failed": {}}
    out = _assemble(merged, {"big": 3})
    assert "big" not in out["found"]
    assert "AssemblyError" in out["failed"]["big"]
    assert "1 of 3" in out["failed"]["big"]


def test_a_job_can_be_cancelled_so_a_stuck_one_costs_a_poll_not_a_restart() -> None:
    """The consumer had three jobs sitting `running` on a shared server with no way to
    clear them short of restarting it. A cancelled job keeps no result, stops counting as
    running, and says so."""
    from biblereference.web.jobs import Jobs

    jobs = Jobs(workers=1)
    try:
        record = jobs.submit_batch("scan", [], {})
        # An empty batch settles immediately; cancelling a settled job is a no-op that
        # returns it unharmed rather than pretending to have stopped something.
        assert jobs.get(record["id"])["state"] == "done"
        again = jobs.cancel(record["id"])
        assert again["state"] == "done", "a finished job is not un-finished by cancelling"

        assert jobs.cancel("no-such-job") is None

        # A job that is genuinely open cancels, drops its result, and leaves `running`.
        opened = jobs._open("scan", {}, total=1)
        assert jobs.running() >= 1
        stopped = jobs.cancel(opened["id"])
        assert stopped["state"] == "cancelled"
        assert "result" not in stopped
        assert jobs.get(opened["id"])["state"] == "cancelled"
    finally:
        jobs.close() if hasattr(jobs, "close") else None
