"""
Quality metrics over a data-graph, and the comparison of two of them.

Objective 5 asks for quality metrics comparing an original knowledge graph with its
repaired form. `docs/quality_metrics.md` is the design note: it gives each metric a
formal definition, says what it is sensitive to and blind to, cites where the
dimension comes from, and commits to a predicted direction under each engine. This
module implements the offline half of that note. Read the note first; the docstrings
here do not repeat its arguments.

Three things this module deliberately does not do.

  * It does not recount violations. Consistency comes from `Validator`, through the
    same `check_one` every other caller uses, and the antecedent extension needed for
    the satisfaction fraction is read off the validator's own evaluator. There is no
    second implementation of `[[phi]] \\ [[psi]]` anywhere in the toolkit.
  * It does not reach the network. Accuracy of additions against the source is the one
    metric that needs a source query, and it lives in `scripts/`, not here.
  * It does not assume a vocabulary. Instance and subclass predicates are parameters
    with defaults, so a graph whose typing spine is `ex:isa` and `ex:kindOf` measures
    the same way a Wikidata slice does. `tests/test_metrics.py` checks that on a
    synthetic graph with no domain semantics and on all three real sources.

Every metric is computed on ONE graph. Comparing two is `compare_metrics`, which is
the only place in the toolkit where a metric delta is computed.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass, fields
from typing import Dict, FrozenSet, Iterable, List, Optional, Set, Tuple

from .constraints.model import ConstraintSet
from .datagraph import DataGraph
from .validator import Validator

#: Edge labels whose object is the subject's class. Split out from the loader's
#: `DEFAULT_TYPE_PREDICATES`, which lumps instance-of and subclass-of together because
#: for its purposes both make the object self-valued. Here the two play different
#: roles, so they are separate parameters.
DEFAULT_INSTANCE_OF = frozenset({"rdf:type", "wdt:P31"})

#: Edge labels forming the class hierarchy.
DEFAULT_SUBCLASS_OF = frozenset({"rdfs:subClassOf", "wdt:P279", "schema:subClassOf"})

#: A class with fewer instances than this is excluded from property coverage: with one
#: instance every coverage is 1.0 by construction and says nothing about the data.
MIN_INSTANCES_FOR_COVERAGE = 2


def split_type_predicates(type_predicates: Optional[Iterable[str]] = None
                          ) -> Tuple[FrozenSet[str], FrozenSet[str]]:
    """Split a loader-style combined type-predicate set into (instance_of, subclass_of).

    The loader takes one set, because for its purposes instance-of and subclass-of
    behave the same: both make the object self-valued. The metrics need the two apart,
    and a caller who passed `--type-predicate` has named their spine without saying
    which half is which.

    The rule is: a label already known to be a subclass predicate is one; everything
    else is treated as instance-of. So a Wikidata caller passing the default set
    explicitly gets the correct split, and a caller with a custom spine gets every
    label read as instance-of and **no hierarchy at all**.

    That last part is a stated limitation, not an accident. Without being told which
    of `ex:isa` and `ex:kindOf` is the hierarchy, the honest reading is that there is
    none, so `redundant_type_edges` comes back 0 rather than wrong. A caller who wants
    the hierarchy measured passes `instance_of` and `subclass_of` to `compute_metrics`
    directly, which is why those remain the real parameters.
    """
    if type_predicates is None:
        return DEFAULT_INSTANCE_OF, DEFAULT_SUBCLASS_OF
    given = frozenset(type_predicates)
    subclass = given & DEFAULT_SUBCLASS_OF
    return given - subclass, subclass


@dataclass(frozen=True)
class GraphMetrics:
    """Every offline metric for one graph. Named fields, never a loose dict.

    The consistency block is `None` when no constraint set was supplied, which is a
    real state: a graph can be measured for size and completeness without a theory to
    check it against, and that is what the synthetic sanity check in T5 does.
    """

    # ---- conciseness -------------------------------------------------------
    nodes: int
    edges: int
    labels: int
    valued_nodes: int
    redundant_type_edges: int
    singleton_classes: int

    # ---- completeness ------------------------------------------------------
    typed_nodes: int
    typed_node_fraction: float
    classes: int
    classes_scored_for_coverage: int
    class_property_pairs: int
    property_coverage_mean: Optional[float]

    # ---- consistency (None when no constraint set was given) ---------------
    constraints_checked: Optional[int] = None
    violations_total: Optional[int] = None
    violated_constraints: Optional[int] = None
    witness_nodes: Optional[int] = None
    witness_node_fraction: Optional[float] = None
    violations_by_tier: Optional[Dict[str, int]] = None
    satisfaction_mean: Optional[float] = None
    satisfaction_scored: Optional[int] = None

    #: Which vocabulary the measurement used, so a number can be read back later.
    instance_of: Tuple[str, ...] = ()
    subclass_of: Tuple[str, ...] = ()

    def to_dict(self) -> Dict:
        return asdict(self)


def _spine(graph: DataGraph, instance_of: FrozenSet[str], subclass_of: FrozenSet[str]
           ) -> Tuple[Dict[str, Set[str]], Dict[str, Set[str]]]:
    """(node -> its direct classes, class -> its direct superclasses).

    One pass over `graph.edges()`, through the public accessor rather than the
    adjacency maps, so this module does not depend on how `DataGraph` stores itself.
    """
    types: Dict[str, Set[str]] = defaultdict(set)
    parents: Dict[str, Set[str]] = defaultdict(set)
    for src, label, dst in graph.edges():
        if label in instance_of:
            types[src].add(dst)
        elif label in subclass_of:
            parents[src].add(dst)
    return types, parents


def _closure(parents: Dict[str, Set[str]]) -> Dict[str, Set[str]]:
    """class -> every proper or improper superclass, over the subclass predicates."""
    cache: Dict[str, Set[str]] = {}

    def ancestors(cls: str) -> Set[str]:
        got = cache.get(cls)
        if got is not None:
            return got
        seen = {cls}
        stack = [cls]
        while stack:
            node = stack.pop()
            for parent in parents.get(node, ()):
                if parent not in seen:
                    seen.add(parent)
                    stack.append(parent)
        cache[cls] = seen
        return seen

    for cls in list(parents):
        ancestors(cls)
    return cache


def _redundant_type_edges(types: Dict[str, Set[str]],
                          closure: Dict[str, Set[str]]) -> int:
    """Type edges whose class is already implied by a more specific type on the same
    node. `v isa Dog` and `v isa Animal` with `Dog subclass-of* Animal` makes the
    second edge carry nothing."""
    redundant = 0
    for _node, classes in types.items():
        if len(classes) < 2:
            continue
        for cls in classes:
            for other in classes:
                if other != cls and cls in closure.get(other, {other}):
                    redundant += 1
                    break
    return redundant


def _property_coverage(graph: DataGraph, types: Dict[str, Set[str]],
                       instance_of: FrozenSet[str], subclass_of: FrozenSet[str],
                       min_instances: int) -> Tuple[int, int, Optional[float]]:
    """(classes scored, (class, predicate) pairs, instance-weighted mean coverage).

    Instances are direct instances only, so the hierarchy does not confound the
    measure. Coverage of `(C, p)` is the share of C's instances with an outgoing `p`.
    A predicate no instance of C carries is not a pair: the local closed-world
    assumption reads silence about a predicate nobody uses as "not part of this
    class", and only silence about a predicate some instances DO carry as
    incompleteness. That assumption is stated in `docs/quality_metrics.md`.
    """
    instances: Dict[str, Set[str]] = defaultdict(set)
    for node, classes in types.items():
        for cls in classes:
            instances[cls].add(node)

    payload = frozenset(graph.labels) - instance_of - subclass_of
    weighted_sum = 0.0
    weight_total = 0
    pairs = 0
    scored_classes = 0
    for cls in sorted(instances):
        members = instances[cls]
        if len(members) < min_instances:
            continue
        scored_classes += 1
        for pred in sorted(payload):
            carriers = sum(1 for m in members if graph.succ(pred, m))
            if carriers == 0:
                continue                       # not a property of this class at all
            pairs += 1
            weighted_sum += (carriers / len(members)) * len(members)
            weight_total += len(members)
    mean = (weighted_sum / weight_total) if weight_total else None
    return scored_classes, pairs, mean


def compute_metrics(graph: DataGraph,
                    constraints: Optional[ConstraintSet] = None, *,
                    instance_of: Optional[Iterable[str]] = None,
                    subclass_of: Optional[Iterable[str]] = None,
                    min_instances: int = MIN_INSTANCES_FOR_COVERAGE,
                    use_closure: bool = True) -> GraphMetrics:
    """Every offline metric for `graph`, against `constraints` where one is given.

    Supplying no constraint set leaves the consistency block `None` rather than zero:
    "no theory to check against" and "checked and found consistent" are different
    states and the record says which.
    """
    inst = frozenset(instance_of) if instance_of is not None else DEFAULT_INSTANCE_OF
    sub = frozenset(subclass_of) if subclass_of is not None else DEFAULT_SUBCLASS_OF

    stats = graph.stats()
    types, parents = _spine(graph, inst, sub)
    closure = _closure(parents)
    typed = len(types)
    node_count = stats["nodes"]

    class_set: Set[str] = set()
    for classes in types.values():
        class_set |= classes
    instance_count: Dict[str, int] = defaultdict(int)
    for classes in types.values():
        for cls in classes:
            instance_count[cls] += 1
    singletons = sum(1 for cls in class_set if instance_count[cls] == 1)

    scored_classes, pairs, coverage_mean = _property_coverage(
        graph, types, inst, sub, min_instances)

    common = {
        "nodes": node_count,
        "edges": stats["edges"],
        "labels": stats["labels"],
        "valued_nodes": stats["valued_nodes"],
        "redundant_type_edges": _redundant_type_edges(types, closure),
        "singleton_classes": singletons,
        "typed_nodes": typed,
        "typed_node_fraction": (typed / node_count) if node_count else 0.0,
        "classes": len(class_set),
        "classes_scored_for_coverage": scored_classes,
        "class_property_pairs": pairs,
        "property_coverage_mean": coverage_mean,
        "instance_of": tuple(sorted(inst)),
        "subclass_of": tuple(sorted(sub)),
    }
    if constraints is None:
        return GraphMetrics(**common)

    validator = Validator(graph, use_closure=use_closure)
    report = validator.validate(constraints)
    witnesses: Set[str] = set()
    satisfaction: List[float] = []
    for violation in report.violations:
        witnesses |= violation.witnesses
        if violation.constraint.tier != "ptime_core":
            continue
        # The antecedent extension comes off the validator's own evaluator, so there
        # is no second implementation of the semantics here. A constraint whose
        # antecedent matches nothing is left unscored rather than scored 1.0: a rule
        # about nothing is unjudged, not satisfied.
        antecedent = validator.ev.eval_node(violation.constraint.phi)
        if antecedent:
            satisfaction.append((len(antecedent) - violation.count) / len(antecedent))

    return GraphMetrics(
        **common,
        constraints_checked=len(report.violations),
        violations_total=report.total_witnesses(),
        violated_constraints=len(report.failing()),
        witness_nodes=len(witnesses),
        witness_node_fraction=(len(witnesses) / node_count) if node_count else 0.0,
        violations_by_tier=report.by_tier(),
        satisfaction_mean=(sum(satisfaction) / len(satisfaction)) if satisfaction else None,
        satisfaction_scored=len(satisfaction),
    )


 
# comparison
 
@dataclass(frozen=True)
class MetricChange:
    """One metric's movement. `relative` is `None` where the before value is zero or
    absent, because a ratio against nothing is not a number."""
    before: Optional[float]
    after: Optional[float]
    absolute: Optional[float]
    relative: Optional[float]

    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass(frozen=True)
class MetricComparison:
    """Per-metric change between two graphs, plus the two records it came from.

    The only place in the toolkit where a metric delta is computed. A caller that
    wants to know what a repair did to a graph reads this, so two callers cannot
    subtract differently.
    """
    before: GraphMetrics
    after: GraphMetrics
    changes: Dict[str, MetricChange]

    def to_dict(self) -> Dict:
        return {"before": self.before.to_dict(), "after": self.after.to_dict(),
                "changes": {k: v.to_dict() for k, v in sorted(self.changes.items())}}


#: Fields a delta is meaningful for. The vocabulary tuples and the by-tier dict are
#: not numbers and are carried in `before`/`after` instead of being subtracted.
_COMPARABLE = tuple(
    f.name for f in fields(GraphMetrics)
    if f.name not in ("instance_of", "subclass_of", "violations_by_tier"))


def compare_metrics(before: GraphMetrics, after: GraphMetrics) -> MetricComparison:
    """Per-metric absolute and relative change from `before` to `after`.

    A metric that is `None` on either side yields a change with `None` in the
    corresponding slot rather than being dropped, so the set of keys does not depend
    on the data and two comparisons are always the same shape.
    """
    if before.instance_of != after.instance_of or before.subclass_of != after.subclass_of:
        raise ValueError(
            "the two records were measured with different typing vocabularies, so "
            "their differences would not mean anything")

    changes: Dict[str, MetricChange] = {}
    for name in _COMPARABLE:
        lhs, rhs = getattr(before, name), getattr(after, name)
        absolute = (rhs - lhs) if (lhs is not None and rhs is not None) else None
        relative = (absolute / lhs) if (absolute is not None and lhs) else None
        changes[name] = MetricChange(before=lhs, after=rhs, absolute=absolute,
                                     relative=relative)
    return MetricComparison(before=before, after=after, changes=changes)


def metric_field_names() -> Tuple[str, ...]:
    """Every field on `GraphMetrics`, for callers that render a table."""
    return tuple(f.name for f in fields(GraphMetrics))


def repair_metrics_block(before: DataGraph, after: Optional[DataGraph],
                         constraints: Optional[ConstraintSet] = None,
                         **kwargs) -> Dict:
    """The `metrics` section of a repair report: both records and the comparison.

    Assembled here rather than in the command line or the viewer, so the two cannot
    describe the same run differently. That is the entry-point parity rule
    applied to a new field: a caller adds this block, it does not build one.

    `after` is `None` for a run the cap aborted, where there is no repaired graph to
    measure. The three keys are present either way, so a reader parsing the report
    does not have to branch on whether an engine ran.
    """
    record = compute_metrics(before, constraints, **kwargs)
    if after is None:
        return {"before": record.to_dict(), "after": None, "changes": None}
    return compare_metrics(record, compute_metrics(after, constraints, **kwargs)).to_dict()
