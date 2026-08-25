"""E0 (CM sprint): prevalence miner, fragment filter, tier classifier -- unit
tests over a small in-memory graph, no network, no fixture dependency, so these
stay fast and independent of the real corpus's future churn."""
from __future__ import annotations


from kgrepair.datagraph import DataGraph  # noqa: E402

from experimental.mining.fragment_filter import check_fragment, filter_candidates  # noqa: E402
from experimental.mining.miner import Candidate, build_index, mine_prevalence  # noqa: E402
from experimental.mining.tier_classifier import classify  # noqa: E402


def _toy_graph() -> DataGraph:
    """A single class wd:Geo, directly P31-typed (no subclass indirection, so
    there is exactly one class node to mine over): 10 entities carry a P17
    (country) edge, 9 of them are typed Geo, the 10th has a P17 edge but no P31
    edge at all -- existential_domain(P17, Geo) should measure exactly
    9/10 = 90% prevalence, support=10 (the P17 population)."""
    g = DataGraph()
    g.set_value("wd:Geo", "wd:Geo")
    for i in range(9):
        g.add_edge(f"wd:c{i}", "wdt:P31", "wd:Geo")
        g.add_edge(f"wd:c{i}", "wdt:P17", f"wd:country{i % 3}")
    g.add_edge("wd:c9", "wdt:P17", "wd:country0")   # P17 edge, but untyped
    return g


def test_existential_domain_recovered_at_90_not_99():
    g = _toy_graph()
    idx = build_index(g, "wikidata", min_support=9)
    by_t = mine_prevalence(idx, domain="geography", thresholds=[0.99, 0.90], min_support=9)
    dom_99 = [c for c in by_t[0.99] if c.kind == "existential_domain"]
    dom_90 = [c for c in by_t[0.90] if c.kind == "existential_domain"]
    assert dom_99 == []          # 9/10 = 90% < 99%
    assert len(dom_90) == 1
    assert dom_90[0].support == 10
    assert dom_90[0].prevalence == 0.9


def test_mining_is_deterministic_across_runs():
    g = _toy_graph()
    idx1 = build_index(g, "wikidata", min_support=9)
    idx2 = build_index(g, "wikidata", min_support=9)
    r1 = mine_prevalence(idx1, domain="geography", thresholds=[0.90], min_support=9)
    r2 = mine_prevalence(idx2, domain="geography", thresholds=[0.90], min_support=9)
    hints1 = [c.cid_hint for c in r1[0.90]]
    hints2 = [c.cid_hint for c in r2[0.90]]
    assert hints1 == hints2 and hints1 != []


def test_threshold_sweep_is_nested():
    """Lower thresholds' survivor sets are supersets of higher thresholds' --
    mechanical by construction, worth guarding directly."""
    g = _toy_graph()
    idx = build_index(g, "wikidata", min_support=5)
    by_t = mine_prevalence(idx, domain="geography", thresholds=[0.99, 0.95, 0.90], min_support=5)
    hints_99 = {c.cid_hint for c in by_t[0.99]}
    hints_95 = {c.cid_hint for c in by_t[0.95]}
    hints_90 = {c.cid_hint for c in by_t[0.90]}
    assert hints_99 <= hints_95 <= hints_90


def test_fragment_filter_accepts_wellformed_candidate():
    result = check_fragment("< down(wdt:P17) >",
                            '< down(wdt:P31) . down(wdt:P279)* . [val("wd:Geo")] >')
    assert result.passed


def test_fragment_filter_rejects_negation():
    result = check_fragment("< down(wdt:P17) >", '! val("wd:Geo")')
    assert not result.passed
    assert "fragment" in result.reason


def test_filter_candidates_splits_survivors_and_rejects():
    good = Candidate(kind="existential_domain", domain="geography", kg="wikidata",
                     antecedent="< down(wdt:P17) >", consequent='val("wd:Geo")',
                     support=10, prevalence=1.0, threshold=0.9, note="", cid_hint="good")
    bad = Candidate(kind="existential_domain", domain="geography", kg="wikidata",
                    antecedent="! < down(wdt:P17) >", consequent='val("wd:Geo")',
                    support=10, prevalence=1.0, threshold=0.9, note="", cid_hint="bad")
    survivors, rejected = filter_candidates([good, bad])
    assert [c.cid_hint for c in survivors] == ["good"]
    assert len(rejected) == 1 and rejected[0][0].cid_hint == "bad"


def test_tier_classifier_routes_ptime_core_kinds():
    for kind in ("existential_domain", "existential_range", "typing_existence",
                "requires_statement"):
        verdict = classify(kind)
        assert verdict.tier == "ptime_core"


def test_tier_classifier_routes_boundary_kinds_regardless_of_confidence():
    for kind in ("symmetric", "inverse", "functional"):
        verdict = classify(kind)
        assert verdict.tier == "boundary"
        assert verdict.direction == "report"


def test_tier_classifier_defaults_unknown_kind_to_boundary():
    verdict = classify("some_future_shape_not_yet_handled")
    assert verdict.tier == "boundary"
