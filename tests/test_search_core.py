"""
The two-axis search core: bitsets, the PCA denominator, and the two pruning laws.

Every claim the search makes about what it is allowed to skip is checked against
`reference_enumerator`, which scores the same space with nothing pruned. The
comparison runs on all three hand-built graphs and on a committed real slice, and
it runs on every build rather than once, because a pruning law is a claim about
every graph and not about the graph it was written on.
"""
from __future__ import annotations

import os

import reference_enumerator as ref
from search_fixtures import (ALL_THREE, B_BODY, B_HEAD, B_SILENT, CONFIG_B,
                             CONFIG_C, graph_b, graph_c)

import kgrepair
from kgrepair import gxpath
from kgrepair.search import (Extensions, NodeSpace, SearchConfig, admitted_identities,
                             antecedent_lattice, conjunction_text, head_axis, lead,
                             lead_text, score, search, tau_text, vocabulary)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GEO = os.path.join(ROOT, "fixtures", "real", "real_wikidata_geography_1000.nt")

#: Bounds the oracle can afford on the real slice. Low enough to enumerate the
#: whole space in well under a second, high enough that both axes have work to do:
#: six class heads, nine predicates, two-atom bodies and two-step heads.
GEO_CONFIG = SearchConfig(min_support=10, min_confidence=0.9,
                          max_antecedent=2, max_path=2)

TAU_CITY = '< down(wdt:P31) . down(wdt:P279)* . [val("wd:City")] >'


def _geo():
    return kgrepair.load_graph(GEO)


def _scores(result):
    """A search result as the oracle spells it: identity to the three numbers."""
    return {s.identity: (s.support, s.denominator, s.confidence) for s in result.admitted}


def _cases():
    """The three hand-built graphs and the real slice, as one sweep."""
    for name, factory, cfg in ALL_THREE:
        yield name, factory(), cfg
    yield "geography", _geo(), GEO_CONFIG


 
# T2: atoms as bitsets
 
def test_the_node_space_round_trips_a_set():
    graph = _geo()
    space = NodeSpace(graph)
    sample = set(sorted(graph.nodes)[:50])
    assert space.to_nodes(space.to_bits(sample)) == sample
    assert space.to_nodes(space.universe) == graph.nodes
    assert NodeSpace.count(space.universe) == len(graph.nodes)
    assert space.to_bits(set()) == 0 and space.to_nodes(0) == set()


def test_a_bitset_extension_equals_the_evaluator_on_the_same_expression():
    """T2's gate, across a sample of every expression shape the search builds:
    class tests, both step directions, conjunctions of two atoms, and two-step
    heads. The bitset path and the evaluator have to agree on all of them."""
    graph = _geo()
    space = NodeSpace(graph)
    ext = Extensions(graph, space)
    ev = gxpath.Evaluator(graph, use_closure=True)
    vocab = vocabulary(graph, GEO_CONFIG)

    texts = [a.text for a in vocab.atoms]
    texts += [conjunction_text([vocab.atoms[i].text, vocab.atoms[j].text])
              for i in range(0, len(vocab.atoms), 5)
              for j in range(i + 1, len(vocab.atoms), 7)]
    texts += [f"< down({p}) . up({q}) >"
              for p in vocab.predicates[:3] for q in vocab.predicates[:3]]
    assert len(texts) > 30, "the sample has to be wide enough to mean something"

    for text in texts:
        assert space.to_nodes(ext.of(text)) == ev.eval_node(gxpath.parse_node(text)), text


def test_a_conjunction_is_an_intersection_and_never_a_second_traversal():
    """The whole point of the bitset representation: once the atoms are in, a
    conjunction is an `and` of two ints. The traversal counter must not move while
    a lattice of conjunctions is being built."""
    graph = _geo()
    space = NodeSpace(graph)
    ext = Extensions(graph, space)
    ev = gxpath.Evaluator(graph, use_closure=True)
    vocab = vocabulary(graph, GEO_CONFIG)

    for atom in vocab.atoms:                     # one traversal each, and only here
        ext.of(atom.text)
    after_atoms = ext.traversals
    assert after_atoms == len(vocab.atoms)

    bodies = antecedent_lattice(vocab.atoms, ext, GEO_CONFIG)
    assert ext.traversals == after_atoms, "building the lattice re-traversed the graph"

    conjunctions = [b for b in bodies if len(b.key) == 2]
    assert conjunctions, "expected the fixture to yield two-atom bodies"
    for body in conjunctions[:20]:
        assert space.to_nodes(body.bits) == ev.eval_node(gxpath.parse_node(body.text))


 
# T3: the PCA denominator
 
def test_lead_reduces_each_head_shape_to_its_first_step():
    """A type test leads with having a type edge, a tested step with the bare
    step, and a longer path with its first step."""
    assert lead_text(TAU_CITY) == "< down(wdt:P31) >"
    assert lead_text('< down(wd:p) . [val("wd:C")] >') == "< down(wd:p) >"
    assert lead_text("< down(wd:p) . up(wd:q) >") == "< down(wd:p) >"
    assert lead_text("< up(wd:q) >") == "< up(wd:q) >"
    assert lead(gxpath.parse_node("< down(wd:p)* . down(wd:q) >")) == \
           gxpath.parse_node("< eps >")


def test_confidence_excludes_the_silent_nodes_the_witness_set_keeps():
    """T3's gate, and the reason `lead` exists, held in one test so the two halves
    cannot drift apart.

    Graph B has twelve nodes with a `cap` edge, nine typed and three silent. The
    denominator counts the nine that carry a type edge at all, so confidence is
    1.0 and the rule is admitted. The violation set counts the three silent nodes,
    because a node that should have a type and has none is exactly what a repair
    is for. Same rule, same graph, two different sets, both correct.
    """
    graph = graph_b()
    space = NodeSpace(graph)
    ext = Extensions(graph, space)
    body, head = ext.of(B_BODY), ext.of(B_HEAD)
    support, denominator, confidence = score(body, head, ext.of(lead_text(B_HEAD)))

    assert (support, denominator, confidence) == (9, 9, 1.0)
    assert NodeSpace.count(body) == 12, "three of the twelve are silent"
    assert space.to_nodes(body & ~head & space.universe) == B_SILENT
    assert ref.witnesses(graph, B_BODY, B_HEAD) == B_SILENT

    # counting the silent nodes in the denominator would have lost the rule
    assert support / NodeSpace.count(body) < CONFIG_B.min_confidence


def test_a_head_nothing_leads_is_unjudgeable_rather_than_false():
    """A zero denominator scores 0.0 and is never admitted. That is not the same
    as evidence against the rule, and the search does not treat it as such."""
    graph = graph_b()
    ext = Extensions(graph, NodeSpace(graph))
    body = ext.of("< up(wd:cap) >")              # the cap targets, none of them typed
    head = ext.of(B_HEAD)
    assert score(body, head, ext.of(lead_text(B_HEAD))) == (0, 0, 0.0)


 
# T4: the antecedent axis
 
def test_the_lattice_is_pruned_by_support_and_keeps_every_body_above_the_floor():
    graph = graph_c()
    ext = Extensions(graph, NodeSpace(graph))
    vocab = vocabulary(graph, CONFIG_C)

    pruned = antecedent_lattice(vocab.atoms, ext, CONFIG_C)
    whole = antecedent_lattice(vocab.atoms, ext, CONFIG_C, prune_support=False)

    assert {b.key for b in pruned} == {("d_n:p",), ("d_n:q",), ("u_n:p",), ("u_n:q",)}
    assert {b.key for b in whole} - {b.key for b in pruned} == {("d_n:r",), ("u_n:r",)}
    assert all(b.size >= CONFIG_C.min_support for b in pruned)


def test_confidence_is_not_monotone_along_the_antecedent_axis():
    """Why the lattice may not be pruned by confidence, on a graph that shows it.

    Ten nodes carry a `p` edge, five typed City and five typed Lake, so the broad
    body scores 0.5 against the City test. Conjoining `s`, which only the City
    ones carry, narrows the body to those five and the score rises to 1.0. A
    lattice that refused to extend a body below the confidence floor would have
    thrown the parent away and never reached the child.
    """
    graph = kgrepair.DataGraph()
    for i in range(5):
        graph.add_edge(f"wd:c{i}", "wd:p", f"wd:t{i}")
        graph.add_edge(f"wd:c{i}", "wd:s", f"wd:u{i}")
        graph.add_edge(f"wd:c{i}", "wdt:P31", "wd:City")
        graph.add_edge(f"wd:l{i}", "wd:p", f"wd:v{i}")
        graph.add_edge(f"wd:l{i}", "wdt:P31", "wd:Lake")
    graph.set_value("wd:City", "wd:City")
    graph.set_value("wd:Lake", "wd:Lake")

    cfg = SearchConfig(min_support=5, min_confidence=0.9, max_antecedent=2, max_path=1)
    head = tau_text("wdt:P31", "wdt:P279", "wd:City")
    scored = ref.enumerate_all(graph, cfg).scored

    broad = scored[(("d_wd:p",), head)]
    narrow = scored[(("d_wd:p", "d_wd:s"), head)]
    assert broad == (5, 10, 0.5) and broad[2] < cfg.min_confidence
    assert narrow == (5, 5, 1.0)

    # dominance off: this is a claim about the lattice, and the narrow rule is
    # extensionally identical to the plain "typed City" one, which outranks it
    # once shaping is on.
    admitted = admitted_identities(search(graph, cfg, prune_dominance=False).admitted)
    assert (("d_wd:p", "d_wd:s"), head) in admitted
    assert (("d_wd:p",), head) not in admitted


 
# T4: the consequent axis
 
def test_head_prefix_refusal_stops_a_subtree_being_generated():
    """Graph C's rare predicate. No body has a node in common with the `r` steps,
    so no body clears the confidence floor on them, and the two-step heads that
    start with `r` are never built. The oracle builds all thirty six."""
    graph = graph_c()
    refusing = search(graph, CONFIG_C)
    generous = search(graph, CONFIG_C, prune_prefix=False)
    oracle = ref.enumerate_all(graph, CONFIG_C)

    assert refusing.heads_generated < generous.heads_generated
    assert generous.heads_generated == oracle.heads == 42
    assert refusing.heads_generated == 30          # 6 one-step, 24 two-step
    assert admitted_identities(refusing.admitted) == admitted_identities(generous.admitted)

    # 20 prefixes are refused in total: the two `r` steps at length one, which is
    # what skips the twelve two-step heads above, and eighteen more at length two,
    # which are recorded but have no level below them to save. The counter counts
    # refusals, not savings; `heads_generated` above is where the saving shows.
    assert refusing.prefixes_refused == 20


def test_the_head_axis_scores_class_heads_without_extending_them():
    """A class test fixes its own path, so it is scored and never grown."""
    graph, cfg = graph_b(), CONFIG_B
    ext = Extensions(graph, NodeSpace(graph))
    vocab = vocabulary(graph, cfg)
    bodies = antecedent_lattice(vocab.atoms, ext, cfg)

    axis = head_axis(bodies, vocab, ext, cfg)
    heads = {s.head_key for s in axis.admitted}
    assert B_HEAD in heads
    assert not any(h.startswith("< down(wdt:P31) . down(wdt:P279)*") and " . down(wd:cap)" in h
                   for h in heads)


 
# T4: agreement with the oracle, one assertion per law, on every graph
 
def test_support_pruning_loses_nothing_above_min_conf():
    """The support floor on the antecedent axis, isolated: head-prefix refusal
    off, so any disagreement is the lattice's."""
    for name, graph, cfg in _cases():
        vocab = vocabulary(graph, cfg)
        oracle = ref.enumerate_all(graph, cfg, vocab)
        result = search(graph, cfg, prune_support=True, prune_prefix=False,
                        prune_dominance=False)
        assert oracle.admitted, f"{name} admitted nothing, so it tests nothing"
        assert _scores(result) == oracle.admitted, name
        assert result.bodies_generated <= oracle.bodies


def test_head_prefix_refusal_loses_nothing_above_min_conf():
    """Head-prefix refusal on the consequent axis, isolated: the lattice unpruned,
    so any disagreement is the head axis's."""
    for name, graph, cfg in _cases():
        vocab = vocabulary(graph, cfg)
        oracle = ref.enumerate_all(graph, cfg, vocab)
        result = search(graph, cfg, prune_support=False, prune_prefix=True,
                        prune_dominance=False)
        assert _scores(result) == oracle.admitted, name
        assert result.heads_generated <= oracle.heads


def test_both_laws_together_admit_exactly_what_the_oracle_admits():
    """Both P4a laws at once, with the shaping filter off on both sides, so this
    stays an assertion about losslessness and nothing else."""
    for name, graph, cfg in _cases():
        oracle = ref.enumerate_all(graph, cfg, vocabulary(graph, cfg))
        result = search(graph, cfg, prune_dominance=False)
        assert _scores(result) == oracle.admitted, name


def test_the_shaped_output_matches_the_oracle_shaped_the_same_way():
    """The whole pipeline, dominance included. The oracle applies the same filter
    as a plain pass over everything it admitted, so the two remain comparable
    after the shaping rule changed what the search returns."""
    for name, graph, cfg in _cases():
        oracle = ref.enumerate_all(graph, cfg, vocabulary(graph, cfg))
        result = search(graph, cfg)
        assert _scores(result) == oracle.dominant, name


def test_the_agreement_sweep_is_not_vacuous():
    """Each law has to actually skip work somewhere in the sweep, or agreeing with
    the oracle proves nothing about it.

    The two laws bite on different cases here, and the test says which. On the
    real slice the support floor skips two thirds of the lattice, while every
    one-step head clears the confidence floor, so head-prefix refusal is checked
    for losslessness there and saves nothing: at `max_path=2` a refusal at the
    last length has no level below it to skip. Graph C is where the head axis
    skips a subtree, because its rare predicate refuses at length one.
    """
    graph = _geo()
    oracle = ref.enumerate_all(graph, GEO_CONFIG, vocabulary(graph, GEO_CONFIG))
    result = search(graph, GEO_CONFIG)
    assert result.bodies_generated < oracle.bodies      # the support floor bit
    assert len(result.admitted) > 100

    c_oracle = ref.enumerate_all(graph_c(), CONFIG_C)
    c_result = search(graph_c(), CONFIG_C)
    assert c_result.heads_generated < c_oracle.heads    # the head prefix bit


def test_the_search_is_deterministic():
    for _name, graph, cfg in _cases():
        first, second = search(graph, cfg), search(graph, cfg)
        assert [s.identity for s in first.admitted] == [s.identity for s in second.admitted]
        assert _scores(first) == _scores(second)


def test_the_search_does_not_mutate_the_graph():
    graph = _geo()
    before = (len(graph.nodes), graph.num_edges(), sorted(graph.labels))
    search(graph, GEO_CONFIG)
    assert (len(graph.nodes), graph.num_edges(), sorted(graph.labels)) == before
