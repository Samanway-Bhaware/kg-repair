"""
T3: verify the existing label-indexed adjacency (no new index is built).

  * index-consistency: after a repair mutates the graph, the maintained _in/_out
    indexes equal a from-scratch rebuild from the surviving edges.
  * selectivity (structural): a backward pre-image over one label visits only that
    label's edges -- the property the micro-benchmark (bench/bench_index.py) times.
"""
import os

from kgrepair import constraints
from kgrepair.datagraph import DataGraph
from kgrepair.gxpath import Evaluator, parse_node
from kgrepair.ntriples import load_ntriples_file
from kgrepair.repair import subset_repair


FIXTURES = os.path.join(os.path.dirname(__file__), "..", "fixtures")

def _materialise_out(g):
    return {l: {s: set(dsts) for s, dsts in srcmap.items() if dsts}
            for l, srcmap in g._out.items() if any(srcmap.values())}


def _materialise_in(g):
    return {l: {d: set(srcs) for d, srcs in dstmap.items() if srcs}
            for l, dstmap in g._in.items() if any(dstmap.values())}


def _rebuild(g):
    fresh = DataGraph()
    for s, l, d in g.edges():
        fresh.add_edge(s, l, d)
    return fresh


def test_indexes_consistent_after_repair():
    cs = constraints.get("geography", "wikidata")
    g = load_ntriples_file(os.path.join(FIXTURES, "synthetic_geography_wd.nt"))
    subset_repair(g, cs, in_place=True)               # mutate via remove_node cascades
    rebuilt = _rebuild(g)
    assert _materialise_out(g) == _materialise_out(rebuilt)
    assert _materialise_in(g) == _materialise_in(rebuilt)


def test_both_directions_are_indexed():
    """Backward (_in) and forward (_out) are both maintained -> down() and up()
    pre-images are each O(matching edges); there is no forward/backward asymmetry."""
    g = DataGraph()
    g.add_edge("a", "L", "b")
    g.add_edge("c", "L", "b")
    g.add_edge("a", "M", "d")
    # backward pre-image (down) uses _in; forward (up) uses _out
    assert Evaluator(g).eval_node(parse_node("< down(L) >")) == {"a", "c"}
    assert Evaluator(g).eval_node(parse_node("< up(L) >")) == {"b"}
    assert g.pred("L", "b") == {"a", "c"} and g.succ("L", "a") == {"b"}


def test_preimage_visits_only_matching_label():
    """Selectivity: pre(down A) is independent of how many B-edges exist."""
    g_few_b = DataGraph()
    g_many_b = DataGraph()
    for g in (g_few_b, g_many_b):
        g.add_edge("s", "A", "t")
    for i in range(500):                              # extra B-edges only in one graph
        g_many_b.add_edge(f"u{i}", "B", f"v{i}")
    assert (Evaluator(g_few_b).eval_node(parse_node("< down(A) >"))
            == Evaluator(g_many_b).eval_node(parse_node("< down(A) >")) == {"s"})
    # the A index is identical regardless of the B population
    assert g_few_b._in["A"] == g_many_b._in["A"]
