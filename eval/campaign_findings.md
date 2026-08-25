# Findings by domain

What repair did in each domain, and anything the numbers show that the constraint set did not anticipate.

## anatomy

| slice | engine | constraint set | core before | core after | edges removed | edges added | outcome |
|---|---|---|---|---|---|---|---|
| real_wikidata_anatomy_1000 | subset | anatomy@wikidata.v2 | 19 | 0 | 53 | 0 | completed |
| real_wikidata_anatomy_1000 | superset | anatomy@wikidata.v2 | 19 | 0 | 0 | 21 | completed |
| real_wikidata_anatomy_1000_typed | subset | anatomy@wikidata.v2 | 10 | 0 | 63 | 0 | completed |
| real_wikidata_anatomy_1000_typed | superset | anatomy@wikidata.v2 | 10 | 0 | 0 | 10 | completed |

## disease

| slice | engine | constraint set | core before | core after | edges removed | edges added | outcome |
|---|---|---|---|---|---|---|---|
| real_wikidata_disease_1000 | subset | disease@wikidata.v2 | 6 | 6 | 0 | 0 | completed |
| real_wikidata_disease_1000 | superset | disease@wikidata.v2 | 6 | 0 | 0 | 6 | completed |

## geography

| slice | engine | constraint set | core before | core after | edges removed | edges added | outcome |
|---|---|---|---|---|---|---|---|
| real_dbpedia_geography_1000 | subset | geography@dbpedia | 2 | 0 | 5 | 0 | completed |
| real_dbpedia_geography_1000 | superset | geography@dbpedia | 2 | 0 | 0 | 2 | completed |
| real_wikidata_geography_10000 | subset | geography@wikidata | 1586 | not run | 0 | 0 | ABORTED-BY-CAP |
| real_wikidata_geography_10000 | superset | geography@wikidata | 1586 | 0 | 0 | 1586 | completed |
| real_wikidata_geography_1000 | subset | geography@wikidata | 67 | 0 | 959 | 0 | completed |
| real_wikidata_geography_1000 | superset | geography@wikidata | 67 | 0 | 0 | 67 | completed |

## medication

| slice | engine | constraint set | core before | core after | edges removed | edges added | outcome |
|---|---|---|---|---|---|---|---|
| real_wikidata_medication_1000 | subset | medication@wikidata.v2 | 129 | 9 | 210 | 0 | completed |
| real_wikidata_medication_1000 | superset | medication@wikidata.v2 | 129 | 0 | 0 | 130 | completed |
| real_wikidata_medication_1000_typed | subset | medication@wikidata.v2 | 370 | 360 | 108 | 0 | completed |
| real_wikidata_medication_1000_typed | superset | medication@wikidata.v2 | 370 | 0 | 0 | 370 | completed |

## taxa

| slice | engine | constraint set | core before | core after | edges removed | edges added | outcome |
|---|---|---|---|---|---|---|---|
| real_wikidata_taxa_10000 | subset | taxa@wikidata | 15 | 3 | 28 | 0 | completed |
| real_wikidata_taxa_10000 | superset | taxa@wikidata | 15 | 0 | 0 | 26 | completed |
| real_wikidata_taxa_1000 | subset | taxa@wikidata | 15 | 3 | 28 | 0 | completed |
| real_wikidata_taxa_1000 | superset | taxa@wikidata | 15 | 0 | 0 | 26 | completed |
| real_yago_taxa_10000 | subset | taxa@yago[partial] | 0 | 0 | 0 | 0 | completed |
| real_yago_taxa_10000 | superset | taxa@yago[partial] | 0 | 0 | 0 | 0 | completed |
| real_yago_taxa_1000 | subset | taxa@yago[partial] | 0 | 0 | 0 | 0 | completed |
| real_yago_taxa_1000 | superset | taxa@yago[partial] | 0 | 0 | 0 | 0 | completed |

