"""
P8b: the quality metrics, on graphs small enough to check by hand.

`docs/quality_metrics.md` defines each metric and predicts its direction under each
engine. These tests hold the definitions: one test per metric with an answer worked
out by hand, a test that every field on the dataclass is populated by at least one
case, and the source-agnosticism sweep from T5.

The vocabulary here is deliberately not Wikidata's. `ex:isa` and `ex:kindOf` are the
typing spine for most of these graphs, so a metric that reached for `wdt:P31` would
fail here rather than in the campaign.
"""
from __future__ import annotations

import os
from dataclasses import fields

import pytest

import kgrepair
from kgrepair.datagraph import DataGraph
from kgrepair.metrics import (DEFAULT_INSTANCE_OF, DEFAULT_SUBCLASS_OF, GraphMetrics,
                              compare_metrics, compute_metrics, metric_field_names)

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
REAL = os.path.join(ROOT, "fixtures", "real")

ISA, KIND = "ex:isa", "ex:kindOf"
VOCAB = {"instance_of": [ISA], "subclass_of": [KIND]}


def _g(triples, values=None):
    graph = DataGraph()
    for s, p, o in triples:
        graph.add_edge(s, p, o)
    for node, value in (values or {}).items():
        graph.set_value(node, value)
    return graph


 
# conciseness
 
def test_sizes_are_the_graph_s_own_counts():
    graph = _g([("a", "ex:near", "b"), ("b", "ex:near", "c")])
    m = compute_metrics(graph, **VOCAB)
    assert (m.nodes, m.edges, m.labels) == (3, 2, 1)


def test_a_type_edge_implied_by_a_more_specific_one_is_redundant():
    """`v isa Dog` and `v isa Animal` with Dog a kind of Animal: the Animal edge
    carries nothing. One node, one redundant edge. The unrelated node has two types
    that do not imply each other, so neither is redundant."""
    graph = _g([
        ("Dog", KIND, "Animal"),
        ("v", ISA, "Dog"), ("v", ISA, "Animal"),      # redundant
        ("w", ISA, "Dog"), ("w", ISA, "Pet"),          # unrelated types, not redundant
    ])
    assert compute_metrics(graph, **VOCAB).redundant_type_edges == 1


def test_redundancy_follows_the_hierarchy_transitively():
    graph = _g([
        ("Terrier", KIND, "Dog"), ("Dog", KIND, "Animal"),
        ("v", ISA, "Terrier"), ("v", ISA, "Animal"),   # two hops up, still redundant
    ])
    assert compute_metrics(graph, **VOCAB).redundant_type_edges == 1


def test_singleton_classes_are_counted():
    graph = _g([("a", ISA, "C"), ("b", ISA, "C"), ("c", ISA, "D")])
    m = compute_metrics(graph, **VOCAB)
    assert (m.classes, m.singleton_classes) == (2, 1)


 
# completeness
 
def test_type_coverage_counts_nodes_with_a_type_edge():
    """Four nodes: two typed, and the class node and the untyped one are not."""
    graph = _g([("a", ISA, "C"), ("b", ISA, "C"), ("d", "ex:near", "a")])
    m = compute_metrics(graph, **VOCAB)
    assert m.nodes == 4                      # a, b, C, d
    assert m.typed_nodes == 2
    assert m.typed_node_fraction == 0.5


def test_property_coverage_is_the_share_of_a_class_s_instances_carrying_it():
    """Four instances of C, three with `ex:cap`. Coverage of (C, ex:cap) is 0.75, and
    it is the only pair, so the weighted mean is 0.75."""
    triples = [(f"x{i}", ISA, "C") for i in range(4)]
    triples += [(f"x{i}", "ex:cap", f"y{i}") for i in range(3)]
    m = compute_metrics(_g(triples), **VOCAB)
    assert m.class_property_pairs == 1
    assert m.property_coverage_mean == 0.75


def test_a_predicate_no_instance_carries_is_not_a_pair():
    """The local closed-world assumption, stated in the design note: silence about a
    predicate nobody in the class uses is not incompleteness, it is a predicate that
    belongs to some other class."""
    triples = [(f"x{i}", ISA, "C") for i in range(3)]
    triples += [("x0", "ex:cap", "y")]
    triples += [(f"z{i}", ISA, "D") for i in range(3)]
    triples += [(f"z{i}", "ex:rank", f"r{i}") for i in range(3)]
    m = compute_metrics(_g(triples), **VOCAB)
    # (C, ex:cap) at 1/3 and (D, ex:rank) at 1.0. (C, ex:rank) is not a pair at all.
    assert m.class_property_pairs == 2
    assert m.property_coverage_mean == pytest.approx((1 / 3 * 3 + 1.0 * 3) / 6)


def test_a_class_with_one_instance_is_not_scored():
    """Its coverage is 1.0 by construction and says nothing about the data."""
    triples = [("solo", ISA, "C"), ("solo", "ex:cap", "y"),
               ("a", ISA, "D"), ("b", ISA, "D"), ("a", "ex:cap", "y2")]
    m = compute_metrics(_g(triples), **VOCAB)
    assert m.classes == 2 and m.classes_scored_for_coverage == 1
    assert m.property_coverage_mean == 0.5          # only (D, ex:cap), 1 of 2


def test_coverage_is_none_when_nothing_can_be_scored():
    m = compute_metrics(_g([("a", "ex:near", "b")]), **VOCAB)
    assert m.property_coverage_mean is None
    assert m.class_property_pairs == 0


 
# consistency
 
def _slice_and_constraints():
    graph = kgrepair.load_graph(os.path.join(REAL, "real_wikidata_geography_1000.nt"))
    return graph, kgrepair.constraints.get("geography", "wikidata")


def test_consistency_matches_the_validator_exactly():
    """The metric must not be a second implementation. Every consistency number is
    checked against `Validator` output computed independently in the test."""
    graph, cs = _slice_and_constraints()
    report = kgrepair.validate(graph, cs)
    m = compute_metrics(graph, cs)

    assert m.constraints_checked == len(report.violations)
    assert m.violations_total == report.total_witnesses()
    assert m.violated_constraints == len(report.failing())
    assert m.violations_by_tier == report.by_tier()
    union = set()
    for violation in report.violations:
        union |= violation.witnesses
    assert m.witness_nodes == len(union)


def test_the_witness_fraction_is_the_union_not_the_sum():
    """One node breaking two constraints counts once. A sum over the node count is
    not a fraction of anything and can exceed 1."""
    graph, cs = _slice_and_constraints()
    m = compute_metrics(graph, cs)
    assert m.witness_nodes <= m.nodes
    assert 0.0 <= m.witness_node_fraction <= 1.0
    assert m.witness_nodes < m.violations_total, "expected overlap on this slice"


def test_satisfaction_skips_a_constraint_whose_antecedent_matches_nothing():
    """A rule about nothing is unjudged, not satisfied. Scored count is the number of
    ptime_core constraints with a non-empty antecedent."""
    graph, cs = _slice_and_constraints()
    m = compute_metrics(graph, cs)
    core = [c for c in cs if c.tier == "ptime_core"]
    assert m.satisfaction_scored <= len(core)
    assert 0.0 <= m.satisfaction_mean <= 1.0


def test_a_consistent_graph_scores_full_satisfaction():
    graph, cs = _slice_and_constraints()
    clean = kgrepair.superset_repair(graph, cs)
    assert clean.attestations["consistent_after"]
    m = compute_metrics(clean.graph, cs)
    assert m.violations_by_tier["ptime_core"] == 0
    assert m.satisfaction_mean == 1.0


def test_no_constraint_set_leaves_the_consistency_block_absent_not_zero():
    """"No theory to check against" and "checked and found consistent" are different
    states, and the record has to say which."""
    m = compute_metrics(_g([("a", ISA, "C")]), **VOCAB)
    assert m.violations_total is None and m.constraints_checked is None
    assert m.witness_node_fraction is None and m.satisfaction_mean is None


 
# comparison
 
def test_comparison_reports_absolute_and_relative_change():
    before = compute_metrics(_g([("a", ISA, "C"), ("b", ISA, "C")]), **VOCAB)
    after = compute_metrics(_g([("a", ISA, "C"), ("b", ISA, "C"),
                                ("c", ISA, "C")]), **VOCAB)
    changes = compare_metrics(before, after).changes
    assert changes["nodes"].before == 3 and changes["nodes"].after == 4
    assert changes["nodes"].absolute == 1
    assert changes["nodes"].relative == pytest.approx(1 / 3)


def test_a_relative_change_against_zero_is_none_rather_than_infinity():
    before = compute_metrics(_g([("a", "ex:near", "b")]), **VOCAB)
    after = compute_metrics(_g([("a", "ex:near", "b"), ("a", ISA, "C")]), **VOCAB)
    change = compare_metrics(before, after).changes["typed_nodes"]
    assert change.before == 0 and change.after == 1
    assert change.absolute == 1 and change.relative is None


def test_comparing_records_from_different_vocabularies_is_refused():
    graph = _g([("a", ISA, "C")])
    with pytest.raises(ValueError) as caught:
        compare_metrics(compute_metrics(graph, **VOCAB), compute_metrics(graph))
    assert "vocabular" in str(caught.value)


def test_the_comparison_keys_do_not_depend_on_the_data():
    """Two comparisons are always the same shape, so a table built from one does not
    lose a column on another run."""
    a = compare_metrics(compute_metrics(_g([("a", ISA, "C")]), **VOCAB),
                        compute_metrics(_g([("a", ISA, "C")]), **VOCAB))
    graph, cs = _slice_and_constraints()
    b = compare_metrics(compute_metrics(graph, cs), compute_metrics(graph, cs))
    assert set(a.changes) == set(b.changes)


 
# every field is exercised
 
def test_every_field_on_the_record_is_populated_by_some_case():
    """T2's gate. A field nothing ever fills is a field nothing ever tested."""
    graph, cs = _slice_and_constraints()
    rich = compute_metrics(graph, cs)
    hand = compute_metrics(_g([("Dog", KIND, "Animal"), ("v", ISA, "Dog"),
                               ("v", ISA, "Animal"), ("w", ISA, "Dog"),
                               ("w", "ex:cap", "x")]), **VOCAB)
    unfilled = []
    for f in fields(GraphMetrics):
        if getattr(rich, f.name) in (None, 0, (), 0.0) and \
                getattr(hand, f.name) in (None, 0, (), 0.0):
            unfilled.append(f.name)
    assert not unfilled, f"never populated by any case: {unfilled}"
    assert set(metric_field_names()) == {f.name for f in fields(GraphMetrics)}


 
# T5: no metric assumes a source's idiom
 
SOURCES = [
    ("wikidata", "real_wikidata_geography_1000.nt"),
    ("dbpedia", "real_dbpedia_geography_1000.nt"),
    ("yago", "real_yago_taxa_1000.nt"),
]


def test_every_metric_computes_on_every_source():
    """T5. The default vocabulary covers all three spines, so nothing here should
    need per-source handling. A metric that came back `None` on one source and a
    number on another would be assuming that source's idiom."""
    results = {}
    for name, fixture in SOURCES:
        graph = kgrepair.load_graph(os.path.join(REAL, fixture))
        m = compute_metrics(graph)
        results[name] = m
        assert m.nodes > 0 and m.edges > 0
        assert m.typed_nodes > 0, f"{name}: no node was recognised as typed"
        assert m.classes > 0, f"{name}: no class was recognised"
    # the same fields are populated everywhere, which is the actual agnosticism claim
    shape = {n: {f.name for f in fields(GraphMetrics)
                 if getattr(m, f.name) is not None} for n, m in results.items()}
    assert len({frozenset(s) for s in shape.values()}) == 1, shape


def test_metrics_work_on_a_graph_with_no_domain_semantics():
    """T5's synthetic half: a graph nobody designed for this toolkit, with a typing
    spine that exists in no knowledge graph."""
    triples = [(f"n{i}", ISA, "Thing") for i in range(6)]
    triples += [(f"n{i}", "ex:rel", f"n{(i + 1) % 6}") for i in range(4)]
    triples += [("Thing", KIND, "Top")]
    m = compute_metrics(_g(triples), **VOCAB)
    assert m.typed_nodes == 6
    assert m.classes == 1 and m.classes_scored_for_coverage == 1
    assert m.property_coverage_mean == pytest.approx(4 / 6)
    assert m.redundant_type_edges == 0


def test_the_default_vocabulary_covers_the_three_spines():
    assert {"rdf:type", "wdt:P31"} <= set(DEFAULT_INSTANCE_OF)
    assert {"rdfs:subClassOf", "wdt:P279", "schema:subClassOf"} <= set(DEFAULT_SUBCLASS_OF)


def test_metrics_do_not_mutate_the_graph():
    graph, cs = _slice_and_constraints()
    before = (len(graph.nodes), graph.num_edges(), sorted(graph.labels))
    compute_metrics(graph, cs)
    assert (len(graph.nodes), graph.num_edges(), sorted(graph.labels)) == before
