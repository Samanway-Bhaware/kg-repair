"""
kgrepair -- a reusable toolkit for polynomial-time set repairs of knowledge graphs.

Implements the tractable core of Abriola, Martinez, Pardal, Cifuentes & Pin Baque,
"On the Complexity of Finding Set Repairs for Data-Graphs" (JAIR 76, 2023):
the positive fragment Reg-GXPath_pos, a sparse evaluator, a validator, the two
polynomial-time repair engines, and constraint definitions for the geography /
taxa / anatomy / disease / medication slices over Wikidata, DBpedia, and YAGO 4.5.

Quick start
-----------
    import kgrepair

    g  = kgrepair.load_graph("slice.nt")
    cs = kgrepair.load_constraint_file("my_constraints.json")

    report = kgrepair.validate(g, cs)
    if not report.consistent:
        result = kgrepair.superset_repair(g, cs)      # fix by addition
        # or   kgrepair.subset_repair(g, cs)          # fix by deletion
        kgrepair.write_ntriples(result.graph, "repaired.nt")

The built-in constraint sets are reached through the `constraints` subpackage,
`kgrepair.constraints.get(domain, kg)`. User-authored constraint files go through
`load_constraint_file`, which does not depend on them.

Public API
----------
The names in `__all__` below, and only those, are the supported surface. They are
documented in `kgrepair.api`, which also records the toolkit's dataset-agnosticism
guarantees: loader neutrality, no extraction coupling, predicate neutrality, and
determinism. Anything not listed -- including the `gxpath`, `pipeline`,
`instrument`, `synthetic`, `derive` and `neighbourhood` modules -- is internal and
may change without notice.

The core has no third-party runtime dependencies. The optional extras (`eval` for
the reporting figures, `viewer` for the Streamlit app, `dev` for pytest) are never
imported from this package.

Deliverable map (proposal numbering):
    D2  constraints/          constraint definitions for the three datasets
    D3  design/               pseudocode + repair design document
    D4  datagraph, ntriples,  graph loader, parser, validator
        gxpath/, validator
    D5  repair/subset.py      SubsetRepair (Algorithm 1)
    D6  repair/superset.py    SupersetRepair (Algorithm 2)
"""
__version__ = "0.5.0"

from . import constraints
from .api import (ABORTED_BY_CAP, AllowList, BoundaryNotRepairable, Candidate,
                  CandidateFile, CandidateGateError, CapDecision, ChangeRecord,
                  Constraint, ConstraintSet, DEFAULT_INSTANCE_OF, DEFAULT_K,
                  DEFAULT_NODE_CAP, DEFAULT_SUBCLASS_OF,
                  DEFAULT_TYPE_PREDICATES, DataGraph, GraphMetrics, MetricChange,
                  MetricComparison, NVEdge, NVNode, NeighbourhoodView,
                  NotSealed, NothingAccepted, OutOfFragment, ReviewIncomplete,
                  RunContext, SUBSET_CAP_DEFAULT, SUPERSET_CAP_DEFAULT, SealMismatch,
                  SourceDrift, SubsetRepairResult, SupersetRepairResult,
                  ValidationReport, Validator, Violation, apply_allowlist,
                  attach_review_attestations, bundle_summary, change_record_center,
                  check_cap, compare_metrics, compute_metrics, diff_lines,
                  code_revision, constraints, constraints_meta, derive_candidate_file,
                  extract_neighbourhood, fill_impact, graph_content_hash,
                  load_allowlist_file,
                  load_constraint_file, load_graph, load_graph_string, load_ntriples,
                  load_ntriples_file, merge_candidates, metric_field_names,
                  read_candidate_file, repair_metrics_block, split_type_predicates,
                  reconstruct_input, report_envelope, reviewed_constraint_set,
                  save_constraint_file,
                  seal_candidates, set_status, slice_meta_from_graph, subset_repair,
                  subset_witness_fraction, superset_addition_fraction, superset_repair,
                  to_ntriples, validate, write_bundle, write_canonical, write_ntriples,
                  zip_bundle)

__all__ = [
    "__version__",
    # graphs
    "DataGraph",
    "load_graph",
    "load_graph_string",
    "load_ntriples",
    "load_ntriples_file",
    "to_ntriples",
    "write_ntriples",
    "DEFAULT_TYPE_PREDICATES",
    # constraints
    "Constraint",
    "ConstraintSet",
    "constraints",
    "load_constraint_file",
    "save_constraint_file",
    # checking
    "Validator",
    "ValidationReport",
    "Violation",
    "validate",
    # repair
    "subset_repair",
    "SubsetRepairResult",
    "superset_repair",
    "SupersetRepairResult",
    "ChangeRecord",
    # safety caps: decide whether to run a repair before running it
    "check_cap",
    "CapDecision",
    "subset_witness_fraction",
    "superset_addition_fraction",
    "SUBSET_CAP_DEFAULT",
    "SUPERSET_CAP_DEFAULT",
    "ABORTED_BY_CAP",
    # inspection
    "extract_neighbourhood",
    "NeighbourhoodView",
    "NVNode",
    "NVEdge",
    "change_record_center",
    "DEFAULT_K",
    "DEFAULT_NODE_CAP",
    # reporting
    "report_envelope",
    # quality metrics
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
    # run recording (optional)
    "RunContext",
    "constraints_meta",
    "slice_meta_from_graph",
    "code_revision",
    # constraint derivation and the review airlock
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
    # optional user-supplied predicate filter
    "apply_allowlist",
    "load_allowlist_file",
    "AllowList",
]
