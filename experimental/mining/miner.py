"""
E0 -- the baseline prevalence/co-occurrence miner.

Design (stated up front, per the sprint's "honest nulls over dressed-up results"
instruction, since these are judgment calls a reader needs to be able to check):

  "Instances of C" are read through the SAME tau_C the hand-curated constraints
  use (down(type).down(subClassOf)*.[val(C)]), evaluated with the real
  `kgrepair.gxpath.Evaluator` -- not a hand-rolled BFS. This ties every mined
  candidate to the exact membership semantics the repair engines already use, and
  means "does this parse as tau_C" is answered by the real parser, not assumed.

  Four candidate shapes, each a single conditional-prevalence measurement:

    existential_domain(p, C):  P(subj typed C | x -p-> _)
    existential_range(p, C):   P(obj  typed C | _ -p-> x)
    requires_statement(C, p):  P(x has outgoing p | x in instances(C))
    typing_existence(p1,p2,C): P(x in instances(C) | x -p1-> _ AND x -p2-> _)
                                (conjunctive completion rule, mirroring
                                geo.wd.type.city's shape) -- bounded to the
                                `top_k_pair_preds` most frequent candidate
                                predicates, an explicit scope limit for a
                                time-boxed baseline, not an exhaustive search.

  Classes considered are every node ever seen as the direct object of a typing
  predicate (P31/P279 or rdf:type/rdfs:subClassOf) -- restricted to those with
  global support >= `min_support` before any (p, C) pair is even formed, so the
  search stays small at slice scale.
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from itertools import combinations
from typing import Dict, List, Set, Tuple

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

from kgrepair import gxpath                       # noqa: E402  (experimental -> core import; allowed)
from kgrepair.datagraph import DataGraph          # noqa: E402
from kgrepair.gxpath import Evaluator             # noqa: E402

# Typing spine per KG -- structural predicates, never mined as candidate
# properties themselves (mirrors src/kgrepair/pipeline/extract.py's own
# _TYPING_PREDS, redefined locally so experimental/ does not reach into another
# module's private name).
TYPING_PREDS: Dict[str, Tuple[str, str]] = {
    "wikidata": ("wdt:P31", "wdt:P279"),
    "dbpedia": ("rdf:type", "rdfs:subClassOf"),
    "yago": ("rdf:type", "rdfs:subClassOf"),
    "synthetic": ("rdf:type", "rdfs:subClassOf"),   # E4: synthetic control (synthetic.py)
}

MINER_ID = "prevalence_v1"


def _tau_c(kg: str, class_value: str) -> str:
    type_pred, subclass_pred = TYPING_PREDS[kg]
    return f'< down({type_pred}) . down({subclass_pred})* . [val("{class_value}")] >'


@dataclass
class Candidate:
    kind: str                 # existential_domain | existential_range |
                               # requires_statement | typing_existence
    domain: str                # anatomy | disease | medication | geography | taxa
    kg: str
    antecedent: str
    consequent: str
    support: int                # |population| the prevalence was measured over
    prevalence: float
    threshold: float
    note: str
    cid_hint: str               # human-readable, not yet a stable cid

    def as_constraint_dict(self, *, source_slice_hash: str, min_support: int) -> Dict:
        """Serialise in the REAL constraint schema (Constraint.to_dict()'s shape),
        provenance='mined', with miner id / params / source-slice hash folded into
        the existing free-form `params` field -- no constraint-schema change."""
        return {
            "cid": self.cid_hint,
            "domain": self.domain,
            "kg": self.kg,
            "kind": self.kind,
            "tier": None,          # filled in by tier_classifier.classify()
            "provenance": "mined",
            "direction": None,     # filled in by tier_classifier.classify()
            "containment": {"phi": self.antecedent, "psi": self.consequent},
            "note": self.note,
            "params": {
                "miner": MINER_ID,
                "threshold": f"{self.threshold:.2f}",
                "support": str(self.support),
                "prevalence": f"{self.prevalence:.4f}",
                "min_support_floor": str(min_support),
                "source_slice_hash": source_slice_hash,
            },
            "version": 1,
        }


@dataclass
class MiningIndex:
    """Precomputed per-slice indexes the miner sweeps over (built once, reused
    across every threshold in a sweep)."""
    g: DataGraph
    kg: str
    class_nodes: List[str]
    class_instances: Dict[str, Set[str]]     # class -> instances(class), via tau_C
    subj_of: Dict[str, Set[str]]              # predicate -> subjects with an outgoing edge
    obj_of: Dict[str, Set[str]]               # predicate -> objects with an incoming edge
    candidate_preds: List[str]


def build_index(g: DataGraph, kg: str, *, min_support: int) -> MiningIndex:
    typing_preds = set(TYPING_PREDS[kg])
    subj_of: Dict[str, Set[str]] = {}
    obj_of: Dict[str, Set[str]] = {}
    class_nodes_raw: Set[str] = set()
    for (s, p, o) in g.edges():
        subj_of.setdefault(p, set()).add(s)
        obj_of.setdefault(p, set()).add(o)
        if p in typing_preds:
            class_nodes_raw.add(o)

    ev = Evaluator(g, use_closure=True)
    class_instances: Dict[str, Set[str]] = {}
    for c in sorted(class_nodes_raw):
        node = gxpath.parse_node(_tau_c(kg, c))
        instances = ev.eval_node(node)
        if len(instances) >= min_support:
            class_instances[c] = instances

    candidate_preds = sorted(set(g.labels) - typing_preds)
    return MiningIndex(
        g=g, kg=kg, class_nodes=sorted(class_instances), class_instances=class_instances,
        subj_of=subj_of, obj_of=obj_of, candidate_preds=candidate_preds,
    )


def _prevalence(population: Set[str], hit_set: Set[str]) -> Tuple[float, int]:
    support = len(population)
    if support == 0:
        return 0.0, 0
    return len(population & hit_set) / support, support


def mine_prevalence(idx: MiningIndex, *, domain: str, thresholds: List[float],
                    min_support: int, top_k_pair_preds: int = 10) -> Dict[float, List[Candidate]]:
    """Sweep every (predicate[, predicate], class) pair once at the LOWEST
    threshold's support floor, then bucket the survivors per threshold -- cheaper
    than re-sweeping per threshold, and makes the nesting (higher threshold's
    candidates subset of lower threshold's) mechanical rather than incidental."""
    by_threshold: Dict[float, List[Candidate]] = {t: [] for t in thresholds}
    lowest = min(thresholds)

    # existential_domain / existential_range: every (p, C) pair with enough support
    for p in idx.candidate_preds:
        subj_pop, obj_pop = idx.subj_of.get(p, set()), idx.obj_of.get(p, set())
        if len(subj_pop) >= min_support:
            for c in idx.class_nodes:
                prev, supp = _prevalence(subj_pop, idx.class_instances[c])
                if prev >= lowest and supp >= min_support:
                    for t in thresholds:
                        if prev >= t:
                            by_threshold[t].append(Candidate(
                                kind="existential_domain", domain=domain, kg=idx.kg,
                                antecedent=f"< down({p}) >", consequent=_tau_c(idx.kg, c),
                                support=supp, prevalence=prev, threshold=t,
                                note=f"mined: subject of {p} is typed {c} in {prev:.1%} of {supp} cases",
                                cid_hint=f"mined.{domain}.dom.{_short(p)}.{_short(c)}",
                            ))
        if len(obj_pop) >= min_support:
            for c in idx.class_nodes:
                prev, supp = _prevalence(obj_pop, idx.class_instances[c])
                if prev >= lowest and supp >= min_support:
                    for t in thresholds:
                        if prev >= t:
                            by_threshold[t].append(Candidate(
                                kind="existential_range", domain=domain, kg=idx.kg,
                                antecedent=f"< up({p}) >", consequent=_tau_c(idx.kg, c),
                                support=supp, prevalence=prev, threshold=t,
                                note=f"mined: object of {p} is typed {c} in {prev:.1%} of {supp} cases",
                                cid_hint=f"mined.{domain}.rng.{_short(p)}.{_short(c)}",
                            ))

    # requires_statement: every (C, p) pair
    for c in idx.class_nodes:
        population = idx.class_instances[c]
        if len(population) < min_support:
            continue
        for p in idx.candidate_preds:
            prev, supp = _prevalence(population, idx.subj_of.get(p, set()))
            if prev >= lowest and supp >= min_support:
                for t in thresholds:
                    if prev >= t:
                        by_threshold[t].append(Candidate(
                            kind="requires_statement", domain=domain, kg=idx.kg,
                            antecedent=_tau_c(idx.kg, c), consequent=f"< down({p}) >",
                            support=supp, prevalence=prev, threshold=t,
                            note=f"mined: instances of {c} have {p} in {prev:.1%} of {supp} cases",
                            cid_hint=f"mined.{domain}.req.{_short(c)}.{_short(p)}",
                        ))

    # typing_existence: conjunctive pairs over the top-K most frequent candidate
    # predicates only -- an explicit, documented scope bound (not exhaustive).
    top_preds = sorted(idx.candidate_preds,
                       key=lambda p: len(idx.subj_of.get(p, set())), reverse=True)[:top_k_pair_preds]
    for p1, p2 in combinations(sorted(top_preds), 2):
        population = idx.subj_of.get(p1, set()) & idx.subj_of.get(p2, set())
        if len(population) < min_support:
            continue
        for c in idx.class_nodes:
            prev, supp = _prevalence(population, idx.class_instances[c])
            if prev >= lowest and supp >= min_support:
                for t in thresholds:
                    if prev >= t:
                        by_threshold[t].append(Candidate(
                            kind="typing_existence", domain=domain, kg=idx.kg,
                            antecedent=f"< down({p1}) > & < down({p2}) >",
                            consequent=_tau_c(idx.kg, c),
                            support=supp, prevalence=prev, threshold=t,
                            note=(f"mined: entities with both {p1} and {p2} are typed "
                                  f"{c} in {prev:.1%} of {supp} cases"),
                            cid_hint=f"mined.{domain}.type.{_short(p1)}_{_short(p2)}.{_short(c)}",
                        ))

    for t in thresholds:
        by_threshold[t].sort(key=lambda cand: (cand.kind, cand.cid_hint))
    return by_threshold


def _short(curie: str) -> str:
    return curie.split(":", 1)[-1].replace('"', "").replace(" ", "_")
