"""
CM sprint / E5 -- regenerates docs/ml_mining.md from the sprint's own JSON
artifacts (experimental/mining/results/*.json, results/cm_sprint_runs.jsonl),
reusing the C2 regeneration discipline (scripts/build_evaluation.py): every
TABLE number below is read from an artifact, not hand-typed. Analysis prose is
different here than in C2 -- the sprint's own hand-written analysis IS this
day's deliverable (not deferred hand-written prose), so guarded prose
blocks are filled in directly rather than left as _TODO_ placeholders. The
guard markers are kept anyway, in the same `<!-- PROSE:key:start/end -->` form,
so a future regeneration preserves any edits made directly in the doc.

Usage: python scripts/build_ml_mining_doc.py
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from collections import defaultdict

ROOT = os.path.join(os.path.dirname(__file__), "..")
MINING_RESULTS = os.path.join(ROOT, "experimental", "mining", "results")
RESULTS = os.path.join(ROOT, "results")
DOCS = os.path.join(ROOT, "docs")
OUT_PATH = os.path.join(DOCS, "ml_mining.md")

PROSE_KEYS = [
    "motivation", "e0_design", "e1_headline", "e1_defect_a", "e1_defect_b",
    "e2_headline", "e2_indictment", "e3_headline", "e4_headline",
    "limitations", "negative_result", "future_work",
]

_PROSE_RE = re.compile(
    r"<!-- PROSE:(?P<key>[\w-]+):start -->\n(?P<body>.*?)\n<!-- PROSE:(?P=key):end -->",
    re.DOTALL)


def _load(name: str):
    path = os.path.join(MINING_RESULTS, name)
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _load_jsonl(path: str):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def md_table(rows, columns=None):
    if not rows:
        return "_(no rows)_"
    cols = columns or list(rows[0].keys())
    lines = ["| " + " | ".join(cols) + " |", "|" + "|".join(["---"] * len(cols)) + "|"]
    for r in rows:
        lines.append("| " + " | ".join(str(r.get(c, "")) for c in cols) + " |")
    return "\n".join(lines)


def _extract_prose(existing_text: str):
    return {m.group("key"): m.group("body") for m in _PROSE_RE.finditer(existing_text)}


def _prose_block(key: str, preserved: dict, default: str) -> str:
    body = preserved.get(key, default)
    return f"<!-- PROSE:{key}:start -->\n{body}\n<!-- PROSE:{key}:end -->"


 
# table builders (numbers only, from artifacts)
 

def table_e0(e0: list) -> str:
    rows = []
    for row in e0:
        for t, rep in row["per_threshold"].items():
            rows.append({
                "slice": row["slice"], "kg": row["kg"], "threshold": t,
                "raw": rep["raw"], "fragment_passed": rep["fragment_passed"],
                "fragment_rejected": rep["fragment_rejected"],
                "ptime_core": rep["by_tier"]["ptime_core"],
                "boundary": rep["by_tier"]["boundary"],
            })
    return md_table(rows)


def table_e1(e1: dict) -> str:
    rows = []
    for res in e1["results"]:
        for t, counts in res["recovery_counts"].items():
            rows.append({"slice": res["slice"], "threshold": t, **counts})
    return md_table(rows)


def table_e2(e2_cells: list) -> str:
    rows = []
    for cell in e2_cells:
        for arm in ("v1", "v2"):
            info = cell[arm]
            rows.append({"cell": cell["cell"], "arm": arm, "additions": info["additions"],
                        "checked": info["checked"], "corroborated": info["corroborated"],
                        "precision": info["precision"]})
        plaus = cell.get("plausibility", {})
        rows.append({"cell": cell["cell"], "arm": "mined",
                    "additions": cell.get("added_edges", cell.get("planned_additions")),
                    "checked": plaus.get("checked"), "corroborated": plaus.get("corroborated"),
                    "precision": f"{plaus['precision']:.1%}" if plaus.get("precision") is not None else "-"})
    return md_table(rows, columns=["cell", "arm", "additions", "checked", "corroborated", "precision"])


def table_e3(e3: dict) -> str:
    rows = []
    for comp in e3["comparisons"]:
        for t, c in comp["by_threshold"].items():
            rows.append({"slice": f"{comp['kg']}/{comp['domain']}", "threshold": t,
                        "e0_recovered": c["e0_recovered"], "e0_candidates": c["e0_candidate_count"],
                        "pca_recovered": c["pca_recovered"], "pca_candidates": c["pca_candidate_count"]})
    return md_table(rows)


def table_e3_inexpressible(e3: dict) -> str:
    rows = []
    for f in e3["inexpressible"]:
        rows.append({"slice": f["slice"], "excluded_predicate": f["excluded_predicate"],
                    "base_confidence": f"{f['base_confidence']:.1%}",
                    "refined_confidence": f"{f['refined_confidence']:.1%}",
                    "fragment_check": f["fragment_check"]})
    return md_table(rows) if rows else "_(none surviving the improvement filter beyond the 2 reported)_"


def table_e4b(e4: dict) -> str:
    rows = []
    for chk in e4["clean_baseline_sanity"]["checks"]:
        rows.append({"slice": chk["slice"], "role": chk["role"], "V": chk.get("V", ""),
                    "total_witnesses": chk.get("total_witnesses", chk.get("status"))})
    return md_table(rows)


def table_e4c(e4: dict) -> str:
    rows = []
    for t, c in e4["synthetic_control"]["by_threshold"].items():
        rows.append({"threshold": t, "recovered": c["recovered"],
                    "of_true_constraints": c["total_true_constraints"],
                    "mined_candidates": c["mined_candidate_count"]})
    return md_table(rows)


def table_test_inventory() -> str:
    tests_dir = os.path.join(ROOT, "tests")
    out = subprocess.run([sys.executable, "-m", "pytest", "--collect-only", "-q", tests_dir],
                         capture_output=True, text=True, cwd=ROOT)
    counts = defaultdict(int)
    total = 0
    for line in out.stdout.splitlines():
        if "::" in line:
            fname = line.split("::", 1)[0].split(os.sep)[-1]
            counts[fname] += 1
            total += 1
    sprint_files = ["test_experimental_isolation.py", "test_mining_e0.py", "test_ml_mining_doc.py"]
    rows = [{"file": f, "count": counts.get(f, 0)} for f in sprint_files]
    rows.append({"file": "**baseline total (all tests/)**", "count": total})
    return md_table(rows)


def sprint_run_counts() -> str:
    recs = _load_jsonl(os.path.join(RESULTS, "cm_sprint_runs.jsonl"))
    by_exp = defaultdict(int)
    for r in recs:
        by_exp[r.get("experiment", "?")] += 1
    rows = [{"experiment": k, "logged_runs": v} for k, v in sorted(by_exp.items())]
    rows.append({"experiment": "**total**", "logged_runs": len(recs)})
    return md_table(rows)


 

def build(preserved: dict) -> str:
    e0 = _load("e0_summary.json")
    e1 = _load("e1_recovery.json")
    e2 = _load("e2_closed_loop.json")
    e3 = _load("e3_horn_pca.json")
    e4 = _load("e4_robustness.json")

    parts = []
    parts.append("# Constraint mining (CM) — one-week experimentation sprint\n")
    parts.append(
        "Every table below is read from `experimental/mining/results/*.json` and "
        "`results/cm_sprint_runs.jsonl` -- reusing the D7/C2 regeneration discipline "
        "(`scripts/build_evaluation.py`). Analysis prose is hand-written directly into "
        "the guarded blocks below (not deferred `_TODO_` placeholders): this sprint's "
        "own write-up IS the day's deliverable, produced the same day the numbers were "
        "measured. Regenerate with `python scripts/build_ml_mining_doc.py`.\n")
    parts.append(
        "**Isolation.** Everything under `experimental/mining/` imports FROM "
        "`src/kgrepair` and is never imported BY it -- enforced by "
        "`tests/test_experimental_isolation.py`, not just documented. No shipped "
        "constraint file, engine, or evaluator changed. `provenance=\"mined\"` marks "
        "every mined artifact so it can never be mistaken for a hand-curated rule.\n")

    parts.append(_prose_block("motivation", preserved, """
Hand-curating constraints does not scale, and every domain this project has
touched needed a human to trace real evidence before a constraint could be
trusted (see `docs/constraints_v2.md`'s RC1/RC2 story). The question this sprint
asks is narrow and empirical, not "can AI write constraints" but: **starting
from nothing but a KG slice and the existing hand-curated sets as ground truth,
how much of that hand-curation can plain statistical mining recover, where does
it fail, and does it fail the same way a human curator's blind spots do?** Five
gated experiments (E0-E4) plus this write-up (E5), each time-boxed to a day,
each shipping evidence whether the result was positive or not.
"""))

    parts.append("## Experiment status\n")
    parts.append(md_table([
        {"experiment": "E0", "day": "1", "status": "SHIPPED", "deliverable": "prevalence miner + fragment filter + tier classifier"},
        {"experiment": "E1", "day": "2", "status": "SHIPPED", "deliverable": "recovery vs v1/v2, defect-reproduction verdicts, sensitivity curves"},
        {"experiment": "E2", "day": "3", "status": "SHIPPED", "deliverable": "closed-loop repair + live plausibility + indictment trace"},
        {"experiment": "E3", "day": "4 (stretch)", "status": "SHIPPED", "deliverable": "PCA-confidence miner vs E0, inexpressible inventory"},
        {"experiment": "E4", "day": "5 AM", "status": "SHIPPED", "deliverable": "cross-source / clean-baseline / synthetic-control spot-checks"},
        {"experiment": "E5", "day": "5 PM", "status": "SHIPPED (this document)", "deliverable": "write-up + housekeeping"},
    ]))

    parts.append("\n## E0 — prevalence miner: run summary\n")
    parts.append(table_e0(e0))
    parts.append(_prose_block("e0_design", preserved, """
Two miners were built, both restricted to positive-node-expression shapes by
construction (fragment membership was verified with the real parser, not
assumed). E0's baseline uses plain prevalence under the Closed-World Assumption
(CWA): every entity satisfying a rule's body that isn't typed the proposed class
counts as a negative, even entities with no typing information at all. Class
membership is measured through the SAME `tau_C` (`down(type).down(subClassOf)*.
[val(C)]`) every hand-curated constraint uses, evaluated by the real
`kgrepair.gxpath.Evaluator` -- not a hand-rolled graph walk. At E0's scale, every
raw candidate passed the fragment filter and landed `ptime_core` -- unsurprising
by construction (the four shapes mined are all built from already-in-fragment
templates); the filter and classifier only became load-bearing once E3 explored
richer shapes.
"""))

    parts.append("\n## E1 — recovery vs. hand-curated v1/v2\n")
    parts.append(table_e1(e1))
    parts.append(_prose_block("e1_headline", preserved, """
**1 of 10 hand-curated `ptime_core` constraints recovered at every threshold
tested** (`geo.wd.req.city_country`); 1 of 10 recovered one of C1's own
evidence-derived meta-classes, but only at the loosest threshold
(`med.wd.rng.treats`, via `wd:Q112193867` "type of disease"); 1 of 10 is
structurally outside the miner's hypothesis space (`typing_inheritance`); the
remaining 7 -- every `given`/`compiled`-provenance domain/range rule -- were
missed at every threshold. This split lines up exactly with the codebase's own
`provenance` field: rules that were themselves originally authored by measuring
prevalence on a clean reference slice (`derived`) are recoverable by more
prevalence measurement; rules declared by the source KG's own schema
(`given`/`compiled`) and frequently violated in the real corpus are not
recoverable by frequency alone at any threshold this sprint tested. Even one
`derived` rule (`geo.wd.type.city`) failed here, because THIS slice
(geography-10k) is less typing-complete than the clean reference slice its
original 98% figure was measured on -- recoverability is a property of (rule,
measurement slice) together, not of the rule alone.

**Novelty**, hand-classified from live-resolved labels (`data/raw/mining/
label_cache.json`): anatomy and medication's novel candidates are dominated by
generic ontology-root classes ("entity," "class") that trivially clear any
prevalence bar without being domain-relevant -- two of anatomy's five sampled
classes are literally the SAME off-domain signal (`geographic entity`,
`region`) C1's RC1 trace found by hand. Geography's novelty profile is
genuinely different: all five sampled classes ("big city," "federated state,"
"first-level administrative division"...) are plausible, domain-relevant
refinements a human curator could reasonably add -- a real, domain-dependent
result, not a universal one.
"""))
    parts.append(_prose_block("e1_defect_a", preserved, """
**Defect-reproduction (a), anatomy's unscoped `wdt:P361` antecedent: neither
reproduced nor fixed, and the reason is structural.** E0's candidate generator
only proposes plain `<down(p)>`/`<up(p)>` antecedents; v2's actual fix (a nested
class test inside the antecedent path) is outside its hypothesis space by
construction, not a threshold miss. And v1's own (buggy, unscoped) rule doesn't
clear the miner's bar either: `wd:Q4936952` ("anatomical structure") support=22,
but only 12.5% of `P361`-subjects are typed it (9/72) -- the same off-domain
reuse that made v1 imprecise also suppresses raw prevalence below anything a
frequency miner would propose.
"""))
    parts.append(_prose_block("e1_defect_b", preserved, """
**Defect-reproduction (b), the "type of X" meta-class idiom: absorbed once,
concretely, but not cleanly.** `mined.medication.rng.P2175.Q112193867`
independently rediscovered C1's exact meta-class at 90.7% prevalence, with zero
knowledge of the RC2 trace. But at the same threshold the same sweep also
proposed five generic-root candidates ("entity," "class" x2, plus two more) for
the identical predicate, several scoring EQUAL OR HIGHER prevalence. Nothing in
E0 ranks by specificity, so the meaningful recovery is present but
indistinguishable, on paper, from the noise around it. Anatomy's 7 traced
meta-classes never appeared at all in this slice -- most likely too rare for
`min_support=20` on a 1000-edge slice, not evidence the mechanism is
domain-specific (E4's synthetic control and YAGO checks below suggest the
mechanism itself generalizes fine on cleaner data).
"""))

    parts.append("\n## E2 — closed-loop vetting: mine → repair → vet → indict\n")
    parts.append(table_e2(e2["cells"]))
    parts.append(_prose_block("e2_headline", preserved, """
Both cells repaired well under the 30% addition cap (anatomy 1.9%, medication
1.4%) using the 0.90 threshold -- justified from E1's own sensitivity curve as
the only threshold where either cell's mined set contains anything E1 could
match to a hand-curated rule at all. **"Does mining land closer to v1 or v2?" is
the wrong frame.** Strict precision (corroborated / classified) puts mined at
or above both hand-curated arms -- tied at 0% for anatomy, genuinely ahead for
medication (mined is the only arm with any nonzero corroboration in either
cell). But the more informative number is the CONTRADICTED fraction: mined is
contradicted far less than v1 in both cells (anatomy: 18.8% vs. v1's 90.4%),
and even less than v2 on anatomy -- not because mining is more accurate, but
because most mined classes are broad enough to be nearly unfalsifiable
(anatomy's plausible rate: 81.3% vs. v1's 9.6%). Low contradiction and being
useful are not the same thing.
"""))
    parts.append(_prose_block("e2_indictment", preserved, """
The indictment trace produced the sprint's single most concrete result. Two
anatomy entities indicted through `mined.anatomy.rng.P206.Q2507626` are, per
live Wikidata, literal **oceans** -- `wdt:P206` ("located in/next to body of
water") is the same cross-domain predicate-reuse pattern RC1 found for `P361`,
discovered here with zero human pointing at it. On medication,
`mined.medication.rng.P2175.Q112193867` produced both a genuine corroboration
AND several contradictions tracing to entities Wikidata itself types as
`symptom or sign` -- independent, same-sprint confirmation (from a completely
different, mined constraint set) of the exact symptom/disease conflation
`docs/constraints_v2.md` already documented as the reason C1 deliberately
excluded "symptom or sign" from its widening. Separately, 3 of 4 entities
indicted under a generic `"class"` rule are real, correctly-typed medications --
contradicted only because the miner picked an uninformative ancestor class, not
because the underlying antecedent was wrong. A meaningful share of "contradicted"
in this experiment is attributable to the miner's OWN class-selection noise, not
to any defect in the data.
"""))

    parts.append("\n## E3 — PCA-confidence miner vs. E0's plain prevalence\n")
    parts.append(table_e3(e3))
    parts.append("\n**Mineable-but-inexpressible inventory** (negated-exclusion refinements, "
                 "confirmed rejected by the real parser, never shipped or used downstream):\n")
    parts.append(table_e3_inexpressible(e3))
    parts.append(_prose_block("e3_headline", preserved, """
PCA candidate volume is `>=` CWA's at every threshold in every slice with any
candidates (expected: shrinking the negative-example denominator can only raise
a ratio). It changes an actual recovery outcome exactly once: medication's
`Q112193867` rule moves from 90.7% (misses the 95% bar) to 95.1% (clears it)
once 6 genuinely-untyped entities are excluded from the count -- a precise,
one-threshold improvement directly attributable to the incompleteness
correction. It does NOT rescue anatomy's `P361` rule (12.5% CWA -> 13.4% PCA,
checked directly) -- confirming E1's diagnosis that this rule's problem is
off-domain contamination, not typing incompleteness. **Comparing CWA vs. PCA
confidence for the same rule is a cheap diagnostic for which of the two failure
modes is at play, without a live Wikidata trace.** The 2-item inexpressible
inventory quantifies, concretely rather than abstractly, what the positive
fragment gives up for tractability: both refinements traded support for a real,
measured confidence gain (61->40 support for +2pp confidence; 48->35 support for
+0.5pp), the standard Horn-rule specialization trade-off, available to a richer
miner but not to one confined to Reg-GXPath_pos.
"""))

    parts.append("\n## E4 — robustness spot-checks\n")
    parts.append("\n**4a. Cross-source transfer** (wikidata-geography mined set -> DBpedia geography): "
                 f"raw transfer = **{e4['cross_source_transfer']['raw_transfer']['total_witnesses_on_dbpedia']} "
                 "witnesses** (zero syntactic overlap between `wdt:`/`wd:` and `dbo:`/`dbr:` vocabularies -- "
                 "confirmed, not assumed). The one rule with a genuinely trivial hand-mapping (City-requires-"
                 f"country -> Settlement-requires-`dbo:country`) scored "
                 f"**{e4['cross_source_transfer']['one_trivial_mapping_attempted']['witnesses_on_dbpedia']} "
                 "witnesses -- does not hold as-is** on the DBpedia slice.\n")
    parts.append("\n**4b. Clean-baseline sanity** (mined on `yago_taxa_1000`, validated in-sample and out-of-sample):\n")
    parts.append(table_e4b(e4))
    parts.append("\n**4c. Synthetic control** (`synthetic_geoLike_1k_s0`, true constraint set known by construction):\n")
    parts.append(table_e4c(e4))
    parts.append(_prose_block("e4_headline", preserved, """
Three short, independent results. Mining does not transfer across KG
vocabularies, not even for the sprint's single cleanest recovery with an
obvious hand-mapping -- a negative result, stated plainly. Mining generalizes
CLEANLY out-of-sample on YAGO (0 witnesses on a 10x-larger held-out rung of the
same clean source) -- the sprint's best positive result, and a useful control:
every noisy or contradictory outcome elsewhere traced back to Wikidata-specific
messiness (predicate reuse, the meta-class idiom, real incompleteness), never
to the mining mechanism itself. And on a slice with a KNOWN ground truth and
zero incompleteness confound, recovery reaches 3 of 4 true rules -- meaningfully
higher than E1's real-corpus rate of 1 of 10 -- with the one remaining gap
(`syn.rng.country`, true prevalence 84.6% in this slice despite only a 2%
injection rate) named and left open rather than explained away.
"""))

    parts.append("\n## Honest limitations\n")
    parts.append(_prose_block("limitations", preserved, """
- **Incompleteness bias, only partially addressed.** E3's PCA correction helps
  exactly when the failure mode IS incompleteness (one confirmed case) and
  correctly does nothing otherwise (one confirmed negative control) -- it is a
  diagnostic, not a general fix, and was only tried for the two domain/range
  shapes, not typing_existence/requires_statement.
- **Threshold sensitivity is real and mostly unhelpful.** Lowering the
  threshold from 99% to 90% roughly doubles novel-candidate volume in the noisy
  domains (anatomy: 66->101) while barely moving recovery -- the extra
  candidates are overwhelmingly the same generic-root noise, not near-misses on
  the hand-curated set.
- **Slice-scale only.** Every measurement here is on 1k-10k-edge slices;
  nothing in this sprint speaks to mining behavior at full-KG scale, where
  support floors, candidate volume, and runtime would all behave differently.
- **One KG family for live vetting.** E2's plausibility loop only ever checked
  against live Wikidata; DBpedia and YAGO have no equivalent oracle available
  in this project, so the closed-loop result (E2) cannot be generalized past
  Wikidata without a comparable live source for the others.
- **Class-selection noise dominates the failure mode this sprint actually
  found**, more than incompleteness or fragment-inexpressibility did in
  practice: E1, E2, and E3 all independently converge on the same diagnosis --
  E0's miner has no mechanism to prefer a specific, informative class over a
  vacuous ontology-root ancestor when both clear the same confidence bar.
"""))

    parts.append("\n## Negative-result assessment\n")
    parts.append(_prose_block("negative_result", preserved, """
Per the sprint's own negative-result rule: mining did NOT underperform
hand-curation everywhere, so the honest characterization is a mixed result, not
a uniform failure. It underperformed badly on strict recovery (1/10 real-corpus
constraints recovered vs. hand-curation's full coverage by definition) and
introduced a genuinely new failure mode (class-selection noise) neither
hand-curated arm exhibited. It matched or beat hand-curation on two narrower,
real measures: E2's contradiction rate (mined additions are wrong far less
often than v1, in both cells) and E4's synthetic-control recovery rate (3/4,
with zero incompleteness confound, vs. E1's real-corpus 1/10). The clean
takeaway is not "mining works" or "mining fails" but that its failure mode is
predictable and diagnosable: it works when the underlying rule is genuinely
prevalence-shaped and the KG's typing is reasonably complete (YAGO, the
synthetic control, medication's one recovery); it fails, specifically and
traceably, on cross-domain predicate reuse and vacuous-class selection --
exactly the two things a plausibility-vetting loop (E2) is positioned to catch
before any mined rule is trusted.
"""))

    parts.append("\n## Future-work architecture\n")
    parts.append(_prose_block("future_work", preserved, """
Grounded in what this sprint actually measured, not proposed in the abstract:

```
  candidate generation (E0 prevalence / E3 PCA-confidence)
        |
        v
  SPECIFICITY RANKING  <-- not built this sprint; the single most-repeated
        |                  finding (E1, E2, E3) is that nothing today
        |                  distinguishes a domain-relevant class from a
        |                  vacuous ontology-root ancestor at equal confidence.
        |                  A minimal version: penalize candidate classes by
        |                  their own instance-count share of |V| (root classes
        |                  are large by definition); a fuller version would
        |                  need an actual specificity/informativeness measure.
        v
  fragment filter (real parser, not a kind-name assumption)
        |
        v
  tier classifier (kind -> ptime_core/boundary, confidence-independent)
        |
        v
  superset_repair (E2's closed loop, already exists, already wired to mined sets)
        |
        v
  LIVE PLAUSIBILITY VETTING (E2, the one component this sprint proved is load-
        |                    bearing: it caught the P206-ocean contamination
        |                    and the P2175 symptom/disease conflation that
        |                    NOTHING upstream of it would have caught)
        v
  human sign-off gate  <-- every mined constraint stays provenance="mined"
                           and is never auto-promoted; nothing in this
                           architecture proposes removing a human decision
                           point, only automating what precedes it
```

The one component this sprint did NOT build and would prioritize first if this
became more than exploratory work is the specificity-ranking stage -- it is the
single highest-leverage gap the evidence points to, ahead of a richer miner
(E3's stretch direction) or broader corpus coverage (E4's direction).
"""))

    parts.append("\n## Reproducibility appendix\n")
    parts.append("\nSprint-tagged run log (`results/cm_sprint_runs.jsonl`, `tag=\"cm-sprint\"`, "
                 "kept separate from `results/runs.jsonl`'s D7 dataset):\n")
    parts.append(sprint_run_counts())
    parts.append("\nSprint-added test files (part of the repo's own suite, not counted separately):\n")
    parts.append(table_test_inventory())
    parts.append(
        "\n- E0: `experimental/mining/results/e0_summary.json` "
        "(`bash: python experimental/mining/run_e0.py`)."
        "\n- E1: `experimental/mining/results/e1_recovery.json` "
        "(`python experimental/mining/e1_recovery.py`)."
        "\n- E2: `experimental/mining/results/e2_closed_loop.json` + "
        "`results/v1_vs_v2_eval.json` (v1/v2 arm, read not re-derived) "
        "(`python experimental/mining/e2_closed_loop.py`)."
        "\n- E3: `experimental/mining/results/e3_horn_pca.json` "
        "(`python experimental/mining/e3_horn_pca.py`)."
        "\n- E4: `experimental/mining/results/e4_robustness.json` "
        "(`python experimental/mining/e4_robustness.py`)."
        "\n- Live-query caches: `data/raw/mining/{ask_cache,entity_type_cache,label_cache}.json` "
        "-- a sprint-scoped cache generation, separate from `data/raw/plausibility/`'s D6/D7 cache."
        "\n- Per-experiment narrative detail beyond this consolidated document: "
        "`experimental/mining/results/e1_recovery.md`, `e2_closed_loop.md`, "
        "`e3_horn_pca.md`, `e4_robustness.md`."
    )

    return "\n".join(parts) + "\n"


def main() -> None:
    preserved = {}
    if os.path.exists(OUT_PATH):
        with open(OUT_PATH, encoding="utf-8") as fh:
            preserved = _extract_prose(fh.read())
    text = build(preserved)
    with open(OUT_PATH, "w", encoding="utf-8") as fh:
        fh.write(text)
    print(f"wrote {OUT_PATH} ({len(text)} bytes)")


if __name__ == "__main__":
    main()
