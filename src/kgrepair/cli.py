"""
Command-line interface: `kgrepair check` and `kgrepair repair`.

A thin skin over the public API in `kgrepair.api`. This module parses arguments,
reads and writes files, and serialises results the API already produces. It holds
no repair, validation, cap, or serialisation logic of its own: the report body
under `result` is the API object's own `to_dict()` verbatim, so the command line
and the viewer cannot drift into different answers about the same graph.

Exit codes
----------
`check`
    0   no ptime_core violations
    2   one or more ptime_core violations
    1   usage or I/O error

    Boundary-tier violations (symmetry, inverse, functional, cardinality, safety
    edges) are reported but never on their own cause exit 2. They are report-only
    by design, so a graph that fails only boundary rules still exits 0.

`repair`
    0   repaired, and the result attests consistency afterwards
    3   ABORTED-BY-CAP: the repair would touch more of the graph than the cap
        allows, so no engine was run and no graph was written
    2   the engine ran but did not attest consistency afterwards
    1   usage or I/O error
    4   a candidate file was refused before any engine ran. The cause is the
        error code in the message: E-UNSEALED, E-PENDING, E-SEAL, E-DRIFT,
        E-FRAGMENT, E-BOUNDARY or E-EMPTY

`derive`
    0   candidates written
    3   nothing cleared the support and confidence floors
    1   usage or I/O error

`review`
    0   every entry decided and the file sealed
    2   quit with entries still undecided, so the file was not sealed
    1   usage or I/O error

Derived constraints never reach an engine on a score alone. `derive` proposes,
`review` records a person's decision on every entry and seals the file, and
`repair --constraints` refuses anything that did not go through both.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import List, Optional

from . import constraints as _constraints
from .api import (DEFAULT_TYPE_PREDICATES, apply_allowlist,
                  attach_review_attestations, check_cap, derive_candidate_file,
                  load_constraint_file, load_graph, merge_candidates,
                  fill_impact, read_candidate_file, repair_metrics_block,
                  report_envelope, compute_metrics, split_type_predicates,
                  reviewed_constraint_set,
                  seal_candidates, set_status, subset_repair, superset_repair,
                  validate, write_canonical, write_ntriples)
from .candidates import ACCEPTED, REJECTED, WEAKENED, CandidateFile
from .derive import GENERATORS, SEARCH, DeriveConfig
from .review import CandidateGateError
from .bundle import bundle_summary, write_bundle, zip_bundle
from .caps import SUBSET_CAP_DEFAULT, SUPERSET_CAP_DEFAULT

EXIT_OK = 0
EXIT_USAGE = 1
EXIT_VIOLATIONS = 2
EXIT_CAPPED = 3
#: The whole pre-flight refusal class for a candidate file: not sealed, entries
#: still pending, seal does not recompute, source hash drift, out of fragment, or
#: boundary tier. One code, because every one of them means the gate refused
#: before an engine ran. The specific cause is the error code in the message
#: (E-UNSEALED, E-PENDING, E-SEAL, E-DRIFT, E-FRAGMENT, E-BOUNDARY, E-EMPTY),
#: which keeps the causes distinguishable without burning further exit codes.
EXIT_GATE_REFUSED = 4
#: derive found nothing that cleared the support and confidence floors.
EXIT_NO_CANDIDATES = 3
#: review was quit with entries still undecided, so the file was not sealed.
EXIT_REVIEW_PENDING = 2

_NO_CONSTRAINTS = (
    "no constraints given: pass --constraints PATH for your own constraint file, "
    "or --domain D --kg K to use one of the built-in sets "
    "(see `kgrepair check --help` for what is available). "
    "Deriving constraints from the data automatically is not wired into this "
    "command; author a constraint file instead."
)


class _CliError(Exception):
    """A usage or I/O problem to report on stderr and exit 1 for."""


 
# parser
 
def _add_common(sub: argparse.ArgumentParser) -> None:
    sub.add_argument("--in", dest="graph_path", metavar="PATH", required=True,
                     help="N-Triples graph to read")
    src = sub.add_mutually_exclusive_group()
    src.add_argument("--constraints", metavar="PATH",
                     help="your own JSON constraint file")
    src.add_argument("--domain", metavar="D",
                     help="built-in constraint domain (geography, taxa, anatomy, "
                          "disease, medication); use with --kg")
    sub.add_argument("--kg", metavar="K",
                     help="built-in constraint knowledge graph (wikidata, dbpedia, "
                          "yago); use with --domain")
    sub.add_argument("--version", type=int, default=1, metavar="N",
                     help="built-in constraint set version (default: 1)")
    sub.add_argument("--type-predicate", dest="type_predicates", action="append",
                     metavar="LABEL",
                     help="edge label that types a node, repeatable. Names the typing "
                          "spine of YOUR graph (for example ex:isa) so class tests can "
                          "reach it. When omitted, the loader's default vocabulary is "
                          "used, which covers rdf:type/rdfs:subClassOf and the Wikidata "
                          "spine")
    sub.add_argument("--allowlist", metavar="PATH",
                     help="opt-in: drop every edge whose predicate is not in this "
                          "allow-list file of yours, before checking or repairing. Off "
                          "unless given. It filters predicate names you chose and "
                          "nothing more")
    sub.add_argument("--report", metavar="PATH",
                     help="write the JSON report here (default: stdout)")
    sub.add_argument("--indent", type=int, default=2, metavar="N",
                     help="JSON indent for the report (default: 2)")


def build_parser() -> argparse.ArgumentParser:
    """The full argument parser. Exposed so `--help` output can be tested."""
    p = argparse.ArgumentParser(
        prog="kgrepair",
        description="Check and repair knowledge graphs against Reg-GXPath_pos "
                    "containment constraints.")
    subs = p.add_subparsers(dest="subcommand",
                            metavar="{check,repair,metrics,derive,review}")

    check = subs.add_parser(
        "check", help="report constraint violations; write no graph",
        description="Load a graph, check it against a constraint set, and write a "
                    "JSON violation report. Exits 2 when any ptime_core constraint "
                    "is violated. Boundary-tier constraints are reported but are "
                    "never on their own a reason to exit 2.")
    _add_common(check)
    check.add_argument("--witness-limit", type=int, default=10, metavar="N",
                       help="how many witnesses to list per constraint; the true "
                            "count is always reported (default: 10, negative for all)")

    repair = subs.add_parser(
        "repair", help="repair the graph and write the result",
        description="Load a graph, repair it under the ptime_core constraints, write "
                    "the repaired graph as N-Triples, and write a JSON change report. "
                    "Exits 3 without running any engine when the repair would touch "
                    "more of the graph than the safety cap allows.")
    _add_common(repair)
    repair.add_argument("--mode", choices=("subset", "superset"), required=True,
                        help="subset repairs by deleting nodes, superset by adding "
                             "structure")
    repair.add_argument("--out", metavar="PATH",
                        help="write the repaired graph here, as N-Triples. Either "
                             "this or --bundle is required")
    repair.add_argument("--bundle", metavar="DIR",
                        help="write a bundle directory: the repaired graph, a "
                             "reversible statement-level diff, the JSON report, and "
                             "a copy of the constraint file that drove the run")
    repair.add_argument("--zip", dest="zip_bundle", action="store_true",
                        help="also pack the bundle directory into one archive")
    repair.add_argument("--max-deletion-fraction", type=float, default=None,
                        metavar="F",
                        help=f"subset only: refuse to run when the repair would delete "
                             f"more than this fraction of the nodes "
                             f"(default: {SUBSET_CAP_DEFAULT})")
    repair.add_argument("--max-addition-fraction", type=float, default=None,
                        metavar="F",
                        help=f"superset only: refuse to run when the repair would add "
                             f"more than this fraction of the edge count "
                             f"(default: {SUPERSET_CAP_DEFAULT})")
    repair.add_argument("--no-prune", dest="prune", action="store_false",
                        help="superset only: skip the redundancy-pruning pass")
    repair.add_argument("--strategy", choices=("full", "incremental"), default="full",
                        help="subset only: re-check policy; both compute the same "
                             "repair (default: full)")
    repair.add_argument("--allow-graph-drift", action="store_true",
                        help="proceed even when a candidate file was derived from a "
                             "different graph than the one being repaired. Recorded in "
                             "the report when used")

    metrics = subs.add_parser(
        "metrics", help="report quality metrics for one graph; change nothing",
        description="Load a graph and write a JSON quality-metrics report: size and "
                    "conciseness, type and property coverage, and, when a constraint "
                    "set is given, consistency and constraint satisfaction. Reads "
                    "only; it writes no graph and runs no engine. Exits 0 unless the "
                    "input cannot be read. `docs/quality_metrics.md` defines every "
                    "metric and says what each is blind to.")
    _add_common(metrics)

    derive = subs.add_parser(
        "derive", help="propose constraint candidates for review",
        description="Profile a graph offline and write constraint candidates to a "
                    "file for a person to review. Nothing written here can repair "
                    "anything: every entry starts pending, and only `kgrepair review` "
                    "can seal the file so `kgrepair repair --constraints` will take "
                    "it. Merges into an existing file, keeping decisions already "
                    "recorded and never re-proposing a rejected rule.")
    derive.add_argument("--in", dest="graph_path", metavar="PATH", required=True,
                        help="N-Triples graph to profile")
    derive.add_argument("--out", metavar="PATH", required=True,
                        help="candidate file to write, or merge into if it exists")
    derive.add_argument("--domain", metavar="D", default="derived",
                        help="domain name recorded on the candidates")
    derive.add_argument("--kg", metavar="K", default="derived",
                        help="knowledge-graph name recorded on the candidates")
    derive.add_argument("--reference", metavar="PATH",
                        help="a second graph to score against, for the stability gate")
    derive.add_argument("--generator", choices=GENERATORS, default=SEARCH,
                        help="which generator proposes the candidates (default: "
                             "search, the two-axis search; shapes is the earlier "
                             "sweep of one template per repairable shape). The "
                             "choice is recorded in the candidate file")
    derive.add_argument("--min-support", type=int, default=5, metavar="N",
                        help="how many nodes a rule needs behind it (default: 5)")
    derive.add_argument("--min-conf", type=float, default=0.9, metavar="F",
                        help="confidence floor a rule has to clear (default: 0.9). "
                             "This decides what is worth proposing, never what is "
                             "accepted; there is no threshold that skips review")
    derive.add_argument("--delta", type=float, default=None, metavar="F",
                        help="with --reference, drop a rule whose confidence on the "
                             "two graphs differs by more than this")
    derive.add_argument("--max-antecedent", type=int, default=None, metavar="K",
                        help="how many atoms an antecedent may conjoin")
    derive.add_argument("--max-path", type=int, default=None, metavar="K",
                        help="how long a consequent path may be")
    derive.add_argument("--type-predicate", dest="type_predicates", action="append",
                        metavar="LABEL",
                        help="edge label that types a node, repeatable")

    review = subs.add_parser(
        "review", help="decide every candidate and seal the file",
        description="Walk the candidates in review order, recording a decision on "
                    "each, and seal the file once nothing is pending. Sealing needs a "
                    "reviewer name, because the seal records who made the decisions.")
    review.add_argument("path", metavar="PATH", help="candidate file to review")
    review.add_argument("--reviewer", metavar="NAME",
                        help="name recorded in the seal. Prompted for if omitted")
    review.add_argument("--graph", dest="graph_path", metavar="PATH",
                        help="graph the candidates were derived from. Given, what "
                             "repairing each entry would change is worked out as you "
                             "reach it, rather than for every candidate up front")
    return p


 
# shared setup: everything both subcommands do before they diverge
 
def _is_candidate_file(path: str) -> bool:
    """True when a --constraints path is a candidate file rather than a plain one."""
    try:
        with open(path, encoding="utf-8") as fh:
            head = json.load(fh)
    except (OSError, ValueError):
        return False
    return isinstance(head, dict) and str(head.get("schema", "")).startswith("kgrepair.candidates/")


def _load_constraints(args):
    if args.constraints and _is_candidate_file(args.constraints):
        # Reviewed candidates take the gated route. Everything the gate refuses
        # raises before an engine is reached.
        return read_candidate_file(args.constraints), os.path.basename(args.constraints)
    if args.constraints:
        if args.kg:
            raise _CliError("--constraints and --kg are alternatives: give a constraint "
                            "file, or a built-in --domain/--kg pair, not both")
        try:
            return load_constraint_file(args.constraints), os.path.basename(args.constraints)
        except OSError as exc:
            raise _CliError(f"could not read constraint file: {exc}") from exc
        except (KeyError, ValueError) as exc:
            raise _CliError(f"malformed constraint file {args.constraints!r}: {exc}") from exc

    if args.domain or args.kg:
        if not (args.domain and args.kg):
            raise _CliError("--domain and --kg must be given together")
        try:
            cs = _constraints.get(args.domain, args.kg, version=args.version)
        except KeyError as exc:
            available = {d: sorted(kgs) for d, kgs in sorted(_constraints.registry().items())}
            raise _CliError(
                f"no built-in constraint set for domain={args.domain!r} "
                f"kg={args.kg!r}; available: {json.dumps(available, sort_keys=True)}"
            ) from exc
        except ValueError as exc:
            raise _CliError(str(exc)) from exc
        return cs, f"{args.domain}/{args.kg}/v{args.version}"

    raise _CliError(_NO_CONSTRAINTS)


def _load_graph(args):
    types = set(args.type_predicates) if args.type_predicates else None
    try:
        graph = load_graph(args.graph_path, type_predicates=types)
    except OSError as exc:
        raise _CliError(f"could not read graph: {exc}") from exc
    except ValueError as exc:
        raise _CliError(f"could not parse graph {args.graph_path!r}: {exc}") from exc
    effective = sorted(types) if types is not None else sorted(DEFAULT_TYPE_PREDICATES)
    return graph, effective


def _maybe_filter(graph, args):
    if not args.allowlist:
        return graph, False, 0
    try:
        filtered, dropped = apply_allowlist(graph, args.allowlist)
    except OSError as exc:
        raise _CliError(f"could not read allow-list: {exc}") from exc
    except (KeyError, ValueError) as exc:
        raise _CliError(f"malformed allow-list {args.allowlist!r}: {exc}") from exc
    return filtered, True, dropped


def _envelope(args, *, source, type_predicates, allowlist_applied, dropped):
    """The thin wrapper around an API object's own to_dict().

    Delegates to `api.report_envelope`, which the viewer uses too, so the same run
    is described identically by both skins.
    """
    return report_envelope(args.subcommand, constraints_source=source,
                           input_name=args.graph_path,
                           type_predicates=type_predicates,
                           allowlist_applied=allowlist_applied,
                           allowlist_edges_dropped=dropped)


def _emit(payload, args) -> None:
    text = json.dumps(payload, indent=args.indent, sort_keys=True) + "\n"
    if args.report:
        try:
            with open(args.report, "w", encoding="utf-8") as fh:
                fh.write(text)
        except OSError as exc:
            raise _CliError(f"could not write report: {exc}") from exc
    else:
        sys.stdout.write(text)


 
# subcommands
 
def _cmd_check(args) -> int:
    cs, source = _load_constraints(args)
    if isinstance(cs, CandidateFile):
        raise _CliError("that is a candidate file. Review and seal it, then use it "
                        "with `kgrepair repair --constraints`")
    graph, types = _load_graph(args)
    graph, filtered, dropped = _maybe_filter(graph, args)

    report = validate(graph, cs)

    payload = _envelope(args, source=source, type_predicates=types,
                        allowlist_applied=filtered, dropped=dropped)
    payload["result"] = report.to_dict(witness_limit=args.witness_limit)
    _emit(payload, args)

    return EXIT_VIOLATIONS if report.by_tier()["ptime_core"] > 0 else EXIT_OK


def _metric_vocabulary(args) -> dict:
    """The typing spine the metrics measure against, from the same flag the loader
    reads. Without this a report about an `ex:isa` graph would name the Wikidata
    spine, which `test_cli.py`'s agnostic gate catches."""
    instance_of, subclass_of = split_type_predicates(args.type_predicates)
    return {"instance_of": instance_of, "subclass_of": subclass_of}


def _cmd_metrics(args) -> int:
    """Quality metrics for one graph. Reads only, so there is no exit code beyond
    success and a usage or I/O failure: a graph with poor metrics is a finding, not
    an error."""
    cs = None
    source = "none"
    if args.constraints or args.domain:
        cs, source = _load_constraints(args)
        if isinstance(cs, CandidateFile):
            raise _CliError("that is a candidate file. Review and seal it, then use "
                            "it with `kgrepair metrics --constraints`")
    graph, types = _load_graph(args)
    graph, filtered, dropped = _maybe_filter(graph, args)

    payload = _envelope(args, source=source, type_predicates=types,
                        allowlist_applied=filtered, dropped=dropped)
    instance_of, subclass_of = split_type_predicates(args.type_predicates)
    payload["result"] = compute_metrics(graph, cs, instance_of=instance_of,
                                        subclass_of=subclass_of).to_dict()
    _emit(payload, args)
    return EXIT_OK


def _cmd_repair(args) -> int:
    if not args.out and not args.bundle:
        raise _CliError("nothing to write: pass --out PATH for the repaired graph, "
                        "--bundle DIR for the full bundle, or both")

    cs, source = _load_constraints(args)
    graph, types = _load_graph(args)
    graph, filtered, dropped = _maybe_filter(graph, args)

    candidate_file = None
    provenance = "built-in" if not args.constraints else "constraint file"
    if isinstance(cs, CandidateFile):
        candidate_file = cs
        provenance = candidate_file.provenance
        cs = reviewed_constraint_set(
            candidate_file, graph,
            allow_graph_drift=getattr(args, "allow_graph_drift", False))

    cap = (args.max_deletion_fraction if args.mode == "subset"
           else args.max_addition_fraction)
    decision = check_cap(graph, cs, args.mode, cap=cap)

    payload = _envelope(args, source=source, type_predicates=types,
                        allowlist_applied=filtered, dropped=dropped)
    payload["mode"] = args.mode
    payload["cap"] = decision.to_dict()

    if decision.aborted:
        payload["result"] = None
        payload["output_basename"] = None
        # No engine ran, so there is no repaired graph to measure. The block keeps
        # its three keys so a reader does not have to branch on that.
        payload["metrics"] = repair_metrics_block(
            graph, None, cs, **_metric_vocabulary(args))
        # A capped run still hands back a bundle. It carries the report and the
        # constraints and nothing else, because no engine ran, and the report says
        # which of those two it is.
        _write_bundle(args, payload, cs, repaired=None, original=None,
                      summary=bundle_summary(
                          mode=args.mode, constraint_provenance=provenance,
                          consistent_after=None, aborted=True,
                          reason=(f"ABORTED-BY-CAP: the repair would touch "
                                  f"{decision.fraction:.3f} of the graph against a "
                                  f"cap of {decision.cap:.3f}, so no engine ran and "
                                  f"no repaired graph was written")))
        _emit(payload, args)
        return EXIT_CAPPED

    if args.mode == "subset":
        result = subset_repair(graph, cs, strategy=args.strategy)
    else:
        result = superset_repair(graph, cs, prune=args.prune)

    if args.out:
        try:
            write_ntriples(result.graph, args.out)
        except OSError as exc:
            raise _CliError(f"could not write repaired graph: {exc}") from exc
        payload["output_basename"] = os.path.basename(args.out)

    body = result.to_dict()
    if candidate_file is not None:
        # Who authorised these rules, and against what. Assembled in the library so
        # the engines stay untouched by the review machinery.
        body = attach_review_attestations(
            body, candidate_file,
            allow_graph_drift=getattr(args, "allow_graph_drift", False))
    payload["result"] = body
    payload["metrics"] = repair_metrics_block(
        graph, result.graph, cs, **_metric_vocabulary(args))

    _write_bundle(args, payload, cs, repaired=result.graph, original=graph,
                  summary=bundle_summary(
                      mode=args.mode, constraint_provenance=provenance,
                      consistent_after=bool(
                          result.attestations.get("consistent_after")),
                      aborted=False))
    _emit(payload, args)

    return EXIT_OK if result.attestations.get("consistent_after") else EXIT_VIOLATIONS


def _write_bundle(args, payload, cs, *, repaired, original, summary) -> None:
    """Write the bundle when one was asked for. I/O only, as this module's rule
    requires: what goes in the report was decided above.

    The summary rides in the bundle's own `report.json` rather than in the payload
    the command line prints. That payload is the one the viewer has to match field
    for field, and adding a field here that the viewer does not produce would break
    the guarantee that the two cannot describe one run differently.
    """
    if not args.bundle:
        return
    if args.constraints:
        # The file the user handed in, copied verbatim, so what drove the run is
        # what they can compare against rather than a re-serialisation of it.
        try:
            with open(args.constraints, encoding="utf-8") as fh:
                constraints_json = fh.read()
        except OSError as exc:
            raise _CliError(f"could not re-read the constraint file: {exc}") from exc
    else:
        # A built-in set has no input file, so the bundle carries the set itself.
        constraints_json = json.dumps(cs.to_dict(), indent=2, sort_keys=True) + "\n"
    try:
        names = write_bundle(args.bundle, report={**payload, "summary": summary},
                             repaired=repaired, original=original,
                             constraints_json=constraints_json)
        if getattr(args, "zip_bundle", False):
            zip_bundle(args.bundle)
    except OSError as exc:
        raise _CliError(f"could not write the bundle: {exc}") from exc
    payload["bundle"] = {"directory": os.path.basename(args.bundle.rstrip(os.sep)),
                         "files": names}


 
# derive
 
def _cmd_derive(args) -> int:
    types = set(args.type_predicates) if args.type_predicates else None
    try:
        graph = load_graph(args.graph_path, type_predicates=types)
        reference = (load_graph(args.reference, type_predicates=types)
                     if args.reference else None)
    except OSError as exc:
        raise _CliError(f"could not read graph: {exc}") from exc
    except ValueError as exc:
        raise _CliError(f"could not parse graph: {exc}") from exc

    cfg = DeriveConfig(min_support=args.min_support,
                       min_pca_confidence=args.min_conf,
                       generator=args.generator)
    if args.max_antecedent is not None:
        cfg.max_typing_antecedent_atoms = args.max_antecedent
    if args.max_path is not None:
        cfg.max_path_depth = args.max_path

    fresh = derive_candidate_file(
        graph, args.domain, args.kg, config=cfg, reference_graph=reference,
        dataset=os.path.basename(args.graph_path), stability_delta=args.delta)

    if os.path.exists(args.out):
        try:
            existing = read_candidate_file(args.out)
        except (OSError, ValueError) as exc:
            raise _CliError(f"could not read the existing candidate file: {exc}") from exc
        merged = merge_candidates(existing, fresh)
        added = len(merged.candidates) - len(existing.candidates)
    else:
        merged, added = fresh, len(fresh.candidates)

    if not merged.candidates:
        sys.stderr.write(
            "kgrepair: nothing cleared the support and confidence floors, so no "
            "candidate file was written. Try a lower --min-support or --min-conf.\n")
        return EXIT_NO_CANDIDATES

    try:
        write_canonical(merged, args.out)
    except OSError as exc:
        raise _CliError(f"could not write the candidate file: {exc}") from exc

    pending = len(merged.pending())
    sys.stdout.write(
        f"{len(merged.candidates)} candidate(s) in {os.path.basename(args.out)} "
        f"({added} new, {pending} pending)\n"
        f"Nothing here can repair anything yet. Run `kgrepair review "
        f"{args.out}` to decide each entry and seal the file.\n")
    return EXIT_OK


 
# review
 
_REVIEW_KEYS = {"a": ACCEPTED, "r": REJECTED, "w": WEAKENED}


def _show(cand, position: int, total: int) -> None:
    sys.stdout.write(
        f"\n[{position}/{total}] {cand.cid}   ({cand.kind}, {cand.tier}, "
        f"repairs by {cand.direction})\n"
        f"  {cand.gloss}\n"
        f"  rule      {cand.antecedent}\n"
        f"            is contained in {cand.consequent}\n")
    ev, im = cand.evidence or {}, cand.impact or {}
    sys.stdout.write(
        f"  evidence  support {ev.get('support')}, confidence {ev.get('confidence')}")
    if ev.get("reference_confidence") is not None:
        sys.stdout.write(f", on the reference graph {ev['reference_confidence']}")
    if ev.get("stability"):
        sys.stdout.write(f", {ev['stability']}")
    sys.stdout.write("\n")
    if im.get("measured"):
        sys.stdout.write(
            f"  impact    {im.get('witnesses')} node(s) break it; accepting it means "
            f"{im.get('subset_deletions')} deletion(s) or "
            f"{im.get('superset_additions')} addition(s)\n")
    else:
        sys.stdout.write(
            f"  impact    {im.get('witnesses')} node(s) break it; what repairing it "
            f"would change has not been computed. Pass --graph to work it out for "
            f"each entry as you reach it.\n")
    if cand.witness_sample:
        sys.stdout.write(f"  for example  {', '.join(cand.witness_sample)}\n")
    if cand.status != "pending":
        sys.stdout.write(f"  already recorded as {cand.status}\n")


def _cmd_review(args, read_line=input) -> int:
    try:
        cf = read_candidate_file(args.path)
    except OSError as exc:
        raise _CliError(f"could not read the candidate file: {exc}") from exc
    except ValueError as exc:
        raise _CliError(f"{os.path.basename(args.path)}: {exc}") from exc

    queue = [c for c in cf.ordered_for_review() if c.status == "pending"]
    total = len(queue)
    if not total:
        sys.stdout.write("Every entry already has a decision.\n")
    sys.stdout.write(
        f"{total} entry(ies) to decide. a accept, r reject, w weaken, s skip, "
        f"q quit without sealing.\n")

    graph = None
    if getattr(args, "graph_path", None):
        try:
            graph = load_graph(args.graph_path)
        except (OSError, ValueError) as exc:
            raise _CliError(f"could not read graph: {exc}") from exc

    for i, cand in enumerate(queue, start=1):
        if graph is not None:
            # Deferred at derive time because it is the expensive half; computed
            # here, for one entry, at the moment someone is looking at it.
            fill_impact(graph, cand)
        _show(cand, i, total)
        while True:
            try:
                answer = (read_line("  a/r/w/s/q > ") or "").strip().lower()
            except EOFError:
                answer = "q"
            if answer == "q":
                sys.stdout.write("Quit. Nothing was sealed.\n")
                _save(cf, args.path)
                return EXIT_REVIEW_PENDING
            if answer == "s":
                break
            if answer in _REVIEW_KEYS:
                note = ""
                if answer == "w":
                    note = (read_line("  what did you weaken it to? > ") or "").strip()
                set_status(cf, cand.cid, _REVIEW_KEYS[answer], note=note)
                _save(cf, args.path)
                break
            sys.stdout.write("  please answer a, r, w, s or q\n")

    still = cf.pending()
    if still:
        sys.stdout.write(f"\n{len(still)} entry(ies) still undecided, so the file "
                         f"was not sealed.\n")
        return EXIT_REVIEW_PENDING

    reviewer = args.reviewer
    if not reviewer:
        try:
            reviewer = (read_line("Reviewer name for the seal > ") or "").strip()
        except EOFError:
            reviewer = ""
    if not reviewer:
        sys.stderr.write("kgrepair: sealing needs a reviewer name; the file was not "
                         "sealed.\n")
        return EXIT_REVIEW_PENDING

    seal_candidates(cf, reviewer)
    _save(cf, args.path)
    sys.stdout.write(
        f"Sealed by {reviewer}. {len(cf.accepted())} accepted, "
        f"{len(cf.refused)} rejected.\n"
        f"Use it with: kgrepair repair --constraints {args.path} ...\n")
    return EXIT_OK


def _save(cf, path: str) -> None:
    try:
        write_canonical(cf, path)
    except OSError as exc:
        raise _CliError(f"could not write the candidate file: {exc}") from exc


 
# entry point
 
def main(argv: Optional[List[str]] = None) -> int:
    """Run the command line and return an exit code. Never calls `sys.exit`."""
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:                    # argparse's own usage errors
        return EXIT_OK if exc.code == 0 else EXIT_USAGE

    if not args.subcommand:
        parser.print_usage(sys.stderr)
        sys.stderr.write("kgrepair: a subcommand is required (check or repair)\n")
        return EXIT_USAGE

    handler = {"check": _cmd_check, "repair": _cmd_repair, "metrics": _cmd_metrics,
               "derive": _cmd_derive, "review": _cmd_review}[args.subcommand]
    try:
        return handler(args)
    except CandidateGateError as exc:
        # The gate refused before any engine ran. One exit code for the whole
        # class; the error code in the message says which refusal it was.
        sys.stderr.write(f"kgrepair: {exc}\n")
        return EXIT_GATE_REFUSED
    except _CliError as exc:
        sys.stderr.write(f"kgrepair: {exc}\n")
        return EXIT_USAGE


if __name__ == "__main__":                       # pragma: no cover
    sys.exit(main())
