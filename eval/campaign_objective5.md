# Objective 5: quality metrics, original against repaired
Definitions in `docs/quality_metrics.md`. Every cell that ran is shown before and after; a cap-aborted cell has no after and says so. `unscored` is a real outcome, not a missing value: after subset repair the antecedents can stop matching anything, and a rule about nothing is unjudged.

## subset repair
| slice | outcome | nodes | edges | typed fraction | property coverage | satisfaction | redundant types | classes | rounds |
|---|---|---|---|---|---|---|---|---|---|
| real_dbpedia_geography_1000 |  | 108 to 106 | 1000 to 995 | 0.7870 to 0.8019 | 0.7551 to 0.6742 | 0.9615 to 1.0000 | 266 to 266 | 29 to 29 | 2 |
| real_wikidata_anatomy_1000 |  | 503 to 484 | 1000 to 947 | 0.2903 to 0.2955 | 0.5759 to 0.5360 | 0.7067 to 1.0000 | 6 to 6 | 85 to 81 | 2 |
| real_wikidata_anatomy_1000_typed |  | 1538 to 1528 | 4180 to 4117 | 0.6372 to 0.6381 | 0.1687 to 0.1631 | 0.8523 to 1.0000 | 118 to 118 | 395 to 391 | 2 |
| real_wikidata_disease_1000 |  | 664 to 664 | 1000 to 1000 | 0.0934 to 0.0934 | 0.3676 to 0.3676 | 0.8125 to 0.8125 | 3 to 3 | 31 to 31 | 1 |
| real_wikidata_geography_10000 | ABORTED-BY-CAP |  |  |  |  |  |  |  |  |
| real_wikidata_geography_1000 |  | 725 to 675 | 1000 to 41 | 0.0579 to 0.0015 | 0.7805 to unscored | 0.4988 to unscored | 0 to 0 | 86 to 5 | 2 |
| real_wikidata_medication_1000 |  | 653 to 533 | 1000 to 790 | 0.0628 to 0.0732 | 0.5806 to 0.5385 | 0.4147 to 0.7500 | 0 to 0 | 35 to 31 | 2 |
| real_wikidata_medication_1000_typed |  | 2862 to 2852 | 8100 to 7992 | 0.7687 to 0.7700 | 0.0202 to 0.0201 | 0.6436 to 0.6694 | 116 to 114 | 436 to 431 | 2 |
| real_wikidata_taxa_10000 |  | 3612 to 3600 | 10000 to 9972 | 0.3070 to 0.3078 | 0.5697 to 0.5694 | 0.8388 to 0.9688 | 27 to 27 | 332 to 330 | 2 |
| real_wikidata_taxa_1000 |  | 570 to 558 | 1000 to 972 | 0.2947 to 0.2993 | 0.5225 to 0.5155 | 0.8388 to 0.9688 | 7 to 7 | 70 to 68 | 2 |
| real_yago_taxa_10000 |  | 5475 to 5475 | 10000 to 10000 | 0.9131 to 0.9131 | 1.0000 to 1.0000 | 1.0000 to 1.0000 | 0 to 0 | 1 to 1 | 1 |
| real_yago_taxa_1000 |  | 515 to 515 | 1000 to 1000 | 0.9709 to 0.9709 | 1.0000 to 1.0000 | 1.0000 to 1.0000 | 0 to 0 | 1 to 1 | 1 |

## superset repair
| slice | outcome | nodes | edges | typed fraction | property coverage | satisfaction | redundant types | classes | rounds |
|---|---|---|---|---|---|---|---|---|---|
| real_dbpedia_geography_1000 |  | 108 to 108 | 1000 to 1002 | 0.7870 to 0.8056 | 0.7551 to 0.7551 | 0.9615 to 1.0000 | 266 to 266 | 29 to 29 | 2 |
| real_wikidata_anatomy_1000 |  | 503 to 503 | 1000 to 1021 | 0.2903 to 0.3280 | 0.5759 to 0.5207 | 0.7067 to 1.0000 | 6 to 6 | 85 to 85 | 3 |
| real_wikidata_anatomy_1000_typed |  | 1538 to 1538 | 4180 to 4190 | 0.6372 to 0.6411 | 0.1687 to 0.1686 | 0.8523 to 1.0000 | 118 to 118 | 395 to 395 | 2 |
| real_wikidata_disease_1000 |  | 664 to 665 | 1000 to 1006 | 0.0934 to 0.0932 | 0.3676 to 0.3942 | 0.8125 to 1.0000 | 3 to 3 | 31 to 31 | 2 |
| real_wikidata_geography_10000 |  | 3707 to 3707 | 10000 to 11586 | 0.2336 to 0.2471 | 0.7100 to 0.5153 | 0.4165 to 1.0000 | 52 to 52 | 275 to 275 | 2 |
| real_wikidata_geography_1000 |  | 725 to 726 | 1000 to 1067 | 0.0579 to 0.0702 | 0.7805 to 0.7108 | 0.4988 to 1.0000 | 0 to 0 | 86 to 87 | 2 |
| real_wikidata_medication_1000 |  | 653 to 655 | 1000 to 1130 | 0.0628 to 0.2427 | 0.5806 to 0.1982 | 0.4147 to 1.0000 | 0 to 0 | 35 to 37 | 3 |
| real_wikidata_medication_1000_typed |  | 2862 to 2863 | 8100 to 8470 | 0.7687 to 0.7705 | 0.0202 to 0.1087 | 0.6436 to 1.0000 | 116 to 116 | 436 to 436 | 2 |
| real_wikidata_taxa_10000 |  | 3612 to 3613 | 10000 to 10026 | 0.3070 to 0.3100 | 0.5697 to 0.5664 | 0.8388 to 1.0000 | 27 to 27 | 332 to 332 | 3 |
| real_wikidata_taxa_1000 |  | 570 to 571 | 1000 to 1026 | 0.2947 to 0.3135 | 0.5225 to 0.4920 | 0.8388 to 1.0000 | 7 to 7 | 70 to 70 | 3 |
| real_yago_taxa_10000 |  | 5475 to 5475 | 10000 to 10000 | 0.9131 to 0.9131 | 1.0000 to 1.0000 | 1.0000 to 1.0000 | 0 to 0 | 1 to 1 | 1 |
| real_yago_taxa_1000 |  | 515 to 515 | 1000 to 1000 | 0.9709 to 0.9709 | 1.0000 to 1.0000 | 1.0000 to 1.0000 | 0 to 0 | 1 to 1 | 1 |
