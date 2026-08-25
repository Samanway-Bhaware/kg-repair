"""
D2 -- Taxa constraints (Wikidata + DBpedia full; YAGO partial, class-level).

Taxa exercise hierarchy + rank-typing + the paper's signature *inheritance*
shape  P31 . P279*  =>  P31  (type completion up the class tree), which is the
natural superset-repair showcase.

Predicates
  Wikidata: P31 instance-of, P279 subclass-of, P171 parent-taxon, P105 rank.
  DBpedia : rdf:type, rdfs:subClassOf, dbo:genus / dbo:family.
  YAGO    : rdf:type, rdfs:subClassOf (taxonomy lives here; predicates flagged
            partial pending dump confirmation).
"""
from __future__ import annotations

from .model import Constraint, ConstraintSet

WD_TAXON = "wd:Q16521"


def _wd_type(class_value: str) -> str:
    return f'< down(wdt:P31) . down(wdt:P279)* . [val("{class_value}")] >'


def wikidata_taxa() -> ConstraintSet:
    cs = ConstraintSet("taxa@wikidata")

    # inheritance / type completion: instance-of a class whose superclass is Taxon
    cs.add(Constraint(
        cid="tax.wd.inherit.taxon",
        domain="taxa", kg="wikidata", kind="typing_inheritance",
        tier="ptime_core", provenance="compiled", direction="superset",
        antecedent='< down(wdt:P31) . down(wdt:P279)* . [val("' + WD_TAXON + '")] >',
        consequent='< down(wdt:P31) . [val("' + WD_TAXON + '")] >',
        note="If x is instance-of some subclass of Taxon, materialise the direct "
             "instance-of Taxon edge (P31.P279* => P31).",
    ))
    cs.add(Constraint(
        cid="tax.wd.dom.parent",
        domain="taxa", kg="wikidata", kind="existential_domain",
        tier="ptime_core", provenance="compiled", direction="subset",
        antecedent="< down(wdt:P171) >",           # has a parent-taxon edge
        consequent=_wd_type(WD_TAXON),             # must be a taxon
        note="Subject of P171 (parent taxon) must be a taxon.",
    ))
    cs.add(Constraint(
        cid="tax.wd.rng.parent",
        domain="taxa", kg="wikidata", kind="existential_range",
        tier="ptime_core", provenance="compiled", direction="subset",
        antecedent="< up(wdt:P171) >",             # is a parent-taxon value
        consequent=_wd_type(WD_TAXON),
        note="Value of P171 (parent taxon) must be a taxon.",
    ))
    cs.add(Constraint(
        cid="tax.wd.req.rank",
        domain="taxa", kg="wikidata", kind="requires_statement",
        tier="ptime_core", provenance="given", direction="superset",
        antecedent=_wd_type(WD_TAXON),
        consequent="< down(wdt:P105) >",           # requires a rank
        note="P2302: every taxon requires a taxon rank (P105).",
    ))
    cs.add(Constraint(
        cid="tax.wd.func.parent",
        domain="taxa", kg="wikidata", kind="functional",
        tier="boundary", provenance="given", direction="report",
        antecedent="< down(wdt:P171) >",
        consequent="T",
        note="A taxon has a single parent taxon; upper-bound needs negation.",
    ))
    return cs


def _dbo_type(class_value: str) -> str:
    return f'< down(rdf:type) . down(rdfs:subClassOf)* . [val("{class_value}")] >'


def dbpedia_taxa() -> ConstraintSet:
    cs = ConstraintSet("taxa@dbpedia")
    cs.add(Constraint(
        cid="tax.db.dom.genus",
        domain="taxa", kg="dbpedia", kind="existential_domain",
        tier="ptime_core", provenance="given", direction="subset",
        antecedent="< down(dbo:genus) >",
        consequent=_dbo_type("dbo:Species"),
        note="rdfs:domain of dbo:genus is dbo:Species.",
    ))
    cs.add(Constraint(
        cid="tax.db.type.species",
        domain="taxa", kg="dbpedia", kind="typing_existence",
        tier="ptime_core", provenance="derived", direction="superset",
        antecedent="< down(dbo:genus) > & < down(dbo:family) >",
        consequent=_dbo_type("dbo:Species"),
        note="Entities with genus+family are typed Species.",
        params={"threshold": "0.98", "reference": "clean-dbpedia-species-slice"},
    ))
    return cs


def yago_taxa() -> ConstraintSet:
    """PARTIAL: YAGO taxa live in the subClassOf taxonomy; predicates flagged
    pending dump confirmation (unresolved pending a dump check)."""
    cs = ConstraintSet("taxa@yago[partial]")
    cs.add(Constraint(
        cid="tax.yg.inherit.taxon",
        domain="taxa", kg="yago", kind="typing_inheritance",
        tier="ptime_core", provenance="compiled", direction="superset",
        antecedent='< down(rdf:type) . down(rdfs:subClassOf)* . [val("schema:Taxon")] >',
        consequent='< down(rdf:type) . [val("schema:Taxon")] >',
        note="PARTIAL slice: class-level taxonomy only; confirm predicates from dump.",
        params={"status": "partial", "confirm": "yago-4.5-dump"},
    ))
    return cs


def all_taxa() -> dict:
    return {
        "wikidata": wikidata_taxa(),
        "dbpedia": dbpedia_taxa(),
        "yago": yago_taxa(),
    }
