"""
E0 -- fragment filter: does a mined candidate survive as a Reg-GXPath_pos
containment? Answered by the REAL parser (`kgrepair.gxpath.parse_node`), not by
inspecting the candidate's `kind` -- a miner that starts emitting negation,
upper-bound cardinality, or universal quantification (none of E0's shapes do, by
construction; a future stretch miner might) is caught here, and the reject count
is itself a finding ("mined-but-inexpressible"), not a silent drop.
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from typing import List, Optional, Tuple

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

from kgrepair import gxpath          # noqa: E402
from kgrepair.gxpath import ParseError  # noqa: E402


@dataclass
class FilterResult:
    passed: bool
    reason: Optional[str] = None


def check_fragment(antecedent: str, consequent: str) -> FilterResult:
    try:
        gxpath.parse_node(antecedent)
    except ParseError as e:
        return FilterResult(False, f"antecedent leaves the fragment: {e}")
    try:
        gxpath.parse_node(consequent)
    except ParseError as e:
        return FilterResult(False, f"consequent leaves the fragment: {e}")
    return FilterResult(True)


def filter_candidates(candidates: List) -> Tuple[List, List[Tuple[object, str]]]:
    """(survivors, [(rejected_candidate, reason), ...]) -- candidates are anything
    with .antecedent/.consequent attributes (Candidate dataclass)."""
    survivors, rejected = [], []
    for cand in candidates:
        result = check_fragment(cand.antecedent, cand.consequent)
        if result.passed:
            survivors.append(cand)
        else:
            rejected.append((cand, result.reason))
    return survivors, rejected
