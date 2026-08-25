"""
P8a/F0: slicing down from one cache generation nests.

The size ladder is built by fetching a cell once at its ceiling and slicing every
smaller rung out of that single generation. That only gives a comparable ladder if
each rung's edge set is contained in the next: otherwise a "smaller slice of the
same graph" is a different graph, and a metric that moves between rungs cannot be
attributed to size.

Three things are asserted here, and they are separate claims:

  * the ordering the cap cuts at is a total order over candidate edges, so the cut
    point is decided by the order and not by dictionary insertion accident;
  * slicing one cache at increasing targets produces a containment chain;
  * the committed generation A ladders, which were built this way months before this
    test existed, actually have the property.

No network. The first two run from a hand-built cache, the third from committed
slices.
"""
from __future__ import annotations

import json
import os
from typing import List

from kgrepair.ntriples import load_ntriples_file
from kgrepair.pipeline import RawCache, SliceParams, slice_from_cache
from kgrepair.pipeline.slicing import ORDERING_KEY, _adjacency
from kgrepair.pipeline.allowlist import load_allowlist

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
REAL = os.path.join(ROOT, "fixtures", "real")
FROZEN = os.path.join(REAL, "_frozen_cache")

ALLOWLIST = "wikidata-geo-taxa-bio-v1"

#: (base name, rungs) for every committed generation A ladder with more than one rung.
COMMITTED_LADDERS = [
    ("real_wikidata_geography", [1000, 10000]),
    ("real_wikidata_taxa", [1000, 10000]),
    ("real_yago_taxa", [1000, 10000]),
]


def _params(target: int) -> SliceParams:
    return SliceParams(source="wikidata", domain="geography", seeds=["wd:Q64"],
                       target_edges=target, allowlist_id=ALLOWLIST)


def _edges_at(target: int):
    return set(slice_from_cache(RawCache(FROZEN), _params(target)).graph.edges())


def _manifest(name: str) -> dict:
    with open(os.path.join(REAL, name + ".manifest.json"), encoding="utf-8") as fh:
        return json.load(fh)


 
# the ordering key
 
def test_the_ordering_key_is_a_total_order_over_candidate_edges():
    """No two candidate edges can compare equal.

    Nodes are visited once each and processed in sorted order, so two edges from
    different nodes are separated by the node. Two edges from the same node are
    separated by the (predicate, object) pair, and `_adjacency` sorts and
    deduplicates those, so a node cannot offer the same pair twice. If either half
    failed, the cap boundary would fall wherever the dictionary happened to iterate.
    """
    adj = _adjacency(RawCache(FROZEN), load_allowlist("wikidata"))
    assert adj, "the frozen cache yielded no adjacency, so this proves nothing"
    for node, pairs in adj.items():
        assert pairs == sorted(pairs), f"{node}: pairs are not in sorted order"
        assert len(pairs) == len(set(pairs)), f"{node}: a pair appears twice"


def test_the_ordering_key_is_recorded_in_the_manifest():
    """A later reader has to be able to tell what the nesting depended on."""
    manifest = slice_from_cache(RawCache(FROZEN), _params(50)).manifest
    assert manifest["ordering_key"] == ORDERING_KEY
    assert "bfs_round" in ORDERING_KEY and "predicate" in ORDERING_KEY


 
# the property, on a cache small enough to reason about
 
def test_slicing_one_cache_at_increasing_targets_nests():
    targets = [5, 20, 50, 100, 400]
    sets = [_edges_at(t) for t in targets]
    for (small, small_t), (large, large_t) in zip(zip(sets, targets),
                                                  zip(sets[1:], targets[1:])):
        assert small <= large, (
            f"target {small_t} is not contained in target {large_t}: "
            f"{len(small - large)} edge(s) present at the smaller rung only")
    assert len(sets[0]) < len(sets[-1]), "the rungs did not actually differ in size"


def test_a_rung_below_the_cap_is_the_whole_cache_and_still_nests():
    """Past exhaustion the walk stops on the frontier rather than the cap, so every
    larger target returns the same edge set. Containment is still what holds."""
    big, bigger = _edges_at(100000), _edges_at(200000)
    assert big == bigger and big <= bigger


def test_nesting_does_not_depend_on_the_target_reaching_a_round_boundary():
    """The cap usually falls in the middle of a node's edge list, which is the case
    the property has to survive. Targets one edge apart are checked so that at least
    one cut lands mid-node.

    The frozen mini-cache holds seven allow-listed edges, so past target seven the
    walk stops on the exhausted frontier and every rung returns the same set. Size is
    asserted only up to that point; containment is asserted throughout, which is the
    property the ladder rests on.
    """
    exhausted_at = len(_edges_at(10 ** 6))
    assert 1 < exhausted_at < 40, "the mini-cache is the wrong size for this test"

    previous = None
    for target in range(1, 40):
        current = _edges_at(target)
        assert len(current) == min(target, exhausted_at)
        if previous is not None:
            assert previous <= current
        previous = current


 
# the committed ladders
 
def _assert_ladder_nests(base: str, rungs: List[int]) -> None:
    previous = None
    generations = set()
    for target in rungs:
        name = f"{base}_{target}"
        edges = set(load_ntriples_file(os.path.join(REAL, name + ".nt")).edges())
        generations.add(_manifest(name)["cache_generation_hash"])
        if previous is not None:
            missing = previous[1] - edges
            assert not missing, (
                f"{base}: rung {previous[0]} is not contained in rung {target}; "
                f"{len(missing)} edge(s) missing, first {sorted(missing)[:2]}")
        previous = (target, edges)
    assert len(generations) == 1, (
        f"{base}: rungs come from {len(generations)} cache generations, so nesting "
        f"was never on offer for this ladder")


def test_every_committed_ladder_nests():
    for base, rungs in COMMITTED_LADDERS:
        _assert_ladder_nests(base, rungs)


def test_the_committed_ladders_are_actually_ladders():
    """Guards the test above against passing because a ladder quietly lost a rung."""
    for base, rungs in COMMITTED_LADDERS:
        assert len(rungs) >= 2
        for target in rungs:
            assert os.path.exists(os.path.join(REAL, f"{base}_{target}.nt"))
