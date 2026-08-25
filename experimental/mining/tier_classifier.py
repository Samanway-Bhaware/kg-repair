"""
E0 -- tier classifier: routes a fragment-passed candidate to ptime_core/boundary
by `kind`, exactly like the hand-curated constraint files do. Confidence never
overrides this: a symmetric/inverse/functional shape is boundary regardless of
how high its measured prevalence is (Theorem 11 does not care that a rule was
learned) -- there are no such shapes in E0's miner today, but this function is
written to hold for a future miner that proposes one, per the sprint's own
requirement.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

# kind -> (tier, default direction). Mirrors src/kgrepair/constraints/model.py's
# tier semantics exactly; direction mirrors the hand-curated convention (existing
# domain/range constraints default to "subset", typing/requires-statement rules
# default to "superset" -- D6 already treats direction as a preference, not a gate).
_PTIME_CORE_KINDS = {
    "existential_domain": "subset",
    "existential_range": "subset",
    "typing_existence": "superset",
    "typing_inheritance": "superset",
    "requires_statement": "superset",
}
_BOUNDARY_KINDS = {"symmetric", "inverse", "functional", "cardinality",
                   "disjoint", "safety_edge"}


@dataclass
class TierVerdict:
    tier: str
    direction: str
    reason: str


def classify(kind: str) -> TierVerdict:
    if kind in _PTIME_CORE_KINDS:
        return TierVerdict("ptime_core", _PTIME_CORE_KINDS[kind],
                           f"{kind} is a positive-node-expression shape both sides")
    if kind in _BOUNDARY_KINDS:
        return TierVerdict("boundary", "report",
                           f"{kind} needs negation or pair-comparison, or (symmetric) "
                           "is NP-complete as a path constraint (Thm 11) -- report-only "
                           "regardless of mined confidence")
    return TierVerdict("boundary", "report",
                       f"unrecognised kind {kind!r}: routed to boundary/report-only "
                       "as the conservative default, never auto-repaired")
