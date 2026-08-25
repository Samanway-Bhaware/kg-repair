"""
Constraint-mining (CM) sprint -- one-week, time-boxed, exploratory.

Question: can Reg-GXPath_pos constraints be automatically mined from a KG slice
where hand-curation is missing? The deliverable is evidence for future work,
not a production feature -- nothing here is wired into the
CLI, the viewer, or the shipped v1/v2 constraint files (`provenance="mined"` marks
every output so it can never be mistaken for a hand-curated rule).

Modules:
  miner.py            E0 -- the baseline prevalence/co-occurrence miner.
  fragment_filter.py  reject candidates that leave Reg-GXPath_pos (E0).
  tier_classifier.py  route survivors to ptime_core/boundary by kind (E0).
  log.py              sprint-tagged JSONL log, kept OUT of results/runs.jsonl so
                      D7's evaluation tables are never touched by sprint runs.
  run_e0.py           Day-1 driver: mine all four target slices at three
                      thresholds, tabulate, write experimental/mining/results/.

See docs/ml_mining.md (written on Day 5 / E5) for the full write-up.
"""
