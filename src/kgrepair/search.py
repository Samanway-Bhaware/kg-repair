"""
Two-axis candidate search: the space, the score, and the two pruned axes.

A candidate is a containment `phi subset-of psi` where `phi` is a conjunction of
positive atoms and `psi` is a single positive head. The search walks two axes
independently:

  * the **antecedent axis** builds conjunctions level by level and is pruned by
    the support floor alone;
  * the **consequent axis** walks heads in ascending path length and refuses a
    prefix no body can clear.

The two are deliberately separate functions with separate tests. Fusing them
would make the two pruning laws share a loop and stop being separately
falsifiable, and they rest on different arguments: one is anti-monotone in the
body, the other is non-increasing along a head prefix.

Nothing here proposes, approves or repairs. It computes scored candidates. The
review airlock (`candidates.py`, `review.py`) is unchanged and still the only
route from a candidate to an engine.

The oracle
----------
`tests/reference_enumerator.py` scores this same space exhaustively, from the
expression text through the parser and the evaluator, with nothing pruned. Every
pruning rule in this module is tested by asserting the pruned search admits
exactly what the oracle admits. That oracle is permanent, not scaffolding: a new
pruning rule that is not checked against it is not finished.

Determinism: every collection is built in sorted order and no wall-clock or
random source is read, so two searches over one graph return identical results.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, FrozenSet, Iterable, List, Optional, Sequence, Set, Tuple

from . import gxpath
from .datagraph import DataGraph
from .gxpath import ast

#: A single path step: ("down", label) or ("up", label).
Step = Tuple[str, str]


@dataclass(frozen=True)
class SearchConfig:
    """Floors and bounds for one search.

    `max_antecedent` bounds the conjunction lattice; `max_path` bounds the length
    of a head. Both default low, because the space is exponential in the first and
    grows as `(2 * predicates) ** max_path` in the second.

    `min_support` is a floor on the number of nodes that satisfy both sides, and
    `min_confidence` a floor on the PCA confidence defined in `score`. A class is
    admitted to the atom vocabulary only if the support floor is met by its own
    extension, which is a statement about the space rather than a pruning step:
    see `vocabulary`.
    """
    min_support: int = 5
    min_confidence: float = 0.9
    max_antecedent: int = 2
    max_path: int = 1
    type_predicate: Optional[str] = None
    subclass_predicate: Optional[str] = None
    #: How much of a failing rule's residual one atom has to account for before the
    #: residual is worth showing a reviewer as a widening. See `residual_widenings`.
    purity_floor: float = 0.9
    #: How many nodes a candidate's antecedent has to match in a reference graph
    #: before the two graphs' confidences are worth comparing. `None` means the
    #: support floor. See `assess_stability`.
    reference_support_floor: Optional[int] = None

    @property
    def effective_reference_floor(self) -> int:
        return (self.min_support if self.reference_support_floor is None
                else self.reference_support_floor)


 
# expression text: one spelling, shared by the search and the oracle
 
def tau_text(type_predicate: str, subclass_predicate: str, cls: str) -> str:
    """The core class test `tau_C`, as the parser spells it."""
    return (f'< down({type_predicate}) . down({subclass_predicate})* '
            f'. [val("{cls}")] >')


def step_text(step: Step) -> str:
    """One path step, `down(P)` or `up(P)`, without the surrounding angle brackets."""
    direction, label = step
    return f"{direction}({label})"


def head_text(steps: Sequence[Step]) -> str:
    """A head over a chain of steps: `< down(P) . up(Q) >`."""
    return "< " + " . ".join(step_text(s) for s in steps) + " >"


def conjunction_text(atom_texts: Sequence[str]) -> str:
    """A conjunction of atoms, as the parser spells it."""
    return " & ".join(atom_texts)


 
# bitsets
 
class NodeSpace:
    """The one place the bitset-to-node correspondence is defined.

    A node set is a Python int whose bit `i` is set when `order[i]` is in the set.
    Every conversion in either direction goes through `to_bits` and `to_nodes`
    here, so the assumption that positions are stable lives in exactly one object
    and cannot drift between the atom builder, the lattice and the scorer.

    The ordering is `sorted(graph.nodes)` taken once at construction. A NodeSpace
    is therefore only valid for the graph it was built from and only while that
    graph is not mutated; the search never mutates a graph.
    """

    def __init__(self, graph: DataGraph):
        self.order: List[str] = sorted(graph.nodes)
        self._index: Dict[str, int] = {n: i for i, n in enumerate(self.order)}
        #: every node, as a bitset. The extension of `T`.
        self.universe: int = (1 << len(self.order)) - 1

    def __len__(self) -> int:
        return len(self.order)

    def to_bits(self, nodes: Iterable[str]) -> int:
        """Node set to bitset. A node the space does not know is ignored, which
        can only happen if the caller mixes graphs; every set the search builds
        comes from the graph this space was built from."""
        bits = 0
        for n in nodes:
            i = self._index.get(n)
            if i is not None:
                bits |= 1 << i
        return bits

    def to_nodes(self, bits: int) -> Set[str]:
        """Bitset back to node set."""
        out: Set[str] = set()
        i = 0
        while bits:
            if bits & 1:
                out.add(self.order[i])
            bits >>= 1
            i += 1
        return out

    @staticmethod
    def count(bits: int) -> int:
        """How many nodes a bitset holds."""
        return bits.bit_count()


 
# the PCA denominator
 
def lead(psi: ast.Node) -> ast.Node:
    """The head's first step, with its tests stripped: the PCA denominator's test.

    A type test reduces to having a type edge at all, a tested step reduces to the
    bare step, and a longer path reduces to its first step. `< down(P) . [phi] >`
    and `< down(P) . down(Q) >` both lead with `< down(P) >`; `tau_C` leads with
    `< down(type) >`.

    Why this is not the violation set. Under an open world a node that says
    nothing is unknown, not a counterexample: a node with no type edge at all is
    not evidence against a typing rule, it is a node the data has not spoken
    about. So the confidence denominator counts only the antecedent nodes that
    lead the head, which is what keeps a sparsely typed slice from sinking an
    otherwise clean candidate.

    The repair path takes the opposite view on purpose. The violation set of
    `phi subset-of psi` stays `[[phi]] \\ [[psi]]`, silent nodes included, because
    a node that should have a type and has none is exactly what a superset repair
    exists to fix. **The scored set and the repaired set are different sets**, and
    `tests/test_search_core.py::test_confidence_excludes_the_silent_nodes_the_witness_set_keeps`
    holds both halves in one place so they cannot drift apart.

    A head whose first step is starred leads with the identity, because a starred
    path matches the empty path and so every node leads it.

    A disjunctive head leads with the disjunction of its disjuncts' leads. A node
    leads `A | B` when it leads either side, because either side is enough to make
    the data speak about it. Residual profiling emits disjunctive heads
    (`residual_widenings`), and the authored v2 sets state the meta-class fix the
    same way, so this case is not hypothetical.
    """
    if isinstance(psi, ast.Disj):
        return ast.Disj(lead(psi.left), lead(psi.right))
    if not isinstance(psi, ast.Has):
        raise ValueError(f"a head has to be an existence test, got {psi!r}")
    return ast.Has(_first_step(psi.path))


def _first_step(a: ast.Path) -> ast.Path:
    if isinstance(a, ast.Seq):
        return _first_step(a.left)
    if isinstance(a, ast.Test):
        # a leading test constrains the start node rather than taking a step
        return ast.Eps()
    if isinstance(a, ast.Star):
        # matches the empty path, so every node leads it
        return ast.Eps()
    if isinstance(a, ast.Alt):
        return ast.Alt(_first_step(a.left), _first_step(a.right))
    if isinstance(a, (ast.Down, ast.Up, ast.Eps)):
        return a
    raise ValueError(f"no leading step defined for {a!r}")


def lead_text(psi_text: str) -> str:
    """`lead` on the surface syntax: parse, take the lead, spell it back.

    Only the shapes this search generates are spelled back, which is every shape
    `lead` can return for a generated head.
    """
    led = lead(gxpath.parse_node(psi_text))
    return _spell(led)


def _spell(psi: ast.Node) -> str:
    if isinstance(psi, ast.Has):
        return f"< {_spell_path(psi.path)} >"
    if isinstance(psi, ast.Disj):
        return f"{_spell(psi.left)} | {_spell(psi.right)}"
    raise ValueError(f"cannot spell {psi!r}")


def _spell_path(a: ast.Path) -> str:
    if isinstance(a, ast.Down):
        return f"down({a.label})"
    if isinstance(a, ast.Up):
        return f"up({a.label})"
    if isinstance(a, ast.Eps):
        return "eps"
    if isinstance(a, ast.Alt):
        return f"({_spell_path(a.left)} + {_spell_path(a.right)})"
    raise ValueError(f"cannot spell {a!r}")


 
# scoring
 
@dataclass(frozen=True)
class Scored:
    """One scored candidate. `body_key` and `head_key` identify it in the space."""
    body_key: Tuple[str, ...]
    head_key: str
    body_text: str
    head_text: str
    body_size: int
    support: int
    denominator: int
    confidence: float

    @property
    def identity(self) -> Tuple[Tuple[str, ...], str]:
        """What the oracle and the search compare on."""
        return (self.body_key, self.head_key)


def score(body_bits: int, head_bits: int, lead_bits: int) -> Tuple[int, int, float]:
    """`(support, denominator, confidence)` for one body against one head.

    Support counts the nodes satisfying both sides. The denominator counts the
    body nodes that lead the head, and confidence is support over that. A body
    where nothing leads the head scores 0.0 and is not admitted: there is no
    evidence either way, which is not the same as evidence against.
    """
    support = NodeSpace.count(body_bits & head_bits)
    denominator = NodeSpace.count(body_bits & lead_bits)
    confidence = (support / denominator) if denominator else 0.0
    return support, denominator, confidence


def admits(support: int, denominator: int, confidence: float,
           cfg: SearchConfig) -> bool:
    """The admission rule, in one place because the oracle applies it too."""
    return (denominator >= 1
            and support >= cfg.min_support
            and confidence >= cfg.min_confidence)


 
# the space
 
@dataclass
class Atom:
    """One antecedent building block: a class test or a single step existence test."""
    key: str
    text: str


@dataclass
class Vocabulary:
    """The atoms and heads a search over one graph may build.

    This is the space itself, shared by the search and the oracle. If the two
    disagreed about the space, comparing what they admit would mean nothing.
    """
    type_predicate: str
    subclass_predicate: str
    predicates: List[str]
    classes: List[str]
    atoms: List[Atom]
    steps: List[Step] = field(default_factory=list)

    def class_heads(self) -> List[str]:
        """Class tests, as heads. A class test is not extended along the path axis:
        its own path is fixed by `tau_C`."""
        return [tau_text(self.type_predicate, self.subclass_predicate, c)
                for c in self.classes]


def vocabulary(graph: DataGraph, cfg: SearchConfig) -> Vocabulary:
    """Build the atom and head vocabulary for `graph`.

    Predicates are every edge label except the typing spine, which the class test
    covers. Steps are `down(P)` and `up(P)` for each, with no floor applied: a step
    atom below the support floor stays in the space so that the lattice's support
    pruning has something to prove against the oracle.

    Classes are floored. A class whose extension holds fewer than `min_support`
    nodes is not in the vocabulary at all. That is a statement about which class
    tests this search is willing to name, not a pruning step, and the oracle reads
    the same vocabulary, so both sides see the same space.
    """
    type_pred, subclass_pred = _spine(graph, cfg)
    predicates = sorted(l for l in graph.labels if l not in (type_pred, subclass_pred))
    steps: List[Step] = []
    for p in predicates:
        steps.append(("down", p))
        steps.append(("up", p))

    ev = gxpath.Evaluator(graph, use_closure=True)
    classes: List[str] = []
    for cls in _class_values(graph, type_pred, subclass_pred):
        text = tau_text(type_pred, subclass_pred, cls)
        if len(ev.eval_node(gxpath.parse_node(text))) >= cfg.min_support:
            classes.append(cls)

    atoms: List[Atom] = []
    for cls in classes:
        atoms.append(Atom(key=f"c_{cls}",
                          text=tau_text(type_pred, subclass_pred, cls)))
    for st in steps:
        direction, label = st
        atoms.append(Atom(key=f"{direction[0]}_{label}", text=f"< {step_text(st)} >"))
    atoms.sort(key=lambda a: a.key)

    return Vocabulary(type_predicate=type_pred, subclass_predicate=subclass_pred,
                      predicates=predicates, classes=classes, atoms=atoms, steps=steps)


def _spine(graph: DataGraph, cfg: SearchConfig) -> Tuple[str, str]:
    """The typing and subclass predicates, from the config or detected.

    Detection is `derive._detect_vocabulary`, reused rather than reimplemented so
    that one detector serves the whole toolkit.
    """
    from .derive import DeriveConfig, _detect_vocabulary
    return _detect_vocabulary(set(graph.labels), sorted(graph.edges()),
                              DeriveConfig(type_predicate=cfg.type_predicate,
                                           subclass_predicate=cfg.subclass_predicate))


def _class_values(graph: DataGraph, type_pred: str, subclass_pred: str) -> List[str]:
    """Every value a class test could name: the data value of any node on the
    typing spine. `tau_C` matches on `val(C)`, so a class with no data value
    cannot be named by one."""
    out: Set[str] = set()
    for src, label, dst in graph.edges():
        if label == type_pred:
            value = graph.value(dst)
            if value is not None:
                out.add(value)
        elif label == subclass_pred:
            for node in (src, dst):
                value = graph.value(node)
                if value is not None:
                    out.add(value)
    return sorted(out)


def heads_of_length(steps: Sequence[Step], prefixes: Sequence[Tuple[Step, ...]]
                    ) -> List[Tuple[Step, ...]]:
    """Every one-step extension of each live prefix, in a settled order."""
    out: List[Tuple[Step, ...]] = []
    for prefix in prefixes:
        for st in steps:
            out.append(prefix + (st,))
    return out


 
# extensions
 
class Extensions:
    """Expression text to bitset, evaluated once per distinct expression.

    Atoms are evaluated here and nowhere else: one backward pre-image traversal
    each, through the audited evaluator rather than a second traversal written for
    this module. Every conjunction thereafter is an intersection of two ints and
    never touches the graph again, which is the whole point of the bitset
    representation.

    Heads are evaluated per head rather than composed, because a head's extension
    is a pre-image chain and not an intersection of its steps' extensions.
    """

    def __init__(self, graph: DataGraph, space: NodeSpace):
        self._ev = gxpath.Evaluator(graph, use_closure=True)
        self._space = space
        self._cache: Dict[str, int] = {}
        self.traversals = 0

    def of(self, text: str) -> int:
        cached = self._cache.get(text)
        if cached is not None:
            return cached
        self.traversals += 1
        bits = self._space.to_bits(self._ev.eval_node(gxpath.parse_node(text)))
        self._cache[text] = bits
        return bits


 
# axis 1: the antecedent lattice
 
@dataclass(frozen=True)
class Body:
    """One antecedent: a conjunction of atoms, with its extension as a bitset."""
    key: Tuple[str, ...]
    text: str
    bits: int

    @property
    def size(self) -> int:
        return NodeSpace.count(self.bits)


def antecedent_lattice(atoms: Sequence[Atom], ext: Extensions, cfg: SearchConfig,
                       *, prune_support: bool = True) -> List[Body]:
    """Conjunctions of up to `max_antecedent` atoms, pruned by the support floor.

    **Confidence must not prune this axis.** Adding a conjunct removes nodes from
    the numerator and from the denominator at the same time, so confidence can
    move either way: a rule that looks hopeless on a broad body can be clean on a
    narrower one, and refusing to extend a low-confidence body would lose it. The
    support floor is the only law that holds here, and it holds because a
    conjunction's extension is contained in each conjunct's, so a body below the
    floor has no extension above it.

    Support pruning is lossless with respect to what is admitted: admission needs
    `|body & head| >= min_support`, and `|body & head| <= |body|`, so a body below
    the floor cannot produce an admitted candidate under any head.

    `prune_support=False` builds the whole lattice. It exists so a test can run
    the two pruning laws separately against the oracle, and is not a tuning knob.
    """
    level: List[Body] = []
    for atom in atoms:
        bits = ext.of(atom.text)
        body = Body(key=(atom.key,), text=atom.text, bits=bits)
        if prune_support and body.size < cfg.min_support:
            continue
        level.append(body)

    by_key = {a.key: a for a in atoms}
    out: List[Body] = list(level)
    for _size in range(2, cfg.max_antecedent + 1):
        nxt: List[Body] = []
        for body in level:
            for atom in atoms:
                if atom.key <= body.key[-1]:      # ascending order, no repeats
                    continue
                bits = body.bits & ext.of(atom.text)
                key = body.key + (atom.key,)
                grown = Body(key=key,
                             text=conjunction_text([by_key[k].text for k in key]),
                             bits=bits)
                if prune_support and grown.size < cfg.min_support:
                    continue
                nxt.append(grown)
        out.extend(nxt)
        level = nxt
    return out


 
# axis 2: the head axis
 
@dataclass
class HeadAxisResult:
    admitted: List[Scored]
    heads_generated: int = 0
    prefixes_refused: int = 0
    dominated: int = 0
    #: Pairs blocked before scoring because the head restates an antecedent atom.
    #: Counted apart from `dominated`: a tautology is refused at generation, not
    #: beaten by a better rule. See `is_tautology`.
    tautologies: int = 0
    #: Pairs with enough support to judge that fell short on confidence. These are
    #: what `residual_widenings` looks at; nothing else reads them.
    near_misses: List[Scored] = field(default_factory=list)


def is_tautology(head_text_: str, atom_texts: FrozenSet[str]) -> bool:
    """Whether a head restates one of its own antecedent's atoms.

    `phi & psi subset-of psi` holds on every graph by construction, so it is not a
    finding about the data. This is the **primary block**, applied at generation:
    the pair is refused before it is scored, so it never reaches the admitted set,
    the candidate file, or `proposals.measure_impact`, which would otherwise run
    two engines over a rule that cannot have a witness.

    Blocking it is not optional shaping. Left in, a tautology scores 1.0, ties with
    every honest rule under the same head and wins the tie-break on atom count, so
    it becomes the only candidate shown for that head: on graph A "typed City
    implies typed City" would suppress "has a capital implies typed City".

    The oracle's `dominance_filter` keeps the same exclusion as a second line of
    defence, so a tautology that reached either side would show up as a
    disagreement rather than as agreement about the wrong set.
    """
    return head_text_ in atom_texts


def dominance_order(bodies: Sequence[Body]) -> List[Body]:
    """Bodies arranged so that a body always follows every body that can dominate it.

    The dominance relation is: `A` precedes `B` when `A`'s extension strictly
    contains `B`'s, or the two extensions are equal and `A` is written with fewer
    atoms (ties broken on the key, so the order is total). Sorting by
    `(-size, atom count, key)` is a linear extension of that, which is what lets
    the online test look only at what it has already admitted.
    """
    return sorted(bodies, key=lambda b: (-b.size, len(b.key), b.key))


def dominates(a_bits: int, a_key: Tuple[str, ...], a_conf: float,
              b_bits: int, b_key: Tuple[str, ...], b_conf: float) -> bool:
    """Whether candidate `a` makes candidate `b` not worth showing a reviewer.

    Same head, `a`'s antecedent at least as general, and `a` at least as
    confident. Two shapes of "at least as general" are covered, and both are
    needed:

      * `a`'s atoms are a strict subset of `b`'s. This is the online test: `b`
        adds a condition to a rule that already held at least as well without it,
        so the condition bought nothing.
      * `a`'s antecedent matches a strictly larger set of nodes. This is what the
        older reduced-cover pass did, and it is kept because it still catches
        cases the first test cannot see: two rules can stand in a
        more-general-than relation extensionally while neither atom set contains
        the other. On the geography slice it removes 363 candidates the atom-set
        test alone keeps, so it was absorbed here rather than dropped.

    Equal extensions are broken on atom count and then on the key, so exactly one
    of any two interchangeable candidates survives and the choice is settled.
    """
    if a_conf < b_conf:
        return False
    if b_bits & ~a_bits:                      # a does not contain b
        return False
    if a_bits != b_bits:                      # a is strictly more general
        return True
    return (len(a_key), a_key) < (len(b_key), b_key)


def head_axis(bodies: Sequence[Body], vocab: Vocabulary, ext: Extensions,
              cfg: SearchConfig, *, prune_prefix: bool = True,
              prune_dominance: bool = True) -> HeadAxisResult:
    """Score every body against every head, walking heads by ascending path length.

    **Head-prefix refusal.** Confidence is non-increasing along a head prefix.
    Extending `< a >` to `< a . b >` can only shrink the numerator, because
    `[[< a . b >]]` is contained in `[[< a >]]`, while the denominator is fixed by
    the first step and so does not move at all. So if no body clears
    `min_confidence` on a prefix, no body clears it on any extension of that
    prefix, and the whole subtree can go ungenerated rather than generated and
    discarded.

    Class heads are scored but never extended: `tau_C` fixes its own path.

    **Dominance.** A candidate is dropped when an already-admitted candidate under
    the same head has an antecedent at least as general and a confidence at least
    as high; see `dominates`. This is a shaping rule and not a losslessness claim:
    it changes what the search returns, so the oracle applies the same filter and
    the two stay comparable.

    `prune_prefix=False` generates every head to `max_path`, and
    `prune_dominance=False` keeps every admitted candidate. Like the lattice flag,
    both exist to let a test isolate one rule against the oracle.
    """
    result = HeadAxisResult(admitted=[])
    ordered = dominance_order(bodies)
    atom_text = {a.key: a.text for a in vocab.atoms}
    body_atoms = {b.key: frozenset(atom_text[k] for k in b.key) for b in bodies}

    for text in vocab.class_heads():
        result.heads_generated += 1
        _score_head(ordered, text, text, ext, cfg, result, prune_dominance, body_atoms)

    live: List[Tuple[Step, ...]] = [()]
    for _length in range(1, cfg.max_path + 1):
        generated = heads_of_length(vocab.steps, live)
        survivors: List[Tuple[Step, ...]] = []
        for steps in generated:
            result.heads_generated += 1
            text = head_text(steps)
            cleared = _score_head(ordered, text, text, ext, cfg, result, prune_dominance,
                                  body_atoms)
            if cleared or not prune_prefix:
                survivors.append(steps)
            else:
                result.prefixes_refused += 1
        live = survivors
    return result


def _score_head(bodies: Sequence[Body], text: str, key: str, ext: Extensions,
                cfg: SearchConfig, result: HeadAxisResult,
                prune_dominance: bool = True,
                body_atoms: Optional[Dict[Tuple[str, ...], FrozenSet[str]]] = None) -> bool:
    """Score one head against every body, in dominance order.

    Returns whether any body cleared the confidence floor, which is what keeps the
    prefix alive. Clearing is judged over every body, dominated ones included: a
    dominated candidate is one a reviewer does not need to see, not one whose
    evidence stops existing.

    Tautologies are refused before they are scored (`is_tautology`), and they still
    count towards clearing the prefix. That is exact rather than generous: a head
    that restates an atom of its body contains that body, and the body leads the
    head, so support equals the denominator and the confidence is 1.0 whenever the
    body matches anything at all. Dropping the pair from the clearing test instead
    would refuse prefixes whose extensions a different body still clears, and the
    prefix law would stop being lossless.
    """
    head_bits = ext.of(text)
    lead_bits = ext.of(lead_text(text))
    cleared = False
    kept: List[Tuple[int, Tuple[str, ...], float]] = []
    for body in bodies:
        if body_atoms is not None and is_tautology(text, body_atoms[body.key]):
            result.tautologies += 1
            if body.bits:                      # confidence is 1.0, see the docstring
                cleared = True
            continue
        support, denominator, confidence = score(body.bits, head_bits, lead_bits)
        if denominator >= 1 and confidence >= cfg.min_confidence:
            cleared = True
        if not admits(support, denominator, confidence, cfg):
            if denominator >= 1 and support >= cfg.min_support:
                result.near_misses.append(Scored(
                    body_key=body.key, head_key=key, body_text=body.text,
                    head_text=text, body_size=body.size, support=support,
                    denominator=denominator, confidence=confidence))
            continue
        if prune_dominance and any(
                dominates(a_bits, a_key, a_conf, body.bits, body.key, confidence)
                for a_bits, a_key, a_conf in kept):
            result.dominated += 1
            continue
        kept.append((body.bits, body.key, confidence))
        result.admitted.append(Scored(
            body_key=body.key, head_key=key, body_text=body.text,
            head_text=text, body_size=body.size, support=support,
            denominator=denominator, confidence=confidence))
    return cleared


 
# residual profiling
 
def disjunction_text(left: str, right: str) -> str:
    """A disjunctive head, as the parser spells it."""
    return f"{left} | {right}"


@dataclass(frozen=True)
class Widening:
    """A second, broader candidate offered alongside a rule that fell short.

    The rule in `original` failed the confidence floor. The nodes that made it
    fail are its residual: body nodes that lead the head and do not satisfy it.
    When one atom accounts for nearly all of them, that is worth showing, because
    it is usually the data saying the rule is right about a population the head
    was written too narrowly to name.

    Both records go to review together. The widening is never offered in place of
    the original: which of the two is true about the world is a judgement, and
    the residual statistics are what a reviewer needs to make it.
    """
    original: Scored
    atom_key: str
    head_text: str
    residual_size: int
    residual_covered: int
    coverage: float
    support: int
    confidence: float
    kind: str = "weakening"

    @property
    def identity(self) -> Tuple[Tuple[str, ...], str]:
        return (self.original.body_key, self.head_text)


def residual_widenings(near_misses: Sequence[Scored], vocab: Vocabulary,
                       ext: Extensions, cfg: SearchConfig) -> List[Widening]:
    """For each rule that fell short, the one atom that explains its residual.

    The residual is `body and lead(head) and not head`: the nodes the data spoke
    about, that the rule claims and the head denies. An atom is a candidate
    explanation when it covers at least `purity_floor` of that residual, and the
    widening is offered only when adding it would actually lift the rule over the
    confidence floor. The denominator does not move, so the confidence gain is
    attributable to the widening and to nothing else.

    An atom whose extension already contains the whole body is skipped. Widening
    with one of those makes the head true of everything the body claims, which is
    not a finding about the data.

    The covered part of the residual has to clear the support floor in its own
    right. Every other emission in this search needs that much evidence behind it,
    and a residual of two nodes is "explained" by almost any atom without that
    meaning anything.

    Scoring. The widened rule is judged on the **original rule's denominator**, so
    the two confidences are comparable and the gain is exactly the residual the
    atom accounted for. The numerator is therefore restricted to the nodes that
    lead the original head, which is the set the original was judged on. Without
    that restriction the disjunct pulls in nodes the original head never spoke
    about and the ratio runs above 1.0.

    One widening per rule, the atom with the best coverage, ties broken on the
    lifted confidence and then the atom key.
    """
    by_key = {a.key: a for a in vocab.atoms}
    out: List[Widening] = []
    for miss in near_misses:
        body_bits = ext.of(miss.body_text)
        head_bits = ext.of(miss.head_text)
        lead_bits = ext.of(lead_text(miss.head_text))
        judged = body_bits & lead_bits
        residual = judged & ~head_bits
        residual_size = NodeSpace.count(residual)
        denominator = NodeSpace.count(judged)
        if residual_size == 0 or denominator == 0:
            continue

        best: Optional[Widening] = None
        for key in sorted(by_key):
            atom_bits = ext.of(by_key[key].text)
            if not (body_bits & ~atom_bits):        # covers the whole body already
                continue
            covered = NodeSpace.count(residual & atom_bits)
            coverage = covered / residual_size
            if coverage < cfg.purity_floor or covered < cfg.min_support:
                continue
            support = NodeSpace.count(judged & (head_bits | atom_bits))
            confidence = support / denominator
            if confidence < cfg.min_confidence:
                continue
            candidate = Widening(
                original=miss, atom_key=key,
                head_text=disjunction_text(miss.head_text, by_key[key].text),
                residual_size=residual_size, residual_covered=covered,
                coverage=coverage, support=support, confidence=confidence)
            if best is None or (-candidate.coverage, -candidate.confidence, key) < \
                    (-best.coverage, -best.confidence, best.atom_key):
                best = candidate
        if best is not None:
            out.append(best)
    return sorted(out, key=lambda w: (-w.coverage, -w.confidence,
                                      w.original.body_key, w.head_text))


 
# stability against a reference graph
 
STABLE, UNSTABLE, NOT_COMPARABLE = "stable", "unstable", "not_comparable"


@dataclass(frozen=True)
class Stability:
    """How a candidate scored on a second graph, and whether that meant anything."""
    outcome: str
    confidence: float
    confidence_ref: Optional[float]
    reference_support: int
    gap: Optional[float]
    reason: str

    @property
    def discard(self) -> bool:
        """Only an outright disagreement is a reason to drop a candidate."""
        return self.outcome == UNSTABLE


def assess_stability(candidates: Sequence[Scored], reference: DataGraph,
                     cfg: SearchConfig, delta: float) -> Dict[Tuple[Tuple[str, ...], str],
                                                              Stability]:
    """Score each candidate on a reference graph and say what the comparison meant.

    Three outcomes, not two. A rule scored against a graph whose antecedent it
    barely matches has an empty or near-empty denominator there, which yields a
    confidence of 0.0 and a gap that looks exactly like instability while actually
    meaning the reference had nothing to say. A Wikidata rule scored against a
    DBpedia slice that shares no predicates hits this every time.

    So the antecedent has to match at least `reference_support_floor` nodes in the
    reference before the two confidences are compared at all. Below that the
    outcome is `not_comparable`: `confidence_ref` is null, the reason is recorded,
    and the candidate goes to review undiscarded. Only an outright disagreement,
    on a reference that had enough to say, is `unstable`.
    """
    space = NodeSpace(reference)
    ext = Extensions(reference, space)
    floor = cfg.effective_reference_floor
    out: Dict[Tuple[Tuple[str, ...], str], Stability] = {}
    for cand in candidates:
        body_bits = ext.of(cand.body_text)
        reference_support = NodeSpace.count(body_bits)
        if reference_support < floor:
            out[cand.identity] = Stability(
                outcome=NOT_COMPARABLE, confidence=cand.confidence,
                confidence_ref=None, reference_support=reference_support, gap=None,
                reason=(f"the antecedent matches {reference_support} node(s) in the "
                        f"reference, below the floor of {floor}, so the reference "
                        f"has nothing to say about this rule"))
            continue
        head_bits = ext.of(cand.head_text)
        lead_bits = ext.of(lead_text(cand.head_text))
        _support, denominator, confidence_ref = score(body_bits, head_bits, lead_bits)
        if denominator < 1:
            out[cand.identity] = Stability(
                outcome=NOT_COMPARABLE, confidence=cand.confidence,
                confidence_ref=None, reference_support=reference_support, gap=None,
                reason=("no node in the reference antecedent leads the head, so "
                        "there is no denominator to score against"))
            continue
        gap = abs(cand.confidence - confidence_ref)
        out[cand.identity] = Stability(
            outcome=STABLE if gap <= delta else UNSTABLE,
            confidence=cand.confidence, confidence_ref=confidence_ref,
            reference_support=reference_support, gap=round(gap, 6),
            reason=(f"scored on {reference_support} reference node(s); "
                    f"confidence gap {round(gap, 6)} against a delta of {delta}"))
    return out


 
# entry point
 
@dataclass
class SearchResult:
    admitted: List[Scored]
    vocabulary: Vocabulary
    bodies_generated: int
    heads_generated: int
    prefixes_refused: int
    dominated: int
    traversals: int
    widenings: List[Widening] = field(default_factory=list)
    near_misses: int = 0
    tautologies: int = 0


def search(graph: DataGraph, cfg: SearchConfig = SearchConfig(), *,
           prune_support: bool = True, prune_prefix: bool = True,
           prune_dominance: bool = True, residual: bool = True) -> SearchResult:
    """Run both axes over `graph` and return the admitted candidates.

    The result is sorted by confidence then support then identity, so two searches
    over one graph return the same list in the same order. `residual=False` skips
    the widening pass, which is the only part of a search whose cost grows with
    what was rejected rather than with what was kept.
    """
    space = NodeSpace(graph)
    ext = Extensions(graph, space)
    vocab = vocabulary(graph, cfg)
    bodies = antecedent_lattice(vocab.atoms, ext, cfg, prune_support=prune_support)
    axis = head_axis(bodies, vocab, ext, cfg, prune_prefix=prune_prefix,
                     prune_dominance=prune_dominance)
    admitted = sorted(axis.admitted,
                      key=lambda s: (-s.confidence, -s.support, s.body_key, s.head_key))
    widenings = (residual_widenings(axis.near_misses, vocab, ext, cfg)
                 if residual else [])
    return SearchResult(admitted=admitted, vocabulary=vocab,
                        bodies_generated=len(bodies),
                        heads_generated=axis.heads_generated,
                        prefixes_refused=axis.prefixes_refused,
                        dominated=axis.dominated,
                        traversals=ext.traversals,
                        widenings=widenings,
                        near_misses=len(axis.near_misses),
                        tautologies=axis.tautologies)


def admitted_identities(scored: Iterable[Scored]) -> FrozenSet[Tuple[Tuple[str, ...], str]]:
    """The admitted set as bare identities, for comparing two searches."""
    return frozenset(s.identity for s in scored)
