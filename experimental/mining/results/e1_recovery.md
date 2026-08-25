# E1 (Day 2) — recovery evaluation: mined vs hand-curated v1/v2

Source data: `experimental/mining/results/e1_recovery.json`, `experimental/mining/candidates/*.json`
(E0 output), `results/cm_sprint_runs.jsonl` (`experiment="E1"` records), `data/raw/mining/label_cache.json`.
Matching rule and all counting logic: `experimental/mining/e1_recovery.py` (see its module
docstring for the exact "recovered"/"novel" definitions used below).

## Recovery table

| slice | cid | kind | mineable? | 0.99 | 0.95 | 0.90 |
|---|---|---|---|---|---|---|
| yago_taxa_1000 | tax.yg.inherit.taxon | typing_inheritance | no | out_of_search_space | out_of_search_space | out_of_search_space |
| anatomy_1000 | ana.wd.dom.partof | existential_domain | yes | missed | missed | missed |
| anatomy_1000 | ana.wd.rng.partof | existential_range | yes | missed | missed | missed |
| medication_1000 | med.wd.dom.treats | existential_domain | yes | missed | missed | missed |
| medication_1000 | med.wd.rng.treats | existential_range | yes | missed | missed | **recovered_v2_added_only** |
| medication_1000 | med.wd.req.route | requires_statement | yes | missed | missed | missed |
| geography_10000 | geo.wd.dom.country | existential_domain | yes | missed | missed | missed |
| geography_10000 | geo.wd.rng.country | existential_range | yes | missed | missed | missed |
| geography_10000 | geo.wd.type.city | typing_existence | yes | missed | missed | missed |
| geography_10000 | geo.wd.req.city_country | requires_statement | yes | **recovered_base_only** | **recovered_base_only** | **recovered_base_only** |

**Headline: 1/10 hand-curated ptime_core constraints recovered at their own base
class, at every threshold; 1/10 recovered one of v2's added meta-classes, at the
loosest threshold only; 1/10 is structurally outside the miner's hypothesis space
regardless of threshold; the remaining 7/10 (all `given`/`compiled`-provenance
domain/range rules) are missed at every threshold tested.**

## Threshold-sensitivity (recovery + novelty vs threshold)

| slice | threshold | recovered_base | recovered_v2_added | missed | out_of_search_space | novel_count |
|---|---|---|---|---|---|---|
| yago_taxa_1000 | 0.99 | 0 | 0 | 0 | 1 | 0 |
| yago_taxa_1000 | 0.95 | 0 | 0 | 0 | 1 | 0 |
| yago_taxa_1000 | 0.90 | 0 | 0 | 0 | 1 | 0 |
| anatomy_1000 | 0.99 | 0 | 0 | 2 | 0 | 66 |
| anatomy_1000 | 0.95 | 0 | 0 | 2 | 0 | 86 |
| anatomy_1000 | 0.90 | 0 | 0 | 2 | 0 | 101 |
| medication_1000 | 0.99 | 0 | 0 | 3 | 0 | 3 |
| medication_1000 | 0.95 | 0 | 0 | 3 | 0 | 13 |
| medication_1000 | 0.90 | 0 | 1 | 2 | 0 | 19 |
| geography_10000 | 0.99 | 1 | 0 | 3 | 0 | 41 |
| geography_10000 | 0.95 | 1 | 0 | 3 | 0 | 54 |
| geography_10000 | 0.90 | 1 | 0 | 3 | 0 | 63 |

**Reading the curve:** recovery is almost flat against threshold (only medication
gains one recovery, and only at the loosest bar) while novelty grows steeply as
the threshold loosens — e.g. anatomy goes 66→86→101 novel candidates from 99%→90%.
Lowering the threshold buys volume, not more of the constraints that matter: the
extra candidates picked up between 99% and 90% are overwhelmingly the same kind of
generic-root noise characterised below, not near-misses on the hand-curated set.

## Manual novelty classification (labels resolved live via `PoliteFetcher`, cached in `data/raw/mining/label_cache.json`)

A 5-class sample per slice at the loosest threshold (0.90, the richest set), by hand:

**anatomy_1000** — all 5 sampled classes are generic ontology-root nodes, not
anatomically meaningful:

| class | label | verdict |
|---|---|---|
| wd:Q35120 | entity | artifact-of-genericity |
| wd:Q16889133 | class | artifact-of-genericity |
| wd:Q27096213 | geographic entity | artifact-of-genericity (off-domain: a *geographic* root, in an *anatomy* slice) |
| wd:Q137023128 | region | artifact-of-genericity (off-domain, same P361-reuse pattern RC1 traced) |
| wd:Q123349660 | geolocatable entity | artifact-of-genericity (off-domain) |

Two of the five (`geographic entity`, `region`) are the *exact same off-domain
signal* C1's RC1 trace found in the hand-curated pipeline — P361 reuse pulling in
geographic/administrative classes. The miner sees the identical cross-domain
contamination a human curator had to trace by hand; it just has no mechanism to
tell "off-domain but prevalent" apart from "on-domain and prevalent."

**medication_1000** — same pattern, one partial exception:

| class | label | verdict |
|---|---|---|
| wd:Q35120 | entity | artifact-of-genericity |
| wd:Q16889133 | class | artifact-of-genericity |
| wd:Q5127848 | class | artifact-of-genericity |
| wd:Q21146257 | type | artifact-of-genericity |
| wd:Q130286945 | type of problem | borderline-plausible (see below) |

`type of problem` points in roughly the right conceptual direction for
`med.wd.rng.treats` (a medication's P2175 target being "a kind of problem" is not
wrong), but it is far too generic to be a useful class test on its own — it is not
one of C1's evidence-derived meta-classes, and using it as a consequent would
under-constrain the rule severely. Classified as *artifact-of-incompleteness /
over-generic*, not *plausible* outright.

**geography_10000** — a genuinely different, more positive profile:

| class | label | verdict |
|---|---|---|
| wd:Q1799794 | administrative territorial entity of a specific level | plausible |
| wd:Q1048835 | political territorial entity | plausible |
| wd:Q107390 | federated state | plausible |
| wd:Q10864048 | first-level administrative division | plausible |
| wd:Q1549591 | big city | plausible |

All five are genuine, domain-relevant geography classes a human curator could
reasonably add (e.g. `big city` as a stricter refinement of `City`, `federated
state`/`first-level administrative division` as meaningful sub-types the current
hand-curated set doesn't distinguish). Geography's ontology neighbourhood is
apparently populated with informative mid-level classes densely enough that a
plain prevalence sweep can land on them without being drowned out by root nodes
the way anatomy/medication were — this is a genuine limitation-dependent result,
not a universal one, and worth stating as such rather than generalizing from one
domain.

**yago_taxa_1000** — 0 novel candidates at any threshold (nothing to sample); the
slice's only ptime_core rule is `out_of_search_space` and the miner otherwise found
nothing else clearing the support floor in this small, clean corpus.

## Defect-reproduction verdict (a) — RC1 (anatomy's unscoped P361 antecedent)

**Does prevalence mining propose the over-broad unscoped P361 antecedent, or does
target-class co-occurrence naturally produce the scoped v2 form?**

**Neither, and the reason is structural, not a threshold miss.** E0's candidate
generator only ever proposes plain `<down(p)>`/`<up(p)>` antecedents for
`existential_domain`/`existential_range` — there is no candidate-generation rule
that nests a class test inside the antecedent path (`<down(P361).[TAU_ANAT_V2]>`,
v2's actual fix shape). That shape is simply outside this miner's hypothesis
space; it cannot be discovered at *any* threshold, by construction, not because it
failed a prevalence check.

What the miner *can* measure is whether it would propose v1's own (unscoped, buggy)
antecedent — and here the direct measurement is unambiguous:

```
subj_of(wdt:P361) = 72 entities
instances(wd:Q4936952 "anatomical structure", v1's own base class) = 22 (clears min_support)
prevalence(P361-subject typed AnatomicalStructure) = 9/72 = 12.5%
```

12.5% is far below even the loosest tested threshold (90%). **The miner does not
reproduce v1's exact rule either** — the same off-domain P361 reuse that made v1
*imprecise* (RC1) suppresses raw prevalence so far that a frequency-based miner
would reject v1's own rule outright, not just fail to improve on it. The practical
verdict: for this constraint, prevalence mining is neither as good as v1 nor as
good as v2 — it produces nothing, because `ana.wd.dom.partof`/`ana.wd.rng.partof`
are `provenance="compiled"` (declared by Wikidata's own P361 domain/range, not by
data statistics), and real-corpus incompleteness pushes their true prevalence well
under any of the thresholds this sprint tested.

## Defect-reproduction verdict (b) — RC2 ("type of X" meta-class idiom)

**Do mined typing constraints stumble on the idiom the same way v1 did, or does
mining over observed typing paths absorb it automatically?**

**Partially absorbed — and the one clean success case is directly traceable.**
`med.wd.rng.treats` (object of `wdt:P2175` typed as a disease) is `missed` at
99%/95% but `recovered_v2_added_only` at 90%:

```
mined.medication.rng.P2175.Q112193867
  < up(wdt:P2175) > => tau_C("wd:Q112193867")     [Q112193867 = "type of disease",
                                                     C1's OWN traced meta-class]
  prevalence = 90.7%, support = 129
```

This is a genuine, unprompted rediscovery of one of C1's exact evidence-derived
meta-classes — the miner found it purely from co-occurrence statistics, with no
knowledge of the RC2 trace. But it did not do so cleanly: at the SAME threshold,
the SAME (predicate, class) sweep also proposed `wd:Q35120` ("entity", 95.4%
prevalence), `wd:Q16889133`/`wd:Q5127848` ("class", 93.8% both), `wd:Q99527517`
and `wd:Q7048977` (93.8%/95.4%) as domain-range candidates for the identical `P2175`
predicate — every one of them a generic ontology-root node, several
scoring HIGHER prevalence than the meaningful meta-class. Nothing in E0's design
ranks or filters on specificity, so `Q112193867` surfaces in the candidate list
but is not distinguished from the noise around it.

Anatomy shows the opposite outcome: none of C1's 7 traced anatomy meta-classes
(`wd:Q112826905`, `wd:Q103812529`, `wd:Q104027169`, `wd:Q103914748`,
`wd:Q113147985`, `wd:Q139550381`, `wd:Q103843042`) appear anywhere in
`real_wikidata_anatomy_1000_typed`'s mined candidates at any threshold — checked
directly against every candidate file, zero matches. The most likely explanation,
consistent with `geo.wd.type.city`'s own measured collapse below (6.2%
prevalence on this slice vs. the 98% it was originally curated at on a separate
clean reference slice), is that this particular 1000-edge anatomy slice is simply
too small/incomplete for several of the rarer meta-classes to clear
`min_support=20` or to reach threshold, not that the mechanism is domain-specific.

**Verdict: mining over observed typing paths can absorb the idiom automatically —
demonstrated once, concretely, not hypothetically — but it does so
inconsistently across domains/slices, and even in the one success case the
meaningful candidate is indistinguishable, on paper, from several vacuous
root-class candidates scored alongside it at equal or higher confidence.** A
usable miner would need a specificity/informativeness signal E0 does not have;
flagged directly as a design gap for E3, not smoothed over.

## Bottom line for E1

The clearest recovery (`geo.wd.req.city_country`, recovered at every threshold
including 99%) and the clearest miss pattern (every `given`/`compiled`
domain/range rule, missed at every threshold) split exactly along the codebase's
own `provenance` field: `derived` rules — which were themselves originally
authored by measuring prevalence on a clean reference slice — are what a
prevalence miner is suited to finding; `given`/`compiled` rules, asserted by the
source KG's own schema and frequently violated in practice (the same
incompleteness D6/D7 already measured at ~10–25% real-corpus violation rates),
are not recoverable by frequency alone at any threshold this sprint tested. Even
one `derived` rule (`geo.wd.type.city`) failed to recover here, because THIS
slice is less typing-complete than the clean reference slice its original 98%
figure was measured on — recoverability is a property of (rule, measurement
slice) together, not of the rule alone.
