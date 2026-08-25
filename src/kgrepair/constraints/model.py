"""
Constraint model.

A constraint is a *containment of positive node expressions*

    phi  subset-of  psi        meaning   [[phi]] subset [[psi]]

evaluated operationally as the violation set  [[phi]] \\ [[psi]].  We deliberately
keep constraints as containments rather than implications phi => psi = psi u not-phi,
because the implication form needs negation and would leave Reg-GXPath_pos.

Each constraint carries:

  * a tier:
      - "ptime_core": the antecedent/consequent are positive NODE expressions, so
        a subset repair is found in PTime (Alg. 1; the paper's Theorem 15 states it
        is the unique subset repair under its hypothesis) and a superset repair is
        found in PTime (Alg. 2; the paper's Corollary 25 states it exists when the
        value alphabet is finite). These are the only constraints the repair engines
        act on. This toolkit does not itself assert uniqueness or minimality of its
        outputs -- see docs/algorithm_fidelity.md.
      - "boundary": symmetric / inverse / functional / disjoint / cardinality
        shapes. These need negation or pair-comparison (or, as *path* constraints,
        push subset repair to NP-complete, Thm 11). They are VALIDATED and
        REPORTED only -- never auto-repaired.

  * provenance: how the rule was obtained --
      - "given"    : stated by the source KG (Wikidata P2302, YAGO SHACL, rdfs).
      - "compiled" : mechanically translated from a `given` statement.
      - "derived"  : induced from data by prevalence on a clean reference slice
                     (threshold recorded in `params`). "mined" is the same idea,
                     written by the candidate search.
      - "authored" : written down by a person in a constraint file they supplied.
                     Asserted rather than measured, which is why an authored
                     candidate file needs no review seal (see `kgrepair.review`).

  * a repair `direction` for ptime_core rules:
      - "subset"   : fix by deletion (remove the offending subject).
      - "superset" : fix by addition (materialise the missing consequent).

    NOTE (D6 reframing). `direction` is a *default preference*, not a capability
    limit. Every ptime_core constraint is `addition_fixable` (its consequent is a
    positive node expression, so it is satisfiable by addition), so SupersetRepair
    (Alg. 2) acts on all of them regardless of `direction`; SubsetRepair (Alg. 1)
    is unchanged and still keys on `direction == "subset"`. The reframing is an
    open design question.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Dict, Optional

from .. import gxpath
from ..gxpath import ast

Tier = str            # "ptime_core" | "boundary"
Provenance = str      # "given" | "compiled" | "derived"
Direction = str       # "subset" | "superset" | "report"


@dataclass
class Constraint:
    """One containment rule `antecedent subset consequent` over a data-graph.

    Both sides are Reg-GXPath_pos node expressions in the concrete syntax the
    parser accepts; they compile lazily to the cached `phi` / `psi` ASTs. `tier`
    decides whether the repair engines may act on it (`ptime_core`) or whether it
    is checked and reported only (`boundary`); see the module docstring for the
    full meaning of `tier`, `provenance` and `direction`.
    """
    cid: str
    domain: str                 # geography | taxa | anatomy | disease | medication
    kg: str                     # wikidata | dbpedia | yago
    kind: str                   # human label: typing_existence, dom_range, symmetric...
    tier: Tier
    provenance: Provenance
    direction: Direction
    # containment  phi subset psi  (concrete Reg-GXPath_pos syntax)
    antecedent: str             # phi
    consequent: str             # psi
    note: str = ""
    params: Dict[str, str] = field(default_factory=dict)
    version: int = 1             # D7/C1: 1 = original; 2 = RC1/RC2 constraint fix
                                  # (widened/narrowed class test); v1 files are never
                                  # edited, v2 lives in *_v2.py so both stay loadable.

    # compiled AST cache
    _phi: Optional[ast.Node] = field(default=None, repr=False, compare=False)
    _psi: Optional[ast.Node] = field(default=None, repr=False, compare=False)

    def compile(self) -> None:
        """Parse both sides; raises ParseError if either leaves the fragment."""
        self._phi = gxpath.parse_node(self.antecedent)
        self._psi = gxpath.parse_node(self.consequent)

    @property
    def phi(self) -> ast.Node:
        if self._phi is None:
            self.compile()
        return self._phi  # type: ignore[return-value]

    @property
    def psi(self) -> ast.Node:
        if self._psi is None:
            self.compile()
        return self._psi  # type: ignore[return-value]

    @property
    def addition_fixable(self) -> bool:
        """
        Capability: can a violation be resolved purely by ADDITION (Algorithm 2)?

        Every ptime_core constraint qualifies -- its consequent is a positive node
        expression, so it is satisfiable by adding the missing structure (a type
        edge for tau_C, an edge for an existential consequent, the required statement
        for requires-statement). Boundary constraints never qualify (report-only).

        This is orthogonal to `direction`, which is only a default repair-mode
        preference (see the class/module note): SupersetRepair acts on every
        addition_fixable constraint regardless of direction.
        """
        return self.tier == "ptime_core"

    def to_dict(self) -> Dict:
        return {
            "cid": self.cid,
            "domain": self.domain,
            "kg": self.kg,
            "kind": self.kind,
            "tier": self.tier,
            "provenance": self.provenance,
            "direction": self.direction,
            "containment": {"phi": self.antecedent, "psi": self.consequent},
            "note": self.note,
            "params": self.params,
            "version": self.version,
        }

    @staticmethod
    def from_dict(d: Dict) -> "Constraint":
        c = d.get("containment", {})
        return Constraint(
            cid=d["cid"], domain=d["domain"], kg=d["kg"], kind=d["kind"],
            tier=d["tier"], provenance=d["provenance"], direction=d["direction"],
            antecedent=c.get("phi", d.get("antecedent", "")),
            consequent=c.get("psi", d.get("consequent", "")),
            note=d.get("note", ""), params=d.get("params", {}),
            version=d.get("version", 1),          # old exports predate the field
        )


class ConstraintSet:
    """An ordered collection of constraints for one (domain, kg) slice.

    A set is portable: `to_file` / `from_file` write and read the JSON constraint-file
    format, so a user can author their own constraints for their own knowledge graph
    and hand the file straight to the validator and the repair engines. Nothing in
    that path is tied to the built-in sets in `constraints.get`.
    """

    def __init__(self, name: str, constraints: Optional[list] = None):
        self.name = name
        self.constraints: list[Constraint] = list(constraints or [])

    def add(self, c: Constraint) -> None:
        self.constraints.append(c)

    def compile_all(self) -> None:
        for c in self.constraints:
            c.compile()

    def ptime_core(self) -> list:
        return [c for c in self.constraints if c.tier == "ptime_core"]

    def boundary(self) -> list:
        return [c for c in self.constraints if c.tier == "boundary"]

    def coverage(self) -> Dict[str, int]:
        core = len(self.ptime_core())
        total = len(self.constraints)
        return {"ptime_core": core, "boundary": total - core, "total": total}

    def __iter__(self):
        return iter(self.constraints)

    def __len__(self):
        return len(self.constraints)

    # -- constraint-file serialisation --------------------------------------
    def to_dict(self) -> Dict:
        """The constraint-file payload: slice name, coverage counts, constraints.

        This is the schema `constraints.export_json` writes and `from_dict` reads.
        Ordering follows the set's own order, so the output is deterministic.
        """
        return {
            "slice": self.name,
            "coverage": self.coverage(),
            "constraints": [c.to_dict() for c in self.constraints],
        }

    @staticmethod
    def from_dict(payload: Dict) -> "ConstraintSet":
        """Rebuild a set from a `to_dict` payload. Unknown top-level keys (such as
        the `availability` field the built-in export adds) are ignored."""
        cs = ConstraintSet(payload.get("slice", "unnamed"))
        for d in payload["constraints"]:
            cs.add(Constraint.from_dict(d))
        return cs

    def to_file(self, path: str, indent: int = 2) -> str:
        """Write this set to a JSON constraint file; return the path written."""
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(self.to_dict(), fh, indent=indent, ensure_ascii=False)
        return path

    @staticmethod
    def from_file(path: str) -> "ConstraintSet":
        """Read a user-supplied JSON constraint file into a `ConstraintSet`.

        This is the entry point for constraints the user authored themselves, as
        opposed to `constraints.get(domain, kg)` which returns a built-in set. The
        expressions are parsed lazily; call `compile_all()` to reject anything that
        leaves the positive fragment up front.
        """
        with open(path, "r", encoding="utf-8") as fh:
            return ConstraintSet.from_dict(json.load(fh))
