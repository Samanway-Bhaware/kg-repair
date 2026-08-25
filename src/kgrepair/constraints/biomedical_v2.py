"""
D7/C1 -- constraints v2: fixes for the two root causes the D6/T5 plausibility trace
attributed to the constraint DEFINITIONS (not the repair engine).

v1 files (`biomedical.py`) are UNTOUCHED and remain independently loadable --
`constraints.get(domain, "wikidata", version=1)` always returns the original v1
ConstraintSet, so every existing number in `docs/real_repair.md` stays
reproducible forever. v2 lives only here.

Evidence base: `bench/trace_rc_shapes.py` re-traced the 279 D6/T5 "contradicted"
additions by CONSTRAINT ID (not just by cell -- a cell can host several constraints,
e.g. `medication_1000` hosts both `med.wd.dom.treats` and `med.wd.rng.treats`, which
share no class test and must not be conflated), batch-fetched each contradicted
entity's real `wdt:P31` targets, and tallied the observed classes. Full output:
`results/rc_shape_trace.json`. The exact shapes below are read off that tally, not
recalled from memory of Wikidata conventions (per the task's read-first rule).

## RC-anatomy (both `ana.wd.dom.partof` and `ana.wd.rng.partof`)

Traced 104 contradicted entities split roughly in two:
  * ~59 are genuinely anatomical, but Wikidata types them via a "class/type-of-X" meta-
    class idiom rather than a direct `wd:Q4936952` (anatomical structure) subclass:
    `wd:Q112826905` "class of anatomical entity" (32x), `wd:Q103812529` "organ type"
    (15x), `wd:Q104027169` "anatomical system type" (3x), `wd:Q103914748` "anatomical
    structure class type" (3x), `wd:Q113147985` "solitary organism subdivision type"
    (2x), `wd:Q139550381` "class of human anatomical entity" (2x), `wd:Q103843042`
    "organism subdivision type" (2x). This is the SAME idiom as RC-disease below,
    applied to anatomy -- a consequent-widening fix (RC2-style).
  * ~45 are genuinely NOT anatomical: `P361` ("part of") is a generic Wikidata property,
    and the frontier-BFS anatomy slice picked up geographic/administrative/financial
    reuse of it -- `wd:Q207520` "region of Japan" (12x total dom+rng), `wd:Q165` "sea"
    (5x), `wd:Q9430` "ocean" (3x), `wd:Q39594` "bay" (2x), `wd:Q82794` "region" (2x),
    `wd:Q327333` "government agency" (2x), `wd:Q151885` "concept" (2x), `wd:Q223371`
    "stock market index" (2x), `wd:Q11691` "stock exchange" (2x). This is an
    ANTECEDENT-scoping problem (RC1-style): the fix requires the OTHER endpoint of the
    `P361` edge to already satisfy the (widened) anatomy test, via a nested node-test in
    the path -- `< down(wdt:P361) . [tau_Anat_v2] >` for dom, `< up(wdt:P361) .
    [tau_Anat_v2] >` for rng (fragment-checked: both are Reg-GXPath_pos positive, no
    evaluator change). This is a genuine recall/precision trade-off, disclosed in
    `docs/constraints_v2.md`: an isolated pair of anatomical entities where NEITHER end
    is yet typed by anything (no other constraint, no meta-class) will not be caught in
    a single round under v2 where v1 would have (over-eagerly) caught it. In practice
    the set-at-a-time fixpoint still catches it as soon as either end is typed by ANY
    other constraint or meta-class match in an earlier round.

## RC-disease (`dis.wd.dom.symptom`, and via the shared class test, `med.wd.rng.treats`)

All 7 `dis.wd.dom.symptom` contradictions, and 99/103 `med.wd.rng.treats`
contradictions (the range side of medication reuses the SAME `tau_Disease` test),
are entities `wdt:P31`-typed `wd:Q112193867` "type of disease" -- Wikidata's
meta-class idiom for disease, never `P31.P279*`-reachable from `wd:Q12136` (disease)
itself. A minority also carry `wd:Q112965645` "symptom or sign" (fully overlapping the
"type of disease" set in this trace -- not a distinct case) or other one-off labels
("biological process", "Wikimedia permanent duplicate item", "medical finding" ...)
that are NOT the same idiom and are deliberately NOT folded in (folding in "symptom or
sign" would let a genuine symptom entity be typed a disease -- "narrow, don't blind").
Fix: widen the disease class test with ONE disjunct, `< down(wdt:P31) .
[val("wd:Q112193867")] >` (direct instance of "type of disease").

## RC-medication (`med.wd.dom.treats`)

All 11 contradictions are `wdt:P31`-typed one of `wd:Q113145171` "type of chemical
entity" (9x), `wd:Q119892838` "type of mixture of chemical entities" (1x), or
`wd:Q59199015` "group of stereoisomers" (1x) -- the same chemical-classification idiom
family, unlike anatomy's, with zero off-domain noise observed. Fix: widen the
medication class test with those three disjuncts.

## What is deliberately NOT touched

RC3 (geography-10k's ~52/120 contradictions, e.g. "canal" not `P279*`-reachable from
"geographic location") is a genuine ontology gap, not a constraint-definition defect --
recorded as evidence for the repair-semantics discussion, not "fixed" here. Geography and
taxa constraint files are untouched (no v2 stamp needed; `constraints.get(..., version=2)`
falls back to their v1 ConstraintSet). Boundary constraints in anatomy/disease/medication
are copied into the v2 sets unchanged (version=1) so `coverage()`/reporting stays complete.
"""
from __future__ import annotations

from .biomedical import WD_ANAT, WD_DISEASE, WD_MED, wikidata_anatomy, wikidata_disease, wikidata_medication
from .model import Constraint, ConstraintSet

# -- traced meta-class disjuncts (see module docstring for provenance) -------------

ANAT_META_CLASSES = (
    "wd:Q112826905",  # class of anatomical entity
    "wd:Q103812529",  # organ type
    "wd:Q104027169",  # anatomical system type
    "wd:Q103914748",  # anatomical structure class type
    "wd:Q113147985",  # solitary organism subdivision type
    "wd:Q139550381",  # class of human anatomical entity
    "wd:Q103843042",  # organism subdivision type
)
DISEASE_META_CLASSES = (
    "wd:Q112193867",  # type of disease
)
MEDICATION_META_CLASSES = (
    "wd:Q113145171",  # type of chemical entity
    "wd:Q119892838",  # type of mixture of chemical entities
    "wd:Q59199015",   # group of stereoisomers
)


def _wd_type(class_value: str) -> str:
    return f'< down(wdt:P31) . down(wdt:P279)* . [val("{class_value}")] >'


def _wd_type_v2(class_value: str, meta_classes) -> str:
    """tau_C widened with a union of direct-instance meta-class disjuncts (RC2)."""
    disjuncts = [_wd_type(class_value)]
    disjuncts += [f'< down(wdt:P31) . [val("{c}")] >' for c in meta_classes]
    return " | ".join(disjuncts)


TAU_ANAT_V2 = _wd_type_v2(WD_ANAT, ANAT_META_CLASSES)
TAU_DISEASE_V2 = _wd_type_v2(WD_DISEASE, DISEASE_META_CLASSES)
TAU_MED_V2 = _wd_type_v2(WD_MED, MEDICATION_META_CLASSES)


def _copy_unchanged(c: Constraint) -> Constraint:
    """Boundary/untouched constraints ride into the v2 set as-is (version=1)."""
    return Constraint(cid=c.cid, domain=c.domain, kg=c.kg, kind=c.kind, tier=c.tier,
                      provenance=c.provenance, direction=c.direction,
                      antecedent=c.antecedent, consequent=c.consequent,
                      note=c.note, params=dict(c.params), version=c.version)


def wikidata_anatomy_v2() -> ConstraintSet:
    cs = ConstraintSet("anatomy@wikidata.v2")
    cs.add(Constraint(
        cid="ana.wd.dom.partof.v2",
        domain="anatomy", kg="wikidata", kind="existential_domain",
        tier="ptime_core", provenance="compiled", direction="subset", version=2,
        antecedent=f"< down(wdt:P361) . [{TAU_ANAT_V2}] >",
        consequent=TAU_ANAT_V2,
        note="RC1+RC2 fix (D7/C1, results/rc_shape_trace.json): narrows the antecedent "
             "to require the P361 TARGET to already be (widened) anatomical -- excludes "
             "cross-domain P361 reuse (geographic/financial 'part of') -- and widens the "
             "consequent with 7 traced anatomy meta-classes (organ type, class of "
             "anatomical entity, ...). Supersedes ana.wd.dom.partof for the fix "
             "evaluation; v1 is untouched and independently loadable.",
        params={"fixes": "RC1,RC2", "baseline_cid": "ana.wd.dom.partof",
               "trace": "results/rc_shape_trace.json"},
    ))
    cs.add(Constraint(
        cid="ana.wd.rng.partof.v2",
        domain="anatomy", kg="wikidata", kind="existential_range",
        tier="ptime_core", provenance="compiled", direction="subset", version=2,
        antecedent=f"< up(wdt:P361) . [{TAU_ANAT_V2}] >",
        consequent=TAU_ANAT_V2,
        note="Symmetric analogue of ana.wd.dom.partof.v2: requires the P361 SOURCE to "
             "already be (widened) anatomical before flagging the target.",
        params={"fixes": "RC1,RC2", "baseline_cid": "ana.wd.rng.partof",
               "trace": "results/rc_shape_trace.json"},
    ))
    v1 = wikidata_anatomy()
    for c in v1:
        if c.tier == "boundary":
            cs.add(_copy_unchanged(c))
    return cs


def wikidata_disease_v2() -> ConstraintSet:
    cs = ConstraintSet("disease@wikidata.v2")
    cs.add(Constraint(
        cid="dis.wd.dom.symptom.v2",
        domain="disease", kg="wikidata", kind="existential_domain",
        tier="ptime_core", provenance="compiled", direction="subset", version=2,
        antecedent="< down(wdt:P780) >",
        consequent=TAU_DISEASE_V2,
        note="RC2 fix: widens the disease class test with the traced 'type of disease' "
             "meta-class idiom (wd:Q112193867) -- resolves 7/7 traced contradictions. "
             "Deliberately does NOT fold in 'symptom or sign' (wd:Q112965645): a symptom "
             "is not a disease, and every traced case already carries 'type of disease' "
             "too, so no case needs that inclusion (narrow, don't blind).",
        params={"fixes": "RC2", "baseline_cid": "dis.wd.dom.symptom",
               "trace": "results/rc_shape_trace.json"},
    ))
    cs.add(Constraint(
        cid="dis.wd.req.cause_or_symptom.v2",
        domain="disease", kg="wikidata", kind="requires_statement",
        tier="ptime_core", provenance="derived", direction="superset", version=2,
        antecedent=TAU_DISEASE_V2,
        consequent="< down(wdt:P780) > | < down(wdt:P828) >",
        note="Antecedent widened for consistency with dis.wd.dom.symptom.v2 -- 'is a "
             "disease' means the same thing everywhere in this constraint set.",
        params={"threshold": "0.98", "reference": "clean-wikidata-disease-slice",
               "fixes": "RC2 (consistency)", "baseline_cid": "dis.wd.req.cause_or_symptom"},
    ))
    v1 = wikidata_disease()
    for c in v1:
        if c.tier == "boundary":
            cs.add(_copy_unchanged(c))
    return cs


def wikidata_medication_v2() -> ConstraintSet:
    cs = ConstraintSet("medication@wikidata.v2")
    cs.add(Constraint(
        cid="med.wd.dom.treats.v2",
        domain="medication", kg="wikidata", kind="existential_domain",
        tier="ptime_core", provenance="compiled", direction="subset", version=2,
        antecedent="< down(wdt:P2175) >",
        consequent=TAU_MED_V2,
        note="RC2 fix: widens the medication class test with the traced chemical-entity "
             "meta-class family (wd:Q113145171/Q119892838/Q59199015) -- resolves 11/11 "
             "traced contradictions, zero off-domain noise observed for this constraint.",
        params={"fixes": "RC2", "baseline_cid": "med.wd.dom.treats",
               "trace": "results/rc_shape_trace.json"},
    ))
    cs.add(Constraint(
        cid="med.wd.rng.treats.v2",
        domain="medication", kg="wikidata", kind="existential_range",
        tier="ptime_core", provenance="compiled", direction="subset", version=2,
        antecedent="< up(wdt:P2175) >",
        consequent=TAU_DISEASE_V2,
        note="Reuses the SAME disease widening as dis.wd.dom.symptom.v2 (this "
             "constraint's consequent is tau_Disease, shared across domain files) -- "
             "resolves 99/103 traced contradictions; the remaining ~4 carry unrelated "
             "one-off labels (biological process, a Wikidata dedup marker, ...) that are "
             "NOT the disease idiom and are correctly left unresolved.",
        params={"fixes": "RC2", "baseline_cid": "med.wd.rng.treats",
               "trace": "results/rc_shape_trace.json"},
    ))
    cs.add(Constraint(
        cid="med.wd.req.route.v2",
        domain="medication", kg="wikidata", kind="requires_statement",
        tier="ptime_core", provenance="derived", direction="superset", version=2,
        antecedent=TAU_MED_V2,
        consequent="< down(wdt:P636) >",
        note="Antecedent widened for consistency with med.wd.dom.treats.v2.",
        params={"threshold": "0.98", "reference": "clean-wikidata-med-slice",
               "fixes": "RC2 (consistency)", "baseline_cid": "med.wd.req.route"},
    ))
    v1 = wikidata_medication()
    for c in v1:
        if c.tier == "boundary":
            cs.add(_copy_unchanged(c))
    return cs


def all_biomedical_v2() -> dict:
    return {
        "anatomy": {"wikidata": wikidata_anatomy_v2()},
        "disease": {"wikidata": wikidata_disease_v2()},
        "medication": {"wikidata": wikidata_medication_v2()},
    }
