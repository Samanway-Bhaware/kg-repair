"""
Shaping a correct candidate set into one a person can review.

P4a's search is right and noisy: it returns everything above the floors, including
rules that restate a rule already shown and rules that restate themselves. This
covers the three things that shape it, and the one thing that is deliberately not
shaping at all:

  * dominance, which drops a candidate another candidate already covers;
  * residual profiling, which offers a second, broader reading of a rule that
    failed, alongside the original and never in place of it;
  * stability against a reference graph, which has three outcomes and not two.

None of them accepts anything. There is no confidence at which this search
approves a rule, and `test_nothing_here_can_accept_anything` holds that.
"""
from __future__ import annotations

import os

import reference_enumerator as ref
from search_fixtures import (CONFIG_A, CONFIG_C, CONFIG_META, DISEASE, META_ATOM,
                             META_BODY, META_HEAD, TYPE_OF_DISEASE, graph_a,
                             graph_c, graph_meta_class)

import kgrepair
from kgrepair.search import (NOT_COMPARABLE, STABLE, UNSTABLE, Extensions, NodeSpace,
                             SearchConfig, admitted_identities, antecedent_lattice,
                             assess_stability, dominance_order, dominates, lead_text,
                             score, search, vocabulary)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GEO = os.path.join(ROOT, "fixtures", "real", "real_wikidata_geography_1000.nt")
TAXA = os.path.join(ROOT, "fixtures", "real", "real_wikidata_taxa_1000.nt")
DBPEDIA = os.path.join(ROOT, "fixtures", "real", "real_dbpedia_geography_1000.nt")

GEO_CONFIG = SearchConfig(min_support=10, min_confidence=0.9,
                          max_antecedent=2, max_path=2)


 
# T1: dominance
 
def test_a_condition_that_bought_nothing_is_dropped_and_the_general_rule_kept():
    """The rule T1 states. A body of eight nodes all typed City scores 1.0; adding
    a second condition that five of them also carry scores 1.0 as well, so the
    condition bought nothing and only the general rule is shown."""
    graph = kgrepair.DataGraph()
    for i in range(8):
        graph.add_edge(f"wd:x{i}", "wd:p", f"wd:t{i}")
        graph.add_edge(f"wd:x{i}", "wdt:P31", "wd:City")
    for i in range(5):
        graph.add_edge(f"wd:x{i}", "wd:s", f"wd:u{i}")
    graph.set_value("wd:City", "wd:City")

    cfg = SearchConfig(min_support=5, min_confidence=0.9, max_antecedent=2, max_path=1)
    head = '< down(wdt:P31) . down(wdt:P279)* . [val("wd:City")] >'

    unshaped = admitted_identities(search(graph, cfg, prune_dominance=False).admitted)
    shaped = admitted_identities(search(graph, cfg).admitted)

    assert (("d_wd:p",), head) in unshaped and (("d_wd:p", "d_wd:s"), head) in unshaped
    assert (("d_wd:p",), head) in shaped, "the general rule has to survive"
    assert (("d_wd:p", "d_wd:s"), head) not in shaped, "the specialisation bought nothing"


def test_a_specialisation_that_earns_its_place_is_kept():
    """Dominance needs the confidence to be at least as high, so a condition that
    genuinely raises it is not dropped.

    Both conditions are needed here and neither will do on its own: `p` covers the
    cities and five lakes, `s` covers the cities and five other lakes, so each
    alone scores 0.5 and only the conjunction scores 1.0. That is what makes the
    conjunction worth showing, and the two broad rules cannot dominate it because
    dominance also requires the confidence not to drop.
    """
    graph = kgrepair.DataGraph()
    for i in range(5):                                  # cities: both conditions
        graph.add_edge(f"wd:city{i}", "wd:p", f"wd:t{i}")
        graph.add_edge(f"wd:city{i}", "wd:s", f"wd:u{i}")
        graph.add_edge(f"wd:city{i}", "wdt:P31", "wd:City")
    for i in range(5):                                  # lakes with p only
        graph.add_edge(f"wd:lakep{i}", "wd:p", f"wd:t2{i}")
        graph.add_edge(f"wd:lakep{i}", "wdt:P31", "wd:Lake")
    for i in range(5):                                  # lakes with s only
        graph.add_edge(f"wd:lakes{i}", "wd:s", f"wd:u2{i}")
        graph.add_edge(f"wd:lakes{i}", "wdt:P31", "wd:Lake")
    graph.set_value("wd:City", "wd:City")
    graph.set_value("wd:Lake", "wd:Lake")

    cfg = SearchConfig(min_support=5, min_confidence=0.9, max_antecedent=2, max_path=1)
    head = '< down(wdt:P31) . down(wdt:P279)* . [val("wd:City")] >'
    shaped = admitted_identities(search(graph, cfg).admitted)
    assert (("d_wd:p", "d_wd:s"), head) in shaped
    assert (("d_wd:p",), head) not in shaped and (("d_wd:s",), head) not in shaped


def test_a_rule_that_restates_one_of_its_own_atoms_is_never_generated():
    """It scores perfectly by construction and says nothing about the data.

    Graph A's ten scoreable pairs come down to three once the tautologies are
    refused and the rest is shaped. Four are rules restating their own atom. The
    rest describe the same six nodes with the same confidence, so one survives per
    head on the tie-break, and every survivor is a statement relating two different
    things: city implies geo, geo implies city, city implies having a capital.

    Leaving the tautologies in would not be harmless noise. They tie on confidence
    with everything else and win the tie-break on atom count, so they would be the
    only candidates shown for their head.

    P4d/T2 moved the block from shaping to generation, so the two counts are now
    separate: `tautologies` counts what was refused before scoring, and `dominated`
    counts only what a better rule beat. The gate on the move is that a tautology
    never reaches the admitted set on the graph P4a deliberately left them in.
    """
    result = search(graph_a(), CONFIG_A)
    shaped = admitted_identities(result.admitted)
    tau_city = '< down(wdt:P31) . down(wdt:P279)* . [val("wd:City")] >'
    tau_geo = '< down(wdt:P31) . down(wdt:P279)* . [val("wd:Geo")] >'

    assert shaped == frozenset({
        (("c_wd:City",), "< down(wd:cap) >"),
        (("c_wd:City",), tau_geo),
        (("c_wd:Geo",), tau_city),
    })
    assert result.tautologies == 4 and result.dominated == 3
    for body_key, head in shaped:
        assert head not in {"< down(wd:cap) >"} or body_key != ("d_wd:cap",)
    assert (("d_wd:cap",), "< down(wd:cap) >") not in shaped
    assert (("u_wd:cap",), "< up(wd:cap) >") not in shaped
    assert (("c_wd:City",), tau_city) not in shaped

    # and the block is not shaping: turning shaping off leaves them out too
    unshaped = admitted_identities(search(graph_a(), CONFIG_A,
                                          prune_dominance=False).admitted)
    assert (("c_wd:City",), tau_city) not in unshaped
    assert (("d_wd:cap",), "< down(wd:cap) >") not in unshaped


def test_reduced_cover_still_earns_its_place_and_is_absorbed_not_deleted():
    """T1's decision, decided by measurement rather than by assumption.

    The online rule compares atom sets: reject a body that strictly extends an
    already-admitted one. The older reduced-cover pass compares extensions: reject
    a body another body's extension strictly contains. They are not the same
    relation, and neither contains the other, so both are kept and `dominates`
    applies both.

    On the geography slice the extensional half removes candidates the atom-set
    half keeps. That measurement is what decided this, so it is asserted rather
    than described.
    """
    graph = kgrepair.load_graph(GEO)
    result = search(graph, GEO_CONFIG, prune_dominance=False)
    space = NodeSpace(graph)
    ext = Extensions(graph, space)
    vocab = vocabulary(graph, GEO_CONFIG)
    bits = {b.key: b.bits for b in antecedent_lattice(vocab.atoms, ext, GEO_CONFIG)}
    atom_text = {a.key: a.text for a in vocab.atoms}

    def survives(identity, conf, use_extensional):
        body_key, head = identity
        if head in {atom_text[k] for k in body_key}:
            return False
        for other in result.admitted:
            if other.head_key != head or other.body_key == body_key:
                continue
            if other.confidence < conf:
                continue
            if set(other.body_key) < set(body_key):
                return False                       # the atom-set half
            if use_extensional and bits[other.body_key] != bits[body_key] \
                    and not (bits[body_key] & ~bits[other.body_key]):
                return False                       # the reduced-cover half
        return True

    atom_only = {s.identity for s in result.admitted if survives(s.identity, s.confidence, False)}
    both = {s.identity for s in result.admitted if survives(s.identity, s.confidence, True)}
    assert both < atom_only, "the extensional half removed nothing the atom-set half missed"
    assert len(atom_only - both) > 100


def test_online_dominance_agrees_with_a_pass_over_everything():
    """The search only ever compares a candidate with what it has already kept.
    The oracle compares against everything admitted. Those agree because dominance
    is transitive: if anything beats a candidate, something the online pass kept
    beats it too."""
    for graph, cfg in ((graph_a(), CONFIG_A), (graph_c(), CONFIG_C),
                       (kgrepair.load_graph(GEO), GEO_CONFIG)):
        oracle = ref.enumerate_all(graph, cfg, vocabulary(graph, cfg))
        assert admitted_identities(search(graph, cfg).admitted) == frozenset(oracle.dominant)


def test_the_dominance_order_puts_a_dominator_before_what_it_dominates():
    graph = kgrepair.load_graph(GEO)
    ext = Extensions(graph, NodeSpace(graph))
    vocab = vocabulary(graph, GEO_CONFIG)
    ordered = dominance_order(antecedent_lattice(vocab.atoms, ext, GEO_CONFIG))
    position = {b.key: i for i, b in enumerate(ordered)}
    for a in ordered:
        for b in ordered:
            if a.key != b.key and dominates(a.bits, a.key, 1.0, b.bits, b.key, 1.0):
                assert position[a.key] < position[b.key], (a.key, b.key)


 
# T2: residual profiling
 
def test_the_meta_class_residual_is_proposed_as_a_widening():
    """T2's gate, on the idiom `tests/test_constraints_v2.py` traced by hand.

    Twelve things with a symptom are typed disease and six are typed through the
    meta-class, so the rule scores 12/18 and fails. The six are its whole residual
    and one atom covers all of them, so the widening is offered: symptom implies
    disease or the meta-class.
    """
    result = search(graph_meta_class(), CONFIG_META)
    widening = next((w for w in result.widenings
                     if w.original.body_text == META_BODY
                     and w.original.head_text == META_HEAD), None)
    assert widening is not None, "the widening the fixture exists for was not proposed"

    assert widening.kind == "weakening"
    assert widening.atom_key == META_ATOM
    assert (widening.residual_size, widening.residual_covered) == (6, 6)
    assert widening.coverage == 1.0
    assert widening.original.support == 12 and widening.original.denominator == 18
    assert round(widening.original.confidence, 4) == 0.6667
    assert widening.confidence == 1.0
    assert TYPE_OF_DISEASE in widening.head_text and DISEASE in widening.head_text


def test_the_original_is_still_present_and_nothing_accepted_it():
    """The widening never replaces the rule it came from. The original travels with
    it, with its own numbers, so a reviewer decides which of the two is true about
    the world rather than being handed the broader one.

    Nothing in the search has a status, an approval or an accept path, so the pair
    reaches review undecided by construction.
    """
    result = search(graph_meta_class(), CONFIG_META)
    widening = next(w for w in result.widenings if w.original.head_text == META_HEAD)

    original = widening.original
    assert original.body_text == META_BODY and original.head_text == META_HEAD
    assert original.confidence < CONFIG_META.min_confidence
    assert original.identity not in admitted_identities(result.admitted), \
        "the original failed the floor; it is present because of its residual"
    assert not hasattr(original, "status") and not hasattr(widening, "status")


def test_a_widening_is_scored_end_to_end_through_the_library_lead():
    """P4d/T1's gate. `search.lead` now takes the disjunctive head that residual
    profiling emits, so the search can score what it produces without a caller
    keeping a private copy of the rule.

    Scored from the head text alone, through the parser and the evaluator, the
    widening reproduces the numbers `residual_widenings` recorded. The denominator
    is the original's, unchanged by the widening, which is what makes the two
    confidences comparable.
    """
    graph = graph_meta_class()
    result = search(graph, CONFIG_META)
    widening = next(w for w in result.widenings if w.original.head_text == META_HEAD)

    # the lead of `A | B` is the disjunction of the two leads, spelled back
    assert lead_text(widening.head_text) == (
        f"{lead_text(META_HEAD)} | {lead_text(widening.head_text.split(' | ')[1])}")

    ext = Extensions(graph, NodeSpace(graph))
    support, denominator, confidence = score(ext.of(widening.original.body_text),
                                             ext.of(widening.head_text),
                                             ext.of(lead_text(widening.head_text)))
    assert (support, denominator) == (widening.support, widening.original.denominator)
    assert confidence == widening.confidence == 1.0


def test_a_widening_needs_real_evidence_behind_the_residual():
    """A residual of two nodes is covered by almost any atom, which would mean
    nothing. The covered part has to clear the support floor in its own right, the
    same evidence every other emission needs."""
    result = search(graph_meta_class(), SearchConfig(
        min_support=7, min_confidence=0.9, max_antecedent=1, max_path=1))
    assert not [w for w in result.widenings if w.original.head_text == META_HEAD], \
        "a residual of six should not clear a support floor of seven"


def test_a_widening_is_never_scored_above_one():
    """Regression. Judging the widened head on its own leading set while keeping
    the original denominator lets the disjunct pull in nodes the original never
    spoke about, and the ratio runs past 1.0."""
    for graph, cfg in ((graph_meta_class(), CONFIG_META),
                       (kgrepair.load_graph(GEO), GEO_CONFIG)):
        for w in search(graph, cfg).widenings:
            assert 0.0 <= w.confidence <= 1.0, w
            assert w.confidence >= w.original.confidence
            assert w.residual_covered <= w.residual_size


def test_widenings_are_only_drawn_from_rules_that_actually_failed():
    graph = kgrepair.load_graph(GEO)
    result = search(graph, GEO_CONFIG)
    oracle = ref.enumerate_all(graph, GEO_CONFIG, vocabulary(graph, GEO_CONFIG))
    assert result.widenings
    for w in result.widenings:
        scored = oracle.scored[w.original.identity]
        assert scored[2] < GEO_CONFIG.min_confidence
        assert w.original.identity not in oracle.admitted


 
# T3: stability, three outcomes
 
def test_a_reference_sharing_no_predicates_is_not_comparable_and_discards_nothing():
    """The case the third outcome exists for, on the pair that actually has it.

    A Wikidata rule scored against a DBpedia slice: the two share no predicate at
    all, Wikidata naming `wdt:P17` where DBpedia names `dbo:country`. Every
    geography antecedent therefore matches nothing in the reference, scoring a
    zero denominator, a confidence of 0.0 and a gap that looks exactly like
    instability while meaning the reference had nothing to say. Every candidate
    has to come back `not_comparable`, with a null reference confidence, and none
    of them may be discarded, even at a delta of zero.
    """
    target = kgrepair.load_graph(GEO)
    reference = kgrepair.load_graph(DBPEDIA)
    assert target.labels & reference.labels == set(), \
        "this test needs a reference that shares no predicate with the target"

    result = search(target, GEO_CONFIG)
    verdicts = assess_stability(result.admitted, reference, GEO_CONFIG, delta=0.0)

    assert len(verdicts) == len(result.admitted) and verdicts
    assert {v.outcome for v in verdicts.values()} == {NOT_COMPARABLE}
    assert all(v.confidence_ref is None for v in verdicts.values())
    assert all(v.gap is None for v in verdicts.values())
    assert not any(v.discard for v in verdicts.values())
    assert all("nothing to say" in v.reason or "no denominator" in v.reason
               for v in verdicts.values())


def test_a_reference_that_shares_some_predicates_is_judged_on_those():
    """The taxa slice is not the no-shared-predicates case, though it looks like
    one: it shares `part of` and `has part` with geography. So some geography
    rules are comparable against it and some are not, and the floor is what tells
    them apart rather than a blanket verdict either way."""
    target, reference = kgrepair.load_graph(GEO), kgrepair.load_graph(TAXA)
    shared = target.labels & reference.labels
    assert shared == {"wdt:P31", "wdt:P361", "wdt:P527"}

    verdicts = assess_stability(search(target, GEO_CONFIG).admitted, reference,
                                GEO_CONFIG, delta=0.0)
    outcomes = {v.outcome for v in verdicts.values()}
    assert NOT_COMPARABLE in outcomes and len(outcomes) > 1
    for verdict in verdicts.values():
        if verdict.outcome == NOT_COMPARABLE:
            assert verdict.confidence_ref is None
        else:
            assert verdict.reference_support >= GEO_CONFIG.effective_reference_floor


def _typed_target(cls: str, count: int = 12) -> kgrepair.DataGraph:
    """`count` things with a symptom, all typed `cls`. The rule "anything with a
    symptom is a `cls`" is admitted here at confidence 1.0."""
    g = kgrepair.DataGraph()
    g.set_value(cls, cls)
    for i in range(count):
        g.add_edge(f"wd:thing{i}", "wdt:P780", f"wd:sign{i}")
        g.add_edge(f"wd:thing{i}", "wdt:P31", cls)
    return g


def test_a_reference_that_agrees_is_stable_and_one_that_disagrees_is_not():
    """With the floor cleared, the comparison happens and both verdicts are
    reachable. Both references carry the target's predicate, so both have
    something to say; what they say is what differs."""
    cfg = SearchConfig(min_support=5, min_confidence=0.9, max_antecedent=1, max_path=1)
    target = _typed_target(DISEASE)
    result = search(target, cfg)
    picked = next(s for s in result.admitted
                  if s.body_text == META_BODY and s.head_text == META_HEAD)

    agreeing = _typed_target(DISEASE, count=10)
    disagreeing = _typed_target("wd:Other", count=10)

    stable = assess_stability([picked], agreeing, cfg, delta=0.05)[picked.identity]
    assert stable.outcome == STABLE and stable.confidence_ref == 1.0
    assert stable.reference_support == 10 and not stable.discard

    unstable = assess_stability([picked], disagreeing, cfg, delta=0.05)[picked.identity]
    assert unstable.outcome == UNSTABLE and unstable.discard
    assert unstable.confidence_ref == 0.0 and unstable.gap == 1.0


def test_the_reference_floor_defaults_to_the_support_floor():
    cfg = SearchConfig(min_support=11)
    assert cfg.effective_reference_floor == 11
    assert SearchConfig(min_support=11, reference_support_floor=3
                        ).effective_reference_floor == 3


def test_a_reference_just_over_the_floor_is_compared_rather_than_excused():
    """The floor is a floor, not a preference: clearing it by one node is enough
    to be judged."""
    cfg = SearchConfig(min_support=5, min_confidence=0.9, max_antecedent=1, max_path=1)
    picked = next(s for s in search(_typed_target(DISEASE), cfg).admitted
                  if s.body_text == META_BODY and s.head_text == META_HEAD)

    verdict = assess_stability([picked], _typed_target(DISEASE, count=5), cfg,
                               delta=0.5)[picked.identity]
    assert verdict.outcome == STABLE
    assert verdict.reference_support == 5 and verdict.confidence_ref == 1.0

    below = assess_stability([picked], _typed_target(DISEASE, count=4), cfg,
                             delta=0.5)[picked.identity]
    assert below.outcome == NOT_COMPARABLE and below.reference_support == 4


def test_nothing_here_can_accept_anything():
    """The property the whole review airlock rests on, asserted at this layer too.
    A search produces scored records. No score, however high, marks one approved,
    and there is no flag on any entry point that would."""
    result = search(graph_meta_class(), CONFIG_META)
    for record in list(result.admitted) + [w.original for w in result.widenings]:
        assert not hasattr(record, "status")
        assert not hasattr(record, "accepted")
    assert not any(name in dir(kgrepair.search) for name in ("accept", "approve",
                                                             "auto_accept"))


def test_shaping_is_deterministic():
    for graph, cfg in ((graph_meta_class(), CONFIG_META),
                       (kgrepair.load_graph(GEO), GEO_CONFIG)):
        first, second = search(graph, cfg), search(graph, cfg)
        assert admitted_identities(first.admitted) == admitted_identities(second.admitted)
        assert [w.identity for w in first.widenings] == [w.identity for w in second.widenings]
