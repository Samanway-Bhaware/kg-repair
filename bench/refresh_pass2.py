"""
Pass-2 refresh: re-fetch the Table 5 corpus from live sources and report the drift.

A diagnostic, not a gate. It has no pass/fail, it reaches the network, and it is
never registered with pytest. Run it by hand when you want to know how far the
upstream data has moved since the frozen corpus was captured.

What it does, per cell:

  1. read the ORIGINAL slice parameters out of the frozen manifest (seeds, target
     edge count, allow-list, frontier rule) rather than re-specifying them;
  2. re-fetch from the live source into a NEW dated cache generation;
  3. re-slice with those identical parameters, so the only thing that varies is
     the upstream data;
  4. check the refreshed slice at the SAME constraint version the frozen baseline
     used;
  5. diff refreshed against frozen at the level of individual constraints.

Provenance separation is the point of the whole exercise. The frozen artifacts
under `fixtures/real/` are the numbers the write-up reports and they are
read-only here. Refreshed artifacts are written to `fixtures/real_refresh/<date>/`
as new files with their own hashes and fetch timestamps. The two sets are
reported side by side and never merged.

Drift expected by source
------------------------
  wikidata  live-edited continuously, so this is where drift shows up. There is
            no release marker to pin against; the fetch timestamp is the only
            identity a refreshed Wikidata slice has.
  dbpedia   periodic releases, so drift is stepwise: nothing for months, then a
            jump when a new release lands behind the endpoint.
  yago      YAGO 4.5 is a fixed release read from a local dump, not an endpoint.
            A refresh re-reads the same file and will show ZERO drift unless the
            dump itself was replaced. The dump's hash and modification time are
            recorded so a swap is visible rather than silent.

Usage
-----
  python bench/refresh_pass2.py                          # all ten cells
  python bench/refresh_pass2.py --source wikidata        # only the live-edited ones
  python bench/refresh_pass2.py --cell real_wikidata_geography_1000
  python bench/refresh_pass2.py --no-fetch               # re-slice from the refresh
                                                         # cache already on disk
  python bench/refresh_pass2.py --report-only --refresh-dir fixtures/real_refresh/20260801
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
# The cell table lives in the pass-1 gate. Importing it keeps one source for which
# cells exist, which constraint version each is pinned to, and what the frozen
# counts are, instead of a second copy here that could drift away from the gate.
sys.path.insert(0, os.path.join(ROOT, "tests"))

from test_regression_pass1 import CELLS                                  # noqa: E402

from kgrepair import constraints                                          # noqa: E402
from kgrepair.ntriples import load_ntriples, load_ntriples_file           # noqa: E402
from kgrepair.pipeline import (RawCache, SliceParams, deny_check,         # noqa: E402
                               load_allowlist, slice_from_cache)
from kgrepair.pipeline.extract import (DBPEDIA_ENDPOINT, WIKIDATA_ENDPOINT,  # noqa: E402
                                       sparql_extract, typing_closure_extract)
from kgrepair.pipeline.fetch import FetchPolicy, PoliteFetcher            # noqa: E402
from kgrepair.pipeline.slicing import typing_complete                     # noqa: E402
from kgrepair.validator import Validator                                  # noqa: E402

FROZEN_DIR = os.path.join(ROOT, "fixtures", "real")
REFRESH_ROOT = os.path.join(ROOT, "fixtures", "real_refresh")
CACHE_ROOT = os.path.join(ROOT, "data", "raw_refresh")
RESULTS_DIR = os.path.join(ROOT, "results")
YAGO_DUMP = os.path.join(ROOT, "data", "dumps", "yago-tiny.zip")

FROZEN_LABEL = "frozen (as-reported)"
REFRESHED_LABEL = "live (D8-release candidate, fetched {date})"

#: How much a slice's edge count may move before the comparison flags it. The
#: target edge count is pinned, so E should be near-constant; a real move means
#: the slice composition shifted and a count change cannot be read as pure drift.
EDGE_DRIFT_TOLERANCE = 0.02


 
# part A: what each cell is, read from its frozen manifest
 
@dataclass
class Cell:
    """One Table 5 cell and everything needed to refresh it.

    `kind` is "bfs" for a slice produced directly by the size-capped walk, or
    "typed" for the two T0 typing-completed slices, which are derived from a base
    slice rather than walked themselves and so have to be rebuilt in two stages.
    """
    name: str
    kind: str
    domain: str
    kg: str
    version: int
    frozen_manifest: Dict
    base_manifest: Dict            # same as frozen_manifest for a "bfs" cell
    frozen_total: int
    frozen_core: int

    @property
    def source(self) -> str:
        return self.frozen_manifest["slice_source"]

    @property
    def target_edges(self) -> int:
        return self.base_manifest["target_edges"]

    def slice_params(self) -> SliceParams:
        """The ORIGINAL parameters, straight out of the frozen manifest.

        Nothing here is re-specified or recomputed. Changing a seed set or an edge
        target on refresh would confound sampling changes with data drift, which is
        the one thing this comparison has to keep apart.
        """
        m = self.base_manifest
        return SliceParams(source=m["slice_source"], domain=m["domain"],
                           seeds=list(m["seeds"]), target_edges=m["target_edges"],
                           allowlist_id=m["allowlist_id"],
                           frontier_rule=m.get("frontier_rule", "sorted_bfs"))

    def constraint_set(self):
        return constraints.get(self.domain, self.kg, version=self.version)


def _read_manifest(name: str) -> Dict:
    with open(os.path.join(FROZEN_DIR, f"{name}.manifest.json"), encoding="utf-8") as fh:
        return json.load(fh)


def _parse_args_table(args: List[str]):
    """(domain, kg, version) out of a pass-1 CELLS argument list."""
    domain = args[args.index("--domain") + 1]
    kg = args[args.index("--kg") + 1]
    version = int(args[args.index("--version") + 1]) if "--version" in args else 1
    return domain, kg, version


def load_cells() -> List[Cell]:
    """Every Table 5 cell, with its parameters read from the frozen manifests."""
    out: List[Cell] = []
    for name, args, total, core in CELLS:
        frozen = _read_manifest(name)
        domain, kg, version = _parse_args_table(args)
        if "seeds" in frozen:
            kind, base = "bfs", frozen
        else:
            # A typing-completed slice records no seeds of its own; it names the
            # base slice it was derived from, and that is where the walk parameters
            # live. Refreshing it means refreshing the base and re-deriving.
            kind, base = "typed", _read_manifest(frozen["supersedes"])
        out.append(Cell(name=name, kind=kind, domain=domain, kg=kg, version=version,
                        frozen_manifest=frozen, base_manifest=base,
                        frozen_total=total, frozen_core=core))
    return out


 
# part B: counting and comparison. Pure, offline, deterministic, re-runnable.
 
@dataclass
class Counts:
    """Violation counts for one slice, at the granularity the comparison needs."""
    total: int = 0                        # both tiers, the Table 5 figure
    core: int = 0                         # ptime_core subtotal, the repairable part
    boundary: int = 0
    per_cid: Dict[str, int] = field(default_factory=dict)
    V: int = 0
    E: int = 0

    def to_dict(self) -> Dict:
        return {"total": self.total, "core": self.core, "boundary": self.boundary,
                "per_cid": dict(sorted(self.per_cid.items())), "V": self.V, "E": self.E}


def counts_from_report(report, graph) -> Counts:
    """Counts for a checked slice, from `ValidationReport.to_dict()`.

    Uses the same report shape and the same tier split the pass-1 gate asserts
    against, so a refreshed number is computed exactly the way a frozen one was.
    """
    result = report.to_dict(witness_limit=0)
    core = sum(c["witness_count"] for c in result["constraints"]
               if c["tier"] == "ptime_core")
    boundary = sum(c["witness_count"] for c in result["constraints"]
                   if c["tier"] == "boundary")
    per_cid = {c["cid"]: c["witness_count"] for c in result["constraints"]
               if c["witness_count"]}
    stats = graph.stats()
    return Counts(total=core + boundary, core=core, boundary=boundary,
                  per_cid=per_cid, V=stats["nodes"], E=stats["edges"])


def counts_from_manifest(manifest: Dict, cs) -> Counts:
    """Counts for a frozen slice, from its manifest's recorded violations.

    The manifest stores one number per constraint that fired, without a tier, so
    the tier split is recovered from the constraint set the cell is pinned to.
    """
    per_cid = dict(manifest.get("violations", {}))
    tier_of = {c.cid: c.tier for c in cs}
    core = sum(n for cid, n in per_cid.items() if tier_of.get(cid) == "ptime_core")
    boundary = sum(n for cid, n in per_cid.items() if tier_of.get(cid) == "boundary")
    return Counts(total=core + boundary, core=core, boundary=boundary,
                  per_cid=per_cid, V=manifest.get("V", 0), E=manifest.get("E", 0))


def prevalence(core: int, edges: int) -> float:
    """Repairable violations per 1000 edges.

    Normalising by size is what separates the two readings of a count change:
    the same prevalence on a different edge count means the slice moved, while a
    changed prevalence at a steady edge count means the data did.
    """
    if edges <= 0:
        return 0.0
    return round(core * 1000.0 / edges, 4)


def cid_deltas(baseline: Counts, refreshed: Counts) -> List[Dict]:
    """One row per constraint that fired in either slice, sorted by cid."""
    rows = []
    for cid in sorted(set(baseline.per_cid) | set(refreshed.per_cid)):
        was = baseline.per_cid.get(cid, 0)
        now = refreshed.per_cid.get(cid, 0)
        rows.append({"cid": cid, "frozen": was, "refreshed": now, "delta": now - was})
    return rows


def edge_drift(baseline: Counts, refreshed: Counts) -> float:
    """Fractional change in edge count. Near zero is expected: the target is pinned."""
    if baseline.E <= 0:
        return 0.0
    return round((refreshed.E - baseline.E) / baseline.E, 4)


def compare_cell(name: str, baseline: Counts, refreshed: Counts,
                 provenance: Optional[Dict] = None) -> Dict:
    """The full comparison for one cell. No I/O, no clock, no network."""
    base_prev = prevalence(baseline.core, baseline.E)
    live_prev = prevalence(refreshed.core, refreshed.E)
    drift = edge_drift(baseline, refreshed)
    return {
        "cell": name,
        "status": "ok",
        "frozen": baseline.to_dict(),
        "refreshed": refreshed.to_dict(),
        "core_delta": refreshed.core - baseline.core,
        "total_delta": refreshed.total - baseline.total,
        "frozen_prevalence_per_1k_edges": base_prev,
        "refreshed_prevalence_per_1k_edges": live_prev,
        "prevalence_delta": round(live_prev - base_prev, 4),
        "edge_drift_fraction": drift,
        "composition_shifted": abs(drift) > EDGE_DRIFT_TOLERANCE,
        "cid_deltas": cid_deltas(baseline, refreshed),
        "moved": refreshed.per_cid != baseline.per_cid,
        "provenance": provenance or {},
    }


def failed_cell(name: str, reason: str, baseline: Optional[Counts] = None) -> Dict:
    """A cell whose fetch did not complete. Recorded, and the run carries on."""
    return {"cell": name, "status": "fetch_failed", "reason": reason,
            "frozen": baseline.to_dict() if baseline else {}, "refreshed": {},
            "cid_deltas": [], "moved": None, "provenance": {}}


 
# part A continued: fetch and re-slice (this is the part that reaches the network)
 
def _file_marker(path: str) -> Dict:
    """Identity of a local dump file, so a swapped release is visible."""
    if not os.path.exists(path):
        return {"path": os.path.relpath(path, ROOT), "present": False}
    with open(path, "rb") as fh:
        digest = hashlib.sha256(fh.read()).hexdigest()[:16]
    return {"path": os.path.relpath(path, ROOT), "present": True, "sha256_16": digest,
            "modified": time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                      time.gmtime(os.path.getmtime(path)))}


def _source_release(source: str) -> Dict:
    """What the refreshed data was fetched against, as far as it can be pinned."""
    if source == "wikidata":
        return {"kind": "live endpoint", "endpoint": WIKIDATA_ENDPOINT,
                "release": "none (continuously edited; the fetch timestamp is the "
                           "only identity this data has)"}
    if source == "dbpedia":
        return {"kind": "live endpoint", "endpoint": DBPEDIA_ENDPOINT,
                "release": "periodic (the endpoint serves whichever release is "
                           "current; drift is stepwise, not continuous)"}
    return {"kind": "local dump", "endpoint": None,
            "release": "YAGO 4.5, a fixed release: zero drift is the expected "
                       "result unless the dump file itself changed",
            "dump": _file_marker(YAGO_DUMP)}


def _content_hash(graph) -> str:
    payload = sorted(graph.edges())
    return hashlib.sha256(json.dumps(payload).encode("utf-8")).hexdigest()[:16]


def _serialize(graph, name: str, header: str) -> str:
    lines = [f"# refreshed slice {name} ({header})"]
    for s, p, o in sorted(graph.edges()):
        lines.append(f"<{s}> <{p}> <{o}> .")
    return "\n".join(lines) + "\n"


def refresh_cell(cell: Cell, out_dir: str, *, do_fetch: bool, min_interval: float,
                 max_requests: int) -> Dict:
    """Re-fetch, re-slice and check one cell. Returns its comparison row.

    A fetch problem for this cell is caught and recorded; the caller keeps going
    with the others.
    """
    cs = cell.constraint_set()
    baseline = counts_from_manifest(cell.frozen_manifest, cs)
    fetched_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    cache = RawCache(os.path.join(CACHE_ROOT, cell.domain))
    al = load_allowlist(cell.source)
    fetch_report: Dict = {}

    try:
        if do_fetch and cell.source in ("wikidata", "dbpedia"):
            fetcher = PoliteFetcher(FetchPolicy(min_interval_s=min_interval))
            fetch_report = sparql_extract(cell.source, cell.domain, cache, fetcher,
                                          target_edges=cell.target_edges,
                                          max_requests=max_requests)
        elif cell.source == "yago" and not os.path.exists(YAGO_DUMP):
            return failed_cell(cell.name, f"YAGO dump not present at "
                                          f"{os.path.relpath(YAGO_DUMP, ROOT)}", baseline)

        params = cell.slice_params()
        sl = slice_from_cache(cache, params, name=cell.name)
        graph = sl.graph
        manifest = dict(sl.manifest)

        if cell.kind == "typed":
            # Same two-stage build the frozen typed slices used: close the typing
            # spine in the cache, then complete the slice's typing without
            # re-running the edge-capped walk, which would re-truncate it.
            closure = {}
            if do_fetch:
                fetcher = PoliteFetcher(FetchPolicy(min_interval_s=min_interval))
                closure = typing_closure_extract(cell.source, cell.domain, cache,
                                                 fetcher, max_rounds=12,
                                                 max_requests=max_requests)
            added = typing_complete(graph, cache, al)
            manifest.update(generation="typed (T0 typing-completed)",
                            supersedes=cell.base_manifest["name"],
                            closure_report=closure, typing_edges_added=added,
                            typing_closure_fetched=bool(do_fetch))

        denied = deny_check(graph, al)
        if denied:
            return failed_cell(cell.name,
                               f"Level-0 deny-check tripped on refreshed data: {denied}",
                               baseline)

        report = Validator(graph, use_closure=True).validate(cs)
        refreshed = counts_from_report(report, graph)

    except Exception as exc:                      # any fetch or slice problem
        return failed_cell(cell.name, f"{type(exc).__name__}: {exc}", baseline)

    stats = graph.stats()
    manifest.update(
        name=cell.name, V=stats["nodes"], E=stats["edges"],
        labels=stats["labels"], data_values=stats["valued_nodes"],
        content_hash=_content_hash(graph),
        violations=refreshed.per_cid,
        constraint_version=cell.version,
        generation_role="refreshed (D8-release candidate)",
        baseline_manifest=cell.frozen_manifest["name"],
        baseline_content_hash=cell.frozen_manifest.get("content_hash", ""),
        fetched_at=fetched_at,
        source_release=_source_release(cell.source),
        fetch_report=fetch_report,
    )

    os.makedirs(out_dir, exist_ok=True)
    base = os.path.join(out_dir, cell.name)
    header = (f"source={cell.source}; refreshed {fetched_at}; "
              f"content_hash={manifest['content_hash']}")
    nt = _serialize(graph, cell.name, header)
    reloaded = load_ntriples(nt.splitlines())
    if set(reloaded.edges()) != set(graph.edges()):
        return failed_cell(cell.name, "round-trip mismatch on the refreshed slice",
                           baseline)
    with open(base + ".nt", "w", encoding="utf-8") as fh:
        fh.write(nt)
    with open(base + ".manifest.json", "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2, sort_keys=True)

    row = compare_cell(cell.name, baseline, refreshed, provenance={
        "fetched_at": fetched_at,
        "refreshed_content_hash": manifest["content_hash"],
        "frozen_content_hash": cell.frozen_manifest.get("content_hash", ""),
        "cache_generation_hash": manifest.get("cache_generation_hash", ""),
        "constraint_version": cell.version,
        "source_release": manifest["source_release"],
        "typing_closure_fetched": manifest.get("typing_closure_fetched"),
    })
    if cell.kind == "typed" and not do_fetch:
        # Without the closure fetch the cache holds no typing beyond whatever a
        # previous run left there, so the slice is under-typed and its counts are
        # not comparable to the frozen baseline. Say so rather than letting the
        # gap read as upstream drift.
        row["caveat"] = ("built with --no-fetch, so the typing-closure fetch this "
                         "cell depends on did not run. The slice is under-typed and "
                         "these counts are not a drift measurement.")
    return row


def report_only(cell: Cell, refresh_dir: str) -> Dict:
    """Recompute a cell's comparison from refreshed artifacts already on disk.

    Offline and deterministic: given a fixed refreshed slice this reproduces the
    same row every time, so a report can be rebuilt without fetching again.
    """
    cs = cell.constraint_set()
    baseline = counts_from_manifest(cell.frozen_manifest, cs)
    nt_path = os.path.join(refresh_dir, f"{cell.name}.nt")
    manifest_path = os.path.join(refresh_dir, f"{cell.name}.manifest.json")
    if not os.path.exists(nt_path):
        return failed_cell(cell.name, f"no refreshed slice at "
                                      f"{os.path.relpath(nt_path, ROOT)}", baseline)
    graph = load_ntriples_file(nt_path)
    report = Validator(graph, use_closure=True).validate(cs)
    refreshed = counts_from_report(report, graph)
    provenance = {}
    if os.path.exists(manifest_path):
        with open(manifest_path, encoding="utf-8") as fh:
            m = json.load(fh)
        provenance = {"fetched_at": m.get("fetched_at", ""),
                      "refreshed_content_hash": m.get("content_hash", ""),
                      "frozen_content_hash": cell.frozen_manifest.get("content_hash", ""),
                      "cache_generation_hash": m.get("cache_generation_hash", ""),
                      "constraint_version": cell.version,
                      "source_release": m.get("source_release", {})}
    return compare_cell(cell.name, baseline, refreshed, provenance)


 
# part C: the report
 
def _pct(x: float) -> str:
    return f"{x * 100:+.1f}%"


def render_markdown(rows: List[Dict], date: str) -> str:
    """The refresh report. Pure text assembly from the comparison rows."""
    live_label = REFRESHED_LABEL.format(date=date)
    out: List[str] = []
    out.append(f"# Pass-2 refresh, {date}\n")
    out.append(
        f"Two independent sets of numbers, reported side by side and never merged.\n\n"
        f"- **{FROZEN_LABEL}**: the committed corpus under `fixtures/real/`. These\n"
        f"  are the figures the write-up reports and the ones "
        f"`tests/test_regression_pass1.py` holds fixed. Nothing in this run modifies\n"
        f"  them.\n"
        f"- **{live_label}**: the same slice parameters re-run against today's\n"
        f"  upstream data, written to `fixtures/real_refresh/{date}/`. These are\n"
        f"  release candidates for D8, not corrections to the reported results.\n\n"
        f"Slice parameters (seeds, target edge count, allow-list, frontier rule) and\n"
        f"the constraint version are read from each frozen manifest and reused, so\n"
        f"the only variable between the two columns is the upstream data.\n")

    moved = [r for r in rows if r["status"] == "ok" and r["moved"]]
    steady = [r for r in rows if r["status"] == "ok" and not r["moved"]]
    failed = [r for r in rows if r["status"] == "fetch_failed"]

    out.append("\n## Summary\n")
    out.append(f"{len(moved)} cell(s) moved, {len(steady)} held steady, "
               f"{len(failed)} did not fetch.\n")
    out.append("\n| cell | status | frozen core | live core | delta | frozen /1k E | "
               "live /1k E | prevalence delta | E drift |")
    out.append("|---|---|---|---|---|---|---|---|---|")
    for r in rows:
        if r["status"] != "ok":
            out.append(f"| {r['cell']} | fetch_failed | "
                       f"{r['frozen'].get('core', '?')} | n/a | n/a | n/a | n/a | n/a | n/a |")
            continue
        flag = " (composition shifted)" if r["composition_shifted"] else ""
        state = "caveat" if r.get("caveat") else ("moved" if r["moved"] else "steady")
        out.append(
            f"| {r['cell']} | {state} | {r['frozen']['core']} | {r['refreshed']['core']} | "
            f"{r['core_delta']:+d} | {r['frozen_prevalence_per_1k_edges']} | "
            f"{r['refreshed_prevalence_per_1k_edges']} | {r['prevalence_delta']:+} | "
            f"{_pct(r['edge_drift_fraction'])}{flag} |")

    if failed:
        out.append("\n### Cells that did not fetch\n")
        for r in failed:
            out.append(f"- `{r['cell']}`: {r['reason']}")
        out.append("\nA fetch failure stops that cell only. The rest of the run "
                   "continues, and the cell can be retried on its own with "
                   "`--cell <name>`.\n")

    out.append("\n## Per cell\n")
    for r in rows:
        out.append(f"\n### {r['cell']}\n")
        if r["status"] != "ok":
            out.append(f"**fetch_failed**: {r['reason']}\n")
            continue
        p = r["provenance"]
        rel = p.get("source_release", {})
        unset = "not recorded"
        out.append(f"- fetched: {p.get('fetched_at') or unset}")
        out.append(f"- source: {rel.get('kind', unset)}"
                   + (f" `{rel['endpoint']}`" if rel.get("endpoint") else ""))
        out.append(f"- source release: {rel.get('release', unset)}")
        if rel.get("dump"):
            d = rel["dump"]
            out.append(f"- dump: `{d.get('path')}` sha256/16 `{d.get('sha256_16', '?')}` "
                       f"modified `{d.get('modified', '?')}`")
        out.append(f"- constraint version: v{p.get('constraint_version', unset)} "
                   f"(the version the frozen baseline used)")
        out.append(f"- content hash: frozen `{p.get('frozen_content_hash') or unset}` "
                   f"vs refreshed `{p.get('refreshed_content_hash') or unset}`")
        out.append(f"- cache generation: `{p.get('cache_generation_hash') or unset}`\n")
        if r.get("caveat"):
            out.append(f"> Not a drift measurement: {r['caveat']}\n")

        out.append(f"| | V | E | ptime_core | boundary | total | per 1k edges |")
        out.append("|---|---|---|---|---|---|---|")
        out.append(f"| {FROZEN_LABEL} | {r['frozen']['V']} | {r['frozen']['E']} | "
                   f"{r['frozen']['core']} | {r['frozen']['boundary']} | "
                   f"{r['frozen']['total']} | {r['frozen_prevalence_per_1k_edges']} |")
        out.append(f"| {live_label} | {r['refreshed']['V']} | {r['refreshed']['E']} | "
                   f"{r['refreshed']['core']} | {r['refreshed']['boundary']} | "
                   f"{r['refreshed']['total']} | {r['refreshed_prevalence_per_1k_edges']} |")

        out.append("\n| constraint | frozen | refreshed | delta |")
        out.append("|---|---|---|---|")
        for row in r["cid_deltas"]:
            out.append(f"| `{row['cid']}` | {row['frozen']} | {row['refreshed']} | "
                       f"{row['delta']:+d} |")

        if r["composition_shifted"]:
            out.append(f"\nEdge count moved {_pct(r['edge_drift_fraction'])} even though "
                       f"the target edge count is pinned. The slice composition itself "
                       f"shifted, so read the count change against the prevalence "
                       f"column rather than as data drift alone.\n")
        if r["core_delta"] < 0:
            out.append(
                "\nThe repairable count fell. Two explanations fit equally well and "
                "this report does not choose between them:\n\n"
                "1. upstream corrected genuine errors, so there is less to repair;\n"
                "2. the slice composition shifted, so a different population is "
                "being measured.\n\n"
                "The prevalence column and the per-constraint table above are what "
                "separate the two: a drop concentrated in one constraint at a steady "
                "edge count points at the first, a drop spread across constraints "
                "alongside an edge or node move points at the second.\n")
        elif r["core_delta"] > 0:
            out.append("\nThe repairable count rose, so today's upstream data breaks "
                       "these rules more often than the frozen capture did.\n")
    return "\n".join(out) + "\n"


 
# driver
 
def select(cells: List[Cell], source: Optional[str], names: List[str]) -> List[Cell]:
    if names:
        wanted = set(names)
        cells = [c for c in cells if c.name in wanted]
    if source:
        cells = [c for c in cells if c.source == source]
    return cells


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--source", choices=["wikidata", "dbpedia", "yago"],
                    help="refresh only this source's cells")
    ap.add_argument("--cell", action="append", default=[],
                    help="refresh only this cell, repeatable")
    ap.add_argument("--no-fetch", action="store_true",
                    help="re-slice from the refresh cache already on disk, no network")
    ap.add_argument("--report-only", action="store_true",
                    help="rebuild the report from refreshed artifacts already written")
    ap.add_argument("--refresh-dir", help="artifact directory for --report-only")
    ap.add_argument("--date", default=time.strftime("%Y%m%d"),
                    help="dated artifact directory to write (default: today)")
    ap.add_argument("--min-interval", type=float, default=1.0)
    ap.add_argument("--max-requests", type=int, default=60)
    args = ap.parse_args()

    cells = select(load_cells(), args.source, args.cell)
    if not cells:
        print("no cells selected", file=sys.stderr)
        return 1

    out_dir = args.refresh_dir or os.path.join(REFRESH_ROOT, args.date)
    rows = []
    for cell in cells:
        print(f"[{cell.name}] {'reporting' if args.report_only else 'refreshing'} "
              f"(source={cell.source}, v{cell.version})", flush=True)
        if args.report_only:
            row = report_only(cell, out_dir)
        else:
            row = refresh_cell(cell, out_dir, do_fetch=not args.no_fetch,
                               min_interval=args.min_interval,
                               max_requests=args.max_requests)
        rows.append(row)
        if row["status"] == "ok":
            print(f"    core {row['frozen']['core']} -> {row['refreshed']['core']} "
                  f"({row['core_delta']:+d}), E drift {_pct(row['edge_drift_fraction'])}")
        else:
            print(f"    fetch_failed: {row['reason']}")

    os.makedirs(RESULTS_DIR, exist_ok=True)
    payload = {
        "date": args.date,
        "frozen_label": FROZEN_LABEL,
        "refreshed_label": REFRESHED_LABEL.format(date=args.date),
        "artifact_dir": os.path.relpath(out_dir, ROOT),
        "note": ("Frozen numbers stay the reproducible figures the write-up "
                 "reports. Refreshed numbers are D8 release candidates. The two "
                 "are never merged."),
        "cells": rows,
    }
    json_path = os.path.join(RESULTS_DIR, f"pass2_refresh_{args.date}.json")
    md_path = os.path.join(RESULTS_DIR, f"pass2_refresh_{args.date}.md")
    with open(json_path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, sort_keys=True)
    with open(md_path, "w", encoding="utf-8") as fh:
        fh.write(render_markdown(rows, args.date))
    print(f"\nwrote {os.path.relpath(md_path, ROOT)}")
    print(f"wrote {os.path.relpath(json_path, ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
