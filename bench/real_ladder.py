"""
P3 + P4: build the real corpus (report-first prevalence) and run capped subset repair.

For every cell: build the slice (live fetch if needed; YAGO from the pre-extracted
dump cache), record violation prevalence FIRST, then apply the deletion-fraction cap
(abort if the first-round subset-witness set exceeds `cap` of nodes) and, if under the
cap, run `subset_repair` with attestations + change log. Everything is logged through
the T1 harness. Emits docs/real_repair.md and docs/real_repair_examples.md.

Usage: python bench/real_ladder.py            # default cells
       python bench/real_ladder.py --repair-strategy incremental
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.dirname(__file__))

from build_real_slice import build, _domain_cs                       # noqa: E402
from kgrepair.instrument import RunContext, constraints_meta, render_table, slice_meta_from_graph  # noqa: E402
from kgrepair.ntriples import load_ntriples_file                     # noqa: E402
from kgrepair.repair import eligible_constraints, subset_repair      # noqa: E402
from kgrepair.validator import Validator                             # noqa: E402

ROOT = os.path.join(os.path.dirname(__file__), "..")
RESULTS = os.path.join(ROOT, "results")
OUT = os.path.join(ROOT, "fixtures", "real")

# (source, domain, target, needs_live_fetch)
CELLS = [
    ("wikidata", "geography", 1000, True), ("wikidata", "geography", 10000, True),
    ("wikidata", "taxa", 1000, True), ("wikidata", "taxa", 10000, True),
    ("wikidata", "anatomy", 1000, True), ("wikidata", "disease", 1000, True),
    ("wikidata", "medication", 1000, True),
    ("dbpedia", "geography", 1000, True),
    ("yago", "taxa", 1000, False), ("yago", "taxa", 10000, False),
]


DOCS = os.path.join(ROOT, "docs")


def _first_round_witnesses(g, cs):
    val = Validator(g, use_closure=True)
    w = set()
    for c in eligible_constraints(cs):
        w |= val.check_one(c).witnesses
    return w


def _write_docs(repair_rows, examples, cap):
    with open(os.path.join(DOCS, "real_repair.md"), "w", encoding="utf-8") as fh:
        fh.write(f"# Real-KG subset repair (P4) — capped at {cap:.0%} deletion fraction\n\n")
        fh.write("Report-first: witness fraction is measured before repairing. A cell "
                 "whose first-round subset-witness set exceeds the cap is **ABORTED-BY-CAP** "
                 "— a reported semantics result (witness-deletion would delete too much of "
                 "an incomplete-but-valid KG), not a failure.\n\n")
        fh.write(render_table(repair_rows) + "\n")
    with open(os.path.join(DOCS, "real_repair_examples.md"), "w", encoding="utf-8") as fh:
        fh.write("# Real repaired-witness examples (P4 qualitative)\n\n")
        fh.write("Sample of nodes deleted by subset repair on Wikidata geography 1k: the "
                 "entity, the violated constraint, and its incident edges in the pre-repair "
                 "graph. Illustrates that real 'violations' are usually *incompleteness* "
                 "(a missing type/statement), which witness-deletion resolves by removal.\n\n")
        for ex in examples:
            fh.write(f"- **{ex['node']}** — violated `{ex['constraint']}`; "
                     f"incident edges: {ex['edges']}\n")
        if not examples:
            fh.write("_(no repaired cell available for sampling)_\n")


def _sample_examples(g_before, res, cs, k=5):
    kind = {c.cid: c.kind for c in cs}
    out = []
    for r in res.changelog:
        if r.op == "remove_node" and len(out) < k:
            edges = [f"{p}->{o}" for p in sorted(g_before.labels) for o in sorted(g_before.succ(p, r.node))][:3]
            out.append({"node": r.node, "constraint": f"{r.constraint} ({kind.get(r.constraint,'')})",
                        "edges": ", ".join(edges) or "(only incoming edges)"})
    return out


def run(cap=0.20, repair_strategy="full", min_interval=1.0):
    corpus_rows, repair_rows, examples = [], [], []
    for source, domain, target, live in CELLS:
        try:
            sl, manifest, rep = build(source, domain, target,
                                      do_fetch=live, min_interval=min_interval)
        except Exception as e:                       # extraction gap -> report, don't skip silently
            corpus_rows.append({"source": source, "domain": domain, "target": target,
                                "status": f"GAP: {type(e).__name__}", "V": 0, "E": 0})
            continue
        g = load_ntriples_file(os.path.join(OUT, sl.name + ".nt"))
        cs = _domain_cs(domain, source)
        viol = manifest["violations"]
        corpus_rows.append({"source": source, "domain": domain, "target": target,
                            "V": manifest["V"], "E": manifest["E"],
                            "n_violations": sum(viol.values()), "status": "OK"})

        # deletion-fraction cap (report-first): decide before repairing
        witnesses = _first_round_witnesses(g, cs)
        frac = len(witnesses) / max(1, manifest["V"])
        mode = f"subset_{repair_strategy}"
        with RunContext(RESULTS, slice=slice_meta_from_graph(
                g, source="real", manifest_hash=manifest["content_hash"],
                params={"slice_source": source, "domain": domain, "target": target,
                        "deletion_cap": cap, "witness_fraction": round(frac, 4)}),
                constraints=constraints_meta(cs), mode=mode) as ctx:
            if frac > cap:
                ctx.status = "ABORTED-BY-CAP"
                repair_rows.append({"source": source, "domain": domain, "target": target,
                                    "witness_frac": f"{frac:.1%}", "action": "ABORTED-BY-CAP",
                                    "removed": "-", "recheck": "-"})
                continue
            g_before = g.clone() if (source, domain, target) == ("wikidata", "geography", 1000) else None
            with ctx.phase("repair_loop"):
                res = subset_repair(g, cs, in_place=True, strategy=repair_strategy,
                                    use_closure=True)
            with ctx.phase("consistency_final"):
                after = Validator(g, use_closure=True).validate(cs)
            ctx.set_repair_result(res, None, after)
            repair_rows.append({"source": source, "domain": domain, "target": target,
                                "witness_frac": f"{frac:.1%}", "action": "repaired",
                                "removed": len(res.deleted_nodes),
                                "recheck": res.recheck_count})
            if g_before is not None:
                examples = _sample_examples(g_before, res, cs)
    return corpus_rows, repair_rows, examples


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cap", type=float, default=0.20)
    ap.add_argument("--repair-strategy", default="full", choices=["full", "incremental"])
    ap.add_argument("--min-interval", type=float, default=1.0)
    args = ap.parse_args()
    corpus, repair, examples = run(args.cap, args.repair_strategy, args.min_interval)
    _write_docs(repair, examples, args.cap)
    print("== corpus ==\n" + render_table(corpus))
    print(f"\n== repair (cap {args.cap:.0%}) ==\n" + render_table(repair))
    print(f"\nwrote docs/real_repair.md, docs/real_repair_examples.md "
          f"({len(examples)} examples)")


if __name__ == "__main__":
    main()
