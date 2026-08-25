"""
P2 fidelity: per-source RDF -> data-graph translation.

  * YAGO single-line-fact reader: parses plain facts, skips @directives and multi-line
    ;/, statements, handles <IRIs>, prefixed names, encoded chars, and literals.
  * Committed real slices (Wikidata/DBpedia geography 1k) round-trip through the loader
    with no parser errors, are Level-0 clean (deny-check), and validate.
"""
import os

from kgrepair import constraints
from kgrepair.ntriples import load_ntriples_file
from kgrepair.pipeline import deny_check, load_allowlist
from kgrepair.pipeline.yago_turtle import iter_single_line_facts
from kgrepair.validator import Validator


REAL = os.path.join(os.path.dirname(__file__), "..", "fixtures", "real")

_YAGO_SAMPLE = [
    "@prefix yago: <http://yago-knowledge.org/resource/> .",   # directive -> skip
    "# a comment -> skip",
    "yago:Aa_achalensis\trdf:type\tschema:Taxon\t.",
    "yago:Aa_achalensis\tschema:parentTaxon\tyago:Aa__u0028_plant_u0029_\t.",
    "yago:Berlin\tschema:location\tyago:Germany\t.",
    'yago:Berlin\tschema:alternateName\t"Berlin"@en\t.',       # literal object
    "schema:CreativeWork rdf:type rdfs:Class, sh:NodeShape ;",  # multi-line -> skip
    "\tys:fromClass wd:Q386724, wd:Q17537576 ;",               # continuation -> skip
    "\tsh:property ys:CreativeWork_property_21 .",              # 2-term end -> skip",
]


def test_yago_reader_parses_facts_skips_directives_and_multiline():
    facts = list(iter_single_line_facts(_YAGO_SAMPLE))
    triples = {(s, p, o) for s, p, o, _lit in facts}
    assert ("yago:Aa_achalensis", "rdf:type", "schema:Taxon") in triples
    assert ("yago:Aa_achalensis", "schema:parentTaxon", "yago:Aa__u0028_plant_u0029_") in triples
    assert ("yago:Berlin", "schema:location", "yago:Germany") in triples
    # literal object parsed with is_literal True and quotes stripped
    lits = [(s, p, o, lit) for s, p, o, lit in facts if lit]
    assert ("yago:Berlin", "schema:alternateName", "Berlin", True) in lits
    # directives, comments, and multi-line statements produced no triples
    assert all(not s.startswith(("@", "#", "schema:CreativeWork")) for s, _p, _o, _l in facts)
    assert len(facts) == 4


def _committed(name):
    path = os.path.join(REAL, name + ".nt")
    if not os.path.exists(path):
        return None
    return load_ntriples_file(path)


def test_committed_wikidata_slice_roundtrips_and_is_level0():
    g = _committed("real_wikidata_geography_1000")
    if g is None:
        return  # slice not built in this environment
    assert g.num_edges() > 0
    assert deny_check(g, load_allowlist("wikidata")) == []      # Level-0
    # class nodes valued so tau_C resolves; validation runs clean (violations fine)
    rep = Validator(g, use_closure=True).validate(constraints.get("geography", "wikidata"))
    assert rep is not None


def test_committed_dbpedia_slice_roundtrips_and_is_level0():
    g = _committed("real_dbpedia_geography_1000")
    if g is None:
        return
    assert g.num_edges() > 0
    assert deny_check(g, load_allowlist("dbpedia")) == []
    rep = Validator(g, use_closure=True).validate(constraints.get("geography", "dbpedia"))
    assert rep is not None
