"""
Sprint-tagged run log -- deliberately a SEPARATE file from results/runs.jsonl.

results/runs.jsonl is D7's frozen evaluation dataset; scripts/build_evaluation.py
aggregates it by (source, mode) into docs/evaluation.md's tables. Appending
sprint records there would risk exactly the kind of "unexpected mode/param shape"
bug already found once in that pipeline (see scripts/build_evaluation.py's
table_6 key() fix). Keeping the sprint's own log in
results/cm_sprint_runs.jsonl gets the same append-only, run_id-traceable
discipline without touching the D7 dataset at all.
"""
from __future__ import annotations

import json
import os
import time
import uuid
from typing import Dict

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
LOG_PATH = os.path.join(ROOT, "results", "cm_sprint_runs.jsonl")


def log_run(experiment: str, record: Dict) -> str:
    """Append one JSON record, return its run_id. `tag` is always 'cm-sprint'."""
    run_id = uuid.uuid4().hex
    full = {
        "run_id": run_id,
        "tag": "cm-sprint",
        "experiment": experiment,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        **record,
    }
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    with open(LOG_PATH, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(full, sort_keys=True) + "\n")
    return run_id
