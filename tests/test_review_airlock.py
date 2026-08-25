"""
The review airlock: derivation proposes, a person decides, only a sealed file repairs.

The property under test is a negative one. No derived constraint reaches an engine
because it scored well. It reaches an engine only after a reviewer decided every
entry and sealed the file, and every way of getting round that has to be refused.

One test per refusal condition, each asserting the exception type and that the
offending cid appears in the message where the refusal is about one entry.
"""
import json
import os

import pytest

import kgrepair
from kgrepair.candidates import (ACCEPTED, PENDING, REJECTED, WEAKENED, CandidateFile,
                                 Candidate, candidate_cid, dumps_canonical,
                                 verify_seal)
from kgrepair.derive import DeriveConfig
from kgrepair.review import (BoundaryNotRepairable, NothingAccepted, NotSealed,
                             OutOfFragment, ReviewIncomplete, SealMismatch,
                             SourceDrift)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GEO = os.path.join(ROOT, "fixtures", "real", "real_wikidata_geography_1000.nt")
TAXA = os.path.join(ROOT, "fixtures", "real", "real_wikidata_taxa_1000.nt")


def _candidate(cid="d.k.derived.00000001", antecedent="< down(ex:p) >",
               consequent='< down(ex:isa) . [val("ex:C")] >', **kw):
    base = dict(cid=cid, kind="existential_domain", tier="ptime_core",
                direction="subset", antecedent=antecedent, consequent=consequent,
                gloss="anything with an outgoing p edge should be a C")
    base.update(kw)
    return Candidate(**base)


def _file(graph=None, candidates=None, dataset="fixture") -> CandidateFile:
    cf = CandidateFile(source={"dataset": dataset, "domain": "d", "kg": "k",
                               "content_hash": (kgrepair.graph_content_hash(graph)
                                                if graph is not None else "")},
                       candidates=list(candidates or [_candidate()]))
    cf.review["review_order"] = [c.cid for c in cf.candidates]
    return cf


def _sealed(graph=None, candidates=None) -> CandidateFile:
    cf = _file(graph, candidates)
    for c in cf.candidates:
        if c.status == PENDING:
            kgrepair.set_status(cf, c.cid, ACCEPTED)
    return kgrepair.seal_candidates(cf, "a reviewer", sealed_at="2026-01-01T00:00:00Z")


# ---------- T1: the file model ----------------------------------------------

def test_cid_is_content_derived_not_a_counter():
    """The same rule always gets the same id, so a decision stays attached to the
    rule it was made about even when the surrounding candidates change."""
    a = candidate_cid("geo", "wd", "< down(p) >", '< down(t) . [val("C")] >')
    b = candidate_cid("geo", "wd", "<  down(p)  >", '< down(t) . [val("C")] >')
    assert a == b                                  # spacing does not change identity
    assert a.startswith("geo.wd.derived.") and len(a.split(".")[-1]) == 8
    assert a != candidate_cid("geo", "wd", "< down(q) >", '< down(t) . [val("C")] >')


def test_round_trip_through_a_file(tmp_path):
    cf = _file()
    path = str(tmp_path / "c.json")
    kgrepair.write_canonical(cf, path)
    back = kgrepair.read_candidate_file(path)
    assert back.to_dict() == cf.to_dict()


def test_two_writes_of_the_same_content_are_byte_identical(tmp_path):
    cf = _file()
    first, second = str(tmp_path / "a.json"), str(tmp_path / "b.json")
    kgrepair.write_canonical(cf, first)
    kgrepair.write_canonical(kgrepair.read_candidate_file(first), second)
    assert open(first, "rb").read() == open(second, "rb").read()


def test_unknown_schema_is_refused(tmp_path):
    path = str(tmp_path / "c.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"schema": "something.else/v9", "candidates": []}, fh)
    with pytest.raises(ValueError, match="schema"):
        kgrepair.read_candidate_file(path)


# ---------- T1: merge -------------------------------------------------------

def test_merge_keeps_decisions_already_recorded():
    existing = _file()
    cid = existing.candidates[0].cid
    kgrepair.set_status(existing, cid, ACCEPTED, note="checked against the source")

    fresh = _file()                                # same rule, proposed again
    merged = kgrepair.merge_candidates(existing, fresh)

    assert len(merged.candidates) == 1
    assert merged.by_cid(cid).status == ACCEPTED
    assert merged.by_cid(cid).note == "checked against the source"


def test_merge_drops_a_cid_that_was_rejected():
    """A rejection sticks. Re-deriving must not put the same rule back in the queue."""
    existing = _file()
    cid = existing.candidates[0].cid
    kgrepair.set_status(existing, cid, REJECTED)
    assert cid in existing.refused

    merged = kgrepair.merge_candidates(existing, _file())
    assert [c.cid for c in merged.candidates] == [cid]
    assert merged.by_cid(cid).status == REJECTED   # retained, not deleted


def test_merge_appends_only_unseen_candidates():
    existing = _file()
    kgrepair.set_status(existing, existing.candidates[0].cid, ACCEPTED)
    fresh = _file(candidates=[_candidate(), _candidate(cid="d.k.derived.deadbeef",
                                                       antecedent="< down(ex:q) >")])
    merged = kgrepair.merge_candidates(existing, fresh)
    assert len(merged.candidates) == 2
    assert merged.by_cid("d.k.derived.deadbeef").status == PENDING


def test_merge_never_leaves_the_file_sealed():
    """A seal covers a set of decisions. Bringing in an entry nobody has seen has
    to reopen the file rather than let the old seal cover it."""
    existing = _sealed()
    assert existing.sealed
    merged = kgrepair.merge_candidates(
        existing, _file(candidates=[_candidate(cid="d.k.derived.deadbeef",
                                               antecedent="< down(ex:q) >")]))
    assert not merged.sealed
    assert merged.review["seal"] is None


def test_changing_a_decision_reopens_a_sealed_file():
    cf = _sealed()
    kgrepair.set_status(cf, cf.candidates[0].cid, REJECTED)
    assert not cf.sealed and cf.review["seal"] is None


# ---------- T3: the gate, one test per refusal ------------------------------

def test_refuses_a_file_that_was_never_sealed():
    cf = _file()
    kgrepair.set_status(cf, cf.candidates[0].cid, ACCEPTED)
    with pytest.raises(NotSealed) as exc:
        kgrepair.reviewed_constraint_set(cf)
    assert "not sealed" in str(exc.value) and "E-UNSEALED" in str(exc.value)


def test_refuses_a_file_with_an_entry_still_pending():
    cf = _file(candidates=[_candidate(), _candidate(cid="d.k.derived.aaaaaaaa",
                                                    antecedent="< down(ex:q) >")])
    kgrepair.set_status(cf, cf.candidates[0].cid, ACCEPTED)
    cf.review["state"] = "sealed"                  # forced, as a hand edit would
    with pytest.raises(ReviewIncomplete) as exc:
        kgrepair.reviewed_constraint_set(cf)
    assert "d.k.derived.aaaaaaaa" in str(exc.value)
    assert exc.value.cid == "d.k.derived.aaaaaaaa"


def test_refuses_a_file_whose_seal_no_longer_recomputes():
    cf = _sealed()
    cf.candidates[0].antecedent = "< down(ex:changed) >"   # edited after sealing
    assert not verify_seal(cf)
    with pytest.raises(SealMismatch) as exc:
        kgrepair.reviewed_constraint_set(cf)
    assert "E-SEAL" in str(exc.value)


def test_refuses_a_file_derived_from_a_different_graph():
    graph = kgrepair.load_graph(GEO)
    other = kgrepair.load_graph(TAXA)
    cf = _sealed(graph)
    with pytest.raises(SourceDrift) as exc:
        kgrepair.reviewed_constraint_set(cf, other)
    assert kgrepair.graph_content_hash(graph) in str(exc.value)
    assert kgrepair.graph_content_hash(other) in str(exc.value)


def test_drift_can_be_allowed_deliberately():
    graph, other = kgrepair.load_graph(GEO), kgrepair.load_graph(TAXA)
    cs = kgrepair.reviewed_constraint_set(_sealed(graph), other, allow_graph_drift=True)
    assert len(cs) == 1


def test_refuses_an_accepted_constraint_outside_the_fragment():
    """A reviewer can type anything into a JSON file, so the fragment check runs on
    load rather than trusting what derivation wrote."""
    cf = _sealed(candidates=[_candidate(consequent='! val("ex:C")')])
    with pytest.raises(OutOfFragment) as exc:
        kgrepair.reviewed_constraint_set(cf)
    assert cf.candidates[0].cid in str(exc.value)
    assert exc.value.cid == cf.candidates[0].cid


def test_refuses_a_boundary_tier_constraint_on_the_repair_path():
    cf = _sealed(candidates=[_candidate(tier="boundary")])
    with pytest.raises(BoundaryNotRepairable) as exc:
        kgrepair.reviewed_constraint_set(cf, for_repair=True)
    assert cf.candidates[0].cid in str(exc.value)
    # It still loads for validation, which is what boundary tier is for.
    assert len(kgrepair.reviewed_constraint_set(cf, for_repair=False)) == 1


def test_refuses_a_file_where_everything_was_rejected():
    cf = _file()
    kgrepair.set_status(cf, cf.candidates[0].cid, REJECTED)
    kgrepair.seal_candidates(cf, "a reviewer", sealed_at="2026-01-01T00:00:00Z")
    with pytest.raises(NothingAccepted) as exc:
        kgrepair.reviewed_constraint_set(cf)
    assert "E-EMPTY" in str(exc.value)


def test_sealing_refuses_while_anything_is_pending():
    cf = _file(candidates=[_candidate(), _candidate(cid="d.k.derived.bbbbbbbb",
                                                    antecedent="< down(ex:q) >")])
    kgrepair.set_status(cf, cf.candidates[0].cid, ACCEPTED)
    with pytest.raises(ValueError, match="pending"):
        kgrepair.seal_candidates(cf, "a reviewer")


def test_sealing_needs_a_reviewer_name():
    cf = _file()
    kgrepair.set_status(cf, cf.candidates[0].cid, ACCEPTED)
    with pytest.raises(ValueError, match="reviewer"):
        kgrepair.seal_candidates(cf, "   ")


def test_a_weakened_entry_loads_like_an_accepted_one():
    cf = _file()
    kgrepair.set_status(cf, cf.candidates[0].cid, WEAKENED, note="broadened the class")
    kgrepair.seal_candidates(cf, "a reviewer", sealed_at="2026-01-01T00:00:00Z")
    cs = kgrepair.reviewed_constraint_set(cf)
    assert len(cs) == 1 and list(cs)[0].note == "broadened the class"


# ---------- there is no way round the gate ----------------------------------

def test_no_score_however_high_can_authorise_a_repair():
    """The point of the whole module. A candidate with perfect evidence is still
    pending, and pending still cannot repair."""
    cand = _candidate(evidence={"support": 10000, "confidence": 1.0})
    cf = _file(candidates=[cand])
    assert cf.candidates[0].status == PENDING
    with pytest.raises(NotSealed):
        kgrepair.reviewed_constraint_set(cf)


def test_derivation_never_returns_anything_already_accepted():
    graph = kgrepair.load_graph(GEO)
    cf = kgrepair.derive_candidate_file(graph, "geography", "wikidata",
                                    config=DeriveConfig(min_support=8,
                                                        min_pca_confidence=0.95),
                                    dataset="geo", measure=False)
    assert cf.candidates, "expected the fixture to yield candidates"
    assert all(c.status == PENDING for c in cf.candidates)
    assert not cf.sealed


# ---------- T2 support: derivation output shape and determinism -------------

def test_two_derive_runs_produce_byte_identical_files():
    graph = kgrepair.load_graph(GEO)
    cfg = DeriveConfig(min_support=8, min_pca_confidence=0.95)
    first = kgrepair.derive_candidate_file(graph, "geography", "wikidata", config=cfg,
                                       dataset="geo")
    second = kgrepair.derive_candidate_file(graph, "geography", "wikidata", config=cfg,
                                        dataset="geo")
    assert dumps_canonical(first) == dumps_canonical(second)


def test_on_a_real_slice_a_gloss_falls_back_to_bare_ids_and_still_carries_evidence():
    """A committed Level-0 slice carries no label predicate at all: the allow-lists
    drop every person-pointing and organisation-pointing predicate before the slice
    is written, and the display-name predicates go with them. So this is the
    fallback path, not the label path. What it checks is that a candidate derived
    from such a slice still reads as a sentence, still carries its evidence and its
    impact, and names its class and predicate by their bare ids rather than
    crashing or inventing a name.

    The label path itself is covered by
    `test_labels_are_used_for_witnesses_where_the_graph_has_them`, on a graph built
    to carry labels."""
    from kgrepair.proposals import build_label_index
    graph = kgrepair.load_graph(GEO)
    assert build_label_index(graph) == {}, (
        "this slice now carries labels, so it no longer exercises the fallback this "
        "test is about; point it at a slice that carries none")

    cf = kgrepair.derive_candidate_file(graph, "geography", "wikidata",
                                        config=DeriveConfig(min_support=8,
                                                            min_pca_confidence=0.95),
                                        dataset="geo")
    assert cf.candidates, "expected the fixture to yield candidates"
    for c in cf.candidates:
        assert c.gloss and "<" not in c.gloss      # a sentence, not path syntax
        # the bare id, unlabelled, is what a gloss over this slice has to show
        named = c.evidence.get("class") or c.evidence.get("predicate")
        assert named is None or named in c.gloss
        assert c.evidence.get("support") is not None
        assert c.evidence.get("confidence") is not None
        assert "witnesses" in c.impact
        assert c.impact["witnesses"] >= len(c.witness_sample)


def test_review_order_leads_with_the_consequential_entries():
    """witnesses * (1 - confidence): a settled rule ranks low however many nodes
    break it, because there is little for a reviewer to weigh."""
    from kgrepair.proposals import review_rank
    assert review_rank({"witnesses": 100}, 1.0) == 0.0
    assert review_rank({"witnesses": 100}, 0.9) > review_rank({"witnesses": 10}, 0.9)
    assert review_rank({"witnesses": 10}, 0.5) > review_rank({"witnesses": 10}, 0.9)


def test_the_stability_gate_drops_a_rule_that_only_holds_on_one_graph():
    graph, reference = kgrepair.load_graph(GEO), kgrepair.load_graph(TAXA)
    cfg = DeriveConfig(min_support=5, min_pca_confidence=0.9)
    loose = kgrepair.derive_candidate_file(graph, "geography", "wikidata", config=cfg,
                                       reference_graph=reference, dataset="geo",
                                       stability_delta=1.0, measure=False)
    strict = kgrepair.derive_candidate_file(graph, "geography", "wikidata", config=cfg,
                                        reference_graph=reference, dataset="geo",
                                        stability_delta=0.0, measure=False)
    assert len(strict.candidates) < len(loose.candidates)
    for c in loose.candidates:
        assert "reference_confidence" in c.evidence
        assert "confidence_gap" in c.evidence


# ---------- T5: readable glosses and witness samples ------------------------

def test_labels_are_used_for_witnesses_where_the_graph_has_them():
    """The project's own Level-0 slices carry no label predicates, so this uses a
    graph that does. Where a label exists it is shown; where none does, the id is
    shown rather than something invented.

    This is the only place the label path is exercised at all, so the first
    assertion guards the graph itself: if it ever stops carrying a label the test
    has to say so, rather than quietly falling through to the id branch and still
    passing."""
    from kgrepair.proposals import build_label_index, display_name
    graph = kgrepair.load_graph_string(
        '<ex:a> <rdfs:label> "Buenos Aires" .\n<ex:a> <ex:p> <ex:b> .\n')
    labels = build_label_index(graph)
    assert labels, (
        "the graph in this test no longer carries a label the index recognises, so "
        "nothing here exercises the label path any more. Either restore a predicate "
        "from proposals.DEFAULT_LABEL_PREDICATES on <ex:a>, or move this test to "
        "whatever the label predicates now are.")
    assert display_name("ex:a", labels) == "Buenos Aires"
    assert display_name("ex:b", labels) == "ex:b"


def test_a_gloss_reads_as_a_sentence_not_as_path_syntax():
    from kgrepair.proposals import gloss_for
    text = gloss_for("existential_domain", cls="ex:City", predicate="ex:country",
                     labels={"ex:City": "city", "ex:country": "country"})
    assert text == "anything with an outgoing country edge should be city"
    for token in ("down(", "up(", "val(", "<", ">", "*"):
        assert token not in text


# ---------- P4b/T4: impact is deferred, and a null impact still works ---------

def test_a_derive_run_leaves_the_engine_numbers_uncomputed():
    """Impact is the expensive half of a derivation: on the ladder in
    `docs/performance.md` the two engine runs are 95 to 99 percent of the total,
    and the cost per candidate tracks its witness count. So a derive run records
    the witness count, which is one evaluation, and leaves the engine numbers null
    until someone looks at the entry."""
    graph = kgrepair.load_graph(GEO)
    cf = kgrepair.derive_candidate_file(graph, "geography", "wikidata",
                                        config=DeriveConfig(min_support=8,
                                                            min_pca_confidence=0.95),
                                        dataset="geo")
    assert cf.candidates
    for c in cf.candidates:
        assert c.impact["measured"] is False
        assert c.impact["subset_deletions"] is None
        assert c.impact["superset_additions"] is None
        assert c.impact["witnesses"] is not None       # one evaluation, kept
        assert c.impact["witnesses"] >= len(c.witness_sample)


def test_an_unmeasured_impact_still_seals_and_still_repairs(tmp_path):
    """T4's gate. Nothing downstream of derivation reads the engine numbers, so a
    file whose impact was never computed goes through review, sealing and repair
    exactly like one whose impact was."""
    graph = kgrepair.load_graph(GEO)
    cf = kgrepair.derive_candidate_file(graph, "geography", "wikidata",
                                        config=DeriveConfig(min_support=8,
                                                            min_pca_confidence=0.95),
                                        dataset="geo")
    assert all(c.impact["measured"] is False for c in cf.candidates)

    for cand in cf.candidates:
        kgrepair.set_status(cf, cand.cid, ACCEPTED)
    kgrepair.seal_candidates(cf, "a reviewer", sealed_at="2026-01-01T00:00:00Z")
    assert cf.sealed and verify_seal(cf)

    path = str(tmp_path / "c.json")
    kgrepair.write_canonical(cf, path)
    back = kgrepair.read_candidate_file(path)
    assert verify_seal(back)

    cs = kgrepair.reviewed_constraint_set(back, graph, for_repair=True)
    assert len(cs) == len(cf.accepted())
    result = kgrepair.superset_repair(graph, cs)
    assert result.attestations["superset_only_added"] is True


def test_filling_an_impact_computes_it_once_and_leaves_it_alone_after():
    graph = kgrepair.load_graph(GEO)
    cf = kgrepair.derive_candidate_file(graph, "geography", "wikidata",
                                        config=DeriveConfig(min_support=8,
                                                            min_pca_confidence=0.95),
                                        dataset="geo")
    cand = cf.candidates[0]
    filled = kgrepair.fill_impact(graph, cand)
    assert filled["measured"] is True
    assert filled["subset_deletions"] is not None or "subset_note" in filled
    assert filled["superset_additions"] is not None or "superset_note" in filled

    cand.impact["superset_additions"] = 12345          # a marker, to prove no recompute
    assert kgrepair.fill_impact(graph, cand)["superset_additions"] == 12345
    assert kgrepair.fill_impact(graph, cand, force=True)["superset_additions"] != 12345


def test_the_seal_does_not_cover_the_impact_numbers():
    """Filling an impact after sealing must not invalidate the seal: the seal is
    over the decisions and the expressions, which is what a reviewer decided on,
    and impact is a measurement of the graph rather than part of the rule."""
    graph = kgrepair.load_graph(GEO)
    cf = kgrepair.derive_candidate_file(graph, "geography", "wikidata",
                                        config=DeriveConfig(min_support=8,
                                                            min_pca_confidence=0.95),
                                        dataset="geo")
    for cand in cf.candidates:
        kgrepair.set_status(cf, cand.cid, ACCEPTED)
    kgrepair.seal_candidates(cf, "a reviewer", sealed_at="2026-01-01T00:00:00Z")

    kgrepair.fill_impact(graph, cf.candidates[0])
    assert verify_seal(cf), "measuring impact must not break the seal"
    assert len(kgrepair.reviewed_constraint_set(cf, graph)) == len(cf.accepted())
