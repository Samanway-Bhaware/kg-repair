"""
The viewer's testable seam: every knowledge-graph operation the screens perform.

Plain Python, no Streamlit. The screens are presentation only and call into here,
the same way `kgrepair.cli` is argparse and file I/O over the same public API.
Keeping the work in this module is what makes the viewer testable without driving
a browser, and it is why the viewer and the command line cannot drift apart: both
build their reports from `kgrepair.report_envelope` plus the API object's own
`to_dict()`, and both take their cap verdict from `kgrepair.check_cap`.

Everything here goes through the `kgrepair` public API. Nothing reaches into an
internal module, and no validation, repair, cap, or serialisation logic is
reimplemented.
"""
from __future__ import annotations

import json
import os
import sys
from contextlib import nullcontext
from dataclasses import dataclass, field
from typing import Dict, Iterable, Optional, Set, Tuple

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import kgrepair
from kgrepair import constraints as constraints_pkg

#: Repair modes the viewer offers, in the order the picker shows them.
MODES = ("subset", "superset")


class ViewerError(Exception):
    """An input problem to show the user as a message, not a stack trace."""


 
# inputs
 
@dataclass
class Session:
    """One loaded graph plus the constraints and settings it was loaded with.

    The unit every screen works from, whichever way the graph arrived. `entry` is
    the fixture manifest when the graph came from one of the project's own slices
    and None when the user uploaded their own, which is the only thing downstream
    screens need to branch on.
    """
    graph: kgrepair.DataGraph
    constraints: kgrepair.ConstraintSet
    graph_name: str
    constraints_source: str
    type_predicates: Set[str]
    allowlist_applied: bool = False
    allowlist_edges_dropped: int = 0
    entry: object = None
    notes: list = field(default_factory=list)

    @property
    def is_upload(self) -> bool:
        return self.entry is None

    @property
    def fingerprint(self) -> tuple:
        """A hashable identity for cache keys and for spotting a changed input."""
        return (self.graph_name, self.constraints_source,
                tuple(sorted(self.type_predicates)), self.allowlist_applied,
                self.allowlist_edges_dropped, len(self.graph.nodes),
                self.graph.num_edges())

    def envelope(self, subcommand: str) -> Dict:
        """The shared report envelope, identical to the one the CLI emits."""
        return kgrepair.report_envelope(
            subcommand, constraints_source=self.constraints_source,
            input_name=self.graph_name, type_predicates=self.type_predicates,
            allowlist_applied=self.allowlist_applied,
            allowlist_edges_dropped=self.allowlist_edges_dropped)

    def stats(self) -> Dict[str, int]:
        return self.graph.stats()


def parse_type_predicates(text: Optional[str]) -> Optional[Set[str]]:
    """Turn the type-predicate box's free text into a set, or None for the default.

    Accepts one label per line or a comma-separated list, and ignores blanks, so a
    user can paste either shape. Returning None means "use the loader's
    `DEFAULT_TYPE_PREDICATES`", which is what an empty box should do.
    """
    if not text or not text.strip():
        return None
    parts = [p.strip() for chunk in text.splitlines() for p in chunk.split(",")]
    labels = {p for p in parts if p}
    return labels or None


def effective_type_predicates(chosen: Optional[Iterable[str]]) -> Set[str]:
    """The label set a load actually used, for display and for the report."""
    return set(chosen) if chosen is not None else set(kgrepair.DEFAULT_TYPE_PREDICATES)


def load_graph_from_text(text: str, name: str,
                         type_predicates: Optional[Iterable[str]] = None):
    """Load an uploaded N-Triples payload, reporting parse problems as ViewerError."""
    try:
        return kgrepair.load_graph_string(text, type_predicates=type_predicates)
    except ValueError as exc:
        raise ViewerError(f"could not parse {name!r} as N-Triples: {exc}") from exc


def load_graph_from_path(path: str, type_predicates: Optional[Iterable[str]] = None):
    """Load an N-Triples file from disk, reporting problems as ViewerError."""
    try:
        return kgrepair.load_graph(path, type_predicates=type_predicates)
    except OSError as exc:
        raise ViewerError(f"could not read graph file: {exc}") from exc
    except ValueError as exc:
        raise ViewerError(f"could not parse {os.path.basename(path)!r} "
                          f"as N-Triples: {exc}") from exc


def load_constraints_from_text(text: str, name: str) -> kgrepair.ConstraintSet:
    """Parse an uploaded constraint file and compile it straight away.

    Compiling here rather than lazily means an expression outside the positive
    fragment (negation, path complement, disequality) is reported on the Load
    screen, where the user can act on it, instead of surfacing much later as a
    failure part way through a check.
    """
    try:
        payload = json.loads(text)
    except (ValueError, UnicodeDecodeError) as exc:
        raise ViewerError(f"{name!r} is not valid JSON: {exc}") from exc
    try:
        cs = kgrepair.ConstraintSet.from_dict(payload)
    except (KeyError, TypeError) as exc:
        raise ViewerError(
            f"{name!r} is not a constraint file: expected a 'constraints' list of "
            f"constraint objects ({exc})") from exc
    return _compiled(cs, name)


def load_constraints_from_path(path: str) -> kgrepair.ConstraintSet:
    """Read a constraint file from disk and compile it. See the uploaded variant."""
    name = os.path.basename(path)
    try:
        cs = kgrepair.load_constraint_file(path)
    except OSError as exc:
        raise ViewerError(f"could not read constraint file: {exc}") from exc
    except (ValueError, KeyError, TypeError) as exc:
        raise ViewerError(
            f"{name!r} is not a constraint file: expected a 'constraints' list of "
            f"constraint objects ({exc})") from exc
    return _compiled(cs, name)


def _compiled(cs: kgrepair.ConstraintSet, name: str) -> kgrepair.ConstraintSet:
    """Parse every expression now, so anything outside the fragment is caught here."""
    try:
        cs.compile_all()
    except Exception as exc:                      # ParseError and anything like it
        raise ViewerError(
            f"a constraint in {name!r} could not be parsed: {exc}. Expressions must "
            f"stay inside the positive fragment, so negation, path complement and "
            f"disequality are rejected.") from exc
    return cs


def builtin_constraint_choices() -> Dict[str, Tuple[str, str, int]]:
    """label -> (domain, kg, version) for every built-in set, in a stable order."""
    out: Dict[str, Tuple[str, str, int]] = {}
    for version in (1, 2):
        for domain, kgmap in sorted(constraints_pkg.registry(version=version).items()):
            for kg in sorted(kgmap):
                out[f"{domain} / {kg} (v{version})"] = (domain, kg, version)
    return out


def load_builtin_constraints(domain: str, kg: str, version: int = 1):
    """One of the constraint sets shipped with the toolkit."""
    try:
        return constraints_pkg.get(domain, kg, version=version)
    except KeyError as exc:
        raise ViewerError(f"no built-in constraint set for domain={domain!r}, "
                          f"kg={kg!r}") from exc


def apply_user_allowlist(graph, allowlist_text: str, name: str):
    """Apply a user's own predicate allow-list to an already-loaded graph.

    Opt in: nothing calls this unless the user supplies a file. It filters on
    predicate names the user chose and does nothing else.
    """
    try:
        payload = json.loads(allowlist_text)
    except (ValueError, UnicodeDecodeError) as exc:
        raise ViewerError(f"{name!r} is not valid JSON: {exc}") from exc
    predicates = payload.get("predicates") if isinstance(payload, dict) else payload
    if not isinstance(predicates, list):
        raise ViewerError(f"{name!r} is not an allow-list file: expected a "
                          f"'predicates' list of predicate labels")
    return kgrepair.apply_allowlist(graph, set(predicates))


 
# check
 
def run_check(session: Session, *, witness_limit: int = 25) -> Dict:
    """Validate the session's graph and return the same report shape the CLI writes.

    The body under `result` is `ValidationReport.to_dict()` untouched, so a check
    looks identical here and on the command line.
    """
    report = kgrepair.validate(session.graph, session.constraints, use_closure=True)
    payload = session.envelope("check")
    payload["result"] = report.to_dict(witness_limit=witness_limit)
    return payload


def check_exit_code(payload: Dict) -> int:
    """The exit code the command line would return for this check payload.

    Kept here so the two skins agree on what counts as a failure: ptime_core
    violations do, boundary-tier violations on their own do not.
    """
    return 2 if payload["result"]["by_tier"]["ptime_core"] > 0 else 0


def violation_rows(session: Session, payload: Dict) -> list:
    """Per-constraint display rows, joining the report to its constraint text."""
    by_cid = {c.cid: c for c in session.constraints}
    rows = []
    for entry in payload["result"]["constraints"]:
        c = by_cid.get(entry["cid"])
        rows.append({
            **entry,
            "provenance": c.provenance if c else "?",
            "containment": f"{c.antecedent}  ⊑  {c.consequent}" if c else "?",
            "report_only": entry["tier"] == "boundary",
        })
    return rows


 
# repair
 
@dataclass
class RepairRun:
    """One repair attempt: the report to show, and the live result when it ran.

    `payload` is the serialisable report, shaped exactly like the command line's.
    `result` is the engine's own result object, kept so a screen can render the
    change log and the neighbourhood diff; it is None when the cap tripped, which
    is the viewer's equivalent of the command line's exit code 3.
    """
    payload: Dict
    decision: kgrepair.CapDecision
    result: object = None

    @property
    def aborted(self) -> bool:
        return self.decision.aborted

    @property
    def exit_code(self) -> int:
        """What the command line would return for this run."""
        if self.aborted:
            return 3
        return 0 if self.result.attestations.get("consistent_after") else 2


def cap_decision(session: Session, mode: str, cap: Optional[float] = None):
    """The shared cap verdict for this session, without running anything."""
    if mode not in MODES:
        raise ViewerError(f"unknown repair mode {mode!r}")
    return kgrepair.check_cap(session.graph, session.constraints, mode, cap=cap)


def _metrics_block(session: Session, repaired) -> Dict:
    """The report's quality-metrics section, from the same library call the command
    line makes. Assembling it here rather than borrowing `kgrepair.repair_metrics_block`
    would put the viewer's report out of step with the command line's, which
    `tests/test_viewer_logic.py` asserts against."""
    instance_of, subclass_of = kgrepair.split_type_predicates(session.type_predicates)
    return kgrepair.repair_metrics_block(
        session.graph, repaired, session.constraints,
        instance_of=instance_of, subclass_of=subclass_of)


def run_repair(session: Session, mode: str, *, cap: Optional[float] = None,
               strategy: str = "full", prune: bool = True, phase=None,
               candidate_file=None) -> RepairRun:
    """Cap-check, then repair if the cap allows.

    The cap verdict comes from `kgrepair.check_cap`, the same call the command
    line and the bench scripts make, so all three abort on the same graphs. The
    engine runs at most once per call.

    `phase` is an optional `RunContext.phase`-style context-manager factory. When
    given, the engine call is timed under the name "repair_loop", which is the
    phase the evaluation tables read. Passing it keeps the run record's shape
    unchanged while the engine is still invoked in exactly one place.

    `candidate_file` is the file the constraints came from, when they came from
    one. Passing it records who authorised the rules, exactly as the command line
    does, and without it the viewer's report would be missing a field the command
    line's has for the same inputs.
    """
    if mode not in MODES:
        raise ViewerError(f"unknown repair mode {mode!r}")

    decision = kgrepair.check_cap(session.graph, session.constraints, mode, cap=cap)
    payload = session.envelope("repair")
    payload["mode"] = mode
    payload["cap"] = decision.to_dict()

    if decision.aborted:
        payload["result"] = None
        payload["metrics"] = _metrics_block(session, None)
        return RepairRun(payload=payload, decision=decision, result=None)

    with (phase("repair_loop") if phase is not None else nullcontext()):
        if mode == "subset":
            result = kgrepair.subset_repair(session.graph, session.constraints,
                                            strategy=strategy)
        else:
            result = kgrepair.superset_repair(session.graph, session.constraints,
                                              prune=prune)
    body = result.to_dict()
    if candidate_file is not None:
        body = kgrepair.attach_review_attestations(body, candidate_file)
    payload["result"] = body
    payload["metrics"] = _metrics_block(session, result.graph)
    return RepairRun(payload=payload, decision=decision, result=result)


def neighbourhood(graph, center: str, *, k: int = kgrepair.DEFAULT_K,
                  node_cap: int = kgrepair.DEFAULT_NODE_CAP, changelog=None):
    """A bounded local view around one node, diff-tagged against a change log."""
    return kgrepair.extract_neighbourhood(graph, center, k=k, node_cap=node_cap,
                                          changelog=changelog)


 
# export
 
def export_payloads(session: Session, payload: Dict, repaired_graph=None) -> Dict:
    """The download bodies for the Export screen, keyed by a short name.

    `graph` is N-Triples for the repaired graph when there is one and the original
    otherwise; `report` is the JSON report, which is byte-identical to what the
    command line writes for the same run.
    """
    graph = repaired_graph if repaired_graph is not None else session.graph
    return {
        "graph": kgrepair.to_ntriples(graph),
        "report": json.dumps(payload, indent=2, sort_keys=True) + "\n",
    }


def isolated_node_count(graph) -> int:
    """Nodes with no incident edge, which N-Triples cannot represent.

    Deletion repair routinely leaves these behind, so the Export screen reports
    the count rather than letting the downloaded file quietly hold fewer nodes.
    """
    edge_bearing = {n for e in graph.edges() for n in (e[0], e[2])}
    return len(graph.nodes) - len(edge_bearing)


 
# P7: uploads, the two flows, and the download bundle
 
#: Serialisations a user might reasonably upload by mistake, and how to spot one.
#: N-Triples is the only accepted graph format, so the point of this table is to
#: say which format was recognised rather than to report a parse error on line 1.
_FOREIGN_GRAPH_MARKERS = (
    ("@prefix", "Turtle"),
    ("@base", "Turtle"),
    ("PREFIX ", "SPARQL or Turtle"),
    ("<rdf:RDF", "RDF/XML"),
    ("<?xml", "RDF/XML"),
    ("{", "JSON-LD"),
)


def detect_foreign_serialisation(text: str) -> Optional[str]:
    """The name of the serialisation this text looks like, when it is not N-Triples.

    A Turtle file uploaded as `.nt` parses as a syntax error on its first prefix
    line, which tells the user nothing useful. Naming the format they actually have
    does, and it is the difference between a message they can act on and one they
    cannot.
    """
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        for marker, name in _FOREIGN_GRAPH_MARKERS:
            if stripped.startswith(marker):
                return name
        return None            # the first real line looks like a triple
    return None


@dataclass
class UploadedGraph:
    """What the Input screen reports back about an uploaded graph, before offering
    anything else to do with it."""
    graph: kgrepair.DataGraph
    name: str
    nodes: int
    edges: int
    content_hash: str
    isolated_nodes: int

    def to_dict(self) -> Dict:
        return {"name": self.name, "nodes": self.nodes, "edges": self.edges,
                "content_hash": self.content_hash,
                "isolated_nodes": self.isolated_nodes}


def accept_uploaded_graph(text: str, name: str,
                          type_predicates: Optional[Iterable[str]] = None
                          ) -> UploadedGraph:
    """Parse, hash and measure an uploaded graph, or refuse it with a reason.

    Nothing else is offered until this returns: a user who uploaded the wrong file
    should find out here, with the counts in front of them, rather than after
    choosing an engine.
    """
    if not text.strip():
        raise ViewerError(f"{name!r} is empty: there is nothing to repair")
    foreign = detect_foreign_serialisation(text)
    if foreign is not None:
        raise ViewerError(
            f"{name!r} looks like {foreign}, and this toolkit reads N-Triples only. "
            f"Convert it first, for example with `rapper -o ntriples`, and upload "
            f"the result.")
    graph = load_graph_from_text(text, name, type_predicates=type_predicates)
    return UploadedGraph(
        graph=graph, name=name, nodes=len(graph.nodes), edges=graph.num_edges(),
        content_hash=kgrepair.graph_content_hash(graph),
        isolated_nodes=isolated_node_count(graph))


def accept_uploaded_constraints(text: str, name: str, graph=None
                                ) -> Tuple[kgrepair.ConstraintSet, Dict]:
    """Load an uploaded constraint file, whichever of the two shapes it is.

    A `kgrepair.candidates/v1` file goes through the same load gate the command
    line uses, so an authored file needs no seal while a derived one still does,
    and every other refusal applies to both. Anything else is read as a plain
    constraint file, which is the shape `save_constraint_file` writes and which the
    committed fixtures use.

    Returns the set and a small description of where it came from, so the screen
    can say which kind of file it read rather than leaving the user to guess.
    """
    try:
        payload = json.loads(text)
    except (ValueError, UnicodeDecodeError) as exc:
        raise ViewerError(f"{name!r} is not valid JSON: {exc}") from exc

    if isinstance(payload, dict) and payload.get("schema") == "kgrepair.candidates/v1":
        try:
            cf = kgrepair.CandidateFile.from_dict(payload)
        except ValueError as exc:
            raise ViewerError(f"{name!r}: {exc}") from exc
        try:
            cs = kgrepair.reviewed_constraint_set(cf, graph, for_repair=True)
        except kgrepair.CandidateGateError as exc:
            # The gate's message already names the code and the offending entry.
            raise ViewerError(str(exc)) from exc
        return cs, {"kind": "candidate file", "provenance": cf.provenance,
                    "entries": len(cf.accepted()), "candidate_file": cf}

    cs = load_constraints_from_text(text, name)
    return cs, {"kind": "constraint file", "provenance": "authored",
                "entries": len(cs)}


 
# the derive, review, seal path
 
@dataclass
class ReviewQueue:
    """A derived candidate file part way through review.

    Holds the file itself and the graph it came from, because impact is measured
    one entry at a time as a reviewer reaches it, which needs both.
    """
    candidate_file: kgrepair.CandidateFile
    graph: kgrepair.DataGraph

    def pending(self) -> list:
        return list(self.candidate_file.pending())

    def entries(self) -> list:
        return list(self.candidate_file.ordered_for_review())

    @property
    def sealed(self) -> bool:
        return self.candidate_file.sealed

    def show(self, cid: str) -> Dict:
        """One entry, with its impact computed now rather than up front.

        Impact is one subset repair and one superset repair, which the cost
        measurement in `docs/performance.md` found to be 96 to 99 percent of a
        derivation. Computing it here means a reviewer pays for the entries they
        actually look at.
        """
        entry = self.candidate_file.by_cid(cid)
        if entry is None:
            raise ViewerError(f"no candidate with id {cid!r} in this file")
        impact = kgrepair.fill_impact(self.graph, entry)
        return {"cid": entry.cid, "gloss": entry.gloss, "kind": entry.kind,
                "antecedent": entry.antecedent, "consequent": entry.consequent,
                "status": entry.status, "evidence": dict(entry.evidence),
                "impact": dict(impact), "witness_sample": list(entry.witness_sample)}

    def decide(self, cid: str, status: str, note: str = "") -> None:
        """Record one decision. Accept, reject, or weaken, and nothing else."""
        if status not in ("accepted", "rejected", "weakened"):
            raise ViewerError(f"unknown decision {status!r}: accept, reject or weaken")
        if self.candidate_file.by_cid(cid) is None:
            raise ViewerError(f"no candidate with id {cid!r} in this file")
        kgrepair.set_status(self.candidate_file, cid, status, note=note)

    def witness_view(self, cid: str, *, k: int = kgrepair.DEFAULT_K):
        """The neighbourhood around this entry's first witness, for the reviewer.

        A rule reads as an abstraction until you see one of the nodes that breaks
        it, so the review screen shows the graph around the first witness rather
        than the expression alone.
        """
        entry = self.candidate_file.by_cid(cid)
        if entry is None:
            raise ViewerError(f"no candidate with id {cid!r} in this file")
        if not entry.witness_sample:
            return None
        return neighbourhood(self.graph, entry.witness_sample[0], k=k)

    def seal(self, reviewer: str) -> kgrepair.CandidateFile:
        """Seal the file once every entry is decided, or say what is left."""
        if not reviewer or not reviewer.strip():
            raise ViewerError("sealing records who made these decisions, so it needs "
                              "a reviewer name")
        still = self.pending()
        if still:
            raise ViewerError(
                f"{len(still)} entry(ies) still undecided, first is {still[0].cid}. "
                f"Every entry has to be decided before the file can be sealed.")
        try:
            return kgrepair.seal_candidates(self.candidate_file, reviewer)
        except ValueError as exc:
            raise ViewerError(str(exc)) from exc

    def constraint_set(self) -> kgrepair.ConstraintSet:
        """The sealed file as a loadable set, through the same gate as everywhere."""
        try:
            return kgrepair.reviewed_constraint_set(self.candidate_file, self.graph)
        except kgrepair.CandidateGateError as exc:
            raise ViewerError(str(exc)) from exc


def start_review(graph, domain: str = "uploaded", kg: str = "uploaded", *,
                 dataset: str = "", **derive_kwargs) -> ReviewQueue:
    """Derive candidates from a graph and hand back a review queue.

    Impact is left uncomputed on purpose; `ReviewQueue.show` fills it in one entry
    at a time. Every entry comes back pending, and nothing here can accept one.
    """
    cf = kgrepair.derive_candidate_file(graph, domain, kg, dataset=dataset,
                                        **derive_kwargs)
    if not cf.candidates:
        raise ViewerError(
            "nothing cleared the support and confidence floors, so there are no "
            "candidates to review. Try a lower support floor, or supply your own "
            "constraint file.")
    return ReviewQueue(candidate_file=cf, graph=graph)


 
# downloads
 
def bundle_payloads(session: Session, run: "RepairRun", *,
                    constraints_json: Optional[str] = None) -> Dict[str, str]:
    """The bundle as in-memory download bodies, keyed by the file name it has on disk.

    The same four files `kgrepair repair --bundle` writes, built from the same
    functions, so what a user downloads here and what they would get from the
    command line for the same inputs are the same bytes.
    """
    summary = kgrepair.bundle_summary(
        mode=run.payload.get("mode", ""),
        constraint_provenance=session.constraints_source,
        consistent_after=(None if run.aborted
                          else bool(run.result.attestations.get("consistent_after"))),
        aborted=run.aborted,
        reason=(f"ABORTED-BY-CAP: the repair would touch "
                f"{run.decision.fraction:.3f} of the graph against a cap of "
                f"{run.decision.cap:.3f}, so no engine ran and no repaired graph "
                f"was written") if run.aborted else None)

    out = {"report.json": json.dumps({**run.payload, "summary": summary},
                                     indent=2, sort_keys=True) + "\n"}
    if constraints_json is not None:
        out["constraints.used.json"] = constraints_json
    if not run.aborted:
        out["repaired.nt"] = kgrepair.to_ntriples(run.result.graph)
        out["changes.nt.diff"] = "".join(
            line + "\n" for line in kgrepair.diff_lines(session.graph,
                                                        run.result.graph))
    return out


def bundle_archive(payloads: Dict[str, str], directory: str) -> str:
    """Write the payloads into a session directory and pack them into one archive.

    The directory is the caller's to clean up. Nothing here writes into the
    committed corpus or the manifest, and an uploaded graph never leaves the
    session directory it was put in.
    """
    os.makedirs(directory, exist_ok=True)
    for name, body in sorted(payloads.items()):
        with open(os.path.join(directory, name), "w", encoding="utf-8") as fh:
            fh.write(body)
    return kgrepair.zip_bundle(directory)


def change_rows(session: Session, run: "RepairRun", *, limit: int = 200) -> list:
    """The change list as display rows, with a plain name where the graph has one.

    Names come from the graph's own label predicates. Where there is none, the id
    is shown: inventing a name the data does not contain would be worse.
    """
    if run.aborted or run.result is None:
        return []
    labels = _label_index(session.graph)
    rows = []
    for record in run.result.changelog[:limit]:
        row = {"operation": record.op}
        if record.op in ("add_edge", "remove_edge"):
            row["subject"] = labels.get(record.src, record.src)
            row["predicate"] = record.label
            row["object"] = labels.get(record.dst, record.dst)
        else:
            row["subject"] = labels.get(record.src, record.src)
            row["predicate"] = ""
            row["object"] = ""
        rows.append(row)
    return rows


def change_counts(run: "RepairRun") -> Dict[str, int]:
    """How many of each kind of change, whether or not the list is shown."""
    if run.aborted or run.result is None:
        return {"add_edge": 0, "remove_edge": 0, "add_node": 0, "remove_node": 0}
    counts = {"add_edge": 0, "remove_edge": 0, "add_node": 0, "remove_node": 0}
    for record in run.result.changelog:
        counts[record.op] = counts.get(record.op, 0) + 1
    return counts


#: Predicates whose object reads as a display name for its subject.
LABEL_PREDICATES = ("rdfs:label", "skos:prefLabel", "schema:name", "foaf:name",
                    "dct:title")


def _label_index(graph) -> Dict[str, str]:
    index: Dict[str, str] = {}
    for src, label, dst in graph.edges():
        if label in LABEL_PREDICATES:
            value = graph.value(dst)
            index.setdefault(src, value if value and value != dst else dst)
    return index
