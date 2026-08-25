"""
P8a/F1: the YAGO seeds are pinned across cache generations.

Wikidata and DBpedia seeds are a written-down constant (`extract.SEEDS`), so they
cannot move when a cell is refetched. YAGO seeds are not: entity IRIs in the dump are
opaque, so `build_real_slice._yago_seeds` derives the taxa seeds from the
`schema:parentTaxon` subjects present in the cache. That derivation is a function of
the cache, so a re-extract that moved the backbone would move the seeds, and a slice
built from the new generation would differ for two reasons at once.

`fixtures/real/pinned_seeds.json` records what generation A produced. These tests
assert the pin is read back verbatim, that it matches generation A byte for byte, and
that pinning changed nothing for a cell that has no pin.

No network. The generation A manifests are committed.
"""
from __future__ import annotations

import json
import os

import build_real_slice as brs

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
REAL = os.path.join(ROOT, "fixtures", "real")

#: Every committed generation A rung whose seeds the pin has to reproduce.
YAGO_RUNGS = ["real_yago_taxa_1000", "real_yago_taxa_10000"]


def _manifest(name: str) -> dict:
    with open(os.path.join(REAL, name + ".manifest.json"), encoding="utf-8") as fh:
        return json.load(fh)


def _pin_file() -> dict:
    with open(os.path.join(REAL, "pinned_seeds.json"), encoding="utf-8") as fh:
        return json.load(fh)


def test_the_pin_file_exists_and_names_the_generation_it_came_from():
    pin = _pin_file()
    assert pin["pinned_from"]["cache_generation_hash"]
    assert pin["pinned_from"]["manifests"]
    assert pin["note"], "a pin nobody can explain later is not a pin"


def test_the_pinned_yago_seeds_are_byte_identical_to_generation_a():
    """F1's gate. Equality against every generation A rung, not just one, so a pin
    taken from a rung that had drifted would fail here."""
    pinned = brs.pinned_seeds("yago", "taxa")
    assert pinned is not None, "the YAGO taxa cell has no pin"
    for name in YAGO_RUNGS:
        assert pinned == _manifest(name)["seeds"], f"{name}: pinned seeds differ"
    assert len(pinned) == 6551


def test_the_pin_is_what_the_slice_builder_actually_uses():
    """Reading the file is not enough: the builder has to prefer it over the
    derivation. Passing a cache that would derive nothing shows which one won."""

    class _EmptyCache:
        def iter_raw_triples(self, _source):
            return iter(())

    seeds = brs._yago_seeds(_EmptyCache(), None, "taxa")
    assert seeds == _manifest(YAGO_RUNGS[0])["seeds"]


def test_an_unpinned_cell_still_derives_from_the_cache():
    """The pin must not change behaviour for a cell it does not cover, or it stops
    being a pin and becomes a rewrite of the seeding rule."""
    assert brs.pinned_seeds("yago", "geography") is None
    assert brs.pinned_seeds("wikidata", "taxa") is None

    class _Cache:
        def iter_raw_triples(self, _source):
            yield ("http://yago-knowledge.org/resource/Berlin",
                   "http://schema.org/location",
                   "http://yago-knowledge.org/resource/Germany", False)

    from kgrepair.pipeline import load_allowlist
    derived = brs._yago_seeds(_Cache(), load_allowlist("yago"), "geography")
    assert derived == ["yago:Berlin"]


def test_the_pinned_seeds_are_sorted_and_carry_no_duplicate():
    """`SliceParams` sorts seeds into the manifest, and the BFS starts from
    `sorted(seeds)`, so a pin that was unsorted or repeated would still slice the
    same. Asserted anyway: it keeps the file diffable."""
    pinned = brs.pinned_seeds("yago", "taxa")
    assert pinned == sorted(pinned)
    assert len(pinned) == len(set(pinned))
