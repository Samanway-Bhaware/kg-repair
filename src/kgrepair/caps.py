"""
Safety caps: decide whether a repair is worth running before running it.

Neither `subset_repair` nor `superset_repair` takes a cap parameter, and neither
result carries a cap outcome. The project's convention, established by
`bench/real_ladder.py` and `bench/real_superset.py` and followed by the viewer,
is a report-first pre-check in the RUNNER layer: measure what fraction of the
graph a repair would touch, and if it exceeds the cap, do not call the engine at
all and record the run as `ABORTED-BY-CAP`.

That is a policy decision about when to act, not part of the repair semantics,
which is why it sits here rather than inside an engine. It lives in the library
rather than in one runner so that the command-line interface, the viewer, and the
bench scripts all reach the same verdict on the same graph, and so their runs stay
directly comparable with the records already in `results/runs.jsonl`.

The two fractions are measured differently, on purpose:

  * the subset measure is the UNION of eligible witnesses over the node count,
    because one deletion clears a node from every rule that flagged it at once;
  * the superset measure is the SUM of core-constraint witness counts over the
    edge count, because each witness needs its own addition regardless of how
    many rules flagged it.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple

from .datagraph import DataGraph
from .repair.subset import eligible_constraints
from .repair.superset import core_constraints
from .validator import Validator

#: Deletion-fraction cap for subset repair, as used by `bench/real_ladder.py`.
SUBSET_CAP_DEFAULT = 0.20
#: Addition-fraction cap for superset repair, as used by `bench/real_superset.py`.
SUPERSET_CAP_DEFAULT = 0.30

ABORTED_BY_CAP = "ABORTED-BY-CAP"


@dataclass(frozen=True)
class CapDecision:
    """Whether a repair should run on this graph, and the measurement behind it.

    `aborted` is True when `fraction` exceeds `cap`, in which case the caller
    should report `ABORTED-BY-CAP` and not call the engine. `witness_count` and
    `denominator` are the raw terms of the fraction, kept so a report can show the
    measurement rather than just the verdict.
    """
    mode: str                 # "subset" | "superset"
    fraction: float
    cap: float
    witness_count: int
    denominator: int          # node count for subset, edge count for superset
    aborted: bool

    @property
    def status(self) -> str:
        """`ABORTED-BY-CAP` when the cap tripped, `OK` otherwise."""
        return ABORTED_BY_CAP if self.aborted else "OK"

    def to_dict(self) -> dict:
        """Deterministic serialisation for a run report."""
        return {
            "mode": self.mode,
            "status": self.status,
            "aborted": self.aborted,
            "cap": self.cap,
            "fraction": round(self.fraction, 6),
            "witness_count": self.witness_count,
            "denominator": self.denominator,
        }


def subset_witness_fraction(graph: DataGraph, cs) -> Tuple[float, int, int]:
    """(fraction, witness_count, node_count) for subset repair.

    The union of eligible (ptime_core/subset) witnesses over the node count, which
    is what a subset repair would delete in its first round.
    """
    validator = Validator(graph, use_closure=True)
    witnesses = set()
    for c in eligible_constraints(cs):
        witnesses |= validator.check_one(c).witnesses
    n = len(graph.nodes)
    return len(witnesses) / max(1, n), len(witnesses), n


def superset_addition_fraction(graph: DataGraph, cs) -> Tuple[float, int, int]:
    """(fraction, witness_count, edge_count) for superset repair.

    The sum of core-constraint witness counts over the edge count, which is the
    number of additions a superset repair would plan.
    """
    validator = Validator(graph, use_closure=True)
    total = sum(len(validator.check_one(c).witnesses) for c in core_constraints(cs))
    e = graph.num_edges()
    return total / max(1, e), total, e


def check_cap(graph: DataGraph, cs, mode: str, cap: float = None) -> CapDecision:
    """Measure the repair fraction for `mode` and decide whether to proceed.

    `mode` is "subset" or "superset"; `cap` defaults to that mode's project
    default. Call this before the engine and skip the engine when
    `decision.aborted` is True.
    """
    if mode == "subset":
        cap = SUBSET_CAP_DEFAULT if cap is None else cap
        fraction, count, denom = subset_witness_fraction(graph, cs)
    elif mode == "superset":
        cap = SUPERSET_CAP_DEFAULT if cap is None else cap
        fraction, count, denom = superset_addition_fraction(graph, cs)
    else:
        raise ValueError(f"unknown repair mode {mode!r}")
    return CapDecision(mode=mode, fraction=fraction, cap=cap, witness_count=count,
                       denominator=denom, aborted=fraction > cap)
