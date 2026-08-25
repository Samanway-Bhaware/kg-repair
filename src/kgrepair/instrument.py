"""
D7 instrumentation harness.

Every measured load / consistency / repair run is wrapped in a `RunContext`, which
times each phase, samples memory, reuses the repair engine's own attestations, and
appends exactly one JSON object per run to an append-only JSONL file under
`results/`. That log is the empirical dataset the D7 evaluation write-up draws on,
so no measured run happens outside this harness.

Design notes / measured deviations from the task premise:
  * `code_revision`: the task asks for a git SHA, but this tree is NOT a git
    repository (measured). We fall back to `nogit:<12-hex>` where the hex is a
    content hash of `src/kgrepair/**/*.py`, so runs are still retraceable to code.
  * Memory: no third-party deps are available, so we use the stdlib only --
    `tracemalloc` for peak traced Python-object bytes (precise for the DataGraph)
    and `resource.ru_maxrss` for process peak RSS (normalised to bytes across
    darwin/linux). `bytes_per_edge` is derived from the traced peak.

Public surface:
  RunContext(...)          context manager wrapping one run
  constraints_meta(cs)     summarise a ConstraintSet for a record
  validate_record(rec)     lightweight schema check -> list[str] of problems
  summarise_timing(path)   size-vs-phase-time table rows
  summarise_strategies(..) full-vs-incremental comparison rows
  render_table(rows)       ascii table string
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import resource
import subprocess
import time
import tracemalloc
import uuid
from contextlib import contextmanager
from typing import Dict, Iterator, List, Optional

_SRC_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # .../src
_MODES = ("consistency", "subset_full", "subset_incremental", "superset")


 
# provenance helpers
 

def _src_content_hash() -> str:
    h = hashlib.sha256()
    for root, _dirs, files in sorted(os.walk(os.path.join(_SRC_ROOT, "kgrepair"))):
        for name in sorted(files):
            if name.endswith(".py"):
                with open(os.path.join(root, name), "rb") as fh:
                    h.update(fh.read())
    return h.hexdigest()[:12]


def code_revision() -> str:
    """An identifier for the code that produced a run, for retraceability.

    The git commit SHA when this tree is a git checkout, otherwise
    `nogit:<hash>` over the package sources, so a record always ties back to
    the code that made it.
    """
    try:
        sha = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=_SRC_ROOT,
            stderr=subprocess.DEVNULL,
        ).decode().strip()
        if sha:
            return sha
    except Exception:
        pass
    return "nogit:" + _src_content_hash()


def content_hash(obj) -> str:
    """Stable hash of any JSON-serialisable object (canonical form)."""
    blob = json.dumps(obj, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def _peak_rss_bytes() -> int:
    ru = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    # darwin reports bytes; linux reports kilobytes.
    return ru if platform.system() == "Darwin" else ru * 1024


def constraints_meta(constraints) -> Dict:
    """Tier/direction counts for the record's `constraints` block."""
    from .constraints.model import ConstraintSet
    cs = constraints.constraints if isinstance(constraints, ConstraintSet) else list(constraints)
    by_tier: Dict[str, int] = {}
    by_dir: Dict[str, int] = {}
    for c in cs:
        by_tier[c.tier] = by_tier.get(c.tier, 0) + 1
        by_dir[c.direction] = by_dir.get(c.direction, 0) + 1
    name = getattr(constraints, "name", "adhoc")
    return {"set_id": name, "count": len(cs), "by_tier": by_tier, "by_direction": by_dir}


def slice_meta_from_graph(graph, *, source: str, manifest_hash: str = "",
                          seed: Optional[int] = None, params: Optional[Dict] = None,
                          hierarchy_depth: Optional[int] = None) -> Dict:
    """Build the `slice` block from a DataGraph's own stats."""
    s = graph.stats()
    return {
        "source": source,                 # "synthetic" | "fixture"
        "manifest_hash": manifest_hash,
        "seed": seed,
        "params": params or {},
        "V": s["nodes"], "E": s["edges"],
        "labels": s["labels"], "data_values": s["valued_nodes"],
        "hierarchy_depth": hierarchy_depth,
    }


 
# run context
 

class RunContext:
    """
    with RunContext(results_dir, slice=..., constraints=..., mode="subset_full") as run:
        with run.phase("load"):        g = load(...)
        with run.phase("repair_loop"): res = subset_repair(...)
        run.set_repair_result(res, before_report, after_report)
    # record written on exit
    """

    def __init__(self, results_dir: str, *, slice: Dict, constraints: Dict,
                 mode: str, config: Optional[Dict] = None,
                 filename: str = "runs.jsonl"):
        if mode not in _MODES:
            raise ValueError(f"mode must be one of {_MODES}, got {mode!r}")
        self.results_dir = results_dir
        self.filename = filename
        self.slice = slice
        self.constraints = constraints
        self.mode = mode
        self.config = config or {}
        self.run_id = uuid.uuid4().hex
        self.phases: Dict[str, float] = {}
        self.repair_stats: Dict = {}
        self.attestations: Dict[str, bool] = {}
        self.status = "OK"
        self._record: Optional[Dict] = None

    # -- phase timing --------------------------------------------------------
    @contextmanager
    def phase(self, name: str) -> Iterator[None]:
        t = time.perf_counter()
        try:
            yield
        finally:
            self.phases[name] = self.phases.get(name, 0.0) + (time.perf_counter() - t)

    # -- results plumbing ----------------------------------------------------
    def set_repair_result(self, result, before=None, after=None) -> None:
        """Pull stats + attestations straight from a SubsetRepairResult."""
        self.attestations = dict(result.attestations)
        stats = {
            "rounds": result.rounds,
            "nodes_removed": len(result.deleted_nodes),
            "edges_removed": sum(1 for r in result.changelog if r.op == "remove_edge"),
            "recheck_count": result.recheck_count,
            "strategy": result.mode,
        }
        if before is not None:
            stats["violations_before"] = {v.constraint.cid: v.count for v in before.failing()}
        if after is not None:
            stats["violations_after"] = {v.constraint.cid: v.count for v in after.failing()}
        self.repair_stats = stats
        if not all(self.attestations.values()):
            self.status = "FAILED"

    def set_superset_result(self, result, before=None, after=None) -> None:
        """Pull stats + attestations straight from a SupersetRepairResult (D6)."""
        self.attestations = dict(result.attestations)
        stats = {
            "rounds": result.rounds,
            "nodes_added": len(result.added_nodes),
            "edges_added": len(result.added_edges),
            "additions_by_kind": dict(result.additions_by_kind),
            "additions_by_constraint": dict(result.additions_by_constraint),
            "fresh_used": len(result.fresh_used),
            "pruned_edges": result.pruned_edges,
            "pruned_nodes": result.pruned_nodes,
            "pool": dict(result.pool),
            "strategy": result.mode,
        }
        if before is not None:
            stats["violations_before"] = {v.constraint.cid: v.count for v in before.failing()}
        if after is not None:
            stats["violations_after"] = {v.constraint.cid: v.count for v in after.failing()}
        self.repair_stats = stats
        if not all(self.attestations.values()):
            self.status = "FAILED"

    def set_attestations(self, attestations: Dict[str, bool]) -> None:
        self.attestations = dict(attestations)
        if not all(self.attestations.values()):
            self.status = "FAILED"

    # -- lifecycle -----------------------------------------------------------
    def __enter__(self) -> "RunContext":
        tracemalloc.start()
        self._wall0 = time.perf_counter()
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        traced_cur, traced_peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        if exc_type is not None:
            self.status = "FAILED"
        edges = max(1, int(self.slice.get("E", 0)))
        self._record = {
            "run_id": self.run_id,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "code_revision": code_revision(),
            "config_hash": content_hash(self.config),
            "status": self.status,
            "slice": self.slice,
            "constraints": self.constraints,
            "mode": self.mode,
            "timings_s": {k: round(v, 6) for k, v in self.phases.items()},
            "wall_total_s": round(time.perf_counter() - self._wall0, 6),
            "repair": self.repair_stats,
            "resources": {
                "peak_rss_bytes": _peak_rss_bytes(),
                "peak_traced_bytes": traced_peak,
                "bytes_per_edge": round(traced_peak / edges, 2),
            },
            "attestations": self.attestations,
        }
        self._write(self._record)
        return False  # never suppress exceptions

    def _write(self, record: Dict) -> None:
        os.makedirs(self.results_dir, exist_ok=True)
        with open(os.path.join(self.results_dir, self.filename), "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")

    @property
    def record(self) -> Optional[Dict]:
        return self._record


 
# schema check (lightweight; no jsonschema dependency)
 

_REQUIRED = {
    "run_id": str, "timestamp": str, "code_revision": str, "config_hash": str,
    "status": str, "slice": dict, "constraints": dict, "mode": str,
    "timings_s": dict, "wall_total_s": (int, float), "repair": dict,
    "resources": dict, "attestations": dict,
}
_SLICE_REQUIRED = {"source": str, "V": int, "E": int, "labels": int, "data_values": int}
_RES_REQUIRED = {"peak_rss_bytes": int, "peak_traced_bytes": int, "bytes_per_edge": (int, float)}


def validate_record(rec: Dict) -> List[str]:
    """Return a list of schema problems; empty list == valid."""
    problems: List[str] = []
    for key, typ in _REQUIRED.items():
        if key not in rec:
            problems.append(f"missing top-level key: {key}")
        elif not isinstance(rec[key], typ):
            problems.append(f"{key}: expected {typ}, got {type(rec[key]).__name__}")
    if rec.get("mode") not in _MODES:
        problems.append(f"mode not in {_MODES}: {rec.get('mode')!r}")
    if rec.get("status") not in ("OK", "FAILED", "ABORTED-BY-CAP"):
        problems.append(f"status not OK/FAILED/ABORTED-BY-CAP: {rec.get('status')!r}")
    sl = rec.get("slice", {})
    for key, typ in _SLICE_REQUIRED.items():
        if key not in sl or not isinstance(sl[key], typ):
            problems.append(f"slice.{key} missing/wrong-type")
    if sl.get("source") not in ("synthetic", "fixture", "real"):
        problems.append(f"slice.source must be synthetic|fixture|real: {sl.get('source')!r}")
    res = rec.get("resources", {})
    for key, typ in _RES_REQUIRED.items():
        if key not in res or not isinstance(res[key], typ):
            problems.append(f"resources.{key} missing/wrong-type")
    return problems


 
# summariser
 

def _load_records(path: str) -> List[Dict]:
    out: List[Dict] = []
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def summarise_timing(path: str) -> List[Dict]:
    """One row per (source, mode, |E|): the phase wall-times, sorted by size."""
    rows: List[Dict] = []
    for r in _load_records(path):
        row = {
            "source": r["slice"]["source"],
            "mode": r["mode"],
            "E": r["slice"]["E"],
            "V": r["slice"]["V"],
            "bytes_per_edge": r["resources"]["bytes_per_edge"],
            "status": r["status"],
        }
        row.update({f"t_{k}": v for k, v in r.get("timings_s", {}).items()})
        rows.append(row)
    rows.sort(key=lambda x: (x["source"], x["E"], x["mode"]))
    return rows


def summarise_strategies(path: str) -> List[Dict]:
    """
    Pair subset_full vs subset_incremental records by |E| and show the recheck /
    repair-loop-time deltas -- the OPT-1 payoff table.
    """
    by_size: Dict[int, Dict[str, Dict]] = {}
    for r in _load_records(path):
        if r["mode"] in ("subset_full", "subset_incremental") and r["repair"]:
            by_size.setdefault(r["slice"]["E"], {})[r["mode"]] = r
    rows: List[Dict] = []
    for e in sorted(by_size):
        pair = by_size[e]
        if "subset_full" in pair and "subset_incremental" in pair:
            f, i = pair["subset_full"], pair["subset_incremental"]
            fr, ir = f["repair"]["recheck_count"], i["repair"]["recheck_count"]
            ft = f["timings_s"].get("repair_loop", 0.0)
            it = i["timings_s"].get("repair_loop", 0.0)
            rows.append({
                "E": e,
                "recheck_full": fr, "recheck_incr": ir,
                "recheck_reduction_%": round(100 * (fr - ir) / fr, 1) if fr else 0.0,
                "t_repair_full_s": ft, "t_repair_incr_s": it,
                "nodes_removed": f["repair"]["nodes_removed"],
            })
    return rows


def render_table(rows: List[Dict]) -> str:
    if not rows:
        return "(no rows)"
    cols: List[str] = []
    for r in rows:
        for k in r:
            if k not in cols:
                cols.append(k)
    widths = {c: max(len(c), *(len(str(r.get(c, ""))) for r in rows)) for c in cols}
    head = "  ".join(c.ljust(widths[c]) for c in cols)
    sep = "  ".join("-" * widths[c] for c in cols)
    body = "\n".join("  ".join(str(r.get(c, "")).ljust(widths[c]) for c in cols) for r in rows)
    return f"{head}\n{sep}\n{body}"
