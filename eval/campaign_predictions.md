# P9/T3: the predictions of P8b, tested
The P8b predictions committed to a direction for each metric under each engine before the campaign ran, including three corrected after a single uncapped run falsified them. This is the verdict. A prediction is scored per cell; `unscored` means the metric was not defined on one side and is reported as its own category rather than dropped.
| prediction | engine | held | failed | unscored | no change | note |
|---|---|---|---|---|---|---|
| ptime_core violations go to 0, as P8b stated it | subset | 6 | 5 | 0 | 0 |  |
| the ptime_core constraints this engine is routed to go to 0 | subset | 9 | 0 | 2 | 0 |  |
| the ptime_core constraints this engine is routed to go to 0 | superset | 12 | 0 | 0 | 0 |  |
| ptime_core violations go to 0, as P8b stated it | superset | 12 | 0 | 0 | 0 |  |
| boundary violations stay flat or fall | subset | 11 | 0 | 0 | 0 |  |
| boundary violations may rise: reported as movement, not as a verdict | superset | rose 0 | fell 0 | 0 | flat 12 | observed |
| typed node fraction falls (corrected in P8b after a falsification) | subset | 1 | 7 | 0 | 3 |  |
| typed node fraction rises | superset | 9 | 1 | 0 | 2 |  |
| property coverage rises or stays flat, or goes unscored (corrected) | subset | 10 | 0 | 1 | 0 |  |
| property coverage falls | superset | 7 | 3 | 0 | 2 |  |
| satisfaction reaches 1.0, or goes unscored (corrected) | subset | 5 | 5 | 1 | 0 |  |
| satisfaction reaches 1.0 | superset | 12 | 0 | 0 | 0 |  |
| node count falls | subset | 11 | 0 | 0 | 0 |  |
| node count rises or stays flat | superset | 12 | 0 | 0 | 0 | weak |
| edge count falls | subset | 8 | 0 | 0 | 3 |  |
| edge count rises | superset | 10 | 0 | 0 | 2 |  |
| redundant type edges fall | subset | 11 | 0 | 0 | 0 |  |
| redundant type edges stay flat, they do not rise | superset | 12 | 0 | 0 | 0 |  |

A `weak` prediction is one stated permissively in P8b ("may rise", "rises or stays flat"). A direction test cannot falsify it, so it is scored on the complementary claim and flagged. Do not read its `held` as confirmation.

## Splits worth reading

### ptime_core violations go to 0, as P8b stated it (subset)
| cell | before | after | verdict |
|---|---|---|---|
| wikidata:geography:1000:subset | 67 | 0 | held |
| wikidata:taxa:1000:subset | 15 | 3 | failed |
| wikidata:taxa:10000:subset | 15 | 3 | failed |
| wikidata:anatomy:1000:subset | 19 | 0 | held |
| wikidata:anatomy:1000:typed:subset | 10 | 0 | held |
| wikidata:disease:1000:subset | 6 | 6 | failed |
| wikidata:medication:1000:subset | 129 | 9 | failed |
| wikidata:medication:1000:typed:subset | 370 | 360 | failed |
| dbpedia:geography:1000:subset | 2 | 0 | held |
| yago:taxa:1000:subset | 0 | 0 | held |
| yago:taxa:10000:subset | 0 | 0 | held |

### the ptime_core constraints this engine is routed to go to 0 (subset)
| cell | before | after | verdict |
|---|---|---|---|
| wikidata:geography:1000:subset | 50 | 0 | held |
| wikidata:taxa:1000:subset | 12 | 0 | held |
| wikidata:taxa:10000:subset | 12 | 0 | held |
| wikidata:anatomy:1000:subset | 19 | 0 | held |
| wikidata:anatomy:1000:typed:subset | 10 | 0 | held |
| wikidata:disease:1000:subset | 0 | 0 | held |
| wikidata:medication:1000:subset | 120 | 0 | held |
| wikidata:medication:1000:typed:subset | 10 | 0 | held |
| dbpedia:geography:1000:subset | 2 | 0 | held |
| yago:taxa:1000:subset | unscored | unscored | unscored |
| yago:taxa:10000:subset | unscored | unscored | unscored |

### typed node fraction falls (corrected in P8b after a falsification) (subset)
| cell | before | after | verdict |
|---|---|---|---|
| wikidata:geography:1000:subset | 0.0579 | 0.0015 | held |
| wikidata:taxa:1000:subset | 0.2947 | 0.2993 | failed |
| wikidata:taxa:10000:subset | 0.3070 | 0.3078 | failed |
| wikidata:anatomy:1000:subset | 0.2903 | 0.2955 | failed |
| wikidata:anatomy:1000:typed:subset | 0.6372 | 0.6381 | failed |
| wikidata:disease:1000:subset | 0.0934 | 0.0934 | no change |
| wikidata:medication:1000:subset | 0.0628 | 0.0732 | failed |
| wikidata:medication:1000:typed:subset | 0.7687 | 0.7700 | failed |
| dbpedia:geography:1000:subset | 0.7870 | 0.8019 | failed |
| yago:taxa:1000:subset | 0.9709 | 0.9709 | no change |
| yago:taxa:10000:subset | 0.9131 | 0.9131 | no change |

### typed node fraction rises (superset)
| cell | before | after | verdict |
|---|---|---|---|
| wikidata:geography:1000:superset | 0.0579 | 0.0702 | held |
| wikidata:geography:10000:superset | 0.2336 | 0.2471 | held |
| wikidata:taxa:1000:superset | 0.2947 | 0.3135 | held |
| wikidata:taxa:10000:superset | 0.3070 | 0.3100 | held |
| wikidata:anatomy:1000:superset | 0.2903 | 0.3280 | held |
| wikidata:anatomy:1000:typed:superset | 0.6372 | 0.6411 | held |
| wikidata:disease:1000:superset | 0.0934 | 0.0932 | failed |
| wikidata:medication:1000:superset | 0.0628 | 0.2427 | held |
| wikidata:medication:1000:typed:superset | 0.7687 | 0.7705 | held |
| dbpedia:geography:1000:superset | 0.7870 | 0.8056 | held |
| yago:taxa:1000:superset | 0.9709 | 0.9709 | no change |
| yago:taxa:10000:superset | 0.9131 | 0.9131 | no change |

### property coverage rises or stays flat, or goes unscored (corrected) (subset)
| cell | before | after | verdict |
|---|---|---|---|
| wikidata:geography:1000:subset | 0.7805 | unscored | unscored |
| wikidata:taxa:1000:subset | 0.5225 | 0.5155 | held |
| wikidata:taxa:10000:subset | 0.5697 | 0.5694 | held |
| wikidata:anatomy:1000:subset | 0.5759 | 0.5360 | held |
| wikidata:anatomy:1000:typed:subset | 0.1687 | 0.1631 | held |
| wikidata:disease:1000:subset | 0.3676 | 0.3676 | held |
| wikidata:medication:1000:subset | 0.5806 | 0.5385 | held |
| wikidata:medication:1000:typed:subset | 0.0202 | 0.0201 | held |
| dbpedia:geography:1000:subset | 0.7551 | 0.6742 | held |
| yago:taxa:1000:subset | 1.0000 | 1.0000 | held |
| yago:taxa:10000:subset | 1.0000 | 1.0000 | held |

### property coverage falls (superset)
| cell | before | after | verdict |
|---|---|---|---|
| wikidata:geography:1000:superset | 0.7805 | 0.7108 | held |
| wikidata:geography:10000:superset | 0.7100 | 0.5153 | held |
| wikidata:taxa:1000:superset | 0.5225 | 0.4920 | held |
| wikidata:taxa:10000:superset | 0.5697 | 0.5664 | held |
| wikidata:anatomy:1000:superset | 0.5759 | 0.5207 | held |
| wikidata:anatomy:1000:typed:superset | 0.1687 | 0.1686 | held |
| wikidata:disease:1000:superset | 0.3676 | 0.3942 | failed |
| wikidata:medication:1000:superset | 0.5806 | 0.1982 | held |
| wikidata:medication:1000:typed:superset | 0.0202 | 0.1087 | failed |
| dbpedia:geography:1000:superset | 0.7551 | 0.7551 | failed |
| yago:taxa:1000:superset | 1.0000 | 1.0000 | no change |
| yago:taxa:10000:superset | 1.0000 | 1.0000 | no change |

### satisfaction reaches 1.0, or goes unscored (corrected) (subset)
| cell | before | after | verdict |
|---|---|---|---|
| wikidata:geography:1000:subset | 0.4988 | unscored | unscored |
| wikidata:taxa:1000:subset | 0.8388 | 0.9688 | failed |
| wikidata:taxa:10000:subset | 0.8388 | 0.9688 | failed |
| wikidata:anatomy:1000:subset | 0.7067 | 1.0000 | held |
| wikidata:anatomy:1000:typed:subset | 0.8523 | 1.0000 | held |
| wikidata:disease:1000:subset | 0.8125 | 0.8125 | failed |
| wikidata:medication:1000:subset | 0.4147 | 0.7500 | failed |
| wikidata:medication:1000:typed:subset | 0.6436 | 0.6694 | failed |
| dbpedia:geography:1000:subset | 0.9615 | 1.0000 | held |
| yago:taxa:1000:subset | 1.0000 | 1.0000 | held |
| yago:taxa:10000:subset | 1.0000 | 1.0000 | held |

## Accuracy of additions
| slice | additions | status | sampled | exact agreement | class agreement | 95 percent interval (class) |
|---|---|---|---|---|---|---|
| real_dbpedia_geography_1000 | 2 | TOO-FEW-TO-SAMPLE |  |  |  |  |
| real_wikidata_anatomy_1000 | 21 | measured | 21 | 1 (0.0476) | 2 (0.0952) | 0.0265 to 0.2891 |
| real_wikidata_anatomy_1000_typed | 10 | measured | 10 | 0 (0.0) | 0 (0.0) | 0.0 to 0.2775 |
| real_wikidata_disease_1000 | 6 | TOO-FEW-TO-SAMPLE |  |  |  |  |
| real_wikidata_geography_1000 | 67 | measured | 40 | 7 (0.175) | 40 (1.0) | 0.9124 to 1.0 |
| real_wikidata_geography_10000 | 1586 | NOT-MEASURED |  |  |  |  |
| real_wikidata_medication_1000 | 130 | NOT-MEASURED |  |  |  |  |
| real_wikidata_medication_1000_typed | 370 | measured | 40 | 0 (0.0) | 0 (0.0) | 0.0 to 0.0876 |
| real_wikidata_taxa_1000 | 26 | NOT-MEASURED |  |  |  |  |
| real_wikidata_taxa_10000 | 26 | NOT-MEASURED |  |  |  |  |
| real_yago_taxa_1000 | 0 | NO-ADDITIONS |  |  |  |  |
| real_yago_taxa_10000 | 0 | NO-ADDITIONS |  |  |  |  |

The two questions differ because the exact one is too strict for a typing addition. Superset repair adds `x isa C` to satisfy a class test that is itself `isa . subclass-of*`, so the source can agree while asserting only a more specific type. Class agreement is the primary measure; the exact column is kept because it is what a naive check reports, and P8b traced the D6 figure of 34.4 percent to that same bias. Sampling is a fixed-seed simple random sample without replacement over the deduplicated addition set, and a cell with too few additions to quote a proportion says so instead of quoting one.
