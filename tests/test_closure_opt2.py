"""
T2 (OPT-2) differential suite: the subClassOf* closure must not change any result.

Closure-enabled evaluation/repair must equal traversal-based on: all fixtures; a
run where repair deletes part of the class hierarchy (forcing cache invalidation);
and seeded random graphs. The full-vs-incremental differential must still hold with
closure enabled.
"""
import os
import random

from kgrepair import constraints
from kgrepair.constraints.model import Constraint, ConstraintSet
from kgrepair.datagraph import DataGraph
from kgrepair.gxpath import Evaluator
from kgrepair.gxpath.ast import type_test
from kgrepair.ntriples import load_ntriples_file
from kgrepair.repair import subset_repair
from kgrepair.validator import Validator


FIXTURES = os.path.join(os.path.dirname(__file__), "..", "fixtures")
_TAU = '< down(wdt:P31) . down(wdt:P279)* . [val("{c}")] >'


def _mixed_constraints():
    def c(cid, ante, cons):
        return Constraint(cid=cid, domain="d", kg="wd", kind="k",
                          tier="ptime_core", provenance="given", direction="subset",
                          antecedent=ante, consequent=cons)
    return ConstraintSet("mixed", [
        c("rng_country", "< up(wdt:P17) >", _TAU.format(c="Q6256")),
        c("dom_country", "< down(wdt:P17) >", _TAU.format(c="Q2221906")),
        c("dom_partof", "< down(wdt:P361) >", _TAU.format(c="Q4936952")),
    ])


def _random_graph(seed):
    rng = random.Random(seed)
    g = DataGraph()
    classes = ["Q6256", "Q2221906", "Q4936952"]
    for cls in classes:
        g.set_value(cls, cls)
    # a small random subclass spine among the classes plus an extra layer
    extra = ["Cx", "Cy"]
    for e in extra:
        g.set_value(e, e)
    for e in extra:
        if rng.random() < 0.7:
            g.add_edge(e, "wdt:P279", rng.choice(classes))
    insts = [f"n{i}" for i in range(rng.randint(3, 8))]
    labels = ["wdt:P31", "wdt:P279", "wdt:P17", "wdt:P361"]
    targets = insts + classes + extra
    for _ in range(rng.randint(3, 16)):
        s, l, d = rng.choice(insts), rng.choice(labels), rng.choice(targets)
        if s != d:
            g.add_edge(s, l, d)
    return g


# ---------- closure == traversal for tau_C directly --------------------------

def test_closure_matches_traversal_for_type_test():
    g = load_ntriples_file(os.path.join(FIXTURES, "synthetic_geography_wd.nt"))
    tau_city = type_test("wdt:P31", "wdt:P279", "wd:Q515")
    plain = Evaluator(g, use_closure=False).eval_node(tau_city)
    cached = Evaluator(g, use_closure=True)
    first = cached.eval_node(tau_city)
    second = cached.eval_node(tau_city)          # exercises the cache hit path
    assert plain == first == second
    assert cached._star_cache, "closure cache should be populated after a star eval"


# ---------- closure == traversal through full repair on fixtures -------------

def test_closure_matches_on_fixtures():
    for domain, fixture in [("geography", "synthetic_geography_wd.nt"),
                            ("anatomy", "synthetic_anatomy_wd.nt"),
                            ("disease", "synthetic_disease_wd.nt")]:
        cs = constraints.get(domain, "wikidata")
        g1 = load_ntriples_file(os.path.join(FIXTURES, fixture))
        g2 = load_ntriples_file(os.path.join(FIXTURES, fixture))
        plain = subset_repair(g1, cs, use_closure=False)
        cached = subset_repair(g2, cs, use_closure=True)
        assert plain.deleted_nodes == cached.deleted_nodes
        assert plain.changelog_dicts() == cached.changelog_dicts()
        assert set(plain.graph.edges()) == set(cached.graph.edges())


# ---------- invalidation: repair deletes part of the hierarchy ---------------

def test_closure_invalidated_when_repair_deletes_hierarchy():
    """C sits on the subClassOf spine and is deleted mid-run; the cached closure
    from round 1 must not leak into later rounds."""
    cs = ConstraintSet("synthetic", [
        Constraint(cid="rng", domain="d", kg="wd", kind="k", tier="ptime_core",
                   provenance="given", direction="subset",
                   antecedent="< up(wdt:P17) >", consequent=_TAU.format(c="Q6256")),
        Constraint(cid="dom", domain="d", kg="wd", kind="k", tier="ptime_core",
                   provenance="given", direction="subset",
                   antecedent="< down(wdt:P17) >", consequent=_TAU.format(c="Q2221906")),
    ])
    g_plain, g_cached = DataGraph(), DataGraph()
    for g in (g_plain, g_cached):
        g.set_value("Q6256", "Q6256")
        g.set_value("Q2221906", "Q2221906")
        g.add_edge("A", "wdt:P31", "G")
        g.add_edge("G", "wdt:P279", "Q2221906")
        g.add_edge("A", "wdt:P17", "B")
        g.add_edge("B", "wdt:P31", "C")
        g.add_edge("C", "wdt:P279", "Q6256")   # spine edge deleted when C goes
        g.add_edge("C", "wdt:P17", "Z")

    plain = subset_repair(g_plain, cs, use_closure=False)
    cached = subset_repair(g_cached, cs, use_closure=True)
    assert plain.deleted_nodes == cached.deleted_nodes
    assert cached.attestations["consistent_after"] is True
    assert {"C", "Z", "B"} <= cached.deleted_nodes


# ---------- closure preserves the full-vs-incremental differential -----------

def test_closure_preserves_strategy_differential_on_random_graphs():
    cs = _mixed_constraints()
    for seed in range(300):
        g = _random_graph(seed)
        results = [subset_repair(g, cs, strategy=s, use_closure=uc)
                   for s in ("full", "incremental") for uc in (False, True)]
        base = results[0]
        for r in results[1:]:
            assert r.deleted_nodes == base.deleted_nodes
            assert set(r.graph.edges()) == set(base.graph.edges())
            assert r.changelog_dicts() == base.changelog_dicts()
            assert r.attestations["consistent_after"]
