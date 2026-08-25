"""
P8a/F6: the dataset refetch report.

Reads the three measurement artifacts this phase produced and renders one document
for the corpus section of the evaluation write-up:

  eval/frontier_probe.json      per-cell ceiling, stop reason, allow-list coverage
  eval/generation_b_ladder.json the rungs sliced out of each generation B cache
  eval/generation_drift.json    generation A against generation B at the 1000 rung

Pure function of those files: sorted iteration, no wall-clock read, no network. The
timings that appear are the ones the probe recorded, which are data. Byte-reproducible
regeneration is asserted by `tests/test_dataset_refetch_doc.py`.

The document states measurements and the conditions they were taken under. It makes
no claim about repair behaviour: nothing in this phase ran an engine.

Usage: python scripts/build_dataset_refetch.py
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

ROOT = os.path.join(os.path.dirname(__file__), "..")
EVAL = os.path.join(ROOT, "eval")
REAL = os.path.join(ROOT, "fixtures", "real")

PROBE = os.path.join(EVAL, "frontier_probe.json")
LADDER = os.path.join(EVAL, "generation_b_ladder.json")
DRIFT = os.path.join(EVAL, "generation_drift.json")
MD_PATH = os.path.join(EVAL, "dataset_refetch.md")
JSON_PATH = os.path.join(EVAL, "dataset_refetch.json")


def _read(path, default=None):
    if not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _table(headers, rows):
    out = ["| " + " | ".join(headers) + " |",
           "|" + "|".join("---" for _ in headers) + "|"]
    for row in rows:
        out.append("| " + " | ".join(str(c) for c in row) + " |")
    return "\n".join(out)


def _generation_a_manifests():
    """Every committed generation A manifest, keyed by its file name.

    Keyed by file name rather than by (source, domain, target): the typing-completed
    `_typed` slices share all three with the slice they were derived from, and they
    carry no cache generation hash of their own, so keying on the triple let a
    `_typed` manifest overwrite the real one and drop that cell from the report.
    """
    out = {}
    for name in sorted(os.listdir(REAL)):
        if not name.endswith(".manifest.json"):
            continue
        with open(os.path.join(REAL, name), encoding="utf-8") as fh:
            m = json.load(fh)
        if m.get("slice_source") is None:
            continue
        out[name] = m
    return out


def collect():
    probe = _read(PROBE, {}) or {}
    ladder = _read(LADDER, {}) or {}
    drift = _read(DRIFT, {}) or {}
    gen_a = _generation_a_manifests()

    a_hashes = {}
    for _name, m in sorted(gen_a.items()):
        cell = f"{m['slice_source']}:{m['domain']}"
        if m.get("cache_generation_hash"):
            a_hashes.setdefault(cell, m["cache_generation_hash"])

    pinned = _read(os.path.join(REAL, "pinned_seeds.json"), {}) or {}
    return {"probe": probe, "ladder": ladder, "drift": drift,
            "generation_a_hashes": a_hashes,
            "pinned_seeds": {src: {dom: len(v) for dom, v in doms.items()}
                             for src, doms in sorted(pinned.get("seeds", {}).items())},
            "pinned_from": pinned.get("pinned_from", {})}


def build(data):
    probe, ladder, drift = data["probe"], data["ladder"], data["drift"]
    parts = ["# Dataset refetch: cache generation B\n",
             "Produced by `python scripts/build_dataset_refetch.py` from the artifacts "
             "of P8a. Every number below is a measurement of the corpus, taken with no "
             "engine running: this phase fetched and sliced, and validated in one place "
             "to express the drift, and did nothing else.\n"]

    # ------ scope
    parts.append("## What was fetched, and where it went\n")
    parts.append(
        "Generation B is written to `data/raw_genB/<domain>/`, a separate cache root. "
        "Generation A lives under `data/raw/` and a fetch into it would add segments "
        "and move its generation hash, which is what happened to anatomy and "
        "medication during the D6 typing closure. Keeping the roots apart is what lets "
        "generation A stay readable and its recorded hash stay meaningful.\n")
    parts.append(
        "Seeds are held constant across the two generations. Wikidata and DBpedia "
        "seeds are a written-down constant (`extract.SEEDS`). YAGO seeds are derived "
        "from the cache backbone, so they are pinned instead: "
        f"`fixtures/real/pinned_seeds.json` records the "
        f"{data['pinned_seeds'].get('yago', {}).get('taxa', 0)} taxa seeds cache "
        f"generation {data['pinned_from'].get('cache_generation_hash', 'A')} produced, "
        "and they are read back verbatim. The allow-list is unchanged. So is the "
        "slicing ordering. A difference between the generations is therefore a "
        "difference in what the source returned.\n")

    # ------ ceilings
    parts.append("## Per-cell ceiling\n")
    if probe.get("cells"):
        parts.append(
            f"Probed at `target_edges={probe.get('target_edges')}` with a request "
            f"budget of {probe.get('max_requests')}. `sparql_extract` over-fetches by "
            f"1.5x, so the target cap fires at "
            f"{int((probe.get('target_edges') or 0) * 1.5)} cached edges.\n")
        rows = []
        for c in sorted(probe["cells"], key=lambda r: (r["source"], r["domain"])):
            if c.get("status") == "FAILED":
                rows.append([f"{c['source']}:{c['domain']}", "FAILED", "", "", "", "",
                             c.get("error", "")[:60]])
                continue
            cov = c.get("coverage") or {}
            rows.append([
                f"{c['source']}:{c['domain']}", c["cached_edges"], c["stop_reason"],
                c["requests"], c["nodes_queried"], c["frontier_remaining"],
                f"{c['wall_clock_s']:.0f}"])
        parts.append(_table(
            ["cell", "allow-listed edges", "stopped by", "requests",
             "nodes queried", "frontier left", "seconds"], rows) + "\n")
        parts.append(
            "`stopped by` is measured rather than inferred: a node that entered the "
            "cache and was never queried as a subject is frontier the walk did not "
            "reach, so `frontier left` at zero is an exhausted cell and a positive "
            "value with the target cap reached is a cell with more to give.\n")
    else:
        parts.append("No probe artifact was found.\n")

    # ------ coverage
    parts.append("## What the allow-list admits\n")
    parts.append(
        "A ceiling measured through the allow-list is a ceiling on allow-listed "
        "structure, not on the source graph. These counts say which. For a sample of "
        "the nodes actually queried, the endpoint was asked for counts grouped by "
        "predicate over the source's predicate universe; the allow-listed and dropped "
        "halves are split locally. Only predicate identifiers and integers were "
        "returned, so no object value entered the process at all, which is stricter "
        "than the fetch path.\n")
    rows = []
    for c in sorted(probe.get("cells", []), key=lambda r: (r["source"], r["domain"])):
        cov = c.get("coverage") or {}
        if not cov.get("sampled"):
            continue
        rows.append([f"{c['source']}:{c['domain']}", cov["sampled"],
                     cov["triples_in_universe"], cov["triples_allow_listed"],
                     cov["triples_dropped"], cov["dropped_fraction"],
                     f"{cov['distinct_predicates_allow_listed']} of "
                     f"{cov['distinct_predicates_seen']}"])
    if rows:
        parts.append(_table(
            ["cell", "nodes sampled", "triples in universe", "allow-listed",
             "dropped", "dropped fraction", "predicates admitted"], rows) + "\n")
        parts.append(
            "The predicate universe is the direct-property namespace for Wikidata, "
            "which is the namespace the allow-list draws from, and every triple with "
            "an IRI object for DBpedia.\n")
        for c in sorted(probe.get("cells", []), key=lambda r: (r["source"], r["domain"])):
            cov = c.get("coverage") or {}
            top = cov.get("top_dropped_by_predicate") or {}
            if not top:
                continue
            listed = ", ".join(f"`{p}` {n}" for p, n in list(top.items())[:5])
            parts.append(f"* {c['source']}:{c['domain']} drops most in {listed}.\n")

    # ------ ladder
    parts.append("\n## The generation B ladder\n")
    if ladder.get("cells"):
        parts.append(
            "One fetch per cell, every rung sliced out of it. Slicing is a pure "
            "function of the cache and the parameters and its ordering does not read "
            "`target_edges`, so rungs cut from one generation nest. A rung shorter "
            "than its target is the cache exhausted, and the ladder stops there rather "
            "than writing the same edge set under more names.\n")
        rows = []
        for cell in sorted(ladder["cells"], key=lambda r: (r["source"], r["domain"])):
            served = [r["target_edges"] for r in cell["rungs"] if not r["short_of_target"]]
            rows.append([
                f"{cell['source']}:{cell['domain']}", cell["cache_generation_hash"],
                cell["ceiling_edges"],
                ", ".join(str(r) for r in served) or "none",
                "yes" if cell["seeds_pinned"] else "no",
                "all" if all(r["nests_in_previous"] for r in cell["rungs"]) else "NO"])
        parts.append(_table(
            ["cell", "generation B hash", "ceiling (edges)", "rungs served",
             "seeds pinned", "rungs nesting"], rows) + "\n")
        parts.append(
            "`rungs nesting` reads `all` when every rung is contained in the one above "
            "it, checked while the ladder was built and again by "
            "`tests/test_slice_nesting.py`.\n")
    else:
        parts.append("No ladder artifact was found.\n")

    # ------ drift
    parts.append("## Generation A against generation B\n")
    if drift.get("cells"):
        parts.append(
            f"At the {drift.get('rung')}-edge rung, the one rung both generations "
            "carry. Validation only.\n")
        rows = []
        for c in sorted(drift["cells"], key=lambda r: (r["source"], r["domain"])):
            if c.get("status") != "ok":
                rows.append([f"{c['source']}:{c['domain']}", c.get("status"),
                             "", "", "", "", "", ""])
                continue
            con = c.get("constraints", {})
            rows.append([
                f"{c['source']}:{c['domain']}", c["A"]["E"], c["B"]["E"],
                c["edges_only_in_A"], c["edges_only_in_B"], c["jaccard"],
                con.get("total_A", ""), con.get("total_B", "")])
        parts.append(_table(
            ["cell", "E in A", "E in B", "only in A", "only in B", "Jaccard",
             "violations A", "violations B"], rows) + "\n")
        parts.append(
            "Violation counts are `Validator` output over the constraint set the "
            "evaluation chapter reads, v2 where the domain has one. They are reported "
            "so the drift is expressed in the terms the campaign uses; no repair was "
            "run to produce them.\n")
        for c in sorted(drift["cells"], key=lambda r: (r["source"], r["domain"])):
            if c.get("status") != "ok":
                continue
            gained, lost = c["labels_only_in_B"], c["labels_only_in_A"]
            if gained or lost:
                parts.append(
                    f"* {c['source']}:{c['domain']} label set moved: "
                    f"gained {gained or 'nothing'}, lost {lost or 'nothing'}.\n")
    else:
        parts.append("No drift artifact was found.\n")

    parts.append("\n## Generation A hashes, for the record\n")
    rows = [[cell, h] for cell, h in sorted(data["generation_a_hashes"].items())]
    parts.append(_table(["cell", "generation A hash (as recorded in the manifest)"],
                        rows) + "\n")
    parts.append(
        "Two of these no longer match the cache on disk: the anatomy and medication "
        "caches gained segments during the D6 typing closure, which moved their "
        "generation hash after the 1000-edge slices had been written. The committed "
        "slices and manifests are unchanged, and they are what generation A means "
        "here.\n")
    return "".join(p if p.endswith("\n") else p + "\n" for p in parts)


def main():
    data = collect()
    os.makedirs(EVAL, exist_ok=True)
    with open(JSON_PATH, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, sort_keys=True)
        fh.write("\n")
    with open(MD_PATH, "w", encoding="utf-8") as fh:
        fh.write(build(data))
    print(f"wrote {MD_PATH}")
    print(f"wrote {JSON_PATH}")


if __name__ == "__main__":
    main()
