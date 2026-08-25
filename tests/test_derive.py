"""Unit tests for the shape-driven constraint candidate generator
(`derive_by_shapes` in src/kgrepair/derive.py).

**Every test in this file pins `generator="shapes"`.** Since P4d the default is the
two-axis search, and these cases are about the shape sweep specifically: its
per-shape templates, its class-granularity choice, its cross-domain contamination
flag and its reduced-cover pass, none of which the search reproduces the same way.
Pinning is explicit rather than by default so the file keeps testing what it was
written for. The search generator's own behaviour is covered by
`test_search_core.py`, `test_search_shaping.py` and `test_search_generator.py`.

Small hand-built DataGraphs, no network and no fixture dependency (except the
round-trip case, which also exercises a committed fixture), so these stay fast and
independent of corpus churn."""
from __future__ import annotations

import os

from kgrepair.datagraph import DataGraph
from kgrepair.derive import (SHAPES, DeriveConfig, _assert_in_fragment,
                             derive_candidates, validates_clean)
from kgrepair.ntriples import load_ntriples_file

SHAPE_CFG = DeriveConfig(generator=SHAPES)

TYPE = "wdt:P31"
SUB = "wdt:P279"

def _type(g: DataGraph, node: str, cls: str) -> None:
    g.add_edge(node, TYPE, cls)
    g.set_value(cls, cls)

def _subclass(g: DataGraph, cls: str, parent: str) -> None:
    g.add_edge(cls, SUB, parent)
    g.set_value(cls, cls)
    g.set_value(parent, parent)

def _row(result, kind=None, predicate=None):
    for r in result.report:
        if (kind is None or r["kind"] == kind) and (predicate is None or r["predicate"] == predicate):
            return r
    return None

def _emitted_cids(result):
    return [c.cid for c in result.constraints]

def test_clear_domain_candidate_is_emitted_with_specific_class():
    g = DataGraph()
    _subclass(g, "wd:City", "wd:Geo")
    for i in range(6):
        g.add_edge(f"wd:x{i}", "wd:cap", f"wd:c{i}")   # outgoing 'cap' edge (the domain body)
        _type(g, f"wd:x{i}", "wd:City")
    res = derive_candidates(g, "geography", "wikidata", SHAPE_CFG)
    row = _row(res, kind="existential_domain", predicate="wd:cap")
    assert row is not None and not row["pruned_redundant"]
    assert row["class"] == "wd:City"                    # specific, not wd:Geo
    assert "wd:Geo" in row["runner_up_classes"]
    assert row["support"] == 6 and row["body_size"] == 6

def test_below_min_support_is_not_emitted():
    g = DataGraph()
    for i in range(3):                                   # 3 < default min_support 5
        g.add_edge(f"wd:x{i}", "wd:cap", f"wd:c{i}")
        _type(g, f"wd:x{i}", "wd:City")
    res = derive_candidates(g, "geography", "wikidata", SHAPE_CFG)
    assert _row(res, predicate="wd:cap") is None
    assert res.stats.get("emitted", 0) == 0
    assert len(res.constraints) == 0

def test_pca_admits_candidate_that_standard_confidence_would_reject():
    """Regression for the PCA-gate fix: a body where standard_conf < min_pca_confidence
    but pca_conf >= min_pca_confidence and the typed-mass floor is met must be emitted.
    Under the old inert standard-confidence gate it was suppressed."""
    g = DataGraph()
    for i in range(9):                                   # 9 typed body nodes
        g.add_edge(f"wd:x{i}", "wd:cap", f"wd:c{i}")
        _type(g, f"wd:x{i}", "wd:City")
    for i in range(9, 12):                               # 3 untyped body nodes
        g.add_edge(f"wd:x{i}", "wd:cap", f"wd:c{i}")
    res = derive_candidates(g, "geography", "wikidata", SHAPE_CFG)
    row = _row(res, kind="existential_domain", predicate="wd:cap")
    assert row is not None and not row["pruned_redundant"]
    assert row["standard_conf"] == 0.75                 # 9 / 12, below min_pca 0.9
    assert row["pca_conf"] == 1.0                       # 9 / 9 typed, clears
    assert row["cid"] in _emitted_cids(res)

def test_granularity_picks_specific_class_not_parent():
    g = DataGraph()
    _subclass(g, "wd:City", "wd:Geo")                   # City is a subclass of Geo
    for i in range(8):
        g.add_edge(f"wd:x{i}", "wd:cap", f"wd:c{i}")
        _type(g, f"wd:x{i}", "wd:City")                 # every body node typed City (and so Geo)
    res = derive_candidates(g, "geography", "wikidata", SHAPE_CFG)
    row = _row(res, kind="existential_domain", predicate="wd:cap")
    assert row["class"] == "wd:City"
    assert row["runner_up_classes"] == ["wd:Geo"]

def test_contamination_flag_fires_on_shared_predicate():
    g = DataGraph()
    # P361 links 10 anatomical structures, but 3 of them are ALSO typed as a disjoint
    # geographic class (the P361 cross-domain leak the study caught by hand).
    for i in range(10):
        g.add_edge(f"wd:a{i}", "wdt:P361", f"wd:w{i}")
        _type(g, f"wd:a{i}", "wd:Anat")
    for i in range(3):
        _type(g, f"wd:a{i}", "wd:Geo")                  # disjoint from wd:Anat (incomparable)
    res = derive_candidates(g, "anatomy", "wikidata", SHAPE_CFG)
    row = _row(res, kind="existential_domain", predicate="wdt:P361")
    assert row is not None and row["class"] == "wd:Anat"
    assert row["contamination"] is True
    assert row["contamination_class"] == "wd:Geo"

def test_requires_statement_carries_low_trust():
    g = DataGraph()
    for i in range(6):
        _type(g, f"wd:t{i}", "wd:Taxon")
        g.add_edge(f"wd:t{i}", "wd:rank", f"wd:r{i}")   # every Taxon carries a rank
    res = derive_candidates(g, "taxa", "wikidata", SHAPE_CFG)
    row = _row(res, kind="requires_statement", predicate="wd:rank")
    assert row is not None
    assert row["low_trust"] is True
    assert row["pca_conf"] == row["standard_conf"]      # PCA cannot rescue a missing edge

def test_anti_monotone_pruning_drops_infrequent_conjunction():
    """Two atoms are each frequent, but their conjoined body is below min_support, so no
    typing candidate is generated for the pair (and it is not extended further)."""
    g = DataGraph()
    for i in range(6):                                   # 6 sources of hasP, all typed
        g.add_edge(f"wd:x{i}", "wd:hasP", f"wd:p{i}")
        _type(g, f"wd:x{i}", "wd:City")
    q_sources = ["wd:x0", "wd:x1", "wd:z0", "wd:z1", "wd:z2", "wd:z3"]  # overlap {x0,x1}=2
    for i, s in enumerate(q_sources):
        g.add_edge(s, "wd:hasQ", f"wd:q{i}")
        _type(g, s, "wd:City")
    res = derive_candidates(g, "geography", "wikidata", SHAPE_CFG)
    # both single atoms are frequent, so their domain candidates exist
    assert _row(res, kind="existential_domain", predicate="wd:hasP") is not None
    assert _row(res, kind="existential_domain", predicate="wd:hasQ") is not None
    # but every 2-atom conjunction has support below the floor, so nothing typing is emitted
    assert all(r["kind"] != "typing_existence" for r in res.report)

def test_reduced_cover_prunes_specific_rule_under_general_one():
    """A general antecedent (larger body) subsumes a more-specific antecedent with the
    same consequent: the specific one is pruned_redundant with subsumed_by set and is
    absent from the emitted ConstraintSet."""
    g = DataGraph()
    for i in range(8):
        g.add_edge(f"wd:x{i}", "wd:hasP", f"wd:p{i}")   # body of hasP = 8
        _type(g, f"wd:x{i}", "wd:City")
    for i in range(5):
        g.add_edge(f"wd:x{i}", "wd:hasQ", f"wd:q{i}")   # hasP & hasQ body = 5 (subset)
    res = derive_candidates(g, "geography", "wikidata", SHAPE_CFG)
    typing = _row(res, kind="typing_existence")
    dom_p = _row(res, kind="existential_domain", predicate="wd:hasP")
    assert dom_p is not None and not dom_p["pruned_redundant"]
    assert typing is not None
    assert typing["pruned_redundant"] is True
    assert typing["subsumed_by"] == dom_p["cid"]
    assert typing["cid"] not in _emitted_cids(res)
    assert dom_p["cid"] in _emitted_cids(res)

def test_clean_subset_baseline_counts_witnesses_on_dirty_target():
    """Mining on a clean reference graph, then counting each emitted candidate's
    violation witnesses on a dirtier target graph."""
    clean = DataGraph()
    for i in range(6):
        clean.add_edge(f"wd:x{i}", "wd:cap", f"wd:c{i}")
        _type(clean, f"wd:x{i}", "wd:City")
    target = DataGraph()
    for i in range(6):                                   # same clean population
        target.add_edge(f"wd:x{i}", "wd:cap", f"wd:c{i}")
        _type(target, f"wd:x{i}", "wd:City")
    for i in range(3):                                   # 3 seeded violations (untyped)
        target.add_edge(f"wd:v{i}", "wd:cap", f"wd:d{i}")
    res = derive_candidates(target, "geography", "wikidata", SHAPE_CFG, reference_graph=clean)
    row = _row(res, kind="existential_domain", predicate="wd:cap")
    assert row is not None and not row["pruned_redundant"]
    assert row["witnesses_on_target"] == 3
    # without a reference graph the field is null
    res0 = derive_candidates(clean, "geography", "wikidata", SHAPE_CFG)
    assert all(r["witnesses_on_target"] is None for r in res0.report)

def test_fragment_guard_rejects_negation_and_passes_every_emitted():
    # a hand-built expression with negation is rejected
    rejected = False
    try:
        _assert_in_fragment("probe.cid", '! val("wd:City")', "< down(wd:cap) >")
    except ValueError:
        rejected = True
    assert rejected
    # and every emitted constraint passes the guard
    g = DataGraph()
    _subclass(g, "wd:City", "wd:Geo")
    for i in range(8):
        g.add_edge(f"wd:x{i}", "wd:cap", f"wd:c{i}")
        g.add_edge(f"wd:x{i}", "wd:loc", f"wd:l{i}")
        _type(g, f"wd:x{i}", "wd:City")
    res = derive_candidates(g, "geography", "wikidata", SHAPE_CFG)
    for c in res.constraints:
        _assert_in_fragment(c.cid, c.antecedent, c.consequent)   # must not raise

def _sample_graph() -> DataGraph:
    g = DataGraph()
    _subclass(g, "wd:City", "wd:Geo")
    for i in range(8):
        g.add_edge(f"wd:x{i}", "wd:cap", f"wd:c{i}")
        g.add_edge(f"wd:x{i}", "wd:loc", f"wd:l{i}")
        _type(g, f"wd:x{i}", "wd:City")
    return g

def test_determinism_two_runs_identical():
    g1, g2 = _sample_graph(), _sample_graph()
    r1 = derive_candidates(g1, "geography", "wikidata", SHAPE_CFG)
    r2 = derive_candidates(g2, "geography", "wikidata", SHAPE_CFG)
    assert [c.to_dict() for c in r1.constraints] == [c.to_dict() for c in r2.constraints]
    assert r1.report == r2.report
    assert r1.stats == r2.stats and r1.vocab == r2.vocab
    assert r1.report  # non-empty, so the equality is meaningful

def test_round_trip_every_emitted_constraint_parses_and_validates():
    g = _sample_graph()
    res = derive_candidates(g, "geography", "wikidata", SHAPE_CFG)
    assert res.stats["emitted"] > 0
    assert validates_clean(g, res)
    # and on a committed real fixture
    fx = load_ntriples_file(os.path.join(os.path.dirname(__file__), "..",
                                         "fixtures", "real", "real_wikidata_anatomy_1000_typed.nt"))
    fres = derive_candidates(fx, "anatomy", "wikidata", SHAPE_CFG)
    assert fres.stats["emitted"] > 0
    assert validates_clean(fx, fres)
