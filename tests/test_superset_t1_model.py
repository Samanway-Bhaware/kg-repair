"""
D6 · T1 -- constraint-model reframing.

Two guards:
  * `addition_fixable` capability derivation: every ptime_core constraint qualifies,
    no boundary constraint does; it is orthogonal to `direction`.
  * subset-invariance: subset_repair on the committed fixtures still produces the
    byte-for-byte identical (changelog, deleted set, rounds, attestations) captured
    in `fixtures/subset_repair_golden.json` -- the D6 work must not perturb Alg. 1.
"""
import json
import os

from kgrepair import constraints
from kgrepair.ntriples import load_ntriples_file
from kgrepair.repair import subset_repair


FIXTURES = os.path.join(os.path.dirname(__file__), "..", "fixtures")

_GOLDEN_CELLS = {
    "synthetic_geography_wd.nt": ("geography", "wikidata"),
    "synthetic_anatomy_wd.nt": ("anatomy", "wikidata"),
    "synthetic_disease_wd.nt": ("disease", "wikidata"),
}


# ---------- addition_fixable capability --------------------------------------

def test_addition_fixable_is_exactly_ptime_core():
    for domain, kg in {("geography", "wikidata"), ("taxa", "wikidata"),
                       ("anatomy", "wikidata"), ("medication", "wikidata")}:
        cs = constraints.get(domain, kg)
        for c in cs:
            assert c.addition_fixable == (c.tier == "ptime_core"), c.cid
        # at least one of each so the assertion is non-vacuous
        assert any(c.addition_fixable for c in cs)


def test_addition_fixable_orthogonal_to_direction():
    cs = constraints.get("geography", "wikidata")
    core = [c for c in cs if c.tier == "ptime_core"]
    # both subset- and superset-direction ptime_core rules are addition_fixable
    assert {c.direction for c in core} >= {"subset", "superset"}
    assert all(c.addition_fixable for c in core)
    # boundary rules (report direction) are never addition_fixable
    assert all(not c.addition_fixable for c in cs if c.tier == "boundary")


# ---------- subset-repair byte-for-byte invariance ---------------------------

def test_subset_repair_matches_frozen_golden():
    golden = json.load(open(os.path.join(FIXTURES, "subset_repair_golden.json")))
    for fx, (domain, kg) in _GOLDEN_CELLS.items():
        g = load_ntriples_file(os.path.join(FIXTURES, fx))
        res = subset_repair(g, constraints.get(domain, kg))
        exp = golden[fx]
        assert res.changelog_dicts() == exp["changelog"], fx
        assert sorted(res.deleted_nodes) == exp["deleted"], fx
        assert res.rounds == exp["rounds"], fx
        assert res.attestations == exp["attest"], fx
