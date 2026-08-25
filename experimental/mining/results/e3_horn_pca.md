# E3 (Day 4, stretch) — PCA-confidence Horn-rule miner vs. E0's plain-prevalence miner

Shipped (E0–E2 all shipped on schedule, so the stretch day proceeded as planned,
not reallocated). Source: `experimental/mining/results/e3_horn_pca.json`,
`experimental/mining/candidates/*_hornpca_*.json`, `results/cm_sprint_runs.jsonl`
(`experiment="E3"`). Scope, per the spec: only the two rule shapes the fragment
can absorb, `p(x,y) => C(x)` and `p(x,y) => C(y)` — no `typing_existence`/
`requires_statement` here (that's E0/E1's territory); comparison is restricted to
E0's own domain/range candidates for a fair like-for-like.

## The incompleteness assumption, stated up front

E0 used the Closed-World Assumption (CWA): every entity with predicate `p` that
isn't typed `C` counts as a negative, even entities with **no type information at
all**. E3 uses AMIE's Partial Completeness Assumption (PCA) instead: an entity
only counts as a valid negative if it is already known to have *some* type (an
outgoing edge on the KG's own typing predicate). Untyped entities are dropped
from both numerator and denominator — "never stated" is treated as unknown, not
as "no." Support stays a plain cardinality count, tracked separately from
confidence.

## Comparison table — recovered count (of curated existential_domain/range
constraints, E1's own matching definition) and candidate volume, by threshold

| slice | threshold | E0 (CWA) recovered | E0 candidates | PCA recovered | PCA candidates |
|---|---|---|---|---|---|
| yago_taxa_1000 | 0.99/0.95/0.90 | 0 | 1 | 0 | 1 |
| anatomy_1000 | 0.99 | 0 | 48 | 0 | 54 |
| anatomy_1000 | 0.95 | 0 | 57 | 0 | 65 |
| anatomy_1000 | 0.90 | 0 | 65 | 0 | 71 |
| medication_1000 | 0.99 | 0 | 3 | 0 | 6 |
| medication_1000 | **0.95** | 0 | 13 | **1** | 20 |
| medication_1000 | 0.90 | 1 | 20 | 1 | 24 |
| geography_10000 | 0.99/0.95/0.90 | 0 | 0 | 0 | 0 |

**PCA candidate volume is consistently higher than CWA's at every threshold in
every slice with any candidates at all** (e.g. anatomy 65→71 at 0.90) — expected
and a good implementation sanity check: removing untyped entities from the
denominator can only raise a ratio, never lower it, so PCA confidence is always
`>=` CWA prevalence for the same `(p, C)` pair.

## PCA beats CWA exactly once, and the improvement is quantified precisely

`hornpca.medication.rng.P2175.Q112193867` (medication's object of "condition
treated" typed as C1's "type of disease" meta-class) is the one case where the
extra rigor changes the outcome, not just the number:

```
CWA (E0):  90.7% (117/129) -- misses the 95% bar
PCA (E3):  95.1% (117/123), 6 entities excluded as untyped-unknown -- clears it
```

Same 117 positive cases; the population shrank because 6 of the 129 CWA
"negatives" turned out to be entities with **zero** typing information at all,
not entities positively typed as something else. Removing them from the
denominator moved this specific, real, evidence-derived recovery from "misses
0.95" to "recovers at 0.95" — a genuine, one-threshold improvement directly
attributable to the PCA correction, not to noise.

## PCA does NOT rescue anatomy's `P361` rule — checked directly, not assumed

E1 already established `ana.wd.dom.partof`'s CWA prevalence at 12.5%. The natural
question is whether that low number was itself an incompleteness artifact PCA
would fix. Checked directly:

```
CWA population: 72 (all P361 subjects)
PCA population: 67 (P361 subjects that ALSO have some type) -- only 5 excluded
PCA confidence(P361 -> AnatomicalStructure) = 9/67 = 13.4%
```

Barely moves (12.5% → 13.4%). **This confirms E1's diagnosis was correct**: the
anatomy P361 rule's low measured prevalence is not a typing-incompleteness
artifact (which PCA would fix) — it is the RC1 off-domain-predicate-reuse
problem (P361 genuinely used for geography/administrative/finance relations in
this slice), which no incompleteness-assumption change can paper over, because
the "wrong" subjects in question mostly ARE typed (as oceans, government
entities, etc. — see E2's indictment trace), just not as anatomy. Two
E0-diagnosed defects, two different PCA outcomes: one where accounting for
incompleteness recovers a real rule, one where it correctly does nothing because
incompleteness was never the actual problem.

## Mineable-but-inexpressible inventory

2 refinements found, both over anatomy_1000, both confirmed rejected by the
**real parser** (not asserted) when actually attempted:

| antecedent attempted | consequent (class) | base confidence | + exclusion | refined confidence | fragment check |
|---|---|---|---|---|---|
| `< down(wdt:P361) > & ! < down(wdt:P17) >` | wd:Q7048977 | 91.0% (61 supp) | exclude `wdt:P17` | **93.0%** (40 supp) | rejected: node complement leaves Reg-GXPath_pos |
| `< down(wdt:P527) > & ! < down(wdt:P131) >` | wd:Q5127848 | 94.1% (48 supp) | exclude `wdt:P131` | **94.6%** (35 supp) | rejected: node complement leaves Reg-GXPath_pos |

Both are genuine "the fragment leaves confidence on the table" cases: a Horn-rule
miner one step richer than E3's own (adding a single negated exclusion atom, a
completely standard AMIE-family refinement) finds a strictly higher-confidence
rule than anything the positive fragment can express, confirmed by handing the
exact string to `gxpath.parse_node()` and watching it reject correctly rather than
assuming it would. Support drops in both cases when the exclusion is added
(61→40, 48→35) — the refinement trades recall for precision, the usual Horn-rule
specialization trade-off — but confidence genuinely improves, not just shifts
around, in both.

Only 2 out of a plausible search space of (candidate_preds × candidate classes ×
top-5 competitor predicates) turned out to both clear the base confidence floor
AND show a genuine improvement from exclusion — most (predicate, class) pairs
either don't have a competing predicate worth excluding, or excluding one drops
support below the floor. This is itself informative: negated-exclusion
refinements are a narrow, situational tool here, not a broadly available upgrade
— the two cases that DID work are, not coincidentally, both anatomy rules with
generic-root consequents (`wd:Q7048977`, `wd:Q5127848`), the exact class-choice
noise E1/E2 already flagged as this domain's dominant problem. Excluding an
off-domain competing predicate nudges those noisy rules slightly cleaner, but
does not fix their underlying vacuousness — the two problems (class specificity,
antecedent scoping) are separable and this refinement only ever touches the
second one.

## Bottom line for E3

PCA-style confidence is a real, measurable improvement over plain prevalence —
demonstrated with one precise, evidence-backed recovery gain, not asserted in
the abstract — but it is not a general fix: it only helps when the underlying
problem actually IS typing incompleteness (medication's case), and correctly
does nothing when the problem is off-domain antecedent contamination instead
(anatomy's case), which is itself a useful diagnostic signal — comparing CWA vs.
PCA confidence for the same rule is a cheap way to tell which of those two
failure modes is at play without doing a full live-Wikidata trace. The
inexpressible inventory is small (2 findings) but genuine, and quantifies
concretely what capability the positive fragment gives up in exchange for
tractability: single-atom negated exclusions that trade a modest amount of
recall for a real, measured confidence gain.
