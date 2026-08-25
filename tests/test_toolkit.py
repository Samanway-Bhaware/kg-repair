"""D2+D4 test suite."""
import os

import pytest

from kgrepair.datagraph import DataGraph
from kgrepair.gxpath import Evaluator, ParseError, parse_node, ast
from kgrepair.gxpath.ast import type_test
from kgrepair import constraints
from kgrepair.constraints.model import Constraint
from kgrepair.ntriples import load_ntriples, load_ntriples_file
from kgrepair.validator import Validator


# ---------- DataGraph -------------------------------------------------------

def test_datagraph_edges_and_values():
    g = DataGraph()
    g.add_edge("a", "p", "b")
    g.set_value("b", "B")
    assert g.succ("p", "a") == {"b"}
    assert g.pred("p", "b") == {"a"}
    assert g.nodes_with_value("B") == {"b"}
    assert g.num_edges() == 1


def test_remove_node_cascades_edges():
    g = DataGraph()
    g.add_edge("a", "p", "b")
    g.add_edge("b", "p", "c")
    g.remove_node("b")
    assert "b" not in g.nodes
    assert g.succ("p", "a") == set()
    assert g.pred("p", "c") == set()


def test_clone_is_independent():
    g = DataGraph()
    g.add_edge("a", "p", "b")
    h = g.clone()
    h.remove_node("a")
    assert g.succ("p", "a") == {"b"}


# ---------- Parser ----------------------------------------------------------

def test_parse_type_test_roundtrip():
    n = parse_node('< down(wdt:P31) . down(wdt:P279)* . [val("wd:Q515")] >')
    assert isinstance(n, ast.Has)


def test_parser_rejects_negation():
    with pytest.raises(ParseError):
        parse_node("not < down(p) >")


def test_parser_rejects_path_complement():
    with pytest.raises(ParseError):
        parse_node("< ~ down(p) >")


def test_parser_rejects_disequality():
    with pytest.raises(ParseError):
        parse_node("< down(p) . [neq] >")


def test_parse_conj_disj():
    n = parse_node("< down(a) > & ( < down(b) > | T )")
    assert isinstance(n, ast.Conj)


# ---------- Evaluator -------------------------------------------------------

def _type_graph():
    g = DataGraph()
    # x -type-> B ; B -subclass-> A  (so x is transitively of type A)
    g.add_edge("x", "type", "B")
    g.add_edge("B", "subclass", "A")
    g.set_value("A", "A")
    g.set_value("B", "B")
    return g


def test_star_transitive_type():
    g = _type_graph()
    ev = Evaluator(g)
    node = type_test("type", "subclass", "A")
    assert ev.eval_node(node) == {"x"}


def test_star_zero_hops():
    g = _type_graph()
    ev = Evaluator(g)
    # x is directly typed B (zero subclass hops)
    node = type_test("type", "subclass", "B")
    assert ev.eval_node(node) == {"x"}


def test_has_backward():
    g = DataGraph()
    g.add_edge("a", "p", "b")
    ev = Evaluator(g)
    assert ev.eval_node(parse_node("< up(p) >")) == {"b"}
    assert ev.eval_node(parse_node("< down(p) >")) == {"a"}


def test_isect_shared_endpoint():
    g = DataGraph()
    # a -p-> t and a -q-> t : a is in isect(down p, down q) pre-image of t
    g.add_edge("a", "p", "t")
    g.add_edge("a", "q", "t")
    g.add_edge("b", "p", "t")  # b lacks q -> excluded
    ev = Evaluator(g)
    node = parse_node("< isect(down(p), down(q)) >")
    assert ev.eval_node(node) == {"a"}


# ---------- Constraints (D2) ------------------------------------------------

def test_registry_availability_matches():
    reg = constraints.registry()
    assert set(reg["geography"]) == {"wikidata", "dbpedia", "yago"}
    assert set(reg["anatomy"]) == {"wikidata"}
    assert set(reg["medication"]) == {"wikidata"}


def test_all_constraints_compile():
    # every antecedent/consequent must parse within Reg-GXPath_pos
    constraints.compile_all()


def test_two_tier_split_present():
    cs = constraints.get("geography", "wikidata")
    assert len(cs.ptime_core()) >= 3
    assert len(cs.boundary()) >= 2


def test_json_export_roundtrip(tmp_path):
    paths = constraints.export_json(str(tmp_path))
    assert paths
    cs = constraints.load_json(paths[0])
    cs.compile_all()
    assert len(cs) > 0


# ---------- Validator (D4) --------------------------------------------------

def _load_geo():
    here = os.path.dirname(__file__)
    fx = os.path.join(here, "..", "fixtures", "synthetic_geography_wd.nt")
    return load_ntriples_file(fx)


def test_validator_finds_seeded_violations():
    g = _load_geo()
    cs = constraints.get("geography", "wikidata")
    report = Validator(g).validate(cs)
    assert not report.consistent
    failing = {v.constraint.cid for v in report.failing()}
    # the three seeded ptime_core violations
    assert "geo.wd.type.city" in failing        # Q999001 untyped
    assert "geo.wd.req.city_country" in failing  # Q999002 no country
    assert "geo.wd.rng.country" in failing       # Q999003 bad country target


def test_wellformed_city_not_flagged():
    g = _load_geo()
    cs = constraints.get("geography", "wikidata")
    report = Validator(g).validate(cs)
    for v in report.failing():
        assert "wd:Q23436" not in v.witnesses  # Edinburgh is clean


def test_boundary_symmetric_reported_not_repaired():
    g = _load_geo()
    cs = constraints.get("geography", "wikidata")
    report = Validator(g).validate(cs)
    sym = [v for v in report.failing() if v.constraint.cid == "geo.wd.sym.border"]
    # the border edge Q145->Q27 has no reverse -> flagged, but tier is boundary
    assert sym and sym[0].constraint.tier == "boundary"


def test_report_summary_runs():
    g = _load_geo()
    cs = constraints.get("geography", "wikidata")
    report = Validator(g).validate(cs)
    assert "INCONSISTENT" in report.summary()
    assert report.by_tier()["ptime_core"] >= 3


# ---------- Anatomy slice (D2 biomedical + D4) ------------------------------

def _load_fixture(name):
    here = os.path.dirname(__file__)
    return load_ntriples_file(os.path.join(here, "..", "fixtures", name))


def test_anatomy_domain_and_range_violations():
    g = _load_fixture("synthetic_anatomy_wd.nt")
    cs = constraints.get("anatomy", "wikidata")
    report = Validator(g).validate(cs)
    fired = {v.constraint.cid: v.witnesses for v in report.failing()}
    assert fired["ana.wd.dom.partof"] == {"wd:Q999101"}   # part-of, not anatomical
    assert fired["ana.wd.rng.partof"] == {"wd:Q999199"}   # part-of target untyped


def test_anatomy_clean_heart_not_flagged():
    g = _load_fixture("synthetic_anatomy_wd.nt")
    cs = constraints.get("anatomy", "wikidata")
    report = Validator(g).validate(cs)
    for v in report.failing():
        assert "wd:Q1072" not in v.witnesses      # heart is clean
        assert "wd:Q9649" not in v.witnesses      # circulatory system is clean


def test_anatomy_inverse_is_boundary_report_only():
    g = _load_fixture("synthetic_anatomy_wd.nt")
    cs = constraints.get("anatomy", "wikidata")
    report = Validator(g).validate(cs)
    inv = [v for v in report.failing()
           if v.constraint.cid == "ana.wd.inv.part_haspart"]
    assert inv and inv[0].constraint.tier == "boundary"
    assert inv[0].constraint.direction == "report"


# ---------- Disease slice (D2 biomedical + D4) ------------------------------

def test_disease_domain_and_requires_violations():
    g = _load_fixture("synthetic_disease_wd.nt")
    cs = constraints.get("disease", "wikidata")
    report = Validator(g).validate(cs)
    fired = {v.constraint.cid: v.witnesses for v in report.failing()}
    assert fired["dis.wd.dom.symptom"] == {"wd:Q999201"}          # symptom, not a disease
    assert fired["dis.wd.req.cause_or_symptom"] == {"wd:Q999202"} # disease, no symptom/cause


def test_disease_disjunctive_consequent_satisfied():
    # Q2840 has BOTH symptom+cause; Q999203 has symptom only -> both satisfy
    g = _load_fixture("synthetic_disease_wd.nt")
    cs = constraints.get("disease", "wikidata")
    report = Validator(g).validate(cs)
    req = [v for v in report.failing()
           if v.constraint.cid == "dis.wd.req.cause_or_symptom"][0]
    assert "wd:Q2840" not in req.witnesses
    assert "wd:Q999203" not in req.witnesses


def test_disease_safety_edge_reported_not_repaired():
    # safety treated-by has consequent T -> never a witness; counted via antecedent
    g = _load_fixture("synthetic_disease_wd.nt")
    cs = constraints.get("disease", "wikidata")
    report = Validator(g).validate(cs)
    safety = [v for v in report.violations
              if v.constraint.cid == "dis.wd.safety.treatedby"][0]
    assert safety.count == 0                                # never flagged
    assert safety.constraint.params.get("reporting") == "aggregate_only"
    ev = Evaluator(g)
    assert len(ev.eval_node(safety.constraint.phi)) == 2    # Q2840, Q999203


def test_medication_constraints_compile_and_split():
    cs = constraints.get("medication", "wikidata")
    cs.compile_all()
    assert len(cs.ptime_core()) == 3
    assert len(cs.boundary()) == 1
