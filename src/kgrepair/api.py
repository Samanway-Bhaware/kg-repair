"""
The public API of the kgrepair package.

Everything a caller needs to load a graph, load or author constraints, check
consistency, repair, and write the result back out is re-exported here and from
`kgrepair` itself. The command-line interface and the Streamlit viewer are thin
skins over exactly this surface; they do not reach into private internals, and
neither should anything else.

Dataset guarantees (established here so every skin inherits them)
-----------------------------------------------------------------
* **Loader neutrality.** `load_graph` / `load_graph_string` preserve arbitrary
  IRIs and CURIEs verbatim. No prefix is expanded or abbreviated on this path.
  IRI-to-CURIE abbreviation belongs to the extraction pipeline
  (`kgrepair.pipeline.slicing`) and is never applied to a raw file load.
* **No extraction coupling.** `validate`, `subset_repair` and `superset_repair`
  take a `DataGraph` and a `ConstraintSet` and nothing else. They never require a
  slice manifest, an `allowlist_id`, an allow-list hash, or the corpus deny-check.
* **Predicate neutrality.** No knowledge-graph-specific predicate is written into
  the graph model, the validator, or the repair engines. Typing predicates such
  as `wdt:P31` or `rdf:type` appear only inside authored constraint files (as the
  `tau_C` class test), which are data, and in the loader's overridable
  `DEFAULT_TYPE_PREDICATES` default. Any knowledge graph with any vocabulary can
  be repaired by authoring a constraint file that names its own predicates.
* **Determinism.** No wall-clock reading and no randomness on any library output
  path; change logs and serialisations are emitted in a canonical order.

Public surface
--------------
Version
    `__version__`
Graphs
    `DataGraph`, `load_graph`, `load_graph_string`, `to_ntriples`,
    `write_ntriples`, `DEFAULT_TYPE_PREDICATES`
Constraints
    `Constraint`, `ConstraintSet`, `load_constraint_file`,
    `save_constraint_file`, `constraints` (the built-in registry subpackage)
Checking
    `Validator`, `ValidationReport`, `Violation`, `validate`
Repair
    `subset_repair`, `SubsetRepairResult`, `superset_repair`,
    `SupersetRepairResult`, `ChangeRecord`
Safety caps (decide whether to run a repair before running it)
    `check_cap`, `CapDecision`, `subset_witness_fraction`,
    `superset_addition_fraction`, `SUBSET_CAP_DEFAULT`, `SUPERSET_CAP_DEFAULT`,
    `ABORTED_BY_CAP`
Inspection
    `extract_neighbourhood`, `NeighbourhoodView`, `NVNode`, `NVEdge`,
    `change_record_center`, `DEFAULT_K`, `DEFAULT_NODE_CAP`
Quality metrics (Objective 5; see `docs/quality_metrics.md` for the definitions)
    `compute_metrics`, `GraphMetrics`, `compare_metrics`, `MetricComparison`,
    `MetricChange`, `repair_metrics_block`, `metric_field_names`,
    `DEFAULT_INSTANCE_OF`, `DEFAULT_SUBCLASS_OF`
Reporting
    `report_envelope`
Output bundle (the repaired graph, a reversible diff, the report, the rules)
    `write_bundle`, `zip_bundle`, `diff_lines`, `reconstruct_input`,
    `bundle_summary`
Run recording (optional; writes a JSONL record per run)
    `RunContext`, `constraints_meta`, `slice_meta_from_graph`, `code_revision`
Constraint derivation and the review airlock
    `derive_candidate_file`, `fill_impact`, `read_candidate_file`,
    `write_canonical`,
    `merge_candidates`, `set_status`, `seal_candidates`, `reviewed_constraint_set`,
    `graph_content_hash`, `Candidate`, `CandidateFile`, `CandidateGateError` and
    its subclasses. Derivation proposes and a person decides; no score authorises
    a repair on its own.
Optional filtering
    `apply_allowlist`, `load_allowlist_file`, `AllowList`

Anything not listed above is internal and unstable. In particular
`kgrepair.gxpath`, `kgrepair.pipeline`, `kgrepair.synthetic` and
`kgrepair.derive` are supporting machinery whose signatures may change without
notice. The `neighbourhood` and `instrument` modules are partly promoted: the
names listed above are supported, the rest of those modules (the JSONL log
summarisers in particular) is not.
"""
from __future__ import annotations

import os
from typing import Iterable, Optional, Tuple

from . import constraints
from .bundle import (bundle_summary, diff_lines, reconstruct_input,
                     write_bundle, zip_bundle)
from .caps import (ABORTED_BY_CAP, SUBSET_CAP_DEFAULT, SUPERSET_CAP_DEFAULT,
                   CapDecision, check_cap, superset_addition_fraction,
                   subset_witness_fraction)
from .candidates import (Candidate, CandidateFile, merge_candidates,
                         read_candidate_file, seal_candidates, set_status,
                         write_canonical)
from .constraints.model import Constraint, ConstraintSet
from .datagraph import DataGraph
from .instrument import (RunContext, code_revision, constraints_meta,
                         slice_meta_from_graph)
from .metrics import (DEFAULT_INSTANCE_OF, DEFAULT_SUBCLASS_OF, GraphMetrics,
                      MetricChange, MetricComparison, compare_metrics,
                      compute_metrics, metric_field_names, repair_metrics_block,
                      split_type_predicates)
from .neighbourhood import (DEFAULT_K, DEFAULT_NODE_CAP, NeighbourhoodView, NVEdge,
                            NVNode, change_record_center, extract_neighbourhood)
from .ntriples import (DEFAULT_TYPE_PREDICATES, load_ntriples, load_ntriples_file,
                       to_ntriples)
from .pipeline.allowlist import AllowList, load_allowlist_file
from .proposals import derive_candidate_file, fill_impact
from .repair import (ChangeRecord, SubsetRepairResult, SupersetRepairResult,
                     subset_repair, superset_repair)
from .review import (BoundaryNotRepairable, CandidateGateError, NotSealed,
                     NothingAccepted, OutOfFragment, ReviewIncomplete, SealMismatch,
                     SourceDrift, attach_review_attestations, graph_content_hash,
                     reviewed_constraint_set)
from .validator import ValidationReport, Validator, Violation


 
# graphs
 
def load_graph(path: str, *, type_predicates: Optional[Iterable[str]] = None) -> DataGraph:
    """Load an N-Triples file into a `DataGraph`.

    IRIs and CURIEs are kept exactly as written. `type_predicates` names the
    typing/subclass spine of the source graph, whose object nodes are self-valued
    so that class tests can match them; it defaults to `DEFAULT_TYPE_PREDICATES`.
    """
    return load_ntriples_file(path, type_predicates=type_predicates)


def load_graph_string(text: str, *,
                      type_predicates: Optional[Iterable[str]] = None) -> DataGraph:
    """Load N-Triples from an in-memory string. See `load_graph`."""
    return load_ntriples(text.splitlines(), type_predicates=type_predicates)


def write_ntriples(graph: DataGraph, path: str) -> str:
    """Serialise `graph` to an N-Triples file; return the path written.

    Companion to `load_graph`: the pair round-trips a repaired graph. Use
    `to_ntriples` for the string form.
    """
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(to_ntriples(graph))
    return path


 
# constraints
 
def load_constraint_file(path: str, *, compile_now: bool = False) -> ConstraintSet:
    """Load a user-authored JSON constraint file into a `ConstraintSet`.

    This is the entry point for your own constraints over your own knowledge
    graph, as distinct from `constraints.get(domain, kg)`, which returns one of
    the built-in sets shipped with the toolkit. The file format is what
    `save_constraint_file` writes: a `slice` name and a list of constraint
    dictionaries in `Constraint.to_dict()` form.

    With `compile_now=True` every expression is parsed immediately, so anything
    that leaves the positive fragment (negation, path complement, disequality)
    raises a `ParseError` here rather than at first evaluation.
    """
    cs = ConstraintSet.from_file(path)
    if compile_now:
        cs.compile_all()
    return cs


def save_constraint_file(cs: ConstraintSet, path: str, *, indent: int = 2) -> str:
    """Write a `ConstraintSet` to a JSON constraint file; return the path written."""
    return cs.to_file(path, indent=indent)


 
# checking
 
def validate(graph: DataGraph, cs, *, use_closure: bool = False) -> ValidationReport:
    """Check `graph` against every constraint in `cs`, returning a report.

    A constraint `phi subset psi` is violated by the nodes in the difference
    `[[phi]] \\ [[psi]]`. Both tiers are checked; the report separates them via
    `by_tier()`, and only `ptime_core` violations are ones the repair engines act
    on. `use_closure` enables the evaluator's subclass-closure memoisation, which
    changes running time but never the result.
    """
    return Validator(graph, use_closure=use_closure).validate(cs)


 
# reporting
 
def report_envelope(subcommand: str, *, constraints_source: str, input_name: str,
                    type_predicates, allowlist_applied: bool = False,
                    allowlist_edges_dropped: int = 0) -> dict:
    """The wrapper a skin puts around an API object's own `to_dict()`.

    Shared by the command-line interface and the viewer so that the same run is
    described identically by both: the body under `result` is always the API
    object's serialisation untouched, and this is the only thing added around it.

    Carries no absolute path and reads no clock, so two runs over the same inputs
    produce identical bytes. `input_name` should already be a basename;
    `type_predicates` is the effective set actually used for the load.
    """
    from . import __version__
    env = {
        "tool_version": __version__,
        "subcommand": subcommand,
        "constraints_source": constraints_source,
        "input_basename": os.path.basename(input_name),
        "type_predicates": sorted(type_predicates),
        "allowlist_applied": allowlist_applied,
    }
    if allowlist_applied:
        env["allowlist_edges_dropped"] = allowlist_edges_dropped
    return env


 
# optional user-supplied predicate filter
 
def apply_allowlist(graph: DataGraph, allowlist) -> Tuple[DataGraph, int]:
    """Drop every edge whose predicate is not on a user-supplied allow-list.

    `allowlist` may be a path to an allow-list JSON file, an `AllowList` object,
    or any iterable of predicate labels. Returns `(filtered_graph, dropped_count)`;
    the input graph is not modified. Nodes are preserved, only edges are dropped,
    so a node that loses all its edges survives as an isolated node.

    This is entirely opt-in. Loading, validating and repairing do no filtering
    unless you call this yourself, and no other function calls it for you.

    It is a convenience filter over predicate names and **carries no personal-data
    guarantee**. Whether a given predicate set is appropriate for your data, your
    ethics approval, or your jurisdiction is your judgement to make, not
    something this function establishes.
    """
    if isinstance(allowlist, AllowList):
        allowed = set(allowlist.predicates)
    elif isinstance(allowlist, str):
        allowed = set(load_allowlist_file(allowlist).predicates)
    else:
        allowed = set(allowlist)

    out = DataGraph()
    for v in sorted(graph.nodes):
        out.add_node(v, graph.value(v))
    dropped = 0
    for s, p, o in sorted(graph.edges()):
        if p in allowed:
            out.add_edge(s, p, o)
        else:
            dropped += 1
    return out, dropped


__all__ = [
    "DataGraph",
    "load_graph",
    "load_graph_string",
    "load_ntriples",
    "load_ntriples_file",
    "to_ntriples",
    "write_ntriples",
    "DEFAULT_TYPE_PREDICATES",
    "Constraint",
    "ConstraintSet",
    "constraints",
    "load_constraint_file",
    "save_constraint_file",
    "Validator",
    "ValidationReport",
    "Violation",
    "validate",
    "subset_repair",
    "SubsetRepairResult",
    "superset_repair",
    "SupersetRepairResult",
    "ChangeRecord",
    "check_cap",
    "CapDecision",
    "subset_witness_fraction",
    "superset_addition_fraction",
    "SUBSET_CAP_DEFAULT",
    "SUPERSET_CAP_DEFAULT",
    "ABORTED_BY_CAP",
    "extract_neighbourhood",
    "NeighbourhoodView",
    "NVNode",
    "NVEdge",
    "change_record_center",
    "DEFAULT_K",
    "DEFAULT_NODE_CAP",
    "report_envelope",
    "compute_metrics",
    "GraphMetrics",
    "compare_metrics",
    "MetricComparison",
    "MetricChange",
    "repair_metrics_block",
    "metric_field_names",
    "split_type_predicates",
    "DEFAULT_INSTANCE_OF",
    "DEFAULT_SUBCLASS_OF",
    "write_bundle",
    "zip_bundle",
    "diff_lines",
    "reconstruct_input",
    "bundle_summary",
    "derive_candidate_file",
    "fill_impact",
    "read_candidate_file",
    "write_canonical",
    "merge_candidates",
    "set_status",
    "seal_candidates",
    "reviewed_constraint_set",
    "graph_content_hash",
    "attach_review_attestations",
    "Candidate",
    "CandidateFile",
    "CandidateGateError",
    "NotSealed",
    "ReviewIncomplete",
    "SealMismatch",
    "SourceDrift",
    "OutOfFragment",
    "BoundaryNotRepairable",
    "NothingAccepted",
    "RunContext",
    "constraints_meta",
    "slice_meta_from_graph",
    "code_revision",
    "apply_allowlist",
    "load_allowlist_file",
    "AllowList",
]
