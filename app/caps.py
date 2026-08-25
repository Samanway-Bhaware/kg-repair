"""
V2/V3 -- cap-check constants and report-first prevalence measures.

These now live in the library, as `kgrepair.caps`, so that the command-line
interface, this viewer, and the bench scripts all reach the same verdict on the
same graph rather than each carrying a copy. This module re-exports them under
the names the viewer screens already use.

The convention itself is unchanged: neither `subset_repair` nor `superset_repair`
takes a cap parameter, so the caller measures the fraction a repair would touch
and decides whether to call the engine at all, logging `ABORTED-BY-CAP` instead
of running it when the fraction exceeds the cap. That keeps the viewer's cap
decisions directly comparable to the CLI/bench runs already in
`results/runs.jsonl`.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from kgrepair import (SUBSET_CAP_DEFAULT, SUPERSET_CAP_DEFAULT, check_cap,
                      subset_witness_fraction, superset_addition_fraction)

__all__ = ["SUBSET_CAP_DEFAULT", "SUPERSET_CAP_DEFAULT", "check_cap",
           "subset_witness_fraction", "superset_addition_fraction"]
