"""
D7/C1 -- constraints v2 (RC1/RC2 fixes) test suite -- additive to test_toolkit.py.

Gates:
  * version discipline: v1 biomedical constraints are byte-identical to the golden
    snapshot captured before v2 existed -- v1 stays permanently reproducible.
  * false-positive fixtures: a v1-only witness (anatomy cross-domain P361 reuse;
    disease/medication meta-class idiom) is NOT a witness under v2.
  * true-positive fixtures: a genuine violation is caught by BOTH v1 and v2 (narrow,
    don't blind).
"""
import json
import os

from kgrepair import constraints
from kgrepair.datagraph import DataGraph
from kgrepair.repair import superset_repair
from kgrepair.validator import Validator


FIXTURES = os.path.join(os.path.dirname(__file__), "..", "fixtures")

# ---------- version discipline -----------------------------------------------

def test_v1_biomedical_constraints_are_byte_identical_to_golden():
    golden = json.load(open(os.path.join(FIXTURES, "constraints_v1_biomedical_golden.json")))
    for domain in ("anatomy", "disease", "medication"):
        cs = constraints.get(domain, "wikidata", version=1)
        current = [c.to_dict() for c in cs]
        assert current == golden[domain], f"{domain} v1 constraints changed -- v1 must stay frozen"


def test_v1_default_and_explicit_are_identical():
    for domain in ("anatomy", "disease", "medication", "geography", "taxa"):
        default = constraints.get(domain, "wikidata")
        explicit = constraints.get(domain, "wikidata", version=1)
        assert [c.to_dict() for c in default] == [c.to_dict() for c in explicit]


def test_v2_falls_back_to_v1_for_untouched_domains():
    for domain in ("geography", "taxa"):
        v1 = constraints.get(domain, "wikidata", version=1)
        v2 = constraints.get(domain, "wikidata", version=2)
        assert [c.to_dict() for c in v1] == [c.to_dict() for c in v2]


def test_v2_sets_are_version_stamped_and_v1_preserved_alongside():
    for domain in ("anatomy", "disease", "medication"):
        v2 = constraints.get(domain, "wikidata", version=2)
        core_v2 = [c for c in v2 if c.tier == "ptime_core"]
        assert core_v2 and all(c.version == 2 for c in core_v2)
        assert all(c.cid.endswith(".v2") for c in core_v2)
        # boundary constraints ride along unchanged (still version 1, original cid)
        boundary_v2 = [c for c in v2 if c.tier == "boundary"]
        v1 = constraints.get(domain, "wikidata", version=1)
        boundary_v1 = [c for c in v1 if c.tier == "boundary"]
        assert [c.cid for c in boundary_v2] == [c.cid for c in boundary_v1]
        assert all(c.version == 1 for c in boundary_v2)


# ---------- RC1: anatomy cross-domain P361 reuse ------------------------------

def _anat_v2_dom():
    cs = constraints.get("anatomy", "wikidata", version=2)
    return next(c for c in cs if c.cid == "ana.wd.dom.partof.v2")


def _anat_v1_dom():
    cs = constraints.get("anatomy", "wikidata", version=1)
    return next(c for c in cs if c.cid == "ana.wd.dom.partof")


def test_rc1_false_positive_geographic_reuse_of_p361_is_fixed():
    """'Eastern Japan -P361-> Japan' style: v1 wrongly flags/repairs it as anatomical;
    v2's antecedent narrowing (target must satisfy the widened anatomy test) excludes it."""
    g = DataGraph()
    g.set_value("wd:Q6256", "wd:Q6256")               # country class
    g.add_edge("wd:Japan", "wdt:P31", "wd:Q6256")      # Japan is a country, not anatomy
    g.add_edge("wd:EasternJapan", "wdt:P361", "wd:Japan")  # geographic part-of reuse

    v1_witnesses = Validator(g).check_one(_anat_v1_dom()).witnesses
    v2_witnesses = Validator(g).check_one(_anat_v2_dom()).witnesses
    assert "wd:EasternJapan" in v1_witnesses, "v1 should (wrongly) flag the geo entity"
    assert "wd:EasternJapan" not in v2_witnesses, "v2 must exclude the geo entity"


def test_rc1_true_positive_direct_anatomical_target_still_caught_by_both():
    """'Toe -P361-> Foot' with Foot directly typed anatomical: both versions must
    still catch the untyped Toe (narrow, don't blind)."""
    g = DataGraph()
    g.set_value("wd:Q4936952", "wd:Q4936952")          # anatomical structure class
    g.add_edge("wd:Foot", "wdt:P31", "wd:Q4936952")    # Foot IS anatomical
    g.add_edge("wd:Toe", "wdt:P361", "wd:Foot")        # Toe part-of Foot, Toe untyped

    v1_witnesses = Validator(g).check_one(_anat_v1_dom()).witnesses
    v2_witnesses = Validator(g).check_one(_anat_v2_dom()).witnesses
    assert "wd:Toe" in v1_witnesses
    assert "wd:Toe" in v2_witnesses


def test_rc2_anatomy_meta_class_idiom_already_consistent_under_v2_only():
    """'Heart' already typed via the traced 'organ type' meta-class idiom, and its
    P361 target is directly anatomical: v1 (no meta-class awareness) wrongly flags
    Heart and would add a redundant/wrong direct type; v2 recognises it as already
    consistent."""
    g = DataGraph()
    g.set_value("wd:Q4936952", "wd:Q4936952")
    g.set_value("wd:Q103812529", "wd:Q103812529")       # 'organ type' meta-class
    g.add_edge("wd:SomeAnatomicalThing", "wdt:P31", "wd:Q4936952")
    g.add_edge("wd:Heart", "wdt:P361", "wd:SomeAnatomicalThing")
    g.add_edge("wd:Heart", "wdt:P31", "wd:Q103812529")  # meta-class-typed, not direct

    v1_witnesses = Validator(g).check_one(_anat_v1_dom()).witnesses
    v2_witnesses = Validator(g).check_one(_anat_v2_dom()).witnesses
    assert "wd:Heart" in v1_witnesses, "v1 should (wrongly) flag the meta-typed entity"
    assert "wd:Heart" not in v2_witnesses, "v2 must recognise the meta-class idiom"


# ---------- RC2: disease "type of disease" meta-class idiom -------------------

def _disease_v2_dom():
    cs = constraints.get("disease", "wikidata", version=2)
    return next(c for c in cs if c.cid == "dis.wd.dom.symptom.v2")


def _disease_v1_dom():
    cs = constraints.get("disease", "wikidata", version=1)
    return next(c for c in cs if c.cid == "dis.wd.dom.symptom")


def test_rc2_disease_meta_class_idiom_is_fixed():
    g = DataGraph()
    g.set_value("wd:Q112193867", "wd:Q112193867")       # 'type of disease' meta-class
    g.add_edge("wd:Headache", "wdt:P780", "wd:SomeSymptom")
    g.add_edge("wd:Headache", "wdt:P31", "wd:Q112193867")

    v1_witnesses = Validator(g).check_one(_disease_v1_dom()).witnesses
    v2_witnesses = Validator(g).check_one(_disease_v2_dom()).witnesses
    assert "wd:Headache" in v1_witnesses
    assert "wd:Headache" not in v2_witnesses


def test_rc2_disease_true_positive_untyped_still_caught_by_both():
    g = DataGraph()
    g.add_edge("wd:Flu", "wdt:P780", "wd:Fever")        # Flu has a symptom, untyped

    v1_witnesses = Validator(g).check_one(_disease_v1_dom()).witnesses
    v2_witnesses = Validator(g).check_one(_disease_v2_dom()).witnesses
    assert "wd:Flu" in v1_witnesses and "wd:Flu" in v2_witnesses

    # and the repair planner still adds the direct disease type for a true positive
    cs2 = constraints.get("disease", "wikidata", version=2)
    res = superset_repair(g, cs2, in_place=False)
    added = {(r.src, r.dst) for r in res.changelog if r.op == "add_edge"}
    assert ("wd:Flu", "wd:Q12136") in added


def test_rc2_disease_symptom_or_sign_is_deliberately_not_folded_in():
    """A pure 'symptom or sign'-typed entity (no 'type of disease' co-type) must NOT
    be treated as satisfying the disease consequent -- folding it in would let a
    genuine symptom be accepted as a disease."""
    g = DataGraph()
    g.set_value("wd:Q112965645", "wd:Q112965645")       # 'symptom or sign' only
    g.add_edge("wd:PureSymptom", "wdt:P780", "wd:SomethingElse")
    g.add_edge("wd:PureSymptom", "wdt:P31", "wd:Q112965645")

    v2_witnesses = Validator(g).check_one(_disease_v2_dom()).witnesses
    assert "wd:PureSymptom" in v2_witnesses, \
        "symptom-or-sign-only entities must remain flagged, not silently accepted as disease"


# ---------- RC2: medication chemical-entity meta-class family -----------------

def _med_v2_dom():
    cs = constraints.get("medication", "wikidata", version=2)
    return next(c for c in cs if c.cid == "med.wd.dom.treats.v2")


def _med_v1_dom():
    cs = constraints.get("medication", "wikidata", version=1)
    return next(c for c in cs if c.cid == "med.wd.dom.treats")


def test_rc2_medication_meta_class_family_is_fixed():
    g = DataGraph()
    g.set_value("wd:Q113145171", "wd:Q113145171")       # 'type of chemical entity'
    g.add_edge("wd:SomeDrug", "wdt:P2175", "wd:SomeCondition")
    g.add_edge("wd:SomeDrug", "wdt:P31", "wd:Q113145171")

    v1_witnesses = Validator(g).check_one(_med_v1_dom()).witnesses
    v2_witnesses = Validator(g).check_one(_med_v2_dom()).witnesses
    assert "wd:SomeDrug" in v1_witnesses
    assert "wd:SomeDrug" not in v2_witnesses


def test_rc2_medication_true_positive_untyped_still_caught_by_both():
    g = DataGraph()
    g.add_edge("wd:Aspirin", "wdt:P2175", "wd:Headache")

    v1_witnesses = Validator(g).check_one(_med_v1_dom()).witnesses
    v2_witnesses = Validator(g).check_one(_med_v2_dom()).witnesses
    assert "wd:Aspirin" in v1_witnesses and "wd:Aspirin" in v2_witnesses


def test_med_rng_treats_v2_reuses_the_disease_widening():
    """med.wd.rng.treats.v2's consequent is tau_Disease_v2 -- the SAME widening as
    dis.wd.dom.symptom.v2, since both reference the shared disease class test."""
    g = DataGraph()
    g.set_value("wd:Q112193867", "wd:Q112193867")
    g.add_edge("wd:SomeDrug", "wdt:P2175", "wd:MetaTypedCondition")
    g.add_edge("wd:MetaTypedCondition", "wdt:P31", "wd:Q112193867")

    cs2 = constraints.get("medication", "wikidata", version=2)
    rng_v2 = next(c for c in cs2 if c.cid == "med.wd.rng.treats.v2")
    witnesses = Validator(g).check_one(rng_v2).witnesses
    assert "wd:MetaTypedCondition" not in witnesses
