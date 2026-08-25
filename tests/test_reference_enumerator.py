"""
The oracle's own correctness, against three graphs whose answers are written out.

The reference enumerator is what every pruning rule in `kgrepair.search` is
checked against, so it needs its own check that does not involve the search at
all. These tests supply one: three graphs small enough that the admitted set can
be read off the data, and the whole set asserted rather than sampled.

If one of these fails, the hand count in the docstring is the appeal, not the
code.
"""
from __future__ import annotations

import reference_enumerator as ref
from kgrepair.search import SearchConfig, vocabulary
from search_fixtures import (ALL_THREE, CONFIG_A, CONFIG_B, CONFIG_C, graph_a,
                             graph_b, graph_c)

TAU_CITY = '< down(wdt:P31) . down(wdt:P279)* . [val("wd:City")] >'
TAU_GEO = '< down(wdt:P31) . down(wdt:P279)* . [val("wd:Geo")] >'
DOWN_CAP = "< down(wd:cap) >"
UP_CAP = "< up(wd:cap) >"


def test_graph_a_admits_exactly_the_six_rules_that_hold_and_say_something():
    """Graph A by hand. Four atoms: City and Geo (both matching the six x nodes,
    since City is a subclass of Geo), the cap sources (the same six), and the cap
    targets (the six c nodes). Four heads: the same two class tests and the two
    step tests.

    Each of the three bodies over the x nodes satisfies all three heads that also
    describe the x nodes, which is nine, and the cap targets satisfy the test that
    describes them, which is a tenth. Four of those ten are a head restating its
    own body atom, and P4d refuses those at generation on both sides (see
    `search.is_tautology`), so six pairs are scored and admitted here.
    """
    result = ref.enumerate_all(graph_a(), CONFIG_A)
    x_bodies = [("c_wd:City",), ("c_wd:Geo",), ("d_wd:cap",)]
    expected = {(body, head)
                for body in x_bodies
                for head in (TAU_CITY, TAU_GEO, DOWN_CAP)}
    expected.add((("u_wd:cap",), UP_CAP))
    tautologies = {(("c_wd:City",), TAU_CITY), (("c_wd:Geo",), TAU_GEO),
                   (("d_wd:cap",), DOWN_CAP), (("u_wd:cap",), UP_CAP)}
    expected -= tautologies

    assert result.admitted_identities == frozenset(expected)
    assert len(expected) == 6
    for identity in expected:
        support, denominator, confidence = result.admitted[identity]
        assert (support, denominator, confidence) == (6, 6, 1.0)
    # refused before scoring, so they are absent from `scored` and not merely
    # missing from `admitted`
    for identity in tautologies:
        assert identity not in result.scored


def test_graph_a_scores_a_disjoint_pair_with_a_zero_denominator():
    """The cap targets against a class test. Nothing is typed among them, so the
    denominator is zero and the pair is unjudgeable rather than false."""
    result = ref.enumerate_all(graph_a(), CONFIG_A)
    assert result.scored[(("u_wd:cap",), TAU_CITY)] == (0, 0, 0.0)


def test_graph_b_admits_the_rule_that_three_silent_nodes_break():
    """Graph B by hand. Twelve cap sources, nine of them typed City. Support is
    nine, the denominator counts only the nine that carry a type edge at all, so
    confidence is 1.0 and the rule is admitted. Counting the three silent nodes in
    the denominator would give 0.75 and lose it."""
    result = ref.enumerate_all(graph_b(), CONFIG_B)
    identity = (("d_wd:cap",), TAU_CITY)
    assert result.admitted[identity] == (9, 9, 1.0)
    # the three pairs where the head restates the body's own atom are refused at
    # generation (P4d/T2), leaving the two that say something about the data
    assert result.admitted_identities == frozenset({
        (("c_wd:City",), DOWN_CAP),
        (("d_wd:cap",), TAU_CITY),
    })


def test_graph_b_witness_set_holds_the_nodes_the_denominator_drops():
    """The same rule, from the repair side: the three silent nodes are witnesses.
    Scored and repaired are different sets, and this is the graph that shows it."""
    g = graph_b()
    assert ref.witnesses(g, DOWN_CAP, TAU_CITY) == {"wd:x9", "wd:x10", "wd:x11"}


def test_graph_c_admits_the_two_step_head_and_never_the_rare_predicate():
    """Graph C by hand. Six a nodes reach a b node by p, and every b node reaches a
    c node by q, so `p then q` describes exactly the six a nodes and is admitted
    under the p sources. The r edges touch two nodes, so nothing over r reaches the
    support floor of five, at either path length."""
    result = ref.enumerate_all(graph_c(), CONFIG_C)
    assert (("d_n:p",), "< down(n:p) . down(n:q) >") in result.admitted
    assert result.admitted[(("d_n:p",), "< down(n:p) . down(n:q) >")] == (6, 6, 1.0)
    over_r = [identity for identity in result.admitted
              if "n:r" in identity[1] or any("n:r" in k for k in identity[0])]
    assert over_r == []


def test_graph_c_enumerates_the_whole_unpruned_space():
    """Six atoms, so six bodies at one atom each. Six one-step heads and thirty six
    two-step heads, and no class heads because the config names a typing spine the
    graph does not have. Nothing is refused, which is the property being asserted:
    the oracle generates the subtrees the search is allowed to skip."""
    vocab = vocabulary(graph_c(), CONFIG_C)
    assert vocab.classes == []
    assert vocab.predicates == ["n:p", "n:q", "n:r"]

    result = ref.enumerate_all(graph_c(), CONFIG_C, vocab)
    assert (result.bodies, result.heads) == (6, 42)
    assert (("d_n:r",), "< down(n:r) . down(n:p) >") in result.scored


def test_every_admitted_candidate_clears_both_floors_on_every_graph():
    """The admission rule, read back off the results on all three graphs."""
    for name, factory, cfg in ALL_THREE:
        result = ref.enumerate_all(factory(), cfg)
        assert result.admitted, f"graph {name} admitted nothing, so it tests nothing"
        for identity, (support, denominator, confidence) in result.admitted.items():
            assert denominator >= 1, f"{name} {identity}"
            assert support >= cfg.min_support, f"{name} {identity}"
            assert confidence >= cfg.min_confidence, f"{name} {identity}"


def test_the_oracle_is_deterministic():
    for _name, factory, cfg in ALL_THREE:
        first = ref.enumerate_all(factory(), cfg)
        second = ref.enumerate_all(factory(), cfg)
        assert first.admitted == second.admitted
        assert first.scored == second.scored


def test_a_lower_floor_admits_a_superset():
    """Sanity on the floors themselves: relaxing support can only add candidates,
    since it is the only thing that changed."""
    loose = ref.enumerate_all(graph_c(), SearchConfig(
        min_support=1, min_confidence=0.9, max_antecedent=1, max_path=2,
        type_predicate="wdt:P31", subclass_predicate="wdt:P279"))
    strict = ref.enumerate_all(graph_c(), CONFIG_C)
    assert strict.admitted_identities < loose.admitted_identities
