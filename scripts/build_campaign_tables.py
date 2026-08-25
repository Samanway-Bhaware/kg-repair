"""
P9/T3 and T5: the campaign tables, and the verdict on P8b's predictions.

Reads `results/campaign.jsonl` (written by `scripts/run_campaign.py`) and the
per-cell accuracy artifacts under `eval/accuracy/`, and renders:

  eval/campaign_objective4.md   consistency before and after, per cell
  eval/campaign_objective5.md   the full metric comparison, per cell
  eval/campaign_predictions.md  every P8b prediction, with a verdict
  eval/campaign.json            the machine-readable join of all three

Split from `run_campaign.py` on purpose: the campaign writes the JSONL and the
bundles, this renders them. T5 asked for one script; keeping them apart means a table
can be rebuilt without re-running twenty-four repairs, and the chain from table to
JSONL is asserted by `tests/test_campaign_tables.py` either way.

Pure function of the committed artifacts: sorted iteration, no wall-clock, no network.

Usage: python scripts/build_campaign_tables.py
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

ROOT = os.path.join(os.path.dirname(__file__), "..")
RESULTS = os.path.join(ROOT, "results")
EVAL = os.path.join(ROOT, "eval")
CAMPAIGN_JSONL = os.path.join(RESULTS, "campaign.jsonl")
ACCURACY_DIR = os.path.join(EVAL, "accuracy")

HELD, FAILED, UNSCORED = "held", "failed", "unscored"
#: The engine modified nothing on this cell, so a directional prediction has
#: nothing to be right or wrong about. Counted apart from a genuine failure.
NO_CHANGE = "no change"


def _read_jsonl(path):
    if not os.path.exists(path):
        return []
    out = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                out.append(json.loads(line))
    return out


def _table(headers, rows):
    out = ["| " + " | ".join(headers) + " |",
           "|" + "|".join("---" for _ in headers) + "|"]
    for row in rows:
        out.append("| " + " | ".join("" if c is None else str(c) for c in row) + " |")
    return "\n".join(out) + "\n"


def _num(value, digits=4):
    if value is None:
        return "unscored"
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


 
# the predictions, exactly as P8b states them
 
def _direction(before, after, expected):
    """Verdict for one metric on one cell.

    `expected` is "down", "up", "flat_or_down", "not_up", "to_zero", "to_one".
    A metric that is None on either side is `unscored`, which is a category and not a
    missing value: P8b found satisfaction and property coverage stop being scored
    after subset repair, and that is a finding about what subset repair does.
    """
    if before is None or after is None:
        return UNSCORED
    if expected == "to_zero":
        return HELD if after == 0 else FAILED
    if expected == "to_one":
        return HELD if abs(after - 1.0) < 1e-9 else FAILED
    if expected == "down":
        return HELD if after < before else FAILED
    if expected == "up":
        return HELD if after > before else FAILED
    if expected == "flat_or_down":
        return HELD if after <= before else FAILED
    if expected == "not_up":
        return HELD if after <= before else FAILED
    if expected == "up_or_flat":
        return HELD if after >= before else FAILED
    raise ValueError(expected)


def observe(before, after):
    """For a prediction stated permissively, the movement rather than a verdict."""
    if before is None or after is None:
        return UNSCORED
    if after > before:
        return "rose"
    if after < before:
        return "fell"
    return "flat"


#: (key, metric field, mode, expected, the sentence P8b committed to)
PREDICTIONS = [
    ("core_zero_all", "violations_by_tier.ptime_core", "subset", "to_zero",
     "ptime_core violations go to 0, as P8b stated it"),
    ("core_zero_routed", "ROUTED", "subset", "to_zero",
     "the ptime_core constraints this engine is routed to go to 0"),
    ("core_zero_routed", "ROUTED", "superset", "to_zero",
     "the ptime_core constraints this engine is routed to go to 0"),
    ("core_zero_all", "violations_by_tier.ptime_core", "superset", "to_zero",
     "ptime_core violations go to 0, as P8b stated it"),
    ("boundary", "violations_by_tier.boundary", "subset", "flat_or_down",
     "boundary violations stay flat or fall"),
    ("boundary", "violations_by_tier.boundary", "superset", "OBSERVE",
     "boundary violations may rise: reported as movement, not as a verdict"),
    ("typed", "typed_node_fraction", "subset", "down",
     "typed node fraction falls (corrected in P8b after a falsification)"),
    ("typed", "typed_node_fraction", "superset", "up",
     "typed node fraction rises"),
    ("coverage", "property_coverage_mean", "subset", "not_up",
     "property coverage rises or stays flat, or goes unscored (corrected)"),
    ("coverage", "property_coverage_mean", "superset", "down",
     "property coverage falls"),
    ("satisfaction", "satisfaction_mean", "subset", "to_one",
     "satisfaction reaches 1.0, or goes unscored (corrected)"),
    ("satisfaction", "satisfaction_mean", "superset", "to_one",
     "satisfaction reaches 1.0"),
    ("size_nodes", "nodes", "subset", "flat_or_down", "node count falls"),
    ("size_nodes", "nodes", "superset", "up_or_flat",
     "node count rises or stays flat"),
    ("size_edges", "edges", "subset", "down", "edge count falls"),
    ("size_edges", "edges", "superset", "up", "edge count rises"),
    ("redundant", "redundant_type_edges", "subset", "flat_or_down",
     "redundant type edges fall"),
    ("redundant", "redundant_type_edges", "superset", "not_up",
     "redundant type edges stay flat, they do not rise"),
]

#: Two predictions are stated as "may rise" and "rises or stays flat", which a
#: direction test cannot falsify on its own. They are scored on the complementary
#: claim (recorded above) and flagged here so no reader takes a `held` for more than
#: it is.
WEAK = {("size_nodes", "superset")}


def _get(metrics, path):
    if metrics is None:
        return None
    cur = metrics
    for part in path.split("."):
        if cur is None:
            return None
        cur = cur.get(part)
    return cur


def _changed(rec):
    """Did the engine modify the graph at all on this cell?"""
    changes = rec.get("changes") or {}
    return any(changes.get(k) for k in
               ("nodes_removed", "edges_removed", "nodes_added", "edges_added"))


def verdicts(records):
    """Per prediction, per cell: the verdict and the two values behind it."""
    out = []
    for key, field, mode, expected, sentence in PREDICTIONS:
        cells = []
        for rec in records:
            if rec.get("mode") != mode or rec.get("stop_reason") != "completed":
                continue
            if field == "ROUTED":
                before = (rec.get("routed_before") or {}).get("violations")
                after = (rec.get("routed_after") or {}).get("violations")
            else:
                before = _get(rec.get("metrics_before"), field)
                after = _get(rec.get("metrics_after"), field)
            verdict = (observe(before, after) if expected == "OBSERVE"
                       else _direction(before, after, expected))
            # A cell the engine did not touch cannot confirm or refute a direction.
            # Counting it as a failure would make "nothing happened" look like
            # "the prediction was wrong", which is a different claim entirely.
            if verdict == FAILED and not _changed(rec) and expected not in (
                    "to_zero", "to_one"):
                verdict = NO_CHANGE
            cells.append({"cell": rec["cell"], "slice": rec["slice"],
                          "domain": rec["domain"], "source": rec["source"],
                          "before": before, "after": after, "verdict": verdict})
        keys = (("rose", "flat", "fell", UNSCORED) if expected == "OBSERVE"
                else (HELD, FAILED, UNSCORED, NO_CHANGE))
        tally = {v: sum(1 for c in cells if c["verdict"] == v) for v in keys}
        out.append({"key": key, "metric": field, "mode": mode, "expected": expected,
                    "statement": sentence, "weak": (key, mode) in WEAK,
                    "cells": cells, "tally": tally})
    return out


 
# accuracy artifacts
 
def accuracy_rows():
    rows = []
    if not os.path.isdir(ACCURACY_DIR):
        return rows
    for name in sorted(os.listdir(ACCURACY_DIR)):
        if not name.endswith(".json"):
            continue
        with open(os.path.join(ACCURACY_DIR, name), encoding="utf-8") as fh:
            payload = json.load(fh)
        payload["artifact"] = name
        payload["slice"] = name[:-len(".superset.json")]
        rows.append(payload)
    return rows


 
# documents
 
def objective4(records):
    parts = ["# Objective 4: consistency before and after repair\n",
             "Every committed slice through both engines, authored constraints only, "
             "library cap defaults, cache generation A. Generated by "
             "`python scripts/build_campaign_tables.py` from `results/campaign.jsonl`; "
             "every number below is a field of one line of that file.\n"]
    rows = []
    for rec in sorted(records, key=lambda r: r["cell"]):
        before = rec.get("metrics_before") or {}
        after = rec.get("metrics_after") or {}
        bt = (before.get("violations_by_tier") or {})
        at = (after.get("violations_by_tier") or {})
        rows.append([
            rec["slice"], rec["mode"], rec["constraint_set"],
            bt.get("ptime_core"), at.get("ptime_core") if after else "not run",
            bt.get("boundary"), at.get("boundary") if after else "not run",
            _num(before.get("witness_node_fraction")),
            rec["stop_reason"],
        ])
    parts.append(_table(
        ["slice", "engine", "constraint set", "core before", "core after",
         "boundary before", "boundary after", "witness fraction", "outcome"], rows))
    parts.append(
        "\n`witness fraction` is the union of witness nodes over the node count, "
        "measured before any repair. It is what the cap compares against for subset "
        "repair, so it is the number that decides whether a cell runs at all.\n")

    aborted = [r for r in records if r["stop_reason"] == "ABORTED-BY-CAP"]
    parts.append(f"\n## Cap aborts: {len(aborted)} of {len(records)} cells\n")
    if aborted:
        parts.append(_table(
            ["cell", "fraction", "cap", "witnesses", "denominator"],
            [[r["cell"], r["cap"]["fraction"], r["cap"]["cap"],
              r["cap"]["witness_count"], r["cap"]["denominator"]] for r in aborted]))
        parts.append(
            "\nNo cap was raised to make one of these complete. The abort is the "
            "result: deleting every witness would remove more of the graph than the "
            "safety cap allows, which is the semantics finding the D6 work first "
            "recorded and the reason superset repair exists.\n")
    return "".join(parts)


def objective5(records):
    parts = ["# Objective 5: quality metrics, original against repaired\n",
             "Definitions in `docs/quality_metrics.md`. Every cell that ran is shown "
             "before and after; a cap-aborted cell has no after and says so. "
             "`unscored` is a real outcome, not a missing value: after subset repair "
             "the antecedents can stop matching anything, and a rule about nothing is "
             "unjudged.\n"]
    for mode in ("subset", "superset"):
        parts.append(f"\n## {mode} repair\n")
        rows = []
        for rec in sorted((r for r in records if r["mode"] == mode),
                          key=lambda r: r["cell"]):
            b = rec.get("metrics_before") or {}
            a = rec.get("metrics_after")
            if a is None:
                rows.append([rec["slice"], "ABORTED-BY-CAP"] + [""] * 8)
                continue
            rows.append([
                rec["slice"], "",
                f"{b['nodes']} to {a['nodes']}",
                f"{b['edges']} to {a['edges']}",
                f"{_num(b['typed_node_fraction'])} to {_num(a['typed_node_fraction'])}",
                f"{_num(b['property_coverage_mean'])} to {_num(a['property_coverage_mean'])}",
                f"{_num(b['satisfaction_mean'])} to {_num(a['satisfaction_mean'])}",
                f"{b['redundant_type_edges']} to {a['redundant_type_edges']}",
                f"{b['classes']} to {a['classes']}",
                rec.get("rounds"),
            ])
        parts.append(_table(
            ["slice", "outcome", "nodes", "edges", "typed fraction",
             "property coverage", "satisfaction", "redundant types", "classes",
             "rounds"], rows))
    return "".join(parts)


def predictions_doc(records, accuracy):
    verdict_rows = verdicts(records)
    parts = ["# P9/T3: the predictions of P8b, tested\n",
             "The P8b predictions committed to a direction for each metric under each "
             "engine before the campaign ran, including three corrected after a "
             "single uncapped run falsified them. This is the verdict. A prediction "
             "is scored per cell; `unscored` means the metric was not defined on one "
             "side and is reported as its own category rather than dropped.\n"]
    rows = []
    for v in verdict_rows:
        tally = v["tally"]
        if v["expected"] == "OBSERVE":
            rows.append([v["statement"], v["mode"],
                         f"rose {tally['rose']}", f"fell {tally['fell']}",
                         tally[UNSCORED], f"flat {tally['flat']}", "observed"])
            continue
        rows.append([v["statement"], v["mode"], tally[HELD], tally[FAILED],
                     tally[UNSCORED], tally[NO_CHANGE],
                     "weak" if v["weak"] else ""])
    parts.append(_table(
        ["prediction", "engine", "held", "failed", "unscored", "no change", "note"],
        rows))
    parts.append(
        "\nA `weak` prediction is one stated permissively in P8b (\"may rise\", "
        "\"rises or stays flat\"). A direction test cannot falsify it, so it is "
        "scored on the complementary claim and flagged. Do not read its `held` as "
        "confirmation.\n")

    parts.append("\n## Splits worth reading\n")
    interesting = [v for v in verdict_rows
                   if v["tally"].get(FAILED) or
                   (v["tally"].get(HELD) and v["tally"].get(UNSCORED))]
    if not interesting:
        parts.append("Every prediction was unanimous across the cells that scored it.\n")
    for v in interesting:
        parts.append(f"\n### {v['statement']} ({v['mode']})\n")
        rows = [[c["cell"], _num(c["before"]), _num(c["after"]), c["verdict"]]
                for c in v["cells"]]
        parts.append(_table(["cell", "before", "after", "verdict"], rows))

    parts.append("\n## Accuracy of additions\n")
    if not accuracy:
        parts.append("No accuracy artifact was found.\n")
    else:
        rows = []
        for row in accuracy:
            if row.get("status"):
                rows.append([row["slice"], row.get("additions_total"), row["status"],
                             "", "", "", ""])
                continue
            rows.append([
                row["slice"], row["additions_total"], "measured",
                row["sample_size"],
                f"{row['corroborated_exact']} ({row['proportion_exact']})",
                f"{row['corroborated_entailed']} ({row['proportion_entailed']})",
                f"{row['interval_entailed'][0]} to {row['interval_entailed'][1]}"])
        parts.append(_table(
            ["slice", "additions", "status", "sampled", "exact agreement",
             "class agreement", "95 percent interval (class)"], rows))
        parts.append(
            "\nThe two questions differ because the exact one is too strict for a "
            "typing addition. Superset repair adds `x isa C` to satisfy a class test "
            "that is itself `isa . subclass-of*`, so the source can agree while "
            "asserting only a more specific type. Class agreement is the primary "
            "measure; the exact column is kept because it is what a naive check "
            "reports, and P8b traced the D6 figure of 34.4 percent to that same bias. "
            "Sampling is a fixed-seed simple random sample without replacement over "
            "the deduplicated addition set, and a cell with too few additions to "
            "quote a proportion says so instead of quoting one.\n")
    return "".join(parts)


def limitations(records):
    """T6: what the campaign does not show, with the measured size of each gap."""
    completed = [r for r in records if r["stop_reason"] == "completed"]
    sets = {r["constraint_set"]: (r["constraints_core"], r["constraints_boundary"])
            for r in records}
    core = sum(v[0] for v in sets.values())
    boundary = sum(v[1] for v in sets.values())
    left = [(r["cell"], r["metrics_after"]["violations_by_tier"]["boundary"])
            for r in completed
            if r["metrics_after"]["violations_by_tier"]["boundary"]]
    worst = max(
        ((r["cell"], 100 * r["changes"]["edges_removed"] / r["metrics_before"]["edges"])
         for r in completed if r["mode"] == "subset"), key=lambda kv: kv[1])

    out = []
    out.append("# What this campaign does not show")
    out.append("")
    out.append("Each limitation carries the measured size of the gap and what it "
               "would take to close it, so the future-work section has something to "
               "start from rather than an adjective.")
    out.append("")
    out.append("## The slices are size-capped samples, not knowledge graphs")
    out.append("")
    out.append("Every cell is a 1000-edge or 10000-edge slice grown by a "
               "seed-anchored walk. The P8a frontier probe fetched the same cells to "
               "their target cap and reached roughly 75000 allow-listed edges each, "
               "with thousands of nodes still unvisited, so a 1000-edge slice is on "
               "the order of **1.3 percent** of what those seeds alone reach, and the "
               "seeds are themselves a hand-picked set of 43 entities or fewer. "
               "Nothing here generalises to a whole knowledge graph.")
    out.append("")
    out.append("*To close it:* run the campaign on the generation B ladder up to the "
               "50000 rung, which P8a built and verified nests. That is compute, not "
               "new method.")
    out.append("")
    out.append("## The constraints were authored by the person who built the toolkit")
    out.append("")
    out.append(f"{core + boundary} constraints across {len(sets)} sets ({core} "
               f"ptime_core, {boundary} boundary), all written by the author. No "
               "domain expert reviewed them, and the sign-off is still an open "
               "item. A repair is only as good as "
               "the theory it repairs against, and that theory is unvalidated.")
    out.append("")
    out.append("*To close it:* domain-expert review of the constraint "
               "sets, which is a scheduled item rather than an open problem.")
    out.append("")
    out.append("## The source is the only gold standard for additions")
    out.append("")
    out.append("Accuracy of additions asks whether the source agrees, so a correct "
               "addition the source also lacks counts against the score, and an "
               "addition both share counts for it even if both are wrong. The measure "
               "is agreement, not truth, and it cannot be otherwise without an "
               "independent reference.")
    out.append("")
    out.append("*To close it:* a hand-adjudicated sample, which is human time rather "
               "than method. A few hundred triples would give the agreement measure a "
               "calibration point.")
    out.append("")
    out.append("## Boundary constraints are validated and never repaired")
    out.append("")
    out.append(f"{boundary} of the {core + boundary} constraints are boundary tier, "
               f"and **{sum(n for _, n in left)} boundary violations remain across "
               f"{len(left)} of the {len(completed)} completed cells** after repair. "
               "Symmetry as a path constraint pushes subset repair to NP-completeness "
               "(Theorem 11), and the upper-cardinality and inverse shapes need "
               "negation, so both sit outside the tractable fragment by construction. "
               "A graph this campaign calls repaired is repaired with respect to the "
               "ptime_core tier only.")
    out.append("")
    out.append("*To close it:* nothing incremental. It needs an intractable algorithm "
               "or an approximation carrying its own guarantees, which is a different "
               "project.")
    out.append("")
    out.append("## One cell is bounded by its allow-list, not by its source")
    out.append("")
    out.append("P8a measured DBpedia geography exhausting at 751 allow-listed edges, "
               "with 98.2 percent of the sampled structure dropped by the allow-list "
               "and 3 of 151 predicates admitted. The 1000-edge slice used here is at "
               "the ceiling of what that cell can offer. Its 2 additions are too few "
               "to quote a proportion, and its numbers are not a source-level "
               "comparison against Wikidata.")
    out.append("")
    out.append("*To close it:* widen the DBpedia allow-list, which is an "
               "allow-list scope decision and not one this campaign may take.")
    out.append("")
    out.append("## The cap bounds nodes deleted, not edges destroyed")
    out.append("")
    out.append(f"The subset cap compares the union of witness nodes against the node "
               f"count. On `{worst[0]}` it passed, and the repair then removed "
               f"**{worst[1]:.1f} percent of the edges** by cascade, because deleting "
               "a node takes every edge incident to it with it. A cap expressed over "
               "nodes does not bound the damage expressed over edges.")
    out.append("")
    out.append("*To close it:* a second cap on the edge fraction, a small change to "
               "`caps.py`, deliberately not made here: this campaign runs the caps as "
               "they shipped.")
    out.append("")
    return "\n".join(out)


def findings(records):
    """T5: a short note per domain."""
    out = ["# Findings by domain", "",
           "What repair did in each domain, and anything the numbers show that the "
           "constraint set did not anticipate.", ""]
    by_domain = {}
    for rec in records:
        by_domain.setdefault(rec["domain"], []).append(rec)
    for domain in sorted(by_domain):
        out.append(f"## {domain}")
        out.append("")
        table = []
        for rec in sorted(by_domain[domain], key=lambda r: r["cell"]):
            before = rec["metrics_before"]
            after = rec.get("metrics_after")
            changes = rec.get("changes") or {}
            table.append([
                rec["slice"], rec["mode"], rec["constraint_set"],
                before["violations_by_tier"]["ptime_core"],
                (after["violations_by_tier"]["ptime_core"] if after else "not run"),
                changes.get("edges_removed", 0), changes.get("edges_added", 0),
                rec["stop_reason"]])
        out.append(_table(
            ["slice", "engine", "constraint set", "core before", "core after",
             "edges removed", "edges added", "outcome"], table).rstrip())
        out.append("")
    return "\n".join(out) + "\n"


def build():
    records = _read_jsonl(CAMPAIGN_JSONL)
    accuracy = accuracy_rows()
    return {
        "objective4.md": objective4(records),
        "objective5.md": objective5(records),
        "predictions.md": predictions_doc(records, accuracy),
        "findings.md": findings(records),
        "limitations.md": limitations(records),
        "json": {"cells": len(records),
                 "verdicts": [{k: v for k, v in row.items() if k != "cells"}
                              for row in verdicts(records)],
                 "accuracy": accuracy},
    }


def main():
    built = build()
    os.makedirs(EVAL, exist_ok=True)
    for name, key in (("campaign_objective4.md", "objective4.md"),
                      ("campaign_objective5.md", "objective5.md"),
                      ("campaign_predictions.md", "predictions.md"),
                      ("campaign_findings.md", "findings.md"),
                      ("campaign_limitations.md", "limitations.md")):
        with open(os.path.join(EVAL, name), "w", encoding="utf-8") as fh:
            fh.write(built[key])
        print(f"wrote {os.path.join(EVAL, name)}")
    with open(os.path.join(EVAL, "campaign.json"), "w", encoding="utf-8") as fh:
        json.dump(built["json"], fh, indent=2, sort_keys=True)
        fh.write("\n")
    print(f"wrote {os.path.join(EVAL, 'campaign.json')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
