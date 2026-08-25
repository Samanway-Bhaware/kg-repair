"""
P8a/F5: what changed between cache generation A and generation B.

Compared at the 1000-edge rung, the one rung both generations have for every cell.
Seeds and the allow-list are held constant across the two (the YAGO seeds by the
explicit pin from F1, the rest by `extract.SEEDS` being a written-down constant), and
the slicing ordering is unchanged, so a difference at this rung is a difference in
what the source returned rather than in how the slice was cut. That reasoning is what
licenses the attribution; it is stated here rather than assumed because it is the
whole value of the comparison.

Validation only. No repair is invoked, and nothing in this file imports an engine.

Usage:
  python bench/generation_drift.py

NOTE: the inputs this script needs are NOT shipped with the repository.
`fixtures/real/generation_b/` and the `data/raw_genB/` cache it slices from were
lost and are not recoverable; only the RESULTS computed from them survive, in
`eval/generation_b_ladder.json` and `eval/generation_drift.json`. Re-running this
against a freshly fetched cache produces a different generation and will NOT
reproduce those committed numbers. See DATA.md.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.dirname(__file__))

from kgrepair import constraints                                        # noqa: E402
from kgrepair.ntriples import load_ntriples_file                        # noqa: E402
from kgrepair.validator import Validator                                # noqa: E402

ROOT = os.path.join(os.path.dirname(__file__), "..")
REAL = os.path.join(ROOT, "fixtures", "real")
GEN_B = os.path.join(REAL, "generation_b")
RUNG = 1000


def _constraint_set(domain, source):
    """The v2 set where the domain has one, otherwise v1, with which it was recorded.

    The evaluation chapter reads v2 where it exists, so the drift is expressed in the
    same terms. A domain with no v2 set is not an error; it is a domain C1 did not
    need to change.
    """
    for version in (2, 1):
        try:
            return constraints.get(domain, source, version=version), version
        except (KeyError, ValueError):
            continue
    return None, None


def _violations(graph, cs):
    report = Validator(graph, use_closure=True).validate(cs)
    return {v.constraint.cid: v.count for v in report.failing()}


def compare(source, domain):
    a_path = os.path.join(REAL, f"real_{source}_{domain}_{RUNG}.nt")
    b_path = os.path.join(GEN_B, f"genB_{source}_{domain}_{RUNG}.nt")
    if not os.path.exists(a_path):
        return {"source": source, "domain": domain, "status": "NO-GENERATION-A"}
    if not os.path.exists(b_path):
        return {"source": source, "domain": domain, "status": "NO-GENERATION-B"}

    a, b = load_ntriples_file(a_path), load_ntriples_file(b_path)
    ea, eb = set(a.edges()), set(b.edges())
    only_a, only_b = ea - eb, eb - ea
    labels_a, labels_b = set(a.labels), set(b.labels)

    cs, version = _constraint_set(domain, source)
    row = {
        "source": source, "domain": domain, "status": "ok", "rung": RUNG,
        "A": {"V": len(a.nodes), "E": len(ea), "labels": len(labels_a)},
        "B": {"V": len(b.nodes), "E": len(eb), "labels": len(labels_b)},
        "delta_V": len(b.nodes) - len(a.nodes),
        "delta_E": len(eb) - len(ea),
        "edges_only_in_A": len(only_a),
        "edges_only_in_B": len(only_b),
        "edges_shared": len(ea & eb),
        "jaccard": round(len(ea & eb) / len(ea | eb), 4) if (ea | eb) else None,
        "labels_only_in_A": sorted(labels_a - labels_b),
        "labels_only_in_B": sorted(labels_b - labels_a),
        "example_edges_only_in_A": [list(e) for e in sorted(only_a)[:3]],
        "example_edges_only_in_B": [list(e) for e in sorted(only_b)[:3]],
    }
    if cs is None:
        row["constraints"] = {"status": "NO-CONSTRAINT-SET"}
    else:
        va, vb = _violations(a, cs), _violations(b, cs)
        row["constraints"] = {
            "set": cs.name, "version": version,
            "violations_A": va, "violations_B": vb,
            "total_A": sum(va.values()), "total_B": sum(vb.values()),
            "cids_only_failing_in_A": sorted(set(va) - set(vb)),
            "cids_only_failing_in_B": sorted(set(vb) - set(va)),
        }
    return row


def discover_cells():
    """Cells with a generation B slice at the compared rung."""
    if not os.path.isdir(GEN_B):
        return []
    out = []
    for name in sorted(os.listdir(GEN_B)):
        if not name.endswith(f"_{RUNG}.nt"):
            continue
        parts = name[len("genB_"):-len(f"_{RUNG}.nt")].split("_", 1)
        if len(parts) == 2:
            out.append((parts[0], parts[1]))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(ROOT, "eval", "generation_drift.json"))
    args = ap.parse_args()

    cells = discover_cells()
    print(f"cells with both generations at the {RUNG}-edge rung: "
          f"{[':'.join(c) for c in cells]}\n")
    rows = [compare(s, d) for s, d in cells]
    for r in rows:
        if r["status"] != "ok":
            print(f"{r['source']}:{r['domain']:12s} {r['status']}")
            continue
        c = r["constraints"]
        print(f"{r['source']}:{r['domain']:12s} "
              f"E {r['A']['E']}->{r['B']['E']} (dV={r['delta_V']:+d}) "
              f"onlyA={r['edges_only_in_A']} onlyB={r['edges_only_in_B']} "
              f"jaccard={r['jaccard']} "
              f"violations {c.get('total_A')}->{c.get('total_B')} "
              f"({c.get('set')} v{c.get('version')})")

    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump({"rung": RUNG, "cells": rows}, fh, indent=2, sort_keys=True)
        fh.write("\n")
    print(f"\nwrote {args.out}")


if __name__ == "__main__":
    main()
