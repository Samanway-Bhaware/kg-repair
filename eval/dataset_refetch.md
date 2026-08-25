# Dataset refetch: cache generation B
Produced by `python scripts/build_dataset_refetch.py` from the artifacts of P8a. Every number below is a measurement of the corpus, taken with no engine running: this phase fetched and sliced, and validated in one place to express the drift, and did nothing else.
## What was fetched, and where it went
Generation B is written to `data/raw_genB/<domain>/`, a separate cache root. Generation A lives under `data/raw/` and a fetch into it would add segments and move its generation hash, which is what happened to anatomy and medication during the D6 typing closure. Keeping the roots apart is what lets generation A stay readable and its recorded hash stay meaningful.
Seeds are held constant across the two generations. Wikidata and DBpedia seeds are a written-down constant (`extract.SEEDS`). YAGO seeds are derived from the cache backbone, so they are pinned instead: `fixtures/real/pinned_seeds.json` records the 6551 taxa seeds cache generation f03b0e645fa0fa7c produced, and they are read back verbatim. The allow-list is unchanged. So is the slicing ordering. A difference between the generations is therefore a difference in what the source returned.
## Per-cell ceiling
Probed at `target_edges=50000` with a request budget of 400. `sparql_extract` over-fetches by 1.5x, so the target cap fires at 75000 cached edges.
| cell | allow-listed edges | stopped by | requests | nodes queried | frontier left | seconds |
|---|---|---|---|---|---|---|
| dbpedia:geography | 751 | frontier exhausted | 3 | 69 | 0 | 22 |
| wikidata:anatomy | 75003 | target cap | 192 | 7654 | 8600 | 404 |
| wikidata:disease | 75312 | target cap | 223 | 8819 | 10250 | 596 |
| wikidata:geography | 75366 | target cap | 189 | 7560 | 8013 | 373 |
| wikidata:medication | 75225 | target cap | 190 | 7572 | 9074 | 585 |
| wikidata:taxa | 75290 | target cap | 226 | 9020 | 11612 | 819 |
`stopped by` is measured rather than inferred: a node that entered the cache and was never queried as a subject is frontier the walk did not reach, so `frontier left` at zero is an exhausted cell and a positive value with the target cap reached is a cell with more to give.
## What the allow-list admits
A ceiling measured through the allow-list is a ceiling on allow-listed structure, not on the source graph. These counts say which. For a sample of the nodes actually queried, the endpoint was asked for counts grouped by predicate over the source's predicate universe; the allow-listed and dropped halves are split locally. Only predicate identifiers and integers were returned, so no object value entered the process at all, which is stricter than the fetch path.
| cell | nodes sampled | triples in universe | allow-listed | dropped | dropped fraction | predicates admitted |
|---|---|---|---|---|---|---|
| dbpedia:geography | 40 | 33088 | 610 | 32478 | 0.9816 | 3 of 151 |
| wikidata:anatomy | 40 | 1899 | 413 | 1486 | 0.7825 | 10 of 328 |
| wikidata:disease | 40 | 2296 | 358 | 1938 | 0.8441 | 13 of 415 |
| wikidata:geography | 40 | 1750 | 382 | 1368 | 0.7817 | 11 of 258 |
| wikidata:medication | 40 | 2145 | 413 | 1732 | 0.8075 | 11 of 293 |
| wikidata:taxa | 40 | 1637 | 352 | 1285 | 0.785 | 11 of 298 |
The predicate universe is the direct-property namespace for Wikidata, which is the namespace the allow-list draws from, and every triple with an IRI object for DBpedia.
* dbpedia:geography drops most in `dbo:subdivision` 148, `dbo:wikiPageExternalLink` 363, `dbo:wikiPageWikiLink` 22344, `http://dbpedia.org/property/leaderName` 50, `http://dbpedia.org/property/leaderTitle` 51.
* wikidata:anatomy drops most in `wdt:P1082` 30, `wdt:P1313` 26, `wdt:P1448` 32, `wdt:P150` 68, `wdt:P1566` 26.
* wikidata:disease drops most in `wdt:P1082` 26, `wdt:P1343` 58, `wdt:P1448` 26, `wdt:P150` 179, `wdt:P1549` 30.
* wikidata:geography drops most in `wdt:P1082` 31, `wdt:P1313` 28, `wdt:P1448` 31, `wdt:P1566` 30, `wdt:P18` 32.
* wikidata:medication drops most in `wdt:P1082` 36, `wdt:P1313` 32, `wdt:P1448` 36, `wdt:P150` 40, `wdt:P1566` 38.
* wikidata:taxa drops most in `wdt:P1082` 30, `wdt:P1448` 20, `wdt:P150` 150, `wdt:P1566` 22, `wdt:P18` 24.

## The generation B ladder
One fetch per cell, every rung sliced out of it. Slicing is a pure function of the cache and the parameters and its ordering does not read `target_edges`, so rungs cut from one generation nest. A rung shorter than its target is the cache exhausted, and the ladder stops there rather than writing the same edge set under more names.
| cell | generation B hash | ceiling (edges) | rungs served | seeds pinned | rungs nesting |
|---|---|---|---|---|---|
| dbpedia:geography | 83b5cf1470ef610e | 751 | 100 | no | all |
| wikidata:anatomy | d1acd9ae9b8189de | 75003 | 100, 1000, 5000, 10000, 20000, 50000 | no | all |
| wikidata:disease | 7c8e6a126de6b1d7 | 75099 | 100, 1000, 5000, 10000, 20000, 50000 | no | all |
| wikidata:geography | 63032a1aa6c91ace | 75366 | 100, 1000, 5000, 10000, 20000, 50000 | no | all |
| wikidata:medication | 8439b27c5d7f175a | 75220 | 100, 1000, 5000, 10000, 20000, 50000 | no | all |
| wikidata:taxa | 8045ecf95e864794 | 75267 | 100, 1000, 5000, 10000, 20000, 50000 | no | all |
`rungs nesting` reads `all` when every rung is contained in the one above it, checked while the ladder was built and again by `tests/test_slice_nesting.py`.
## Generation A against generation B
At the 1000-edge rung, the one rung both generations carry. Validation only.
| cell | E in A | E in B | only in A | only in B | Jaccard | violations A | violations B |
|---|---|---|---|---|---|---|---|
| dbpedia:geography | 1000 | 751 | 273 | 24 | 0.71 | 2 | 0 |
| wikidata:anatomy | 1000 | 1000 | 128 | 128 | 0.773 | 50 | 48 |
| wikidata:disease | 1000 | 1000 | 47 | 47 | 0.9102 | 6 | 6 |
| wikidata:geography | 1000 | 1000 | 39 | 39 | 0.9249 | 101 | 106 |
| wikidata:medication | 1000 | 1000 | 21 | 21 | 0.9589 | 130 | 131 |
| wikidata:taxa | 1000 | 1000 | 64 | 64 | 0.8797 | 15 | 15 |
Violation counts are `Validator` output over the constraint set the evaluation chapter reads, v2 where the domain has one. They are reported so the drift is expressed in the terms the campaign uses; no repair was run to produce them.
* wikidata:geography label set moved: gained ['wdt:P279'], lost nothing.

## Generation A hashes, for the record
| cell | generation A hash (as recorded in the manifest) |
|---|---|
| dbpedia:geography | 296ed37c1208f72d |
| wikidata:anatomy | 945c14f78dccfaf4 |
| wikidata:disease | 3085978bd6b5d403 |
| wikidata:geography | b5517c8202f32a08 |
| wikidata:medication | 4f8e94a01745a755 |
| wikidata:taxa | 3a0100e11766b685 |
| yago:taxa | f03b0e645fa0fa7c |
Two of these no longer match the cache on disk: the anatomy and medication caches gained segments during the D6 typing closure, which moved their generation hash after the 1000-edge slices had been written. The committed slices and manifests are unchanged, and they are what generation A means here.
