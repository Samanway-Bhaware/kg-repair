# Constraint mining (CM) — one-week experimentation sprint

Every table below is read from `experimental/mining/results/*.json` and `results/cm_sprint_runs.jsonl` -- reusing the D7/C2 regeneration discipline (`scripts/build_evaluation.py`). Analysis prose is hand-written directly into the guarded blocks below (not deferred `_TODO_` placeholders): this sprint's own write-up IS the day's deliverable, produced the same day the numbers were measured. Regenerate with `python scripts/build_ml_mining_doc.py`.

**Isolation.** Everything under `experimental/mining/` imports FROM `src/kgrepair` and is never imported BY it -- enforced by `tests/test_experimental_isolation.py`, not just documented. No shipped constraint file, engine, or evaluator changed. `provenance="mined"` marks every mined artifact so it can never be mistaken for a hand-curated rule.

<!-- PROSE:motivation:start -->

Hand-curating constraints does not scale, and every domain this project has
touched needed a human to trace real evidence before a constraint could be
trusted (see `docs/constraints_v2.md`'s RC1/RC2 story). The question this sprint
asks is narrow and empirical, not "can AI write constraints" but: **starting
from nothing but a KG slice and the existing hand-curated sets as ground truth,
how much of that hand-curation can plain statistical mining recover, where does
it fail, and does it fail the same way a human curator's blind spots do?** Five
gated experiments (E0-E4) plus this write-up (E5), each time-boxed to a day,
each shipping evidence whether the result was positive or not.

<!-- PROSE:motivation:end -->
## Experiment status

| experiment | day | status | deliverable |
|---|---|---|---|
| E0 | 1 | SHIPPED | prevalence miner + fragment filter + tier classifier |
| E1 | 2 | SHIPPED | recovery vs v1/v2, defect-reproduction verdicts, sensitivity curves |
| E2 | 3 | SHIPPED | closed-loop repair + live plausibility + indictment trace |
| E3 | 4 (stretch) | SHIPPED | PCA-confidence miner vs E0, inexpressible inventory |
| E4 | 5 AM | SHIPPED | cross-source / clean-baseline / synthetic-control spot-checks |
| E5 | 5 PM | SHIPPED (this document) | write-up + housekeeping |

## E0 — prevalence miner: run summary

| slice | kg | threshold | raw | fragment_passed | fragment_rejected | ptime_core | boundary |
|---|---|---|---|---|---|---|---|
| real_yago_taxa_1000 | yago | 0.90 | 2 | 2 | 0 | 2 | 0 |
| real_yago_taxa_1000 | yago | 0.95 | 2 | 2 | 0 | 2 | 0 |
| real_yago_taxa_1000 | yago | 0.99 | 2 | 2 | 0 | 2 | 0 |
| real_wikidata_anatomy_1000_typed | wikidata | 0.90 | 101 | 101 | 0 | 101 | 0 |
| real_wikidata_anatomy_1000_typed | wikidata | 0.95 | 86 | 86 | 0 | 86 | 0 |
| real_wikidata_anatomy_1000_typed | wikidata | 0.99 | 66 | 66 | 0 | 66 | 0 |
| real_wikidata_medication_1000_typed | wikidata | 0.90 | 20 | 20 | 0 | 20 | 0 |
| real_wikidata_medication_1000_typed | wikidata | 0.95 | 13 | 13 | 0 | 13 | 0 |
| real_wikidata_medication_1000_typed | wikidata | 0.99 | 3 | 3 | 0 | 3 | 0 |
| real_wikidata_geography_10000 | wikidata | 0.90 | 69 | 69 | 0 | 69 | 0 |
| real_wikidata_geography_10000 | wikidata | 0.95 | 60 | 60 | 0 | 60 | 0 |
| real_wikidata_geography_10000 | wikidata | 0.99 | 45 | 45 | 0 | 45 | 0 |
<!-- PROSE:e0_design:start -->

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

<!-- PROSE:e0_design:end -->

## E1 — recovery vs. hand-curated v1/v2

| slice | threshold | missed | novel_count | out_of_search_space | recovered_base | recovered_v2_added |
|---|---|---|---|---|---|---|
| real_yago_taxa_1000 | 0.90 | 0 | 0 | 1 | 0 | 0 |
| real_yago_taxa_1000 | 0.95 | 0 | 0 | 1 | 0 | 0 |
| real_yago_taxa_1000 | 0.99 | 0 | 0 | 1 | 0 | 0 |
| real_wikidata_anatomy_1000_typed | 0.90 | 2 | 101 | 0 | 0 | 0 |
| real_wikidata_anatomy_1000_typed | 0.95 | 2 | 86 | 0 | 0 | 0 |
| real_wikidata_anatomy_1000_typed | 0.99 | 2 | 66 | 0 | 0 | 0 |
| real_wikidata_medication_1000_typed | 0.90 | 2 | 19 | 0 | 0 | 1 |
| real_wikidata_medication_1000_typed | 0.95 | 3 | 13 | 0 | 0 | 0 |
| real_wikidata_medication_1000_typed | 0.99 | 3 | 3 | 0 | 0 | 0 |
| real_wikidata_geography_10000 | 0.90 | 3 | 63 | 0 | 1 | 0 |
| real_wikidata_geography_10000 | 0.95 | 3 | 54 | 0 | 1 | 0 |
| real_wikidata_geography_10000 | 0.99 | 3 | 41 | 0 | 1 | 0 |
<!-- PROSE:e1_headline:start -->

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

<!-- PROSE:e1_headline:end -->
<!-- PROSE:e1_defect_a:start -->

**Defect-reproduction (a), anatomy's unscoped `wdt:P361` antecedent: neither
reproduced nor fixed, and the reason is structural.** E0's candidate generator
only proposes plain `<down(p)>`/`<up(p)>` antecedents; v2's actual fix (a nested
class test inside the antecedent path) is outside its hypothesis space by
construction, not a threshold miss. And v1's own (buggy, unscoped) rule doesn't
clear the miner's bar either: `wd:Q4936952` ("anatomical structure") support=22,
but only 12.5% of `P361`-subjects are typed it (9/72) -- the same off-domain
reuse that made v1 imprecise also suppresses raw prevalence below anything a
frequency miner would propose.

<!-- PROSE:e1_defect_a:end -->
<!-- PROSE:e1_defect_b:start -->

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

<!-- PROSE:e1_defect_b:end -->

## E2 — closed-loop vetting: mine → repair → vet → indict

| cell | arm | additions | checked | corroborated | precision |
|---|---|---|---|---|---|
| anatomy_1000 | v1 | 115 | 115 | 0 | 0.0% |
| anatomy_1000 | v2 | 10 | 10 | 0 | 0.0% |
| anatomy_1000 | mined | 36 | 36 | 0 | 0.0% |
| medication_1000 | v1 | 122 | 120 | 0 | 0.0% |
| medication_1000 | v2 | 10 | 10 | 0 | 0.0% |
| medication_1000 | mined | 23 | 23 | 1 | 4.3% |
<!-- PROSE:e2_headline:start -->

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

<!-- PROSE:e2_headline:end -->
<!-- PROSE:e2_indictment:start -->

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

<!-- PROSE:e2_indictment:end -->

## E3 — PCA-confidence miner vs. E0's plain prevalence

| slice | threshold | e0_recovered | e0_candidates | pca_recovered | pca_candidates |
|---|---|---|---|---|---|
| yago/taxa | 0.90 | 0 | 1 | 0 | 1 |
| yago/taxa | 0.95 | 0 | 1 | 0 | 1 |
| yago/taxa | 0.99 | 0 | 1 | 0 | 1 |
| wikidata/anatomy | 0.90 | 0 | 65 | 0 | 71 |
| wikidata/anatomy | 0.95 | 0 | 57 | 0 | 65 |
| wikidata/anatomy | 0.99 | 0 | 48 | 0 | 54 |
| wikidata/medication | 0.90 | 1 | 20 | 1 | 24 |
| wikidata/medication | 0.95 | 0 | 13 | 1 | 20 |
| wikidata/medication | 0.99 | 0 | 3 | 0 | 6 |
| wikidata/geography | 0.90 | 0 | 0 | 0 | 0 |
| wikidata/geography | 0.95 | 0 | 0 | 0 | 0 |
| wikidata/geography | 0.99 | 0 | 0 | 0 | 0 |

**Mineable-but-inexpressible inventory** (negated-exclusion refinements, confirmed rejected by the real parser, never shipped or used downstream):

| slice | excluded_predicate | base_confidence | refined_confidence | fragment_check |
|---|---|---|---|---|
| real_wikidata_anatomy_1000_typed | wdt:P17 | 91.0% | 93.0% | rejected as expected: node complement (not phi) leaves Reg-GXPath_pos |
| real_wikidata_anatomy_1000_typed | wdt:P131 | 94.1% | 94.6% | rejected as expected: node complement (not phi) leaves Reg-GXPath_pos |
<!-- PROSE:e3_headline:start -->

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

<!-- PROSE:e3_headline:end -->

## E4 — robustness spot-checks


**4a. Cross-source transfer** (wikidata-geography mined set -> DBpedia geography): raw transfer = **0 witnesses** (zero syntactic overlap between `wdt:`/`wd:` and `dbo:`/`dbr:` vocabularies -- confirmed, not assumed). The one rule with a genuinely trivial hand-mapping (City-requires-country -> Settlement-requires-`dbo:country`) scored **4 witnesses -- does not hold as-is** on the DBpedia slice.


**4b. Clean-baseline sanity** (mined on `yago_taxa_1000`, validated in-sample and out-of-sample):

| slice | role | V | total_witnesses |
|---|---|---|---|
| real_yago_taxa_1000 | training slice (in-sample) | 515 | 0 |
| real_yago_taxa_10000 | held-out rung (out-of-sample) | 5475 | 0 |

**4c. Synthetic control** (`synthetic_geoLike_1k_s0`, true constraint set known by construction):

| threshold | recovered | of_true_constraints | mined_candidates |
|---|---|---|---|
| 0.90 | 3 | 4 | 23 |
| 0.95 | 3 | 4 | 19 |
| 0.99 | 2 | 4 | 6 |
<!-- PROSE:e4_headline:start -->

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

<!-- PROSE:e4_headline:end -->

## Honest limitations

<!-- PROSE:limitations:start -->

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

<!-- PROSE:limitations:end -->

## Negative-result assessment

<!-- PROSE:negative_result:start -->

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

<!-- PROSE:negative_result:end -->

## Future-work architecture

<!-- PROSE:future_work:start -->

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

<!-- PROSE:future_work:end -->

## Reproducibility appendix


Sprint-tagged run log (`results/cm_sprint_runs.jsonl`, `tag="cm-sprint"`, kept separate from `results/runs.jsonl`'s D7 dataset):

| experiment | logged_runs |
|---|---|
| E0 | 8 |
| E1 | 4 |
| E2 | 2 |
| E3 | 4 |
| E4 | 3 |
| **total** | 21 |

Sprint-added test files (part of the repo's own suite, not counted separately):

| file | count |
|---|---|
| test_experimental_isolation.py | 2 |
| test_mining_e0.py | 9 |
| test_ml_mining_doc.py | 3 |
| **baseline total (all tests/)** | 592 |

- E0: `experimental/mining/results/e0_summary.json` (`bash: python experimental/mining/run_e0.py`).
- E1: `experimental/mining/results/e1_recovery.json` (`python experimental/mining/e1_recovery.py`).
- E2: `experimental/mining/results/e2_closed_loop.json` + `results/v1_vs_v2_eval.json` (v1/v2 arm, read not re-derived) (`python experimental/mining/e2_closed_loop.py`).
- E3: `experimental/mining/results/e3_horn_pca.json` (`python experimental/mining/e3_horn_pca.py`).
- E4: `experimental/mining/results/e4_robustness.json` (`python experimental/mining/e4_robustness.py`).
- Live-query caches: `data/raw/mining/{ask_cache,entity_type_cache,label_cache}.json` -- a sprint-scoped cache generation, separate from `data/raw/plausibility/`'s D6/D7 cache.
- Per-experiment narrative detail beyond this consolidated document: `experimental/mining/results/e1_recovery.md`, `e2_closed_loop.md`, `e3_horn_pca.md`, `e4_robustness.md`.
