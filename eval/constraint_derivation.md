# Constraint derivation evaluation

Mined candidates from `src/kgrepair/derive.py` scored against the authored constraint sets. A mined candidate matches an authored one when the kind and predicate set agree and the class is equal (exact) or within one subclass hop (relaxed). Regenerate with `python scripts/eval_derivation.py`; guarded for byte-reproducibility by `tests/test_derive_eval.py`.

**Generator: `shapes`.** Every number below is the shape-driven sweep, pinned explicitly. Since P4d the derivation default is the two-axis search (`kgrepair.search`), which this table does not measure; the search's own evaluation is `eval/derivation_search_evaluation.md`.

Thresholds (DeriveConfig): min_support=5, min_pca_confidence=0.9, min_typed_fraction=0.5, contamination_frac=0.2.

## Overall precision / recall / F1 by domain

| domain | fixture | mined | authored (v1) | P exact v1 | R exact v1 | F1 exact v1 | P relax v1 | R relax v1 | F1 relax v1 | P relax v2 | R relax v2 | F1 relax v2 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| geography | real_wikidata_geography_1000 | 47 | 4 | 4.3% | 50.0% | 7.8% | 4.3% | 50.0% | 7.8% | 4.3% | 50.0% | 7.8% |
| taxa | real_wikidata_taxa_1000 | 4 | 3 | 50.0% | 66.7% | 57.1% | 50.0% | 66.7% | 57.1% | 50.0% | 66.7% | 57.1% |
| anatomy | real_wikidata_anatomy_1000_typed | 21 | 2 | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% |
| disease | real_wikidata_disease_1000 | 4 | 2 | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% | 25.0% | 50.0% | 33.3% |
| medication | real_wikidata_medication_1000_typed | 14 | 3 | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% | 7.1% | 33.3% | 11.8% |

## By shape, aggregated across domains (relaxed match)

| shape | mined | authored v1 | P v1 | R v1 | F1 v1 | authored v2 | P v2 | R v2 | F1 v2 |
|---|---|---|---|---|---|---|---|---|---|
| existential_domain | 13 | 5 | 7.7% | 20.0% | 11.1% | 5 | 15.4% | 40.0% | 22.2% |
| existential_range | 17 | 4 | 11.8% | 50.0% | 19.0% | 4 | 17.6% | 75.0% | 28.6% |
| typing_existence | 15 | 1 | 0.0% | 0.0% | 0.0% | 1 | 0.0% | 0.0% | 0.0% |
| requires_statement | 45 | 4 | 2.2% | 25.0% | 4.1% | 4 | 2.2% | 25.0% | 4.1% |

## Reading these numbers
Recall is which authored constraints the profiler rediscovers; precision is how many mined candidates correspond to an authored one. Low precision on requires_statement is expected and is flagged low_trust in the approval report: a missing edge is the very violation the repair engine exists to fix, so profiling cannot tell a real requirement from an incidental one. The relaxed column credits a class chosen one subclass hop away from the authored class, which is where class-granularity selection lands most of its near-misses.

