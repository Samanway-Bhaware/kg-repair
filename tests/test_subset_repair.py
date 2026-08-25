"""D5 SubsetRepair (Algorithm 1) test suite -- additive to test_toolkit.py."""
import json
import os

from kgrepair import constraints
from kgrepair.constraints.model import Constraint, ConstraintSet
from kgrepair.datagraph import DataGraph
from kgrepair.ntriples import load_ntriples_file
from kgrepair.repair import subset_repair, eligible_constraints
from kgrepair.validator import Validator


FIXTURES = os.path.join(os.path.dirname(__file__), "..", "fixtures")

def _geo():
    g = load_ntriples_file(os.path.join(FIXTURES, "synthetic_geography_wd.nt"))
    return g, constraints.get("geography", "wikidata")


# ---------- eligibility -------------------------------------------------------

def test_eligible_is_ptime_core_subset_only():
    _, cs = _geo()
    elig = eligible_constraints(cs)
    assert elig, "geography must have at least one subset-direction ptime_core rule"
    for c in elig:
        assert c.tier == "ptime_core" and c.direction == "subset"
    # superset-direction and boundary rules are excluded
    ids = {c.cid for c in elig}
    assert "geo.wd.req.city_country" not in ids   # superset-direction
    assert "geo.wd.sym.border" not in ids         # boundary


# ---------- core behaviour ----------------------------------------------------

def test_subset_repair_deletes_the_seeded_witnesses():
    g, cs = _geo()
    res = subset_repair(g, cs)
    # dom.country witness (has P17, untyped) and rng.country witness (bad P17 target)
    assert "wd:Q999001" in res.deleted_nodes
    assert "wd:Q999099" in res.deleted_nodes
    assert res.attestations["consistent_after"] is True


def test_input_graph_not_mutated_by_default():
    g, cs = _geo()
    before_nodes = set(g.nodes)
    before_edges = set(g.edges())
    subset_repair(g, cs)  # in_place defaults to False
    assert set(g.nodes) == before_nodes
    assert set(g.edges()) == before_edges
    assert "wd:Q999001" in g.nodes  # still present in the original


def test_in_place_mutates_the_given_graph():
    g, cs = _geo()
    res = subset_repair(g, cs, in_place=True)
    assert res.graph is g
    assert "wd:Q999001" not in g.nodes


# ---------- cascade (D5.md gate) ---------------------------------------------

def test_deletion_cascades_incident_edges_into_changelog():
    g, cs = _geo()
    res = subset_repair(g, cs)
    edge_recs = {(r.src, r.label, r.dst) for r in res.changelog if r.op == "remove_edge"}
    # Q999001's two outgoing edges must be logged as cascaded removals
    assert ("wd:Q999001", "wdt:P17", "wd:Q145") in edge_recs
    assert ("wd:Q999001", "wdt:P131", "wd:Q22") in edge_recs
    # the dangling P17 edge into the deleted bad target is logged too
    assert ("wd:Q999003", "wdt:P17", "wd:Q999099") in edge_recs
    # every deleted node has a matching remove_node record
    node_recs = {r.node for r in res.changelog if r.op == "remove_node"}
    assert node_recs == res.deleted_nodes


# ---------- values untouched (D5.md gate) ------------------------------------

def test_data_values_never_modified():
    g, cs = _geo()
    original = {v: g.value(v) for v in g.nodes}
    res = subset_repair(g, cs)
    for v in res.graph.nodes:
        assert res.graph.value(v) == original[v]
    assert res.attestations["data_values_unmodified"] is True
    # no ChangeRecord is anything other than a removal
    assert res.attestations["subset_only_deleted"] is True
    assert all(r.op in ("remove_node", "remove_edge") for r in res.changelog)


# ---------- uniqueness / order-independence (Thm 14) -------------------------

def test_repair_is_order_independent():
    g1, cs = _geo()
    elig = eligible_constraints(cs)
    forward = ConstraintSet("fwd", list(elig))
    reverse = ConstraintSet("rev", list(reversed(elig)))

    g2 = load_ntriples_file(os.path.join(FIXTURES, "synthetic_geography_wd.nt"))
    r1 = subset_repair(g1, forward)
    r2 = subset_repair(g2, reverse)

    assert r1.deleted_nodes == r2.deleted_nodes
    assert set(r1.graph.nodes) == set(r2.graph.nodes)
    assert set(r1.graph.edges()) == set(r2.graph.edges())


# ---------- fixpoint: a deletion creates a *new* witness ---------------------

def test_fixpoint_catches_witness_created_by_a_deletion():
    """
    Deleting the class node C strips B out of tau_Country while B stays a P17
    target, so B only becomes an rng witness in a *later* round. A single pass
    would miss it; the loop must not.
    """
    tau_country = '< down(wdt:P31) . down(wdt:P279)* . [val("Q6256")] >'
    tau_geo = '< down(wdt:P31) . down(wdt:P279)* . [val("Q2221906")] >'
    cs = ConstraintSet("synthetic", [
        Constraint(cid="rng", domain="geo", kg="wd", kind="existential_range",
                   tier="ptime_core", provenance="given", direction="subset",
                   antecedent="< up(wdt:P17) >", consequent=tau_country),
        Constraint(cid="dom", domain="geo", kg="wd", kind="existential_domain",
                   tier="ptime_core", provenance="given", direction="subset",
                   antecedent="< down(wdt:P17) >", consequent=tau_geo),
    ])

    g = DataGraph()
    g.set_value("Q6256", "Q6256")            # country class
    g.set_value("Q2221906", "Q2221906")      # geo class
    # A is a legitimate geo entity that points a country edge at B
    g.add_edge("A", "wdt:P31", "G")
    g.add_edge("G", "wdt:P279", "Q2221906")
    g.add_edge("A", "wdt:P17", "B")
    # B is a country only because of C (which itself is a dom witness -> gets deleted)
    g.add_edge("B", "wdt:P31", "C")
    g.add_edge("C", "wdt:P279", "Q6256")
    g.add_edge("C", "wdt:P17", "Z")          # C has a country edge but isn't a geo entity

    res = subset_repair(g, cs)
    assert res.attestations["consistent_after"] is True
    assert "wd:Q6256" not in res.deleted_nodes and "Q6256" in res.graph.nodes  # class survives
    # C (dom) and Z (rng) fall in round 1; B only becomes a witness after C is gone
    assert {"C", "Z", "B"} <= res.deleted_nodes
    assert res.rounds >= 2
    # A survives: it is a valid geo entity throughout
    assert "A" in res.graph.nodes


# ---------- boundary / superset rules left alone -----------------------------

def test_boundary_and_superset_rules_are_untouched():
    g, cs = _geo()
    res = subset_repair(g, cs)
    gp = res.graph
    # Q999002 (typed City, no country) is a *superset*-direction violation: not D5's job
    assert "wd:Q999002" in gp.nodes
    # Q145 is the reported-only symmetric-border witness: still present
    assert "wd:Q145" in gp.nodes
    # validating the full set on the repaired graph, the superset + boundary rules
    # still fire, while the subset-direction rules are now clean
    report = Validator(gp).validate(cs)
    failing = {v.constraint.cid: v.count for v in report.failing()}
    assert failing.get("geo.wd.req.city_country", 0) > 0     # superset still violated
    assert failing.get("geo.wd.sym.border", 0) > 0           # boundary still reported
    for c in eligible_constraints(cs):
        assert failing.get(c.cid, 0) == 0                    # subset rules resolved


# ---------- idempotence & no-op --------------------------------------------

def test_repair_is_idempotent():
    g, cs = _geo()
    once = subset_repair(g, cs)
    twice = subset_repair(once.graph, cs)
    assert twice.changelog == []
    assert twice.deleted_nodes == set()
    assert twice.attestations["consistent_after"] is True


def test_consistent_graph_is_left_unchanged():
    # a lone well-formed country: no subset witnesses
    g = DataGraph()
    g.set_value("wd:Q6256", "wd:Q6256")
    g.add_edge("wd:Q145", "wdt:P31", "wd:Q6256")
    _, cs = _geo()
    res = subset_repair(g, cs)
    assert not res.changed
    assert res.deleted_nodes == set()


# ---------- changelog serialisation -----------------------------------------

def test_changelog_serialises_to_json():
    g, cs = _geo()
    res = subset_repair(g, cs)
    payload = json.loads(res.changelog_json())
    assert isinstance(payload, list) and len(payload) == len(res.changelog)
    for rec in payload:
        assert rec["op"] in ("remove_node", "remove_edge")
        assert "round" in rec and "constraint" in rec
