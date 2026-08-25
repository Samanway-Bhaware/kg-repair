
"""
Validator (D4).

Definition-3 consistency for a containment  phi subset psi  is checked
operationally: a node x violates the constraint iff

    x in [[phi]]   and   x not in [[psi]]        i.e.   x in [[phi]] \\ [[psi]]

A graph is consistent with a constraint set R iff no constraint has any
violation. The validator returns a structured report so the same object drives
both the CLI diagnostics and the repair engines (which only ever act on the
ptime_core violations).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Set

from .constraints.model import Constraint, ConstraintSet
from .datagraph import DataGraph
from .gxpath import Evaluator


@dataclass
class Violation:
    """One constraint's outcome on one graph: the nodes that break it.

    `witnesses` is the difference `[[phi]] \\ [[psi]]`, so an empty set means the
    constraint holds. A `boundary`-tier violation is reported and never repaired.
    """
    constraint: Constraint
    witnesses: Set[str]  # nodes in [[phi]] \ [[psi]]

    @property
    def count(self) -> int:
        return len(self.witnesses)


@dataclass
class ValidationReport:
    """The result of checking a graph against a constraint set.

    Holds one `Violation` per constraint checked, in constraint-set order. Use
    `consistent`, `failing()`, `by_tier()` and `summary()` to read it.
    """
    violations: List[Violation] = field(default_factory=list)

    @property
    def consistent(self) -> bool:
        return all(v.count == 0 for v in self.violations)

    def failing(self) -> List[Violation]:
        return [v for v in self.violations if v.count > 0]

    def total_witnesses(self) -> int:
        return sum(v.count for v in self.violations)

    def by_tier(self) -> Dict[str, int]:
        out = {"ptime_core": 0, "boundary": 0}
        for v in self.failing():
            out[v.constraint.tier] = out.get(v.constraint.tier, 0) + v.count
        return out

    def to_dict(self, witness_limit: int = 10) -> Dict:
        """Canonical JSON serialisation of a consistency check.

        The one shape any consumer of a validation run should emit, so the
        command-line interface and the viewer never drift into parallel formats.
        Constraints appear in constraint-set order and witnesses are sorted, so
        two runs over the same graph produce identical output.

        `witness_limit` bounds how many witnesses are listed per constraint;
        `witness_count` always reports the true total, and `witnesses_truncated`
        says whether the list was cut. Pass a negative limit to list them all.
        """
        constraints = []
        for v in self.violations:
            witnesses = sorted(v.witnesses)
            shown = witnesses if witness_limit < 0 else witnesses[:witness_limit]
            constraints.append({
                "cid": v.constraint.cid,
                "kind": v.constraint.kind,
                "tier": v.constraint.tier,
                "direction": v.constraint.direction,
                "witness_count": v.count,
                "witnesses": shown,
                "witnesses_truncated": len(shown) < len(witnesses),
            })
        return {
            "consistent": self.consistent,
            "by_tier": self.by_tier(),
            "total_witnesses": self.total_witnesses(),
            "failing_count": len(self.failing()),
            "constraints": constraints,
        }

    def summary(self) -> str:
        """A human-readable one-block report; `to_dict` is the machine-readable form."""
        if self.consistent:
            return "consistent: no violations"
        lines = []
        for v in self.failing():
            lines.append(
                f"  [{v.constraint.tier:10}] {v.constraint.cid:22} "
                f"{v.constraint.kind:20} -> {v.count} violation(s)"
            )
        head = (f"INCONSISTENT: {len(self.failing())} constraint(s), "
                f"{self.total_witnesses()} witness(es)")
        return head + "\n" + "\n".join(lines)


class Validator:
    """Checks a graph against constraints of the form `phi subset psi`.

    Bound to one graph, and holds a live reference to it: the repair engines
    re-use a single validator while they mutate their working copy. For a
    one-shot check, `kgrepair.validate(graph, constraints)` is the shorter form.

    `use_closure` enables the evaluator's subclass-closure memoisation. It changes
    running time only; results are identical either way.
    """

    def __init__(self, graph: DataGraph, use_closure: bool = False):
        self.g = graph
        self.ev = Evaluator(graph, use_closure=use_closure)

    def check_one(self, c: Constraint) -> Violation:
        """Evaluate one constraint; witnesses are the nodes in `[[phi]] \\ [[psi]]`."""
        phi_set = self.ev.eval_node(c.phi)
        psi_set = self.ev.eval_node(c.psi)
        return Violation(constraint=c, witnesses=phi_set - psi_set)

    def validate(self, constraints) -> ValidationReport:
        """Check every constraint in a `ConstraintSet` (or any iterable of them)."""
        cs = constraints.constraints if isinstance(constraints, ConstraintSet) else list(constraints)
        return ValidationReport(violations=[self.check_one(c) for c in cs])
