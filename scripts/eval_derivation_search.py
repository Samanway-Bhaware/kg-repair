"""
P4c: evaluation of the two-axis derivation search (`src/kgrepair/search.py`).

Four questions, one per table:

  T1  does pruning lose anything above the confidence floor
  T2  does the search recover constraints a third party wrote
  T3  does a rule derived on one source hold on another
  T4  does it recover the authored sets, and what does it miss and why
  T5  does impact ordering save a reviewer effort against score ordering

Every number written here goes to `results/derivation_eval.jsonl` first, one record
per finding, each carrying the slice `content_hash` and the `code_revision` it was
produced under. The markdown tables under `eval/` are rendered from that file, so a
chapter cites an artifact rather than a transcribed number.

Reproducibility. No wall-clock is written into any record except the timing table,
where the measurement is the point; everything else is sorted and deterministic.
Runtimes are the one field that will differ between machines, and they are flagged
in the table itself.

Dependency note: matplotlib for the T5 figure, the same evaluation-tooling exception
`scripts/build_evaluation.py` already carries. `src/kgrepair/` stays stdlib-only.

Usage: python scripts/eval_derivation_search.py
"""
from __future__ import annotations

import json
import os
import sys
import time
from collections import Counter, defaultdict
from typing import Dict, List, Optional, Set, Tuple

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tests"))

from kgrepair import constraints as authored              # noqa: E402
from kgrepair.datagraph import DataGraph                  # noqa: E402
from kgrepair.instrument import code_revision             # noqa: E402
from kgrepair.ntriples import load_ntriples_file          # noqa: E402
from kgrepair.review import graph_content_hash            # noqa: E402
from kgrepair.search import (NOT_COMPARABLE, STABLE, UNSTABLE, Extensions,  # noqa: E402
                             NodeSpace, SearchConfig, Scored, assess_stability,
                             lead_text, search, vocabulary)
import reference_enumerator as ref                        # noqa: E402

ROOT = os.path.join(os.path.dirname(__file__), "..")
REAL = os.path.join(ROOT, "fixtures", "real")
EVAL_DIR = os.path.join(ROOT, "eval")
RESULTS = os.path.join(ROOT, "results")
JSONL_PATH = os.path.join(RESULTS, "derivation_eval.jsonl")
MD_PATH = os.path.join(EVAL_DIR, "derivation_search_evaluation.md")
JSON_PATH = os.path.join(EVAL_DIR, "derivation_search_evaluation.json")
FIGURE_PATH = os.path.join(ROOT, "docs", "figures", "fig5_reviewer_effort.png")
P2302_CACHE = os.path.join(ROOT, "data", "raw", "constraints", "wikidata_p2302.json")

#: The bounds every table uses, so the four questions are asked of one search.
CONFIG = SearchConfig(min_support=10, min_confidence=0.9, max_antecedent=2, max_path=2)

#: Small enough for the oracle to enumerate the whole space, which is what T1 needs.
ABLATION_SLICE = "real_wikidata_geography_1000"

CONFIDENCE_BANDS = ((0.9, 0.95), (0.95, 0.99), (0.99, 1.01))

#: The P2302 constraint types this fragment can state, and the shape each becomes.
#: Everything else is outside the fragment or outside what the search generates, and
#: is counted separately: conflating the two would report a modelling boundary as a
#: failure to find something.
EXPRESSIBLE = {
    "Q21503250": "domain",      # type constraint: subjects of P are of type C
    "Q21510865": "range",       # value-type constraint: objects of P are of type C
    "Q21503247": "requires",    # item-requires-statement: items with P also have Q
}
NOT_EXPRESSIBLE_REASON = {
    "Q21502838": "conflicts-with needs negation",
    "Q21510851": "allowed-qualifiers is about statement structure, not the graph",
    "Q52004125": "allowed-entity-types is about the entity model, not the graph",
    "Q53869507": "property-scope is about statement structure, not the graph",
    "Q52558054": "citation-needed is a sourcing rule, not a graph shape",
    "Q21510855": "allowed-units is about literals, which set repairs cannot touch",
    "Q25796498": "contemporary constraint compares time values",
    "Q21510859": "one-of enumerates allowed values; the search generates no value lists",
    "Q21510864": "value-requires-statement is a rule about the object, not the subject",
    "Q52060874": "allowed-qualifiers variant, as above",
    "Q21510862": "symmetric is a path constraint, boundary tier by Thm 11",
    "Q54554025": "single-best-value needs counting",
    "Q21502410": "distinct-values needs disequality",
    "Q19474404": "single-value needs counting",
}


 
# helpers
 
def _slice(name: str) -> DataGraph:
    return load_ntriples_file(os.path.join(REAL, name + ".nt"))


def _band(confidence: float) -> str:
    for low, high in CONFIDENCE_BANDS:
        if low <= confidence < high:
            return f"{low:.2f}-{high:.2f}" if high <= 1.0 else f"{low:.2f}-1.00"
    return "below floor"


def _class_of_head(head: str) -> Optional[str]:
    """The class a type-test head names, or None for a step head."""
    marker = '[val("'
    if marker not in head:
        return None
    return head.split(marker, 1)[1].split('"', 1)[0]


def _predicate_of_step_head(head: str) -> Optional[Tuple[str, str]]:
    """(direction, predicate) for a single-step head, else None."""
    inner = head.strip("<> ").strip()
    if " . " in inner or "(" not in inner:
        return None
    direction, rest = inner.split("(", 1)
    return direction.strip(), rest.rstrip(")").strip()


def signature(cand: Scored) -> Optional[Tuple[str, str, str]]:
    """A candidate as (shape, predicate, target), for comparison with a written rule.

    Only single-atom antecedents get a signature. A conjunction is a rule no
    third-party constraint language in scope here can state, so comparing it with
    one would be comparing different claims.
    """
    if len(cand.body_key) != 1:
        return None
    atom = cand.body_key[0]
    kind, _, name = atom.partition("_")
    cls = _class_of_head(cand.head_text)
    if cls is not None:
        if kind == "d":
            return ("domain", name, cls)
        if kind == "u":
            return ("range", name, cls)
        return None
    step = _predicate_of_step_head(cand.head_text)
    if step is not None and kind == "d" and step[0] == "down":
        return ("requires", name, step[1])
    return None


def _superclasses(graph: DataGraph, subclass_pred: str) -> Dict[str, Set[str]]:
    """value -> every class value reachable upward, for tolerant class matching."""
    parents: Dict[str, Set[str]] = defaultdict(set)
    for src, label, dst in graph.edges():
        if label == subclass_pred:
            sv, dv = graph.value(src), graph.value(dst)
            if sv and dv:
                parents[sv].add(dv)
    closure: Dict[str, Set[str]] = {}
    for start in parents:
        seen, stack = {start}, [start]
        while stack:
            node = stack.pop()
            for parent in parents.get(node, ()):
                if parent not in seen:
                    seen.add(parent)
                    stack.append(parent)
        closure[start] = seen
    return closure


def _class_matches(found: str, wanted: Set[str], closure: Dict[str, Set[str]]) -> bool:
    """A candidate's class matches a written class when it is the same class, or a
    subclass of it, or a superclass of it. Being one hop off in a hierarchy is a
    different granularity choice about the same rule, not a different rule."""
    bare = {c.split(":", 1)[-1] for c in wanted}
    found_bare = found.split(":", 1)[-1]
    if found_bare in bare:
        return True
    if any(w in {c.split(":", 1)[-1] for c in closure.get(found, ())} for w in bare):
        return True
    for w in wanted:
        for spelling in (w, "wd:" + w.split(":", 1)[-1]):
            if found_bare in {c.split(":", 1)[-1] for c in closure.get(spelling, ())}:
                return True
    return False


 
# T1: pruning ablation
 
def t1_ablation() -> Dict:
    graph = _slice(ABLATION_SLICE)
    oracle = ref.enumerate_all(graph, CONFIG, vocabulary(graph, CONFIG))
    truth = set(oracle.admitted)

    rows = []
    for label, support, prefix in (("neither", False, False),
                                   ("support only", True, False),
                                   ("head prefix only", False, True),
                                   ("both", True, True)):
        start = time.perf_counter()
        result = search(graph, CONFIG, prune_support=support, prune_prefix=prefix,
                        prune_dominance=False, residual=False)
        elapsed = time.perf_counter() - start
        got = {s.identity for s in result.admitted}
        bands = Counter(_band(s.confidence) for s in result.admitted)
        rows.append({
            "configuration": label,
            "support_pruning": support, "head_prefix_refusal": prefix,
            "bodies_generated": result.bodies_generated,
            "heads_generated": result.heads_generated,
            "prefixes_refused": result.prefixes_refused,
            "admitted": len(result.admitted),
            "bands": {band: bands.get(band, 0) for band, in
                      [(f"{low:.2f}-{high:.2f}" if high <= 1.0 else f"{low:.2f}-1.00",)
                       for low, high in CONFIDENCE_BANDS]},
            "lost_above_min_conf": sorted(truth - got),
            "runtime_s": round(elapsed, 4),
        })

    return {
        "slice": ABLATION_SLICE,
        "content_hash": graph_content_hash(graph),
        "oracle_admitted": len(truth),
        "oracle_bodies": oracle.bodies, "oracle_heads": oracle.heads,
        "rows": rows,
        "any_loss": any(r["lost_above_min_conf"] for r in rows),
    }


 
# T2: third-party ground truth
 
def _p2302_rules(cache: Dict) -> Tuple[List[Dict], Counter]:
    """Written constraints split into the ones this fragment can state and the ones
    it cannot, with a reason recorded for every exclusion."""
    expressible, excluded = [], Counter()
    for prop, statements in sorted(cache["constraints"].items()):
        for st in statements:
            shape = EXPRESSIBLE.get(st["constraint_type"])
            if shape is None:
                excluded[st["constraint_type"]] += 1
                continue
            if shape in ("domain", "range"):
                if not st["classes"]:
                    excluded[st["constraint_type"] + " (no class named)"] += 1
                    continue
                expressible.append({"shape": shape, "predicate": "wdt:" + prop,
                                    "targets": st["classes"]})
            else:
                if not st["properties"]:
                    excluded[st["constraint_type"] + " (no property named)"] += 1
                    continue
                expressible.append({"shape": "requires", "predicate": "wdt:" + prop,
                                    "targets": ["wdt:" + p for p in st["properties"]]})
    return expressible, excluded


def t2_third_party(slices: List[str]) -> Dict:
    if not os.path.exists(P2302_CACHE):
        return {"available": False,
                "reason": f"no cache at {os.path.relpath(P2302_CACHE, ROOT)}; "
                          f"run scripts/fetch_p2302.py"}
    with open(P2302_CACHE, encoding="utf-8") as fh:
        cache = json.load(fh)
    written, excluded = _p2302_rules(cache)

    found_signatures: Set[Tuple[str, str, str]] = set()
    closures: Dict[str, Dict[str, Set[str]]] = {}
    candidate_count = 0
    per_slice = []
    for name in slices:
        graph = _slice(name)
        vocab = vocabulary(graph, CONFIG)
        closures[name] = _superclasses(graph, vocab.subclass_predicate)
        result = search(graph, CONFIG)
        signatures = {sig for sig in (signature(c) for c in result.admitted) if sig}
        found_signatures |= signatures
        candidate_count += len(result.admitted)
        per_slice.append({"slice": name, "content_hash": graph_content_hash(graph),
                          "candidates": len(result.admitted),
                          "with_a_comparable_signature": len(signatures)})

    merged_closure: Dict[str, Set[str]] = defaultdict(set)
    for closure in closures.values():
        for key, value in closure.items():
            merged_closure[key] |= value

    # A written rule is only in scope when its predicate occurs in a slice at all.
    predicates_present = set()
    for name in slices:
        predicates_present |= set(_slice(name).labels)

    in_scope, out_of_scope = [], []
    for rule in written:
        (in_scope if rule["predicate"] in predicates_present else out_of_scope).append(rule)

    hits, misses = [], []
    for rule in in_scope:
        matched = None
        for shape, predicate, target in found_signatures:
            if shape != rule["shape"] or predicate != rule["predicate"]:
                continue
            if rule["shape"] == "requires":
                if target in rule["targets"]:
                    matched = target
                    break
            elif _class_matches(target, set(rule["targets"]), merged_closure):
                matched = target
                break
        record = {"shape": rule["shape"], "predicate": rule["predicate"],
                  "targets": rule["targets"][:6],
                  "targets_total": len(rule["targets"])}
        if matched:
            record["matched_by"] = matched
            hits.append(record)
        else:
            misses.append(record)

    corroborated = 0
    for shape, predicate, target in found_signatures:
        for rule in in_scope:
            if rule["shape"] == shape and rule["predicate"] == predicate:
                if (target in rule["targets"] if shape == "requires"
                        else _class_matches(target, set(rule["targets"]), merged_closure)):
                    corroborated += 1
                    break

    return {
        "available": True,
        "source": "Wikidata P2302 property constraints",
        "cache": os.path.relpath(P2302_CACHE, ROOT),
        "properties_fetched": len(cache["constraints"]),
        "statements_total": sum(len(v) for v in cache["constraints"].values()),
        "expressible_total": len(written),
        "expressible_in_scope": len(in_scope),
        "expressible_out_of_scope": len(out_of_scope),
        "expressible_and_found": len(hits),
        "expressible_and_missed": len(misses),
        "not_expressible": [{"constraint_type": k, "count": n,
                             "reason": NOT_EXPRESSIBLE_REASON.get(k.split(" ")[0],
                                                                  "not a graph-shape rule")}
                            for k, n in sorted(excluded.items())],
        "not_expressible_total": sum(excluded.values()),
        "hits": sorted(hits, key=lambda r: (r["shape"], r["predicate"])),
        "misses": sorted(misses, key=lambda r: (r["shape"], r["predicate"])),
        "candidates_total": candidate_count,
        "candidates_corroborated": corroborated,
        "per_slice": per_slice,
        "yago_shacl": {"available": False,
                       "reason": "no SHACL shape file is committed and the YAGO 4.5 "
                                 "schema dump is not in the offline corpus, so the "
                                 "YAGO half of this comparison was not run"},
    }


 
# T3: cross-source transfer
 
#: Hand-written vocabulary maps, so a rule derived on Wikidata can be stated in the
#: target's own vocabulary and actually scored there. Written out rather than derived,
#: because there is no alignment in the corpus and inventing one automatically would
#: be a different piece of research. Only the predicates and classes the committed
#: slices actually use appear here.
VOCABULARY_MAPS = {
    "real_dbpedia_geography_1000": {
        "wdt:P17": "dbo:country", "wdt:P31": "rdf:type", "wdt:P279": "rdfs:subClassOf",
        "wd:Q6256": "dbo:Country", "wd:Q3624078": "dbo:Country",
        "wd:Q515": "dbo:City", "wd:Q1549591": "dbo:City",
        "wd:Q200250": "dbo:PopulatedPlace", "wd:Q51929311": "dbo:PopulatedPlace",
    },
    "real_yago_taxa_1000": {
        "wdt:P171": "schema:parentTaxon", "wdt:P31": "rdf:type",
        "wdt:P279": "rdfs:subClassOf",
        "wd:Q16521": "schema:Taxon", "wd:Q112826905": "schema:Taxon",
        "wd:Q24017414": "schema:Taxon", "wd:Q2996394": "schema:Taxon",
        "wd:Q55983715": "schema:Taxon",
    },
}


def translate(text: str, mapping: Dict[str, str]) -> Optional[str]:
    """Rewrite an expression into a target vocabulary, or None if any term is
    unmapped. Refusing a partial translation is deliberate: a rule half in one
    vocabulary is not the same rule, and scoring it would be meaningless."""
    out = text
    terms = set()
    for token in text.replace("(", " ").replace(")", " ").replace('"', " ").split():
        if ":" in token and not token.startswith("["):
            terms.add(token.strip(".*[]<>| "))
    for term in terms:
        if term in mapping:
            out = out.replace(term, mapping[term])
        elif term.startswith(("wd:", "wdt:")):
            return None
    return out


#: The RC1 case itself, not a reconstruction of it: the authored anatomy rules whose
#: over-breadth the C1 investigation traced, together with the v2 rules that fixed
#: them. Each is scored on its home slice and on the slice the shared predicate drags
#: in, and named individually as the phase asks.
RC1_PROBES = [
    {"name": "ana.wd.dom.partof (v1)", "domain": "anatomy", "version": 1,
     "cid": "ana.wd.dom.partof",
     "why": "part-of is reused for geographic containment, so this anatomy-scoped "
            "rule also claims that every place that is part of another place is an "
            "anatomical structure"},
    {"name": "ana.wd.rng.partof (v1)", "domain": "anatomy", "version": 1,
     "cid": "ana.wd.rng.partof",
     "why": "the same reuse read from the object end"},
    {"name": "ana.wd.dom.partof.v2 (fixed)", "domain": "anatomy", "version": 2,
     "cid": "ana.wd.dom.partof.v2",
     "why": "the C1 fix, which scopes the antecedent so the geographic population "
            "is no longer claimed. Included as the contrast case"},
]


def _score_pair(graph: DataGraph, body: str, head: str) -> Optional[Scored]:
    from kgrepair.search import score
    ext = Extensions(graph, NodeSpace(graph))
    body_bits = ext.of(body)
    support, denominator, confidence = score(body_bits, ext.of(head),
                                             ext.of(lead_text(head)))
    if denominator < 1:
        return None
    return Scored(body_key=("probe",), head_key=head, body_text=body, head_text=head,
                  body_size=NodeSpace.count(body_bits), support=support,
                  denominator=denominator, confidence=confidence)


def _histogram(drops: List[float]) -> Dict[str, int]:
    bins = Counter()
    for drop in drops:
        if drop <= 0:
            bins["no drop"] += 1
        elif drop < 0.25:
            bins["0.00-0.25"] += 1
        elif drop < 0.5:
            bins["0.25-0.50"] += 1
        elif drop < 0.75:
            bins["0.50-0.75"] += 1
        else:
            bins["0.75-1.00"] += 1
    return dict(sorted(bins.items()))


def _transfer_one(domain, target_name, reference_name, translated: bool) -> Dict:
    target, reference = _slice(target_name), _slice(reference_name)
    result = search(target, CONFIG)
    mapping = VOCABULARY_MAPS.get(reference_name, {}) if translated else {}

    scored: List[Scored] = []
    untranslatable = 0
    for cand in result.admitted:
        if not translated:
            scored.append(cand)
            continue
        body = translate(cand.body_text, mapping)
        head = translate(cand.head_text, mapping)
        if body is None or head is None:
            untranslatable += 1
            continue
        scored.append(Scored(body_key=cand.body_key, head_key=cand.head_key,
                             body_text=body, head_text=head, body_size=cand.body_size,
                             support=cand.support, denominator=cand.denominator,
                             confidence=cand.confidence))

    verdicts = assess_stability(scored, reference, CONFIG, delta=0.1)
    drops, counts = [], Counter()
    for cand in scored:
        verdict = verdicts[cand.identity]
        counts[verdict.outcome] += 1
        if verdict.confidence_ref is not None:
            drops.append(round(cand.confidence - verdict.confidence_ref, 4))

    return {
        "domain": domain, "target": target_name, "reference": reference_name,
        "vocabulary": "translated" if translated else "as derived",
        "target_hash": graph_content_hash(target),
        "reference_hash": graph_content_hash(reference),
        "shared_predicates": sorted(target.labels & reference.labels),
        "candidates": len(result.admitted),
        "untranslatable": untranslatable,
        "scored_on_reference": len(scored),
        "stable": counts[STABLE], "unstable": counts[UNSTABLE],
        "not_comparable": counts[NOT_COMPARABLE],
        "comparable": len(drops),
        "drop_histogram": _histogram(drops),
        "drop_min": min(drops) if drops else None,
        "drop_median": sorted(drops)[len(drops) // 2] if drops else None,
        "drop_max": max(drops) if drops else None,
    }


def t3_transfer(pairs: List[Tuple[str, str, str]]) -> Dict:
    out = []
    for domain, target_name, reference_name in pairs:
        out.append(_transfer_one(domain, target_name, reference_name, translated=False))
        out.append(_transfer_one(domain, target_name, reference_name, translated=True))

    # RC1: the authored anatomy rules themselves, scored on their home slice and on
    # the slice the shared predicate drags in.
    home = _slice("real_wikidata_anatomy_1000_typed")
    intruder = _slice("real_wikidata_geography_1000")
    probes = []
    for probe in RC1_PROBES:
        cs = authored.get(probe["domain"], "wikidata", version=probe["version"])
        constraint = next((c for c in cs if c.cid == probe["cid"]), None)
        if constraint is None:
            continue
        on_home = _score_pair(home, constraint.antecedent, constraint.consequent)
        on_intruder = _score_pair(intruder, constraint.antecedent, constraint.consequent)
        verdict = None
        if on_home is not None:
            verdict = assess_stability([on_home], intruder, CONFIG,
                                       delta=0.1)[on_home.identity]
        probes.append({
            "name": probe["name"], "cid": probe["cid"], "why": probe["why"],
            "antecedent": constraint.antecedent, "consequent": constraint.consequent,
            "anatomy_confidence": round(on_home.confidence, 4) if on_home else None,
            "anatomy_judged": on_home.denominator if on_home else None,
            "geography_confidence": (round(on_intruder.confidence, 4)
                                     if on_intruder else None),
            "geography_judged": on_intruder.denominator if on_intruder else None,
            "verdict": verdict.outcome if verdict else "unjudgeable on the home slice",
            "verdict_reason": (verdict.reason if verdict else
                               "nothing in the home antecedent leads the head"),
            "would_be_discarded": bool(verdict and verdict.discard),
        })

    return {"pairs": out, "rc1_probes": probes}


 
# T4: the authored sets
 
def _authored_signature(constraint) -> Optional[Tuple[str, str, str]]:
    body, head = constraint.antecedent, constraint.consequent
    cls = _class_of_head(head)
    step = _predicate_of_step_head(body)
    body_cls = _class_of_head(body)
    if cls is not None and step is not None:
        return (("domain" if step[0] == "down" else "range"), step[1], cls)
    head_step = _predicate_of_step_head(head)
    if body_cls is not None and head_step is not None:
        return ("requires", body_cls, head_step[1])
    return None


def t4_authored(cells: List[Tuple[str, str, str]]) -> Dict:
    rows, unrecovered = [], []
    for domain, kg, slice_name in cells:
        graph = _slice(slice_name)
        vocab = vocabulary(graph, CONFIG)
        closure = _superclasses(graph, vocab.subclass_predicate)
        result = search(graph, CONFIG)
        found = {sig for sig in (signature(c) for c in result.admitted) if sig}
        atom_bodies = {a.text for a in vocab.atoms}
        ext = Extensions(graph, NodeSpace(graph))

        for version in (1, 2):
            try:
                cs = authored.get(domain, kg, version=version)
            except Exception:
                continue
            core = [c for c in cs if c.tier == "ptime_core"]
            hits = 0
            for constraint in core:
                sig = _authored_signature(constraint)
                matched = False
                if sig is not None:
                    for shape, predicate, target in found:
                        if shape != sig[0] or predicate != sig[1]:
                            continue
                        if shape == "requires":
                            matched = target == sig[2]
                        else:
                            matched = _class_matches(target, {sig[2]}, closure)
                        if matched:
                            break
                if matched:
                    hits += 1
                    continue

                # classify the miss
                if sig is None:
                    reason = ("outside the search space: the antecedent or consequent "
                              "is a shape the generator never emits")
                    body_size = None
                else:
                    # How many nodes the authored antecedent actually matches here.
                    # Below the support floor the search could not have proposed it
                    # whatever else is true, so that is the explanation and the
                    # remaining misses are the ones that need a better one.
                    try:
                        body_size = NodeSpace.count(ext.of(constraint.antecedent))
                    except Exception:
                        body_size = None
                    if body_size is not None and body_size < CONFIG.min_support:
                        reason = (f"below the support floor: the antecedent matches "
                                  f"{body_size} node(s) on this slice, against a floor "
                                  f"of {CONFIG.min_support}")
                    else:
                        reason = ("a genuine gap: the antecedent is frequent enough and "
                                  "the shape is in the space, but no candidate matched")
                unrecovered.append({
                    "domain": domain, "kg": kg, "version": version,
                    "cid": constraint.cid, "kind": constraint.kind,
                    "antecedent": constraint.antecedent,
                    "consequent": constraint.consequent,
                    "antecedent_matches": body_size,
                    "classification": reason,
                })
            rows.append({
                "domain": domain, "kg": kg, "version": version, "slice": slice_name,
                "content_hash": graph_content_hash(graph),
                "authored_core": len(core), "recovered": hits,
                "recall": round(hits / len(core), 4) if core else None,
                "candidates": len(result.admitted),
            })
    return {"rows": rows, "unrecovered": unrecovered}


 
# T5: reviewer effort
 
def t5_reviewer_effort(cells: List[Tuple[str, str, str]]) -> Dict:
    """Pooled across every slice with an authored set.

    One slice on its own yields too few accepts for the two orderings to be
    distinguishable, so the queue a reviewer would actually face is modelled as the
    whole corpus at once. The accept count is reported alongside the curves,
    because it is what decides how much weight the comparison can carry.
    """
    from kgrepair.validator import Validator
    from kgrepair.constraints.model import Constraint

    entries, per_slice = [], []
    for domain, kg, slice_name in cells:
        graph = _slice(slice_name)
        closure = _superclasses(graph, vocabulary(graph, CONFIG).subclass_predicate)
        result = search(graph, CONFIG)
        cs = authored.get(domain, kg, version=2)
        oracle = {sig for sig in (_authored_signature(c) for c in cs
                                  if c.tier == "ptime_core") if sig}
        validator = Validator(graph, use_closure=True)

        accepts = 0
        for cand in result.admitted:
            sig = signature(cand)
            accept = False
            if sig is not None:
                for shape, predicate, target in oracle:
                    if shape == sig[0] and predicate == sig[1]:
                        accept = (target == sig[2] if shape == "requires"
                                  else _class_matches(sig[2], {target}, closure))
                        if accept:
                            break
            witnesses = validator.check_one(Constraint(
                cid=cand.head_key, domain=domain, kg=kg, kind="typing_existence",
                tier="ptime_core", provenance="mined", direction="superset",
                antecedent=cand.body_text, consequent=cand.head_text)).count
            accepts += 1 if accept else 0
            entries.append({"identity": [domain, list(cand.body_key), cand.head_key],
                            "confidence": cand.confidence, "witnesses": witnesses,
                            "accept": accept})
        per_slice.append({"domain": domain, "slice": slice_name,
                          "content_hash": graph_content_hash(graph),
                          "candidates": len(result.admitted), "oracle_accepts": accepts})

    def curve(key):
        ordered = sorted(entries, key=key)
        total, out = 0, []
        for i, entry in enumerate(ordered, start=1):
            total += 1 if entry["accept"] else 0
            out.append({"decisions": i, "accepted": total})
        return out

    by_confidence = curve(lambda e: (-e["confidence"], str(e["identity"])))
    by_impact = curve(lambda e: (-(e["witnesses"] * (1.0 - e["confidence"])),
                                 str(e["identity"])))
    accepted_total = sum(1 for e in entries if e["accept"])

    def decisions_to(curve_rows, fraction):
        want = max(1, int(round(accepted_total * fraction)))
        for row in curve_rows:
            if row["accepted"] >= want:
                return row["decisions"]
        return None

    return {
        "per_slice": per_slice,
        "candidates": len(entries), "oracle_accepts": accepted_total,
        "by_confidence": by_confidence, "by_impact": by_impact,
        "decisions_to_half_by_confidence": decisions_to(by_confidence, 0.5),
        "decisions_to_half_by_impact": decisions_to(by_impact, 0.5),
        "decisions_to_all_by_confidence": decisions_to(by_confidence, 1.0),
        "decisions_to_all_by_impact": decisions_to(by_impact, 1.0),
        "limitation": ("the oracle is the authored v2 set, so this measures agreement "
                       "with one author's choices, not what a reviewer would actually "
                       "decide"),
    }


def _figure(t5: Dict) -> Optional[str]:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return None
    fig, ax = plt.subplots(figsize=(7, 4.5), dpi=110)
    for rows, label, style in ((t5["by_confidence"], "confidence descending", "-"),
                               (t5["by_impact"], "witnesses x (1 - confidence)", "--")):
        ax.plot([r["decisions"] for r in rows], [r["accepted"] for r in rows],
                style, label=label)
    ax.set_xlabel("decisions made")
    ax.set_ylabel("constraints accepted")
    ax.set_title("Reviewer effort, authored v2 as the oracle")
    ax.legend(loc="lower right")
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(FIGURE_PATH, metadata={"Software": None})
    plt.close(fig)
    return os.path.relpath(FIGURE_PATH, ROOT)


 
# reporting
 
def md_table(rows, columns) -> str:
    if not rows:
        return "_(none)_"
    head = "| " + " | ".join(columns) + " |"
    sep = "|" + "|".join("---" for _ in columns) + "|"
    body = "\n".join("| " + " | ".join(str(r.get(c, "")) for c in columns) + " |"
                     for r in rows)
    return f"{head}\n{sep}\n{body}"


def write_jsonl(records: List[Dict]) -> None:
    revision = code_revision()
    with open(JSONL_PATH, "w", encoding="utf-8") as fh:
        for record in records:
            fh.write(json.dumps({**record, "code_revision": revision},
                                sort_keys=True) + "\n")


def build_markdown(t1, t2, t3, t4, t5, figure) -> str:
    band_names = [f"{low:.2f}-{high:.2f}" if high <= 1.0 else f"{low:.2f}-1.00"
                  for low, high in CONFIDENCE_BANDS]
    ablation_rows = []
    for row in t1["rows"]:
        entry = {"configuration": row["configuration"],
                 "bodies": row["bodies_generated"], "heads": row["heads_generated"],
                 "admitted": row["admitted"], "runtime_s": row["runtime_s"],
                 "lost above min_conf": len(row["lost_above_min_conf"])}
        entry.update({band: row["bands"].get(band, 0) for band in band_names})
        ablation_rows.append(entry)

    parts = [
        "# Derivation search evaluation (P4c)",
        "",
        "Every number here is rendered from `results/derivation_eval.jsonl`, one record "
        "per finding, each carrying the slice `content_hash` and the `code_revision` it "
        "was produced under. Regenerate with `python scripts/eval_derivation_search.py`. "
        f"Search bounds throughout: `min_support={CONFIG.min_support}`, "
        f"`min_confidence={CONFIG.min_confidence}`, "
        f"`max_antecedent={CONFIG.max_antecedent}`, `max_path={CONFIG.max_path}`.",
        "",
        "## T1. Pruning ablation",
        "",
        f"Slice `{t1['slice']}`, small enough for the reference enumerator to score the "
        f"whole space: {t1['oracle_bodies']} bodies against {t1['oracle_heads']} heads, "
        f"{t1['oracle_admitted']} admitted with nothing pruned. Dominance is off in all "
        "four runs, so this is about the two pruning laws and nothing else.",
        "",
        md_table(ablation_rows, ["configuration", "bodies", "heads", "admitted"]
                 + band_names + ["lost above min_conf", "runtime_s"]),
        "",
        ("**Nothing above the confidence floor was lost in any configuration.** That is "
         "the claim the two laws make, and it is the claim this table exists to test: "
         "every configuration admitted exactly what the unpruned oracle admitted."
         if not t1["any_loss"] else
         "**A configuration lost candidates above the confidence floor.** See the "
         "`lost_above_min_conf` field in the results file; this is a defect, not a "
         "tuning matter."),
        "",
        "Runtimes are wall-clock on one machine and are the only figures here that will "
        "not reproduce exactly elsewhere.",
        "",
        "## T2. Recovery against third-party constraints",
        "",
    ]

    if not t2.get("available"):
        parts += [f"_Not run: {t2['reason']}_", ""]
    else:
        parts += [
            f"Source: {t2['source']}, cached at `{t2['cache']}` by "
            f"`scripts/fetch_p2302.py`. {t2['properties_fetched']} properties, "
            f"{t2['statements_total']} constraint statements.",
            "",
            "The two counts the gate asks for are reported separately from the ones the "
            "fragment cannot state at all. Conflating them would report a modelling "
            "boundary as a failure to find something.",
            "",
            md_table([
                {"count": t2["statements_total"], "category": "constraint statements fetched"},
                {"count": t2["not_expressible_total"], "category": "not expressible in this fragment or not generated by this search"},
                {"count": t2["expressible_total"], "category": "expressible as a rule of one of the three shapes"},
                {"count": t2["expressible_out_of_scope"], "category": "expressible, but the predicate does not occur in any committed slice"},
                {"count": t2["expressible_in_scope"], "category": "**expressible and in scope**"},
                {"count": t2["expressible_and_found"], "category": "**expressible and found**"},
                {"count": t2["expressible_and_missed"], "category": "**expressible and missed**"},
            ], ["category", "count"]),
            "",
            f"Precision the other way round: {t2['candidates_corroborated']} of "
            f"{t2['candidates_total']} candidates across the scored slices correspond to "
            f"a written constraint. That number is low by construction and should be read "
            f"with care: the search proposes rules about a 1000-edge sample, while the "
            f"written constraints describe the whole of Wikidata, so most candidates are "
            f"about populations no written constraint mentions.",
            "",
            "### What was found",
            "",
            md_table(t2["hits"], ["shape", "predicate", "matched_by", "targets_total"]),
            "",
            "### What was missed",
            "",
            md_table(t2["misses"], ["shape", "predicate", "targets", "targets_total"]),
            "",
            "### What the fragment cannot state",
            "",
            md_table(t2["not_expressible"], ["constraint_type", "count", "reason"]),
            "",
            f"_YAGO SHACL: {t2['yago_shacl']['reason']}._",
            "",
        ]

    parts += ["## T3. Cross-source transfer", ""]
    parts += [md_table(t3["pairs"], ["domain", "reference", "vocabulary", "candidates",
                                     "untranslatable", "stable", "unstable",
                                     "not_comparable", "comparable", "drop_median",
                                     "drop_max"]), ""]
    for pair in t3["pairs"]:
        parts += [f"**{pair['domain']}, {pair['vocabulary']}, against "
                  f"`{pair['reference']}`.** Shared predicates: "
                  f"{', '.join(pair['shared_predicates']) or 'none'}. "
                  f"Confidence-drop distribution over the {pair['comparable']} comparable "
                  f"candidates: " +
                  (", ".join(f"{k} {v}" for k, v in pair["drop_histogram"].items())
                   or "none comparable") + ".", ""]

    parts += ["### Over-broad rules of the RC1 shape", "",
              "Not a reconstruction of the RC1 shape but the case itself: the authored "
              "anatomy rules whose over-breadth the C1 investigation traced, plus the v2 "
              "rule that fixed one of them as a contrast. Each is scored on its home "
              "slice and on the geography slice that the shared part-of predicate drags "
              "in. Named individually.", ""]
    for probe in t3["rc1_probes"]:
        parts += [f"- **{probe['name']}.** {probe['why']}. On the anatomy slice: "
                  f"confidence {probe['anatomy_confidence']} over "
                  f"{probe['anatomy_judged']} judged node(s). On the geography slice, "
                  f"which the shared predicate drags in: "
                  f"{probe['geography_confidence']} over {probe['geography_judged']}. "
                  f"Stability verdict: **{probe['verdict']}** "
                  f"({probe['verdict_reason']}). Discarded by the gate: "
                  f"{probe['would_be_discarded']}."]
    parts += [""]

    parts += ["## T4. Recovery against the authored sets", "",
              "Weaker evidence than T2 and reported second for that reason: agreement "
              "with one author's choices on one slice is a narrow yardstick, and the "
              "author of the constraints and the author of the search are the same "
              "person. The third-party comparison is the one that carries weight.", "",
              md_table(t4["rows"], ["domain", "kg", "version", "slice", "authored_core",
                                    "recovered", "recall", "candidates"]), "",
              "### Every authored constraint no candidate reproduces", "",
              md_table(t4["unrecovered"], ["domain", "version", "cid", "kind",
                                           "antecedent_matches", "classification"]), ""]

    parts += ["## T5. Reviewer effort", "",
              f"Pooled over every slice with an authored set: {t5['candidates']} "
              f"candidates, {t5['oracle_accepts']} of which the authored v2 sets "
              f"accept.", "",
              md_table(t5["per_slice"], ["domain", "slice", "candidates",
                                         "oracle_accepts"]), "",
              md_table([
                  {"ordering": "confidence descending",
                   "decisions to half the accepts": t5["decisions_to_half_by_confidence"],
                   "decisions to all the accepts": t5["decisions_to_all_by_confidence"]},
                  {"ordering": "witnesses x (1 - confidence)",
                   "decisions to half the accepts": t5["decisions_to_half_by_impact"],
                   "decisions to all the accepts": t5["decisions_to_all_by_impact"]},
              ], ["ordering", "decisions to half the accepts", "decisions to all the accepts"]),
              ""]
    if figure:
        parts += [f"![Reviewer effort]({os.path.relpath(FIGURE_PATH, EVAL_DIR)})", ""]
    parts += [f"**Limitation, stated with the result rather than after it:** "
              f"{t5['limitation']}. A reviewer who disagreed with the authored set would "
              f"produce a different curve, and nothing here measures whether the authored "
              f"set is right.", ""]

    return "\n".join(parts)


def main() -> int:
    os.makedirs(EVAL_DIR, exist_ok=True)
    slices = ["real_wikidata_geography_1000", "real_wikidata_taxa_1000"]

    t1 = t1_ablation()
    t2 = t2_third_party(slices)
    t3 = t3_transfer([
        ("geography", "real_wikidata_geography_1000", "real_dbpedia_geography_1000"),
        ("taxa", "real_wikidata_taxa_1000", "real_yago_taxa_1000"),
    ])
    cells = [
        ("geography", "wikidata", "real_wikidata_geography_1000"),
        ("taxa", "wikidata", "real_wikidata_taxa_1000"),
        ("anatomy", "wikidata", "real_wikidata_anatomy_1000_typed"),
        ("disease", "wikidata", "real_wikidata_disease_1000"),
        ("medication", "wikidata", "real_wikidata_medication_1000_typed"),
    ]
    t4 = t4_authored(cells)
    t5 = t5_reviewer_effort(cells)
    figure = _figure(t5)

    write_jsonl([
        {"task": "T1", "finding": "pruning ablation", **t1},
        {"task": "T2", "finding": "third-party recovery", **t2},
        {"task": "T3", "finding": "cross-source transfer", **t3},
        {"task": "T4", "finding": "authored recovery", **t4},
        {"task": "T5", "finding": "reviewer effort", **t5},
    ])
    with open(JSON_PATH, "w", encoding="utf-8") as fh:
        json.dump({"config": {"min_support": CONFIG.min_support,
                              "min_confidence": CONFIG.min_confidence,
                              "max_antecedent": CONFIG.max_antecedent,
                              "max_path": CONFIG.max_path},
                   "T1": t1, "T2": t2, "T3": t3, "T4": t4, "T5": t5},
                  fh, indent=2, sort_keys=True)
        fh.write("\n")
    with open(MD_PATH, "w", encoding="utf-8") as fh:
        fh.write(build_markdown(t1, t2, t3, t4, t5, figure))

    sys.stdout.write(f"wrote {os.path.relpath(MD_PATH, ROOT)}, "
                     f"{os.path.relpath(JSON_PATH, ROOT)}, "
                     f"{os.path.relpath(JSONL_PATH, ROOT)}\n")
    if t1["any_loss"]:
        sys.stderr.write("STOP: a pruning configuration lost candidates above "
                         "min_conf. See T1.lost_above_min_conf.\n")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
