"""
Turning a derivation run into a candidate file a person can review.

`kgrepair.derive` scores rules against a graph. This module takes what it emitted
and builds the reviewable artifact: a plain reading of each rule, a sample of the
nodes that break it, what repairing it would actually do to the graph, and an
order that puts the consequential decisions first.

Everything here is proposal-side. Nothing in this module can authorise a repair;
that needs a reviewer and a seal, and the gate lives in `kgrepair.review`.
"""
from __future__ import annotations

import re
from dataclasses import replace
from typing import Dict, Iterable, List, Optional, Tuple

from .candidates import Candidate, CandidateFile, candidate_cid
from .constraints.model import Constraint, ConstraintSet
from .datagraph import DataGraph
from .derive import GENERATORS, DeriveConfig, derive_candidates as _derive_raw
from .repair import subset_repair, superset_repair
from .review import graph_content_hash
from .validator import Validator

#: Predicates whose object is treated as a display name for its subject. Used only
#: to make a review readable; nothing downstream depends on a label existing.
DEFAULT_LABEL_PREDICATES = ("rdfs:label", "skos:prefLabel", "schema:name",
                            "foaf:name", "dct:title")

#: How many witnesses a candidate carries as an illustration.
WITNESS_SAMPLE_SIZE = 3

_CURIE = re.compile(r"^[A-Za-z][\w.\-]*:(.+)$")


 
# plain readings
 
def build_label_index(graph: DataGraph,
                      label_predicates: Iterable[str] = DEFAULT_LABEL_PREDICATES) -> Dict[str, str]:
    """node id -> display name, for whatever the graph actually labels.

    Note for the project's own corpus: the Level-0 allow-lists exclude label
    predicates, so a committed real slice carries no labels and this index comes
    back empty. Everything below then falls back to the node id, which is honest:
    inventing a name the data does not contain would be worse than showing the id.
    """
    preds = tuple(label_predicates)
    index: Dict[str, str] = {}
    for src, label, dst in sorted(graph.edges()):
        if label not in preds:
            continue
        value = graph.value(dst)
        name = value if value is not None and value != dst else dst
        index.setdefault(src, name)
    return index


def display_name(node: str, labels: Dict[str, str]) -> str:
    """A node's label where the graph has one, otherwise its own id."""
    return labels.get(node, node)


def _local(term: str) -> str:
    m = _CURIE.match(term)
    return m.group(1) if m else term


def _name(term: str, labels: Dict[str, str]) -> str:
    """How a class or predicate is written in a gloss."""
    return labels.get(term, term)


#: One template per derived shape. Plain English, no path syntax.
_GLOSS = {
    "existential_domain":
        "anything with an outgoing {predicate} edge should be {a_class}",
    "existential_range":
        "anything on the receiving end of a {predicate} edge should be {a_class}",
    "typing_existence":
        "anything matching this pattern should be {a_class}",
    "requires_statement":
        "everything that is {a_class} should have an outgoing {predicate} edge",
    "weakening":
        "everything that is {a_class} should have an outgoing {predicate} edge, "
        "or match the broader alternative recorded with this entry",
}


def gloss_for(kind: str, *, cls: Optional[str], predicate: Optional[str],
              labels: Dict[str, str]) -> str:
    """A one-line reading of a rule, for someone deciding whether it is true.

    Deliberately does not restate the Reg-GXPath expression: the expression is
    carried alongside for anyone who wants it, and a reviewer judging whether a
    rule is right about the world is better served by a sentence.
    """
    template = _GLOSS.get(kind)
    if template is None:
        return f"a derived {kind.replace('_', ' ')} rule"
    cls_name = _name(cls, labels) if cls else "of the expected type"
    pred_name = _name(predicate, labels) if predicate else "the expected"
    return template.format(a_class=cls_name, predicate=pred_name)


 
# evidence, witnesses, impact
 
def _one_constraint_set(c: Constraint) -> ConstraintSet:
    return ConstraintSet(f"candidate@{c.cid}", [c])


def witness_sample(graph: DataGraph, c: Constraint, labels: Dict[str, str],
                   size: int = WITNESS_SAMPLE_SIZE) -> Tuple[List[str], int]:
    """(sample, total) of the nodes this rule says are wrong.

    Sorted before slicing, so the same graph always illustrates a rule with the
    same nodes.
    """
    violation = Validator(graph, use_closure=True).check_one(c)
    ordered = sorted(violation.witnesses)
    return [display_name(n, labels) for n in ordered[:size]], len(ordered)


def deferred_impact(witnesses: Optional[int] = None) -> Dict:
    """An impact record with the engine numbers not yet computed.

    Measured, not assumed: on the size ladder in `docs/performance.md` the engine
    runs are 95 to 99 percent of what a derivation costs, and the cost per
    candidate tracks its witness count, reaching half a minute for a single
    candidate at the 100k rung. So a derive run records the witness count, which
    is one evaluation, and leaves the two engine numbers null until someone
    actually looks at the entry.

    `measured` is what tells a reader that null means "not computed yet" rather
    than "the engine could not act on this".
    """
    return {"witnesses": witnesses, "subset_deletions": None,
            "superset_additions": None, "measured": False}


def fill_impact(graph: DataGraph, candidate, force: bool = False) -> Dict:
    """Compute a deferred impact record, at the point someone reviews the entry.

    Returns the candidate's impact either way, so a caller can show it without
    checking first. Already-measured entries are left alone unless `force`.
    """
    if candidate.impact.get("measured") and not force:
        return candidate.impact
    constraint = Constraint(
        cid=candidate.cid, domain="", kg="", kind=candidate.kind,
        tier=candidate.tier, provenance="mined", direction=candidate.direction,
        antecedent=candidate.antecedent, consequent=candidate.consequent)
    candidate.impact = measure_impact(graph, constraint)
    return candidate.impact


def measure_impact(graph: DataGraph, c: Constraint) -> Dict:
    """What accepting this one rule would do to the graph.

    Runs both engines over a one-constraint set through the public entry points,
    so a reviewer sees the cost of a decision rather than only its score. The
    engines are never reached from here without a constraint that already parsed.

    This is the expensive half of a derivation. See `deferred_impact` for why a
    derive run no longer calls it for every candidate.
    """
    cs = _one_constraint_set(c)
    impact: Dict = {"witnesses": 0, "subset_deletions": None,
                    "superset_additions": None, "measured": True}
    impact["witnesses"] = Validator(graph, use_closure=True).check_one(c).count
    try:
        impact["subset_deletions"] = len(subset_repair(graph, cs).deleted_nodes)
    except Exception as exc:                       # a shape one engine cannot act on
        impact["subset_deletions"] = None
        impact["subset_note"] = f"{type(exc).__name__}: {exc}"
    try:
        impact["superset_additions"] = len(superset_repair(graph, cs).added_edges)
    except Exception as exc:
        impact["superset_additions"] = None
        impact["superset_note"] = f"{type(exc).__name__}: {exc}"
    return impact


def review_rank(impact: Dict, confidence: float) -> float:
    """witnesses * (1 - confidence).

    Puts the entries where a decision changes the most and the evidence is least
    settled at the front of the queue. A rule with perfect confidence ranks zero
    however many witnesses it has, because there is little for a reviewer to weigh.
    """
    return float(impact.get("witnesses") or 0) * (1.0 - float(confidence or 0.0))


 
# the bridge
 
def derive_candidate_file(graph: DataGraph, domain: str, kg: str, *,
                          config: Optional[DeriveConfig] = None,
                          reference_graph: Optional[DataGraph] = None,
                          dataset: str = "", stability_delta: Optional[float] = None,
                          label_predicates: Iterable[str] = DEFAULT_LABEL_PREDICATES,
                          measure: bool = False,
                          generator: Optional[str] = None) -> CandidateFile:
    """Returns a `CandidateFile`: derived candidates wrapped for human review.

    The reviewable artifact, as distinct from `derive.derive_candidates`, which
    returns a scored `DerivationResult` and is the profiling step underneath this
    one. This is the public entry point; that one is internal.

    Offline: the graph is already loaded, and nothing here fetches anything.

    `stability_delta`, with a `reference_graph`, drops any candidate whose
    confidence on the two graphs differs by more than the delta. A rule that only
    holds on one of them is a fact about that graph rather than about the domain,
    and both numbers are recorded in the candidate's evidence either way.

    Impact is deferred by default. Every candidate carries its witness count,
    which is one evaluation, and the two engine numbers stay null until someone
    reviews the entry and `fill_impact` computes them. `measure=True` restores the
    old behaviour of running both engines for every candidate up front, which on
    the measured ladder is 95 to 99 percent of the total cost.

    `generator` selects which generator runs, overriding `config.generator` when
    given. It is a plain string (`"search"` or `"shapes"`) so that a caller which
    cannot reach `DeriveConfig`, such as the viewer, can still choose one. Whichever
    ran is recorded in the file's `parameters`, so every candidate file says how it
    was produced.

    Every candidate comes back `pending`. There is no path through this function
    that marks anything accepted.
    """
    cfg = config or DeriveConfig()
    if generator is not None:
        if generator not in GENERATORS:
            raise ValueError(f"unknown generator {generator!r}; "
                             f"expected one of {list(GENERATORS)}")
        cfg = replace(cfg, generator=generator)
    stability = reference_graph is not None and stability_delta is not None

    # `derive.derive_candidates` reads `reference_graph` as "profile and score on
    # the reference, then count witnesses on the target". The stability gate needs
    # the other arrangement: score the target, score the reference, compare. So the
    # reference is withheld from the main run and scored separately below.
    result = _derive_raw(graph, domain, kg, cfg,
                         reference_graph=None if stability else reference_graph)
    labels = build_label_index(graph, label_predicates)
    by_cid = {r["cid"]: r for r in result.report}

    ref_conf: Dict[str, float] = {}
    if stability:
        ref_result = _derive_raw(reference_graph, domain, kg, cfg)
        # A rule the reference run did not emit at all scores zero there, which is
        # the honest reading: the reference gave no support for it.
        ref_conf = {r["cid"]: r.get("pca_conf", 0.0) for r in ref_result.report}

    candidates: List[Candidate] = []
    ranked: List[Tuple[float, str]] = []
    for c in result.constraints:
        rep = by_cid.get(c.cid, {})
        conf = float(rep.get("pca_conf", 0.0) or 0.0)

        evidence = {
            "support": rep.get("support"),
            "confidence": conf,
            "standard_confidence": rep.get("standard_conf"),
            "exceptions": rep.get("exceptions", []),
            "class": rep.get("class"),
            "predicate": rep.get("predicate"),
            "low_trust": rep.get("low_trust"),
            "low_trust_reason": rep.get("low_trust_reason"),
        }

        if ref_conf:
            reference = float(ref_conf.get(c.cid, 0.0) or 0.0)
            evidence["reference_confidence"] = reference
            evidence["confidence_gap"] = round(abs(conf - reference), 6)
            if abs(conf - reference) > float(stability_delta):
                # Holds on one graph and not the other, so it describes a graph
                # rather than the domain. Dropped, with both numbers recorded.
                continue

        sample, total = witness_sample(graph, c, labels)
        impact = measure_impact(graph, c) if measure else deferred_impact(total)

        cid = candidate_cid(domain, kg, c.antecedent, c.consequent)
        candidates.append(Candidate(
            cid=cid, kind=c.kind, tier=c.tier, direction=c.direction,
            antecedent=c.antecedent, consequent=c.consequent,
            gloss=gloss_for(c.kind, cls=rep.get("class"), predicate=rep.get("predicate"),
                            labels=labels),
            evidence=evidence, impact=impact, witness_sample=sample))
        ranked.append((review_rank(impact, conf), cid))

    # Highest rank first; cid breaks ties so the order is settled.
    ranked.sort(key=lambda pair: (-pair[0], pair[1]))

    cf = CandidateFile(
        source={"dataset": dataset, "domain": domain, "kg": kg,
                "content_hash": graph_content_hash(graph),
                "reference": ({"dataset": "", "content_hash":
                               graph_content_hash(reference_graph)}
                              if reference_graph is not None else None)},
        parameters={"generator": cfg.generator,
                    "min_support": cfg.min_support,
                    "min_confidence": cfg.min_pca_confidence,
                    "max_antecedent": cfg.max_typing_antecedent_atoms,
                    "max_path": cfg.max_path_depth,
                    "stability_delta": stability_delta,
                    "type_predicate": result.vocab.get("type_predicate"),
                    "subclass_predicate": result.vocab.get("subclass_predicate")},
        candidates=candidates)
    cf.review["review_order"] = [cid for _rank, cid in ranked]
    from . import __version__
    cf.toolkit_version = __version__
    return cf
