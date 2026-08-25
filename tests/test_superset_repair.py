"""
D6 · T2 -- SupersetRepair (Algorithm 2) engine tests.

Each ptime_core consequent shape repaired on a small fixture; the set-at-a-time
cascade; determinism under constraint-order reversal; and the addition-only /
values-untouched invariants.
"""
import os

from kgrepair import constraints
from kgrepair.constraints.model import Constraint, ConstraintSet
from kgrepair.datagraph import DataGraph
from kgrepair.ntriples import load_ntriples_file
from kgrepair.repair import superset_repair
from kgrepair.validator import Validator


FIXTURES = os.path.join(os.path.dirname(__file__), "..", "fixtures")

WD = {"geo": "wd:Q2221906", "city": "wd:Q515", "country": "wd:Q6256",
      "taxon": "wd:Q16521", "disease": "wd:Q12136"}

def _tau(c):
    return f'< down(wdt:P31) . down(wdt:P279)* . [val("{c}")] >'


def _classes(g, *cids):
    for c in cids:
        g.set_value(c, c)              # class nodes are self-valued (loader rule)


def _core_consistent(g, cs):
    rep = Validator(g, use_closure=True).validate(cs)
    return all(v.count == 0 for v in rep.failing() if v.constraint.tier == "ptime_core")


# ---------- per-shape repair --------------------------------------------------

def test_existential_domain_adds_type_edge():
    cs = ConstraintSet("t", [Constraint(
        cid="dom", domain="d", kg="wd", kind="existential_domain",
        tier="ptime_core", provenance="c", direction="subset",
        antecedent="< down(wdt:P17) >", consequent=_tau(WD["geo"]))])
    g = DataGraph()
    _classes(g, WD["geo"])
    g.add_edge("x", "wdt:P17", "y")           # x has a country edge, is untyped
    res = superset_repair(g, cs)
    assert ("x", "wdt:P31", WD["geo"]) in res.added_edges
    assert res.attestations["consistent_after"]
    assert not res.graph is g and "x" in g.nodes    # original untouched


def test_existential_range_adds_type_to_target():
    cs = ConstraintSet("t", [Constraint(
        cid="rng", domain="d", kg="wd", kind="existential_range",
        tier="ptime_core", provenance="c", direction="subset",
        antecedent="< up(wdt:P17) >", consequent=_tau(WD["country"]))])
    g = DataGraph()
    _classes(g, WD["country"])
    g.add_edge("x", "wdt:P17", "y")           # y is a country-edge target, untyped
    res = superset_repair(g, cs)
    assert ("y", "wdt:P31", WD["country"]) in res.added_edges
    assert res.attestations["consistent_after"]


def test_typing_existence_types_the_node():
    cs = ConstraintSet("t", [Constraint(
        cid="typ", domain="d", kg="wd", kind="typing_existence",
        tier="ptime_core", provenance="c", direction="superset",
        antecedent="< down(wdt:P17) > & < down(wdt:P131) >", consequent=_tau(WD["city"]))])
    g = DataGraph()
    _classes(g, WD["city"])
    g.add_edge("x", "wdt:P17", "a")
    g.add_edge("x", "wdt:P131", "b")
    res = superset_repair(g, cs)
    assert ("x", "wdt:P31", WD["city"]) in res.added_edges
    assert res.attestations["consistent_after"]


def test_requires_statement_adds_existential_edge():
    cs = ConstraintSet("t", [Constraint(
        cid="req", domain="d", kg="wd", kind="requires_statement",
        tier="ptime_core", provenance="c", direction="superset",
        antecedent=_tau(WD["city"]), consequent="< down(wdt:P17) >")])
    g = DataGraph()
    _classes(g, WD["city"])
    g.add_edge("x", "wdt:P31", WD["city"])     # x is a City with no P17
    res = superset_repair(g, cs)
    outs = res.graph.succ("wdt:P17", "x")
    assert outs and next(iter(outs)).startswith("fresh:req:")
    assert res.attestations["consistent_after"]


def test_typing_inheritance_adds_direct_type():
    cs = ConstraintSet("t", [Constraint(
        cid="inh", domain="d", kg="wd", kind="typing_inheritance",
        tier="ptime_core", provenance="c", direction="superset",
        antecedent=_tau(WD["taxon"]),
        consequent=f'< down(wdt:P31) . [val("{WD["taxon"]}")] >')])
    g = DataGraph()
    _classes(g, WD["taxon"], "wd:Bird")
    g.add_edge("wd:Bird", "wdt:P279", WD["taxon"])
    g.add_edge("x", "wdt:P31", "wd:Bird")       # instance of a Taxon subclass
    res = superset_repair(g, cs)
    assert ("x", "wdt:P31", WD["taxon"]) in res.added_edges
    assert res.attestations["consistent_after"]


def test_disjunctive_consequent_satisfies_left():
    cs = ConstraintSet("t", [Constraint(
        cid="dis", domain="d", kg="wd", kind="requires_statement",
        tier="ptime_core", provenance="c", direction="superset",
        antecedent=_tau(WD["disease"]),
        consequent="< down(wdt:P780) > | < down(wdt:P828) >")])
    g = DataGraph()
    _classes(g, WD["disease"])
    g.add_edge("x", "wdt:P31", WD["disease"])
    res = superset_repair(g, cs)
    assert res.graph.succ("wdt:P780", "x")        # left disjunct chosen
    assert not res.graph.succ("wdt:P828", "x")
    assert res.attestations["consistent_after"]


# ---------- class node materialised when absent ------------------------------

def test_absent_class_node_is_materialised_as_new_valued_node():
    cs = ConstraintSet("t", [Constraint(
        cid="dom", domain="d", kg="wd", kind="existential_domain",
        tier="ptime_core", provenance="c", direction="subset",
        antecedent="< down(wdt:P17) >", consequent=_tau(WD["geo"]))])
    g = DataGraph()
    g.add_edge("x", "wdt:P17", "y")            # NO class node present
    res = superset_repair(g, cs)
    assert WD["geo"] in res.added_nodes
    assert res.graph.value(WD["geo"]) == WD["geo"]
    assert res.attestations["consistent_after"]
    assert res.attestations["data_values_unmodified"]


# ---------- set-at-a-time cascade --------------------------------------------

def test_cascade_reaches_fixpoint_over_multiple_rounds():
    """A requires-statement fresh target becomes a range witness in a later round."""
    g = load_ntriples_file(os.path.join(FIXTURES, "synthetic_geography_wd.nt"))
    cs = constraints.get("geography", "wikidata")
    res = superset_repair(g, cs)
    assert res.rounds >= 2
    assert any(r.round >= 2 for r in res.changelog)      # a cascade addition exists
    assert res.attestations["consistent_after"]
    assert _core_consistent(res.graph, cs)


# ---------- determinism -------------------------------------------------------

def test_determinism_under_constraint_order_reversal():
    cs = constraints.get("geography", "wikidata")
    core = [c for c in cs if c.tier == "ptime_core"]
    fwd = ConstraintSet("fwd", list(core) + [c for c in cs if c.tier == "boundary"])
    rev = ConstraintSet("rev", list(reversed(core)) + [c for c in cs if c.tier == "boundary"])
    g1 = load_ntriples_file(os.path.join(FIXTURES, "synthetic_geography_wd.nt"))
    g2 = load_ntriples_file(os.path.join(FIXTURES, "synthetic_geography_wd.nt"))
    r1 = superset_repair(g1, fwd)
    r2 = superset_repair(g2, rev)
    assert set(r1.graph.edges()) == set(r2.graph.edges())
    assert set(r1.graph.nodes) == set(r2.graph.nodes)
    assert r1.changelog_dicts() == r2.changelog_dicts()   # byte-identical change log


# ---------- invariants: never delete, never touch boundary or values ---------

def test_addition_only_and_boundary_untouched():
    g = load_ntriples_file(os.path.join(FIXTURES, "synthetic_geography_wd.nt"))
    cs = constraints.get("geography", "wikidata")
    before_edges = set(g.edges())
    original = {v: g.value(v) for v in g.nodes}
    res = superset_repair(g, cs)
    # every original edge survives (nothing deleted)
    assert before_edges <= set(res.graph.edges())
    assert all(r.op in ("add_node", "add_edge") for r in res.changelog)
    # original data values unchanged
    for v in original:
        if v in res.graph.nodes:
            assert res.graph.value(v) == original[v]
    # boundary constraints are not acted on (no P47/P36 additions)
    for r in res.changelog:
        assert r.constraint not in ("geo.wd.sym.border", "geo.wd.inv.capital",
                                    "geo.wd.func.country")


def test_consistent_graph_is_left_unchanged():
    g = DataGraph()
    _classes(g, WD["country"])
    g.add_edge("wd:Q145", "wdt:P31", WD["country"])
    cs = ConstraintSet("t", [Constraint(
        cid="rng", domain="d", kg="wd", kind="existential_range",
        tier="ptime_core", provenance="c", direction="subset",
        antecedent="< up(wdt:P17) >", consequent=_tau(WD["country"]))])
    res = superset_repair(g, cs)
    assert not res.changed
    assert res.added_edges == set()
