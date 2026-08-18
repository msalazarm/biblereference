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
            "big\x00" + "0": [
                {"passage": "MAT 5:7", "span": [100, 150]},
                {"passage": "JHN 1:1", "span": [800, 840]},
            ],
            "big\x00" + "1": [
                # The same match seen from the other side of the seam: exact duplicate.
                {"passage": "JHN 1:1", "span": [800, 840]},
                # And a truncated sighting of it: contained, dropped.
                {"passage": "JHN 1:1", "span": [810, 840]},
                {"passage": "ROM 1:1", "span": [1200, 1260]},
            ],
            "small": [{"passage": "PSA 22:1", "span": [3, 30]}],
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
        "found": {"big\x00" + "0": [{"passage": "MAT 5:7", "span": [1, 9]}]},
        "failed": {"big\x00" + "1": "TypeError: text must be a string"},
    }
    out = _assemble(merged, {"big": 2})
    assert "big" not in out["found"]
    assert out["failed"] == {"big": "TypeError: text must be a string"}
