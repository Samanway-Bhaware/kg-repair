"""
P9: the repair campaign. Every committed slice through both engines, with the
quality metrics of P8b measured before and after.

One script, one argument. The campaign is repeatable rather than a sequence of
commands someone remembers, and every number in `eval/` traces back to a line of
`results/campaign.jsonl` written here.

Settings, fixed once and used unchanged for every cell:

  * **Constraints**: `constraints.get(domain, kg, version=2)`. Version 2 exists only
    for anatomy, disease and medication (the C1 work); for every other domain the
    call falls back to version 1. The set's own name is recorded per cell, so a
    reader can see which was actually used rather than trusting the request.
  * **Caps**: the library defaults, `SUBSET_CAP_DEFAULT` (0.20 of nodes) and
    `SUPERSET_CAP_DEFAULT` (0.30 of edges), through `check_cap`, which is the same
    report-first pre-check the command line and the viewer use. **A cap abort is a
    result and is never retried at a higher cap.**
  * **Corpus**: cache generation A, the frozen committed slices under
    `fixtures/real/`. Generation B exists (P8a) and is not used here: the evaluation
    chapter cites generation A, and mixing the two would put a drift difference
    inside a repair comparison.

Timing and memory come from separate passes over the same repair. Wrapping the
engine in `tracemalloc` inflates its runtime badly enough to dominate the
measurement, which `bench/derive_cost.py` found the hard way, so the timed pass runs
clean and a second pass measures allocation.

Usage: python scripts/run_campaign.py --out eval
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import tracemalloc

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import kgrepair                                                        # noqa: E402
from kgrepair.instrument import code_revision                          # noqa: E402
from kgrepair.repair import eligible_constraints                       # noqa: E402
from kgrepair.metrics import compare_metrics, compute_metrics          # noqa: E402

ROOT = os.path.join(os.path.dirname(__file__), "..")
REAL = os.path.join(ROOT, "fixtures", "real")
RESULTS = os.path.join(ROOT, "results")
CAMPAIGN_JSONL = os.path.join(RESULTS, "campaign.jsonl")

MODES = ("subset", "superset")

#: (source, domain, target, variant). `variant` names the typing-completed slices
#: built during D6/T0; they are separate slices, not alternative renderings of one,
#: and both are run because the pair is what shows the effect of the typing closure.
SLICES = [
    ("wikidata", "geography", 1000, ""),
    ("wikidata", "geography", 10000, ""),
    ("wikidata", "taxa", 1000, ""),
    ("wikidata", "taxa", 10000, ""),
    ("wikidata", "anatomy", 1000, ""),
    ("wikidata", "anatomy", 1000, "typed"),
    ("wikidata", "disease", 1000, ""),
    ("wikidata", "medication", 1000, ""),
    ("wikidata", "medication", 1000, "typed"),
    ("dbpedia", "geography", 1000, ""),
    ("yago", "taxa", 1000, ""),
    ("yago", "taxa", 10000, ""),
]

#: (domain, kg) pairs with no cell, and why. Reported up front so nothing is
#: discovered missing mid-campaign.
ABSENT = [
    ("anatomy", "dbpedia", "no constraint set and no slice: the biomedical domains "
                           "were scoped to Wikidata at D1/D2"),
    ("anatomy", "yago", "same scoping decision"),
    ("disease", "dbpedia", "same scoping decision"),
    ("disease", "yago", "same scoping decision"),
    ("medication", "dbpedia", "same scoping decision"),
    ("medication", "yago", "same scoping decision"),
    ("taxa", "dbpedia", "constraint set exists but no slice was ever built for it, "
                        "so there is nothing to repair"),
    ("geography", "yago", "constraint set exists but no slice: YAGO geography uses "
                          "schema:location where the constraints name "
                          "schema:containedInPlace, recorded as a coverage gap"),
]


def slice_name(source, domain, target, variant):
    base = f"real_{source}_{domain}_{target}"
    return f"{base}_{variant}" if variant else base


def matrix():
    """Every cell, as (source, domain, target, variant, mode)."""
    return [(s, d, t, v, m) for (s, d, t, v) in SLICES for m in MODES]


def _manifest(name):
    path = os.path.join(REAL, name + ".manifest.json")
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _routed_violations(graph, cs, mode):
    """Violations over the constraints this engine is actually routed to act on.

    `subset_repair` acts only on `ptime_core` constraints whose `direction` is
    "subset" (`eligible_constraints`), and its `consistent_after` attestation is
    about those. Superset repair takes every `ptime_core` constraint, direction
    having been reframed as a preference at D6. Recording this alongside the
    all-core count is what lets a prediction be scored against what the engine
    claims rather than against what a reader assumed it claims.
    """
    routed = (eligible_constraints(cs) if mode == "subset"
              else [c for c in cs if c.tier == "ptime_core"])
    if not routed:
        return {"constraints": 0, "violations": None}
    report = kgrepair.validate(graph, routed)
    return {"constraints": len(routed), "violations": report.total_witnesses()}


def _repair(graph, cs, mode):
    if mode == "subset":
        return kgrepair.subset_repair(graph, cs)
    return kgrepair.superset_repair(graph, cs)


def _change_counts(result, mode):
    if mode == "subset":
        return {"nodes_removed": len(result.deleted_nodes),
                "edges_removed": sum(1 for r in result.changelog
                                     if r.op == "remove_edge"),
                "nodes_added": 0, "edges_added": 0,
                "recheck_count": result.recheck_count}
    return {"nodes_removed": 0, "edges_removed": 0,
            "nodes_added": len(result.added_nodes),
            "edges_added": len(result.added_edges),
            "pruned_edges": result.pruned_edges,
            "pruned_nodes": result.pruned_nodes}


def run_cell(source, domain, target, variant, mode, *, out_dir, revision):
    name = slice_name(source, domain, target, variant)
    path = os.path.join(REAL, name + ".nt")
    manifest = _manifest(name)

    graph = kgrepair.load_graph(path)
    cs = kgrepair.constraints.get(domain, source, version=2)

    before = compute_metrics(graph, cs)
    routed_before = _routed_violations(graph, cs, mode)
    decision = kgrepair.check_cap(graph, cs, mode)

    record = {
        "cell": f"{source}:{domain}:{target}{':' + variant if variant else ''}:{mode}",
        "source": source, "domain": domain, "target_edges": target,
        "variant": variant or None, "slice": name, "mode": mode,
        "slice_content_hash": manifest.get("content_hash"),
        "cache_generation_hash": manifest.get("cache_generation_hash"),
        "constraint_set": cs.name,
        "constraint_version_requested": 2,
        "constraints_core": sum(1 for c in cs if c.tier == "ptime_core"),
        "constraints_boundary": sum(1 for c in cs if c.tier == "boundary"),
        "cap": decision.to_dict(),
        "code_revision": revision,
        "metrics_before": before.to_dict(),
        "routed_before": routed_before,
    }

    if decision.aborted:
        record["stop_reason"] = "ABORTED-BY-CAP"
        record["metrics_after"] = None
        record["routed_after"] = None
        record["changes"] = None
        record["timings_s"] = {}
        record["resources"] = {}
        # The partial bundle is kept: the report and the constraints, with no
        # repaired graph, which is what the command line writes for a capped run.
        _write_bundle(out_dir, name, mode, record, graph, None, cs)
        return record

    t0 = time.perf_counter()
    result = _repair(graph, cs, mode)
    elapsed = time.perf_counter() - t0

    # Second pass, only for allocation. See the module docstring on why it is not
    # folded into the timed pass.
    tracemalloc.start()
    _mem_result = _repair(graph, cs, mode)
    traced_peak = tracemalloc.get_traced_memory()[1]
    tracemalloc.stop()
    del _mem_result

    after = compute_metrics(result.graph, cs)
    record["stop_reason"] = "completed"
    record["metrics_after"] = after.to_dict()
    record["routed_after"] = _routed_violations(result.graph, cs, mode)
    record["comparison"] = compare_metrics(before, after).to_dict()["changes"]
    record["changes"] = _change_counts(result, mode)
    record["rounds"] = result.rounds
    record["attestations"] = result.attestations
    record["timings_s"] = {"repair_loop": round(elapsed, 4)}
    record["resources"] = {"peak_traced_bytes": traced_peak,
                           "bytes_per_edge": round(traced_peak / max(1, before.edges), 1)}
    _write_bundle(out_dir, name, mode, record, graph, result, cs)
    # The change log goes beside the bundle rather than into the campaign record: it
    # is what `scripts/addition_accuracy.py` samples, and inlining several thousand
    # add-edge records per cell would make the JSONL unreadable for everything else.
    log_path = os.path.join(out_dir, "bundles", f"{name}.{mode}", "changelog.json")
    with open(log_path, "w", encoding="utf-8") as fh:
        json.dump({"changelog": result.changelog_dicts()}, fh, indent=1, sort_keys=True)
        fh.write("\n")
    record["changelog_path"] = os.path.relpath(log_path, ROOT)
    return record


def _write_bundle(out_dir, name, mode, record, original, result, cs):
    directory = os.path.join(out_dir, "bundles", f"{name}.{mode}")
    payload = {"campaign_record": record}
    try:
        kgrepair.write_bundle(
            directory,
            report={**payload, "summary": kgrepair.bundle_summary(
                mode=mode, constraint_provenance="authored",
                consistent_after=(None if result is None
                                  else bool(result.attestations.get("consistent_after"))),
                aborted=result is None,
                reason=("ABORTED-BY-CAP: the repair would touch "
                        f"{record['cap']['fraction']:.3f} of the graph against a cap "
                        f"of {record['cap']['cap']:.3f}, so no engine ran")
                if result is None else None)},
            repaired=None if result is None else result.graph,
            original=None if result is None else original,
            constraints_json=json.dumps(cs.to_dict(), indent=2, sort_keys=True) + "\n")
    except OSError as exc:
        record["bundle_error"] = str(exc)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(ROOT, "eval"),
                    help="directory for the bundles and the tables")
    args = ap.parse_args()

    revision = code_revision()
    cells = matrix()
    print(f"campaign: {len(SLICES)} slices x {len(MODES)} engines = {len(cells)} cells")
    print(f"caps: subset {kgrepair.SUBSET_CAP_DEFAULT}, "
          f"superset {kgrepair.SUPERSET_CAP_DEFAULT}; code revision {revision}\n")
    print("absent cells:")
    for domain, kg, why in ABSENT:
        print(f"  {domain}:{kg}  {why}")
    print()

    os.makedirs(RESULTS, exist_ok=True)
    os.makedirs(args.out, exist_ok=True)
    records = []
    for source, domain, target, variant, mode in cells:
        try:
            record = run_cell(source, domain, target, variant, mode,
                              out_dir=args.out, revision=revision)
        except Exception as exc:                  # a failed cell is recorded, not fatal
            record = {"cell": f"{source}:{domain}:{target}:{mode}",
                      "source": source, "domain": domain, "mode": mode,
                      "stop_reason": "FAILED",
                      "error": f"{type(exc).__name__}: {exc}"}
        records.append(record)
        cap = record.get("cap", {})
        print(f"{record['cell']:44s} {record['stop_reason']:16s} "
              f"fraction={cap.get('fraction', '?')} "
              f"t={record.get('timings_s', {}).get('repair_loop', '-')}")

    with open(CAMPAIGN_JSONL, "w", encoding="utf-8") as fh:
        for record in records:
            fh.write(json.dumps(record, sort_keys=True) + "\n")
    print(f"\nwrote {CAMPAIGN_JSONL} ({len(records)} records)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
