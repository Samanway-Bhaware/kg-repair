# E2 (Day 3) — closed-loop vetting: mine → repair → vet → indict, end to end

Source data: `experimental/mining/results/e2_closed_loop.json` (fresh, live-checked
this run), `results/v1_vs_v2_eval.json` (existing D7 artifact, read not
re-derived — a sprint non-goal is re-running settled D7 tables). Live Wikidata
queries went through the project's own `PoliteFetcher`, cached in
`data/raw/mining/{ask_cache,entity_type_cache}.json` — a new, sprint-scoped cache
generation, separate from D6/D7's `data/raw/plausibility/`.

**Threshold used: 0.90** (justified from E1's sensitivity curve, not asserted —
see `e1_recovery.md`: it is the only threshold at which either cell's mined set
contains anything E1 could match to a hand-curated rule at all). **Cap: 30%
addition fraction**, the same `SUPERSET_CAP_DEFAULT` convention `bench/real_superset.py`
uses. Both cells ran well under cap (anatomy 1.9%, medication 1.4%) — the mined
sets, despite containing 101 and 20 constraints respectively, only needed to fill
small gaps, since most mined rules already have 90%+ prevalence in the graph they
were mined from.

**One operational note, not a design bug:** the first run of this experiment
crashed on a transient Wikidata network timeout, and the original script only
saved its query cache once at the end — so the crash lost all progress. Fixed
before re-running: `ask_typed`/`ask_has_type` now save the cache after every new
query and return `None` (recorded as "unknown", not a crash) on a failed request,
so a single flaky query no longer costs the whole run. 4 of anatomy's 36 checks
came back `unknown` on the successful run; medication had none.

## Three-way comparison table

| cell | arm | additions | checked | classified | corroborated | contradicted | plausible | unknown | precision (of classified) |
|---|---|---|---|---|---|---|---|---|---|
| anatomy_1000 | v1 (known-defective) | 115 | 115 | 115 | 0 | 104 | 11 | 0 | 0.0% |
| anatomy_1000 | v2 (C1-repaired) | 10 | 10 | 10 | 0 | 4 | 6 | 0 | 0.0% |
| anatomy_1000 | **mined (0.90)** | 36 | 36 | 32 | 0 | 6 | 26 | 4 | 0.0% |
| medication_1000 | v1 (known-defective) | 122 | 120 | 120 | 0 | 114 | 6 | 0 | 0.0% |
| medication_1000 | v2 (C1-repaired) | 10 | 10 | 10 | 0 | 4 | 6 | 0 | 0.0% |
| medication_1000 | **mined (0.90)** | 23 | 23 | 23 | **1** | 12 | 10 | 0 | **4.3%** |

## Does mining land closer to v1 or v2? — closer to neither; a third failure mode

**Strict precision (corroborated ÷ classified) puts mined at or above both v1
and v2** — tied at 0% for anatomy, genuinely ahead of both for medication (mined
is the *only* arm with a nonzero corroboration in either cell). But precision
alone hides the real story, which is in the **contradicted-fraction**, not the
corroborated one:

| cell | v1 contradicted% | v2 contradicted% | mined contradicted% |
|---|---|---|---|
| anatomy_1000 | 90.4% (104/115) | 40.0% (4/10) | **18.8%** (6/32) |
| medication_1000 | 95.0% (114/120) | 40.0% (4/10) | 52.2% (12/23) |

Mined additions are contradicted far less often than v1 in both cells (anatomy
especially: 18.8% vs. v1's 90.4%), and in anatomy even less often than v2. **This
is not because mining is more accurate** — it is because most mined classes are
broad enough (E1's "artifact-of-genericity" finding) that live Wikidata can
rarely definitively rule them out; they land `plausible` instead of `contradicted`
or `corroborated`. Anatomy's plausible fraction is 81.3% (26/32) — far higher than
v1's 9.6% or v2's 60%. Low contradiction is not the same thing as being useful;
a rule broad enough to be almost unfalsifiable will show exactly this profile.

## Indictment trace (entity-level, C1 methodology)

**anatomy_1000** — 6 contradicted entities traced (all that were available; fewer
than the 20-sample target, reported as such rather than padded):

| entity | mined target class | indicted constraint | entity's REAL Wikidata type(s) |
|---|---|---|---|
| wd:Q788 | wd:Q2507626 | `mined.anatomy.rng.P206.Q2507626` | **ocean** |
| wd:Q98 | wd:Q2507626 | `mined.anatomy.rng.P206.Q2507626` | **ocean** |
| wd:Q1074185 | wd:Q82794 | `mined.anatomy.dom.P131.Q82794` | website, prefectural government, local government |
| wd:Q117351898 | wd:Q82794 | `mined.anatomy.type.P17_P527.Q82794` | legal form |
| wd:Q1345738 | wd:Q7048977 | `mined.anatomy.dom.P527.Q7048977` | biological process |
| wd:Q2038676 | wd:Q5127848 | `mined.anatomy.type.P361_P527.Q5127848` | **anatomical structure** |

Two entities are ANATOMY SLICE items that live Wikidata types as literal
**oceans** — `mined.anatomy.rng.P206.Q2507626` is indicted directly: `wdt:P206`
("located in or next to body of water") is a geography predicate the anatomy
slice's frontier BFS swept up, and the miner, with no domain awareness, dutifully
built a rule from it. This is the *exact same cross-domain predicate-reuse
pattern* C1's RC1 trace found for `wdt:P361` in the hand-curated pipeline — found
here independently, by a different predicate, with no human pointing at it. Two
more (`Q82794`-targeting rules) trace to administrative/government entities via
`wdt:P131` — the same signature. One case (`wd:Q2038676`) is a **false
contradiction**: the entity really is an "anatomical structure," it just doesn't
`P279*`-chain to the specific (and, per E1's labeling, fairly generic) class
`wd:Q5127848` the miner happened to select — this is E1's "vacuous class
selection" problem manifesting as a wrong indictment, not a real error in the
underlying data.

**medication_1000** — 12 contradicted entities traced:

| indicted constraint | count | pattern in REAL types |
|---|---|---|
| `mined.medication.rng.P2175.Q112193867` ("type of disease") | 6 | mixed: some genuinely symptom-typed (`symptom type`, `symptom or sign` ×2), one disease-quality-flag artifact (`Wikimedia permanent duplicate item`), one arguably-adjacent (`arthropathy`) |
| `mined.medication.rng.P2176.Q16889133` ("class" — generic) | 4 | **3 of 4 are real, correctly-typed medications** (`medication`/`biopharmaceutical`, `medication`/`mixture`/`low molecular weight heparin` ×2) — false contradictions, same vacuous-class-selection artifact as anatomy's Q5127848 case |
| `mined.medication.rng.P769.Q16889133` ("class" — generic) | 2 | one real medication (false contradiction again), one genuinely different category (`chemical element`) |

The `Q112193867` trace is the most informative single result in this experiment:
`wdt:P2175` ("medical condition treated") points to a **mix of diseases and
symptoms** in the real data — exactly the reason `docs/constraints_v2.md`
documents for *deliberately excluding* `wd:Q112965645` ("symptom or sign") from
C1's disease meta-class widening ("a symptom is not a disease, folding it in
would misclassify symptoms as diseases"). That was a design decision made from
the RC-shape trace's evidence; **E2's independent live trace reproduces the same
underlying data pattern from a completely different constraint set (mined, not
hand-curated)** — real, converging confirmation that the symptom/disease
conflation in `P2175`'s target population is a genuine property of the KG, not an
artifact of either constraint-authoring process.

The `Q16889133` rows show the *inverse* of E1's earlier concern: not every
contradiction against a generic class is a genuine error. 3 of 6 entities
indicted through generic-class rules are, per their real Wikidata typing, exactly
what the mined rule said they should roughly be (medications) — contradicted only
because the miner picked an uninformatively broad ancestor rather than a specific
one. **A meaningful fraction of "contradicted" in this experiment is attributable
to class-selection noise, not to the antecedent being wrong** — the RC1/RC2
distinction C1 had to draw by hand for the hand-curated pipeline has a close
mining-side analogue: contradictions here split between genuine off-domain
antecedent contamination (the oceans), genuine data-idiom conflation (symptom vs.
disease), and pure class-specificity artifacts of the miner itself.

## Bottom line for E2

The closed loop runs end to end without hand-curation and produces genuinely
interpretable output: report-first caps correctly gate both repairs, both repairs
attest clean (`consistent_after=True` for both cells), and the live plausibility
check surfaces real signal — including one authentic corroboration
(`mined.medication.rng.P2175.Q112193867`) and a second independent confirmation
of the symptom/disease conflation C1 already had to design around. But "mining
lands closer to v1 or v2" is the wrong frame: mined additions are *less often
wrong* than v1 by a wide margin (contradicted-fraction), *sometimes right* where
neither v1 nor v2 was (medication's one corroboration), yet introduce a failure
mode neither hand-curated arm has at all — indictments that trace back to the
miner's own arbitrary choice of an overly generic ancestor class rather than to
any defect in the underlying data. A useful automatic miner would need to fix
that third failure mode specifically, not just tune its threshold.
