"""
P1 gate: two-stage fetch/slice architecture.

  * determinism from a frozen cache (two runs -> identical hashes);
  * allow-list deny-check (person/org predicates never reach a slice);
  * manifest schema-valid + real/ namespace;
  * loader round-trip (emitted slice loads through ntriples.py + DataGraph + Validator
    with no parser errors).
No network: everything runs from the committed frozen mini-cache.
"""
import os

from kgrepair import constraints
from kgrepair.ntriples import load_ntriples
from kgrepair.pipeline import (RawCache, SliceParams, deny_check, load_allowlist,
                               slice_from_cache)
from kgrepair.validator import Validator


FROZEN = os.path.join(os.path.dirname(__file__), "..", "fixtures", "real", "_frozen_cache")

_PARAMS = SliceParams(source="wikidata", domain="geography", seeds=["wd:Q64"],
                      target_edges=100, allowlist_id="wikidata-geo-taxa-bio-v1")

_REQUIRED_MANIFEST_KEYS = {
    "name", "namespace", "slice_source", "source", "domain", "target_edges", "seeds",
    "frontier_rule", "allowlist_id", "allowlist_hash", "cache_generation_hash",
    "query_hashes", "V", "E", "labels", "data_values", "content_hash",
}


def _slice():
    return slice_from_cache(RawCache(FROZEN), _PARAMS)


# ---------- determinism ------------------------------------------------------

def test_slice_is_deterministic_from_frozen_cache():
    a, b = _slice(), _slice()
    assert a.manifest["content_hash"] == b.manifest["content_hash"]
    assert a.manifest["cache_generation_hash"] == b.manifest["cache_generation_hash"]
    assert a.to_ntriples() == b.to_ntriples()


def test_abbreviation_produces_curie_vocabulary():
    g = _slice().graph
    # full IRIs were abbreviated to the constraint vocabulary
    assert "wd:Q64" in g.nodes and "wd:Q515" in g.nodes
    assert "wdt:P31" in g.labels and "wdt:P279" in g.labels
    assert not any(l.startswith("http") for l in g.labels)


# ---------- allow-list deny-check (Level-0) ----------------------------------

def test_denied_person_predicate_never_reaches_the_slice():
    al = load_allowlist("wikidata")
    g = _slice().graph
    # P6 (head of government -> a person) is in the raw cache but must be dropped
    assert "wdt:P6" not in g.labels
    assert "wd:Q99999901" not in g.nodes           # the person object never enters
    assert deny_check(g, al) == []                  # no denied predicate emitted
    # only whitelisted predicates survive
    assert all(al.allows(p) for p in g.labels)


# ---------- manifest schema --------------------------------------------------

def test_manifest_schema_valid_and_real_namespaced():
    m = _slice().manifest
    assert _REQUIRED_MANIFEST_KEYS <= set(m)
    assert m["namespace"] == "real" and m["slice_source"] == "wikidata"
    assert m["allowlist_id"] == "wikidata-geo-taxa-bio-v1" and m["allowlist_hash"]
    assert m["cache_generation_hash"] and isinstance(m["query_hashes"], list)


# ---------- loader round-trip ------------------------------------------------

def test_emitted_slice_loads_and_validates_without_parser_errors():
    sl = _slice()
    g = load_ntriples(sl.to_ntriples().splitlines())     # must not raise
    assert set(g.edges()) == set(sl.graph.edges())
    # class nodes valued by the loader rule so tau_C can match
    assert g.value("wd:Q515") == "wd:Q515"
    # validating with the real geography@wikidata constraints runs cleanly
    report = Validator(g).validate(constraints.get("geography", "wikidata"))
    assert report is not None                            # violations are fine; errors are not


def test_frontier_is_size_capped():
    params = SliceParams(source="wikidata", domain="geography", seeds=["wd:Q64"],
                         target_edges=3, allowlist_id="wikidata-geo-taxa-bio-v1")
    g = slice_from_cache(RawCache(FROZEN), params).graph
    assert g.num_edges() == 3                            # hard cap respected
