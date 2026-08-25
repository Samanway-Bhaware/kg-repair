"""
Abstract syntax for the positive fragment Reg-GXPath_pos.

Two mutually recursive sorts:

  Path expressions  a ::= eps                      (identity)
                        | down(label)              (forward edge  down_a)
                        | up(label)                (backward edge up_a)
                        | seq(a, b)                (composition  a . b)
                        | alt(a, b)                (union        a u b)
                        | star(a)                  (Kleene star  a*)
                        | isect(a, b)              (intersection a n b)   [bounded]
                        | test(phi)                (node test    [phi])

  Node expressions  phi ::= top                    (all nodes  T)
                          | has(a)                 (exists path  <a>)
                          | veq(c)                 (data value equals constant c)
                          | conj(phi, psi)         (phi n psi)
                          | disj(phi, psi)         (phi u psi)

The fragment is *positive*: there is deliberately NO complement of a node
expression (no  not phi) and NO complement of a path (no  a-bar). Those two
constructs are what push subset repair to NP-completeness and superset repair to
undecidability (Abriola et al., Thms 12 and 19), so they are not representable
here. The parser additionally rejects them at the surface-syntax level.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple, Union


# ---- path expressions -------------------------------------------------------

@dataclass(frozen=True)
class Eps:
    """Identity path: relates every node to itself."""


@dataclass(frozen=True)
class Down:
    label: str  # down_a : one forward hop along edge label a


@dataclass(frozen=True)
class Up:
    label: str  # up_a : one backward hop along edge label a


@dataclass(frozen=True)
class Seq:
    left: "Path"
    right: "Path"


@dataclass(frozen=True)
class Alt:
    left: "Path"
    right: "Path"


@dataclass(frozen=True)
class Star:
    inner: "Path"


@dataclass(frozen=True)
class Isect:
    left: "Path"
    right: "Path"


@dataclass(frozen=True)
class Test:
    node: "Node"  # [phi] : identity restricted to nodes satisfying phi


Path = Union[Eps, Down, Up, Seq, Alt, Star, Isect, Test]


# ---- node expressions -------------------------------------------------------

@dataclass(frozen=True)
class Top:
    """T : the set of all nodes."""


@dataclass(frozen=True)
class Has:
    path: "Path"  # <a> : nodes from which some a-path departs


@dataclass(frozen=True)
class ValueEq:
    const: str  # c= : nodes whose data value equals the constant c


@dataclass(frozen=True)
class Conj:
    left: "Node"
    right: "Node"


@dataclass(frozen=True)
class Disj:
    left: "Node"
    right: "Node"


Node = Union[Top, Has, ValueEq, Conj, Disj]


# ---- convenience builders ---------------------------------------------------

def seq_all(*parts: Path) -> Path:
    """Left-fold a chain of path steps into nested Seq nodes."""
    if not parts:
        return Eps()
    acc = parts[0]
    for p in parts[1:]:
        acc = Seq(acc, p)
    return acc


def type_test(type_label: str, subclass_label: str, class_value: str) -> Node:
    """
    The core RDF type test  tau_C = < down_type . down_subClassOf* . [C=] >.

    A node x satisfies tau_C iff following one `type` edge and then zero or more
    `subClassOf` edges reaches a class node whose value is C. The Kleene star over
    subClassOf gives transitive class closure -- the real heart of the regular-path
    machinery in practice.
    """
    return Has(seq_all(
        Down(type_label),
        Star(Down(subclass_label)),
        Test(ValueEq(class_value)),
    ))


def has_edge(label: str) -> Node:
    """< down_a > : nodes that are the source of at least one a-edge."""
    return Has(Down(label))


def is_target_of(label: str) -> Node:
    """< up_a > : nodes that are the target of at least one a-edge."""
    return Has(Up(label))


def contains_free_vars(node: Node) -> Tuple[bool, str]:
    """
    Cheap well-formedness check used by the parser/validator: the positive
    fragment we support has no variables, so this always returns (False, "").
    Kept as a hook so future data-joins (=, join tests) can report unbound vars.
    """
    return (False, "")
