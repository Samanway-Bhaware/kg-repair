"""
D2 -- Geography constraints (available across all three KGs).

Constraint shapes exercised here:
  * existential domain/range  (ptime_core, given/compiled)
  * typing existence          (ptime_core, derived)   -- type completion
  * requires-statement        (ptime_core, given)     -- P2302 style
  * symmetry / inverse / functional (boundary)        -- reported only

Predicates
  Wikidata: P31 instance-of, P279 subclass-of, P17 country, P131 located-in,
            P47 shares-border-with (sym), P36 capital, P1376 capital-of (inv).
  DBpedia : rdf:type, rdfs:subClassOf, dbo:country, dbo:location,
            dbo:... (domain/range from rdfs).
  YAGO    : rdf:type, rdfs:subClassOf, schema:containedInPlace, SHACL shapes.
"""
from __future__ import annotations

from .model import Constraint, ConstraintSet

# class value constants (the [C=] endpoints)
WD_GEO = "wd:Q2221906"        # geographic location
WD_CITY = "wd:Q515"           # city
WD_COUNTRY = "wd:Q6256"       # country


def _wd_type(class_value: str) -> str:
    # tau_C = < down(P31) . down(P279)* . [val(C)] >
    return f'< down(wdt:P31) . down(wdt:P279)* . [val("{class_value}")] >'


def wikidata_geography() -> ConstraintSet:
    cs = ConstraintSet("geography@wikidata")

    cs.add(Constraint(
        cid="geo.wd.dom.country",
        domain="geography", kg="wikidata", kind="existential_domain",
        tier="ptime_core", provenance="compiled", direction="subset",
        antecedent="< down(wdt:P17) >",              # subject of a country edge
        consequent=_wd_type(WD_GEO),                 # must be a geographic entity
        note="Every subject of P17 (country) is a geographic location.",
    ))
    cs.add(Constraint(
        cid="geo.wd.rng.country",
        domain="geography", kg="wikidata", kind="existential_range",
        tier="ptime_core", provenance="compiled", direction="subset",
        antecedent="< up(wdt:P17) >",                # target of a country edge
        consequent=_wd_type(WD_COUNTRY),             # must be a country
        note="Every value of P17 (country) is a country.",
    ))
    cs.add(Constraint(
        cid="geo.wd.type.city",
        domain="geography", kg="wikidata", kind="typing_existence",
        tier="ptime_core", provenance="derived", direction="superset",
        antecedent="< down(wdt:P17) > & < down(wdt:P131) >",  # looks like a city
        consequent=_wd_type(WD_CITY),                          # ...so type it City
        note="Entities with both country and located-in edges are typed City.",
        params={"threshold": "0.98", "reference": "clean-wikidata-city-slice"},
    ))
    cs.add(Constraint(
        cid="geo.wd.req.city_country",
        domain="geography", kg="wikidata", kind="requires_statement",
        tier="ptime_core", provenance="given", direction="superset",
        antecedent=_wd_type(WD_CITY),                # every City ...
        consequent="< down(wdt:P17) >",              # ... must state a country
        note="Wikidata P2302 'item requires statement': City requires P17.",
    ))

    # boundary constraints -- validated & reported, never repaired
    cs.add(Constraint(
        cid="geo.wd.sym.border",
        domain="geography", kg="wikidata", kind="symmetric",
        tier="boundary", provenance="given", direction="report",
        antecedent="< down(wdt:P47) >",
        consequent="< up(wdt:P47) >",
        note="P47 shares-border-with is symmetric; as a PATH constraint this "
             "pushes subset repair to NP-complete (Thm 11), so report only.",
    ))
    cs.add(Constraint(
        cid="geo.wd.inv.capital",
        domain="geography", kg="wikidata", kind="inverse",
        tier="boundary", provenance="given", direction="report",
        antecedent="< down(wdt:P36) >",
        consequent="< up(wdt:P1376) >",
        note="P36 capital is inverse of P1376 capital-of; report only.",
    ))
    cs.add(Constraint(
        cid="geo.wd.func.country",
        domain="geography", kg="wikidata", kind="functional",
        tier="boundary", provenance="given", direction="report",
        antecedent="< down(wdt:P17) >",
        consequent="T",
        note="P17 is single-value (functional); upper-bound needs negation, "
             "so report only (validated externally by counting successors).",
    ))
    return cs


def _dbo_type(class_value: str) -> str:
    return f'< down(rdf:type) . down(rdfs:subClassOf)* . [val("{class_value}")] >'


def dbpedia_geography() -> ConstraintSet:
    cs = ConstraintSet("geography@dbpedia")
    cs.add(Constraint(
        cid="geo.db.dom.country",
        domain="geography", kg="dbpedia", kind="existential_domain",
        tier="ptime_core", provenance="given", direction="subset",
        antecedent="< down(dbo:country) >",
        consequent=_dbo_type("dbo:Place"),
        note="rdfs:domain of dbo:country is dbo:Place.",
    ))
    cs.add(Constraint(
        cid="geo.db.rng.country",
        domain="geography", kg="dbpedia", kind="existential_range",
        tier="ptime_core", provenance="given", direction="subset",
        antecedent="< up(dbo:country) >",
        consequent=_dbo_type("dbo:Country"),
        note="rdfs:range of dbo:country is dbo:Country.",
    ))
    cs.add(Constraint(
        cid="geo.db.type.settlement",
        domain="geography", kg="dbpedia", kind="typing_existence",
        tier="ptime_core", provenance="derived", direction="superset",
        antecedent="< down(dbo:country) > & < down(dbo:location) >",
        consequent=_dbo_type("dbo:Settlement"),
        note="Infobox-derived places with country+location are typed Settlement.",
        params={"threshold": "0.98", "reference": "clean-dbpedia-place-slice"},
    ))
    cs.add(Constraint(
        cid="geo.db.sym.border",
        domain="geography", kg="dbpedia", kind="symmetric",
        tier="boundary", provenance="given", direction="report",
        antecedent="< down(dbo:neighboringMunicipality) >",
        consequent="< up(dbo:neighboringMunicipality) >",
        note="neighbouring-municipality is symmetric; report only.",
    ))
    return cs


def _yago_type(class_value: str) -> str:
    return f'< down(rdf:type) . down(rdfs:subClassOf)* . [val("{class_value}")] >'


def yago_geography() -> ConstraintSet:
    cs = ConstraintSet("geography@yago")
    cs.add(Constraint(
        cid="geo.yg.dom.containment",
        domain="geography", kg="yago", kind="existential_domain",
        tier="ptime_core", provenance="given", direction="subset",
        antecedent="< down(schema:containedInPlace) >",
        consequent=_yago_type("schema:Place"),
        note="SHACL: subject of containedInPlace is a schema:Place.",
    ))
    cs.add(Constraint(
        cid="geo.yg.rng.containment",
        domain="geography", kg="yago", kind="existential_range",
        tier="ptime_core", provenance="given", direction="subset",
        antecedent="< up(schema:containedInPlace) >",
        consequent=_yago_type("schema:Place"),
        note="SHACL: value of containedInPlace is a schema:Place.",
    ))
    cs.add(Constraint(
        cid="geo.yg.req.country",
        domain="geography", kg="yago", kind="requires_statement",
        tier="ptime_core", provenance="given", direction="superset",
        antecedent=_yago_type("schema:City"),
        consequent="< down(schema:containedInPlace) >",
        note="SHACL sh:minCount 1 on containedInPlace for City.",
    ))
    return cs


def all_geography() -> dict:
    return {
        "wikidata": wikidata_geography(),
        "dbpedia": dbpedia_geography(),
        "yago": yago_geography(),
    }
