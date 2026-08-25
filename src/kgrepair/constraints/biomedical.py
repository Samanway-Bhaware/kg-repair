"""
D2 -- Biomedical constraints (Wikidata only; DBpedia partial, YAGO none by design).

Three Level-0 concept slices -- these are abstract medical *concepts*, never
patient data, and the person/organisation edges are dropped upstream by the D1
allow-lists. Safety-critical edges (disease treated-by, medication interaction)
are kept but the corresponding rules are boundary/report-only and their outputs
are aggregate-only.

Anatomy    : P361 part-of, P527 has-part, P2289 connected-to* / develops-from.
Disease    : P279 subclass, P780 symptoms, P828 has-cause, P276 location,
             P2176 drug-used-for-treatment.
Medication : P2175 medical-condition-treated, P769 significant-drug-interaction,
             P636 route-of-administration, P279 subclass. (Relational edges only,
             to avoid the chemical-compound literal trap.)
"""
from __future__ import annotations

from .model import Constraint, ConstraintSet

WD_ANAT = "wd:Q4936952"       # anatomical structure
WD_DISEASE = "wd:Q12136"      # disease
WD_MED = "wd:Q12140"          # medication


def _wd_type(class_value: str) -> str:
    return f'< down(wdt:P31) . down(wdt:P279)* . [val("{class_value}")] >'


def wikidata_anatomy() -> ConstraintSet:
    cs = ConstraintSet("anatomy@wikidata")
    cs.add(Constraint(
        cid="ana.wd.dom.partof",
        domain="anatomy", kg="wikidata", kind="existential_domain",
        tier="ptime_core", provenance="compiled", direction="subset",
        antecedent="< down(wdt:P361) >",
        consequent=_wd_type(WD_ANAT),
        note="Subject of an anatomical part-of edge is an anatomical structure.",
    ))
    cs.add(Constraint(
        cid="ana.wd.rng.partof",
        domain="anatomy", kg="wikidata", kind="existential_range",
        tier="ptime_core", provenance="compiled", direction="subset",
        antecedent="< up(wdt:P361) >",
        consequent=_wd_type(WD_ANAT),
        note="Value of an anatomical part-of edge is an anatomical structure.",
    ))
    cs.add(Constraint(
        cid="ana.wd.inv.part_haspart",
        domain="anatomy", kg="wikidata", kind="inverse",
        tier="boundary", provenance="given", direction="report",
        antecedent="< down(wdt:P361) >",           # x part-of y
        consequent="< up(wdt:P527) >",             # y has-part x
        note="P361 part-of is inverse of P527 has-part; report only.",
    ))
    return cs


def wikidata_disease() -> ConstraintSet:
    cs = ConstraintSet("disease@wikidata")
    cs.add(Constraint(
        cid="dis.wd.dom.symptom",
        domain="disease", kg="wikidata", kind="existential_domain",
        tier="ptime_core", provenance="compiled", direction="subset",
        antecedent="< down(wdt:P780) >",           # has symptoms
        consequent=_wd_type(WD_DISEASE),
        note="Subject of P780 (symptoms) is a disease.",
    ))
    cs.add(Constraint(
        cid="dis.wd.req.cause_or_symptom",
        domain="disease", kg="wikidata", kind="requires_statement",
        tier="ptime_core", provenance="derived", direction="superset",
        antecedent=_wd_type(WD_DISEASE),
        consequent="< down(wdt:P780) > | < down(wdt:P828) >",
        note="A disease should state at least a symptom or a cause "
             "(disjunctive existential consequent).",
        params={"threshold": "0.98", "reference": "clean-wikidata-disease-slice"},
    ))
    cs.add(Constraint(
        cid="dis.wd.safety.treatedby",
        domain="disease", kg="wikidata", kind="safety_edge",
        tier="boundary", provenance="given", direction="report",
        antecedent="< down(wdt:P2176) >",          # drug used for treatment
        consequent="T",
        note="Safety-critical treated-by edge: report AGGREGATE COUNTS ONLY, "
             "never auto-repair.",
        params={"reporting": "aggregate_only"},
    ))
    return cs


def wikidata_medication() -> ConstraintSet:
    cs = ConstraintSet("medication@wikidata")
    cs.add(Constraint(
        cid="med.wd.dom.treats",
        domain="medication", kg="wikidata", kind="existential_domain",
        tier="ptime_core", provenance="compiled", direction="subset",
        antecedent="< down(wdt:P2175) >",          # medical-condition-treated
        consequent=_wd_type(WD_MED),
        note="Subject of P2175 (condition treated) is a medication.",
    ))
    cs.add(Constraint(
        cid="med.wd.rng.treats",
        domain="medication", kg="wikidata", kind="existential_range",
        tier="ptime_core", provenance="compiled", direction="subset",
        antecedent="< up(wdt:P2175) >",
        consequent=_wd_type(WD_DISEASE),
        note="Value of P2175 (condition treated) is a disease.",
    ))
    cs.add(Constraint(
        cid="med.wd.req.route",
        domain="medication", kg="wikidata", kind="requires_statement",
        tier="ptime_core", provenance="derived", direction="superset",
        antecedent=_wd_type(WD_MED),
        consequent="< down(wdt:P636) >",           # route of administration
        note="A medication should state a route of administration.",
        params={"threshold": "0.98", "reference": "clean-wikidata-med-slice"},
    ))
    cs.add(Constraint(
        cid="med.wd.safety.interaction",
        domain="medication", kg="wikidata", kind="safety_edge",
        tier="boundary", provenance="given", direction="report",
        antecedent="< down(wdt:P769) >",           # significant drug interaction
        consequent="< up(wdt:P769) >",
        note="Drug-interaction is symmetric AND safety-critical: report aggregate "
             "counts only, never auto-repair.",
        params={"reporting": "aggregate_only"},
    ))
    return cs


def all_biomedical() -> dict:
    return {
        "anatomy": {"wikidata": wikidata_anatomy()},
        "disease": {"wikidata": wikidata_disease()},
        "medication": {"wikidata": wikidata_medication()},
    }
