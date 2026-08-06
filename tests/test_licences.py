"""What a text may be used for, and the ways of getting that wrong.

The value of modelling licences at all is that the library can be *asked* a question it
could not answer before -- which of sixty corpora forbid commercial use. These tests are
about the two ways that answer goes wrong: a licence read too loosely, so something
restricted looks free; and a licence not read at all, silently defaulting to permissive.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from biblereference.licences import LICENCES, from_url, get, strictest
from biblereference.store import DataHome, SourceMeta, open_store, read_meta, write_corpus


def test_the_registry_is_internally_consistent() -> None:
    """Every licence knows its own id, and says something about itself."""
    for key, licence in LICENCES.items():
        assert licence.id == key
        assert licence.name and licence.summary and licence.notice
        # Attribution is required by everything except the public domain, which is the
        # only entry that obliges nothing at all.
        assert licence.attribution == (licence.id != "public-domain")


def test_public_domain_is_the_only_thing_that_obliges_nothing() -> None:
    public = get("public-domain")
    assert public.commercial and not public.share_alike and not public.attribution
    assert not public.restricted
    assert public.rank == min(licence.rank for licence in LICENCES.values())


@pytest.mark.parametrize(
    ("target", "expected"),
    [
        ("https://creativecommons.org/licenses/by/4.0/", "cc-by-4.0"),
        # The Digital Syriac Corpus writes http, the Patristic Text Archive https, and one
        # of them omits the trailing slash. Treating those as different licences would
        # file two thirds of the Syriac as unknown.
        ("http://creativecommons.org/licenses/by/4.0", "cc-by-4.0"),
        ("HTTPS://CreativeCommons.org/licenses/BY-NC/4.0/", "cc-by-nc-4.0"),
        ("https://creativecommons.org/licenses/by-sa/4.0/", "cc-by-sa-4.0"),
        ("https://creativecommons.org/licenses/by-nc-sa/4.0/", "cc-by-nc-sa-4.0"),
        ("https://creativecommons.org/publicdomain/zero/1.0/", "public-domain"),
    ],
)
def test_a_creative_commons_url_is_recognised_however_it_is_written(
    target: str, expected: str
) -> None:
    licence = from_url(target)
    assert licence is not None and licence.id == expected


@pytest.mark.parametrize(
    "target",
    [
        None,
        "",
        "https://example.invalid/terms.html",
        "See the publisher's website",
        # 3.0 differs from 4.0 in ways nobody here has read. Saying so is the point.
        "https://creativecommons.org/licenses/by-nc/3.0/",
    ],
)
def test_a_licence_nobody_has_read_returns_nothing_rather_than_something_permissive(
    target: str | None,
) -> None:
    """The one mistake in this module that nobody would notice.

    A parser meeting an unfamiliar licence has to record that it did not understand it. If
    ``from_url`` guessed a permissive default, a restricted text would be filed as free and
    every count built on it would be wrong in the direction that gets someone sued.
    """
    assert from_url(target) is None


def test_the_strictest_licence_governs_a_mixed_set() -> None:
    """A collection is only as usable as its most restricted member.

    Rounding the other way would state a freedom the holder does not have, which is the
    whole reason this function exists rather than an ad-hoc ``min``.
    """
    assert strictest([get("cc-by-4.0"), get("cc-by-nc-4.0")]).id == "cc-by-nc-4.0"
    assert strictest([get("public-domain"), get("cc-by-sa-4.0")]).id == "cc-by-sa-4.0"
    assert strictest([get("cc-by-nc-4.0"), get("cc-by-nc-sa-4.0")]).id == "cc-by-nc-sa-4.0"
    assert strictest([get("cc-by-4.0")]).id == "cc-by-4.0"
    with pytest.raises(ValueError):
        strictest([])


def test_a_file_can_be_wrong_about_its_own_licence() -> None:
    """The Patristic Text Archive publishes the SBL Greek New Testament under a CC BY
    header. The text is the SBLGNT, whose own terms are not CC BY, and printing the
    header's claim would state something untrue in a document meant to be relied on.
    """
    sblgnt = get("sblgnt")
    assert not sblgnt.commercial
    assert sblgnt.restricted
    assert "Society of Biblical Literature" in sblgnt.notice


def test_an_unknown_id_names_what_is_known() -> None:
    with pytest.raises(KeyError, match=r"cc-by-4\.0"):
        get("cc-by-9.9")


# --------------------------------------------------------------------------------------
# Reaching the database
# --------------------------------------------------------------------------------------


def test_the_terms_survive_a_round_trip_through_the_database(tmp_path: Path) -> None:
    home = DataHome(tmp_path)
    write_corpus(
        home,
        SourceMeta(
            corpus="demo",
            label="Demo",
            language="syc",
            versification="org",
            licence_id="cc-by-nc-4.0",
            licence_ids="cc-by-4.0,cc-by-nc-4.0",
        ),
        [],
    )
    (stored,) = read_meta(home)
    assert stored.licence_id == "cc-by-nc-4.0"
    assert stored.terms is not None and not stored.terms.commercial
    assert stored.licence_ids == "cc-by-4.0,cc-by-nc-4.0"


def test_a_corpus_with_no_recorded_licence_says_nothing_rather_than_yes(
    tmp_path: Path,
) -> None:
    """Fifty-five corpora predate this module. Their terms are unread, not permissive."""
    home = DataHome(tmp_path)
    write_corpus(
        home,
        SourceMeta(corpus="old", label="Old", language="en", versification="eng"),
        [],
    )
    (stored,) = read_meta(home)
    assert stored.licence_id is None
    assert stored.terms is None


def test_a_database_built_before_the_licence_columns_is_migrated(tmp_path: Path) -> None:
    """`CREATE TABLE IF NOT EXISTS` does nothing to a table that already exists.

    So a new column in the schema never reaches a database somebody has already built, and
    the first write after an upgrade fails with `table source_meta has no column named
    licence_id`. Rebuilding is not an answer: the real one is the better part of a
    gigabyte and takes an hour to reindex.
    """
    home = DataHome(tmp_path)
    home.prepare()
    with sqlite3.connect(home.database) as connection:
        connection.execute(
            "CREATE TABLE source_meta (corpus TEXT PRIMARY KEY, label TEXT NOT NULL, "
            "language TEXT NOT NULL, versification TEXT NOT NULL, license TEXT, "
            "attribution TEXT, source_url TEXT, fetched_at TEXT, built_at TEXT, "
            "verse_count INTEGER NOT NULL DEFAULT 0)"
        )
        connection.execute(
            "INSERT INTO source_meta (corpus, label, language, versification) "
            "VALUES ('ancient', 'Built last year', 'en', 'eng')"
        )

    # Reading it works either way, because the dataclass defaults cover the gap...
    assert [item.corpus for item in read_meta(home)] == ["ancient"]

    # ...but writing to it does not, unless the columns are added.
    with open_store(home) as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(source_meta)")}
    assert {"licence_id", "licence_ids"} <= columns

    write_corpus(
        home,
        SourceMeta(
            corpus="new", label="New", language="syc", versification="org", licence_id="cc-by-4.0"
        ),
        [],
    )
    assert {item.corpus for item in read_meta(home)} == {"ancient", "new"}


def test_an_underlying_licence_governs_rather_than_the_header() -> None:
    """The one direction this must never round.

    The Patristic Text Archive publishes the SBL Greek New Testament under a CC BY 4.0
    header, and CC BY permits commercial use; the SBLGNT's own terms do not. Answering
    with the header would tell a user they may do something they may not.
    """
    from dataclasses import replace

    declared = replace(get("cc-by-4.0"), underlying=get("sblgnt"))
    assert declared.commercial, "the header itself does say so"
    assert not declared.effective.commercial, "but the edition does not"
    assert declared.restricted
    assert "governed by" in declared.describe()
    assert "non-commercial" in declared.describe()


def test_a_plain_licence_governs_itself() -> None:
    for licence in LICENCES.values():
        assert licence.effective is licence
