"""
Constraint candidate generator: derive in-fragment ptime_core constraints from a
DataGraph by profiling, for human approval.

This is the data-profiling prototype the constraint-mining study recommended as its
follow-up: a generator whose output is always a positive node expression (in-fragment
by construction), scored so a reviewer can approve or reject each candidate.

Three design choices are worth attributing:

  * PCA (partial-completeness) confidence, from the AMIE rule-mining line, is the sole
    confidence gate. Under open-world data a node that simply lacks a type is unknown,
    not a counterexample, so the PCA denominator counts only body nodes that carry some
    type at all. Admission works in two steps: a typed-mass floor decides whether there
    is enough typed evidence in the body to judge the candidate at all, and then PCA
    confidence decides admission. Standard confidence is still computed and reported but
    never gates, so untyped body nodes no longer sink an otherwise-clean candidate.

  * Class-granularity is an explicit scored choice, not a guess. The study found
    class-selection noise (a candidate attached to a vague root class such as "entity")
    to be the dominant failure of naive profiling, so for each candidate we score every
    class the body is typed under and select the most specific one that still clears the
    thresholds, recording the runners-up for the reviewer.

  * A contamination flag automates the plausibility check that was previously run by
    hand (a shared predicate leaking an unrelated class into a slice). Drawing on
    local-closed-world negative evidence, when a large fraction of a predicate's
    endpoints are typed under a class disjoint from the chosen one, the candidate is
    flagged (not filtered) with the top competing class.

Typing inheritance is deliberately out of scope here: it is schema-derived from the
subclass hierarchy, not something to read off data prevalence.

Fragment exclusion (enforced, not assumed). Every candidate is a containment of
positive node expressions, phi subset-of psi, across only the four repairable shapes.
The generator never emits an implication, a data-equality consequent (x.value = y.value
or any two-variable join), or any negative or path-complement target. Negation is what
pushes subset repair to NP-completeness and superset repair to undecidability (Abriola
et al., Thms 12 and 19), so it is outside the repairable fragment by construction.
`_assert_in_fragment` parses both sides with the real parser and walks each ast to
confirm no negation or complement node is present before any Constraint is built.

Everything emitted carries provenance "mined" and never enters an authored constraint
set. Determinism: all iteration is over sorted collections; thresholds come only from
DeriveConfig; no randomness or wall-clock enters the output.
"""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

from . import gxpath
from . import search
from .constraints.model import Constraint, ConstraintSet
from .datagraph import DataGraph
from .validator import Validator

# ast node types that would leave the positive fragment. The parser already rejects
# the concrete syntax for these, so this set is a defensive belt for a future ast that
# grows such nodes; it is checked by name so it holds even then.
_FORBIDDEN_AST_NAMES = frozenset({"Not", "Neg", "Complement", "Compl", "PathCompl",
                                  "Diff", "NotEq", "Neq", "Implies"})

# Predicate-name priorities used when the type/subclass vocabulary is not supplied.
# Each pair is (type_predicate, subclass_predicate); the first pair whose BOTH members
# occur as edge labels in the graph wins. This is the deterministic detector for the
# project slices; a structural fallback (below) handles anything else.
_KNOWN_VOCAB = (
    ("wdt:P31", "wdt:P279"),
    ("rdf:type", "rdfs:subClassOf"),
    ("rdf:type", "schema:subClassOf"),
)


#: The two generators `derive_candidates` can run. `SEARCH` is the default from
#: P4d; `SHAPES` is the original shape-driven sweep, kept selectable and with its
#: own tests. See `derive_candidates` for what the choice changes.
SEARCH = "search"
SHAPES = "shapes"
GENERATORS = (SEARCH, SHAPES)


@dataclass
class DeriveConfig:
    min_support: int = 5
    min_pca_confidence: float = 0.9
    min_typed_fraction: float = 0.5            # typed-mass floor for a body to be judged
    contamination_frac: float = 0.2
    type_predicate: Optional[str] = None       # None -> detect
    subclass_predicate: Optional[str] = None   # None -> detect
    max_typing_antecedent_atoms: int = 2
    max_path_depth: int = 1                     # >1 also mines forward-path atoms
    max_exceptions_listed: int = 10
    # direction per shape; overridable without touching the shape logic
    direction_overrides: Dict[str, str] = field(default_factory=dict)
    #: Which generator `derive_candidates` runs; one of `GENERATORS`. Last in the
    #: field order on purpose, so that adding it could not shift any positional
    #: argument an existing caller passes.
    generator: str = SEARCH

    def direction_for(self, kind: str) -> str:
        # "superset" for anything not named here: a shape whose default is not
        # recorded is one nobody has argued should be repaired by deletion, and
        # `direction` is a preference rather than a capability limit (D6:
        # the direction-as-preference reframing).
        default = {
            "existential_domain": "subset",
            "existential_range": "subset",
            "typing_existence": "superset",
            "requires_statement": "superset",
            "weakening": "superset",
        }.get(kind, "superset")
        return self.direction_overrides.get(kind, default)


@dataclass
class DerivationResult:
    constraints: ConstraintSet          # candidates that cleared thresholds
    report: List[Dict]                  # per-candidate approval payload, sorted
    stats: Dict[str, int]               # counts by shape
    vocab: Dict[str, str]               # detected/used type + subclass predicate


 
# vocabulary detection
 

def _detect_vocabulary(labels: Set[str], edges: List[Tuple[str, str, str]],
                       cfg: DeriveConfig) -> Tuple[str, str]:
    """Return (type_predicate, subclass_predicate). Honour config overrides; else try
    the known-name priority list; else a simple structural heuristic (the subclass
    predicate connects high-fan-in class nodes to each other, the type predicate points
    into them)."""
    tp, sp = cfg.type_predicate, cfg.subclass_predicate
    if tp is not None and sp is not None:
        return tp, sp
    # A known pair is accepted on the strength of its TYPE predicate alone: a slice may
    # carry instance types with no in-slice subclass edges, and tau_C with an absent
    # subclass predicate simply degenerates to a direct-type match, still in-fragment.
    for cand_tp, cand_sp in _KNOWN_VOCAB:
        if cand_tp in labels:
            return cfg.type_predicate or cand_tp, cfg.subclass_predicate or cand_sp

    # structural fallback: in-degree per node across all edges
    indeg: Dict[str, int] = defaultdict(int)
    src_by_pred: Dict[str, Set[str]] = defaultdict(set)
    tgt_by_pred: Dict[str, Set[str]] = defaultdict(set)
    for s, p, o in edges:
        indeg[o] += 1
        src_by_pred[p].add(s)
        tgt_by_pred[p].add(o)
    if not indeg:
        return (tp or "rdf:type", sp or "rdfs:subClassOf")
    # class nodes = the top decile by in-degree
    ranked = sorted(indeg, key=lambda n: (-indeg[n], n))
    class_nodes = set(ranked[: max(1, len(ranked) // 10)])
    # subclass predicate: its endpoints are mostly class nodes (class-to-class)
    def class_to_class_score(p: str) -> float:
        endpoints = src_by_pred[p] | tgt_by_pred[p]
        if not endpoints:
            return 0.0
        return len(endpoints & class_nodes) / len(endpoints)
    detected_sp = sp or max(sorted(labels), key=class_to_class_score, default="rdfs:subClassOf")
    # type predicate: points into class nodes with the largest instance fan-in
    def type_score(p: str) -> float:
        if p == detected_sp or not tgt_by_pred[p]:
            return 0.0
        return len(tgt_by_pred[p] & class_nodes) / len(tgt_by_pred[p]) * len(src_by_pred[p])
    detected_tp = tp or max(sorted(labels), key=type_score, default="rdf:type")
    return detected_tp, detected_sp


 
# graph profile
 

class _Profile:
    """Precomputed indexes a derivation sweep reads from. Built once per graph."""

    def __init__(self, graph: DataGraph, type_pred: str, subclass_pred: str):
        self.g = graph
        self.type_pred = type_pred
        self.subclass_pred = subclass_pred
        edges = sorted(graph.edges())
        self.edges = edges

        self.src_of: Dict[str, Set[str]] = defaultdict(set)   # predicate -> source nodes
        self.tgt_of: Dict[str, Set[str]] = defaultdict(set)   # predicate -> target nodes
        self.direct_types: Dict[str, Set[str]] = defaultdict(set)   # node -> classes via type edge
        self.subclass_parents: Dict[str, Set[str]] = defaultdict(set)  # class -> direct superclasses
        for s, p, o in edges:
            self.src_of[p].add(s)
            self.tgt_of[p].add(o)
            if p == type_pred:
                self.direct_types[s].add(o)
            elif p == subclass_pred:
                self.subclass_parents[s].add(o)

        self._super_cache: Dict[str, Set[str]] = {}
        self._desc_cache: Dict[str, Set[str]] = {}
        # inverse subclass edges for descendant queries
        self._subclass_children: Dict[str, Set[str]] = defaultdict(set)
        for child, parents in self.subclass_parents.items():
            for par in parents:
                self._subclass_children[par].add(child)

        # typed closure per node: every class it is an instance of (type then subclass*)
        self.typed_closure: Dict[str, Set[str]] = {}
        self.class_instances: Dict[str, Set[str]] = defaultdict(set)
        for node in sorted(self.direct_types):
            closure: Set[str] = set()
            for cls in self.direct_types[node]:
                closure |= self.superclasses(cls)
            self.typed_closure[node] = closure
            for cls in closure:
                self.class_instances[cls].add(node)

    def superclasses(self, cls: str) -> Set[str]:
        cached = self._super_cache.get(cls)
        if cached is not None:
            return cached
        seen = {cls}
        stack = [cls]
        while stack:
            x = stack.pop()
            for par in self.subclass_parents.get(x, ()):
                if par not in seen:
                    seen.add(par)
                    stack.append(par)
        self._super_cache[cls] = seen
        return seen

    def descendants(self, cls: str) -> Set[str]:
        cached = self._desc_cache.get(cls)
        if cached is not None:
            return cached
        seen: Set[str] = set()
        stack = [cls]
        while stack:
            x = stack.pop()
            for child in self._subclass_children.get(x, ()):
                if child not in seen:
                    seen.add(child)
                    stack.append(child)
        self._desc_cache[cls] = seen
        return seen

    def has_any_type(self, node: str) -> bool:
        return node in self.direct_types

    def depth(self, cls: str) -> int:
        """Specificity proxy: number of proper superclasses. More superclasses means
        deeper in the hierarchy, i.e. more specific."""
        return len(self.superclasses(cls)) - 1

    def comparable(self, a: str, b: str) -> bool:
        return a == b or a in self.superclasses(b) or b in self.superclasses(a)

    def candidate_classes_for(self, body: Set[str]) -> List[str]:
        classes: Set[str] = set()
        for x in body:
            classes |= self.typed_closure.get(x, set())
        return sorted(classes)


 
# scoring + granularity
 

@dataclass
class _ClassScore:
    cls: str
    support: int
    body_size: int
    body_typed_size: int
    standard_conf: float
    pca_conf: float


def _score_class(prof: _Profile, body: Set[str], cls: str) -> _ClassScore:
    instances = prof.class_instances.get(cls, set())
    support = len(body & instances)
    body_typed = sum(1 for x in body if prof.has_any_type(x))
    std = support / len(body) if body else 0.0
    pca = support / body_typed if body_typed else 0.0
    return _ClassScore(cls, support, len(body), body_typed, std, pca)


def _select_class(prof: _Profile, body: Set[str], cfg: DeriveConfig
                  ) -> Tuple[Optional[_ClassScore], List[_ClassScore]]:
    """Choose the most specific class that clears the thresholds; return it plus the
    runners-up (other clearing classes). See the module docstring on why granularity
    is scored rather than guessed."""
    scored = [_score_class(prof, body, c) for c in prof.candidate_classes_for(body)]
    # typed-mass floor: only judge a candidate when enough of its body carries some type
    # at all. This is a per-body gate (body_typed_size is constant across classes), so it
    # decides whether there is typed evidence to judge, not which class wins.
    qualifying = [s for s in scored
                  if s.body_typed_size >= 1
                  and (s.body_typed_size / s.body_size) >= cfg.min_typed_fraction]
    # PCA confidence is the only confidence gate; standard_conf is reported, never gates.
    clearing = [s for s in qualifying
                if s.support >= cfg.min_support and s.pca_conf >= cfg.min_pca_confidence]
    if not clearing:
        return None, []
    clearing_ids = {s.cls for s in clearing}
    # most specific: no other clearing class is a proper subclass of it
    specific = [s for s in clearing
                if not (prof.descendants(s.cls) & (clearing_ids - {s.cls}))]
    pool = specific or clearing
    pool.sort(key=lambda s: (-prof.depth(s.cls), -s.support, s.cls))
    chosen = pool[0]
    runners = sorted((s for s in clearing if s.cls != chosen.cls),
                     key=lambda s: (-s.pca_conf, -s.support, s.cls))
    return chosen, runners


def _contamination(prof: _Profile, endpoints: Set[str], cls: str, cfg: DeriveConfig
                   ) -> Tuple[bool, Optional[str]]:
    """Flag when at least contamination_frac of the endpoints carry a type disjoint
    from `cls` (incomparable in the subclass hierarchy). Returns (flag, top competing
    class). A warning for the reviewer, never a filter."""
    competing: Dict[str, int] = defaultdict(int)
    contaminated = 0
    for x in endpoints:
        disjoint_here = sorted(d for d in prof.direct_types.get(x, ())
                               if not prof.comparable(d, cls))
        if disjoint_here:
            contaminated += 1
            for d in disjoint_here:
                competing[d] += 1
    if not endpoints or contaminated / len(endpoints) < cfg.contamination_frac:
        return False, None
    top = sorted(competing, key=lambda d: (-competing[d], d))[0]
    return True, top


 
# constraint string builders (mirroring the parser's concrete syntax exactly)
 

def _tau(prof: _Profile, cls: str) -> str:
    return (f'< down({prof.type_pred}) . down({prof.subclass_pred})* '
            f'. [val("{cls}")] >')


def _has_out(pred: str) -> str:
    return f"< down({pred}) >"


def _has_in(pred: str) -> str:
    return f"< up({pred}) >"


def _local(term: str) -> str:
    return term.split(":", 1)[-1] if ":" in term else term


def _ast_names(node) -> List[str]:
    """Every ast node type name reachable from `node` (node or path)."""
    names = [type(node).__name__]
    for attr in ("path", "node", "inner", "left", "right"):
        child = getattr(node, attr, None)
        if child is not None:
            names += _ast_names(child)
    return names


def _assert_in_fragment(cid: str, antecedent: str, consequent: str) -> None:
    """Parse both sides with the real parser and confirm neither ast carries a negation
    or path-complement node. The parser already rejects the concrete syntax for these,
    so a ParseError here means the candidate left the fragment; the name walk is a
    defensive belt for any future ast node. Raises ValueError naming the offending cid."""
    for side, text in (("antecedent", antecedent), ("consequent", consequent)):
        try:
            tree = gxpath.parse_node(text)
        except gxpath.ParseError as exc:
            raise ValueError(f"{cid}: {side} left the positive fragment: {exc}") from exc
        bad = _FORBIDDEN_AST_NAMES.intersection(_ast_names(tree))
        if bad:
            raise ValueError(f"{cid}: {side} contains a forbidden node {sorted(bad)}")


 
# candidate generation per shape
 

def _mineable_predicates(prof: _Profile) -> List[str]:
    return sorted(p for p in prof.src_of
                  if p not in (prof.type_pred, prof.subclass_pred))


def _exceptions(body: Set[str], satisfied: Set[str], cfg: DeriveConfig) -> List[str]:
    return sorted(body - satisfied)[: cfg.max_exceptions_listed]


def _emit(domain: str, kg: str, kind: str, role: str, key: str, antecedent: str,
          consequent: str, cfg: DeriveConfig, note: str) -> Constraint:
    cid = f"{domain}.{kg}.{role}.{key}.mined"
    _assert_in_fragment(cid, antecedent, consequent)
    return Constraint(
        cid=cid,
        domain=domain, kg=kg, kind=kind, tier="ptime_core", provenance="mined",
        direction=cfg.direction_for(kind), antecedent=antecedent, consequent=consequent,
        note=note,
        params={"miner": "profile_v1"},
    )


@dataclass
class _Candidate:
    """One generated candidate carried through scoring, reduced-cover, and reporting.
    `body` is the antecedent's node set (used only for reduced-cover subsumption; it
    never enters the JSON, only its size does). `consequent_key` groups candidates that
    share a consequent so redundancy can be judged within a group."""
    constraint: Constraint
    report: Dict
    body: frozenset
    consequent_key: str


@dataclass
class _Atom:
    """A single positive existence test used as a building block of the conjunction
    lattice: < down(P) >, < up(P) >, or (when path mining is on) a forward path."""
    text: str
    key: str
    body: frozenset


def _domain_range_candidates(prof: _Profile, domain: str, kg: str, cfg: DeriveConfig,
                             is_range: bool) -> List[_Candidate]:
    out: List[_Candidate] = []
    role = "rng" if is_range else "dom"
    kind = "existential_range" if is_range else "existential_domain"
    endpoints_of = prof.tgt_of if is_range else prof.src_of
    for pred in _mineable_predicates(prof):
        body = set(endpoints_of.get(pred, set()))
        if len(body) < cfg.min_support:
            continue
        chosen, runners = _select_class(prof, body, cfg)
        if chosen is None:
            continue
        antecedent = _has_in(pred) if is_range else _has_out(pred)
        consequent = _tau(prof, chosen.cls)
        gloss = (f"nodes that are the target of {pred} are typed {chosen.cls}"
                 if is_range else
                 f"nodes with an outgoing {pred} edge are typed {chosen.cls}")
        con = _emit(domain, kg, kind, role, _local(pred), antecedent, consequent, cfg, gloss)
        contaminated, top = _contamination(prof, body, chosen.cls, cfg)
        satisfied = body & prof.class_instances.get(chosen.cls, set())
        report = {
            "kind": kind, "human_gloss": gloss, "class": chosen.cls, "predicate": pred,
            "support": chosen.support, "body_size": chosen.body_size,
            "standard_conf": round(chosen.standard_conf, 4), "pca_conf": round(chosen.pca_conf, 4),
            "exceptions": _exceptions(body, satisfied, cfg),
            "runner_up_classes": [r.cls for r in runners[:5]],
            "contamination": contaminated, "contamination_class": top,
            "low_trust": False,
        }
        out.append(_Candidate(con, report, frozenset(body), f"class:{chosen.cls}"))
    return out


def _forward_path_body(prof: _Profile, labels: Tuple[str, ...]) -> frozenset:
    """Start nodes of a forward path down(labels[0]) . down(labels[1]) . ... computed by
    walking the label chain backwards over the edge index. Forward-only, so it stays a
    positive path node expression."""
    starts = set(prof.src_of.get(labels[-1], set()))
    for lab in reversed(labels[:-1]):
        prev = {x for x in prof.src_of.get(lab, set()) if prof.g.succ(lab, x) & starts}
        starts = prev
    return frozenset(starts)


def _level1_atoms(prof: _Profile, cfg: DeriveConfig) -> List[_Atom]:
    """Frequent single-step atoms (down and up), plus forward-path atoms when
    max_path_depth > 1. Only atoms whose body clears min_support are kept, so the
    lattice starts from frequent building blocks."""
    atoms: Dict[str, _Atom] = {}
    for pred in _mineable_predicates(prof):
        s = frozenset(prof.src_of.get(pred, set()))
        if len(s) >= cfg.min_support:
            atoms[f"d_{_local(pred)}"] = _Atom(_has_out(pred), f"d_{_local(pred)}", s)
        t = frozenset(prof.tgt_of.get(pred, set()))
        if len(t) >= cfg.min_support:
            atoms[f"u_{_local(pred)}"] = _Atom(_has_in(pred), f"u_{_local(pred)}", t)
    if cfg.max_path_depth > 1:
        preds = [p for p in _mineable_predicates(prof)
                 if len(prof.src_of.get(p, set())) >= cfg.min_support]
        frontier = [(p,) for p in preds]
        for _depth in range(2, cfg.max_path_depth + 1):
            nxt: List[Tuple[str, ...]] = []
            for labels in frontier:
                for p in preds:
                    ext = labels + (p,)
                    body = _forward_path_body(prof, ext)
                    if len(body) < cfg.min_support:      # anti-monotone on path length
                        continue
                    text = "< " + " . ".join(f"down({lab})" for lab in ext) + " >"
                    key = "p_" + "_".join(_local(lab) for lab in ext)
                    atoms[key] = _Atom(text, key, body)
                    nxt.append(ext)
            frontier = nxt
    return [atoms[k] for k in sorted(atoms)]


def _typing_candidates(prof: _Profile, domain: str, kg: str, cfg: DeriveConfig
                       ) -> List[_Candidate]:
    """Level-wise conjunction lattice over frequent atoms, pruned anti-monotonically by
    antecedent support: a conjoined body below min_support is neither emitted nor
    extended. Single-atom antecedents are the domain/range shapes and are emitted there,
    so only conjunctions of two or more atoms become typing_existence candidates."""
    out: List[_Candidate] = []
    if cfg.max_typing_antecedent_atoms < 2:
        return out
    atoms = _level1_atoms(prof, cfg)
    by_key = {a.key: a for a in atoms}
    current: Dict[Tuple[str, ...], frozenset] = {(a.key,): a.body for a in atoms}
    for _k in range(2, cfg.max_typing_antecedent_atoms + 1):
        nxt: Dict[Tuple[str, ...], frozenset] = {}
        for combo in sorted(current):
            for a in atoms:
                if a.key <= combo[-1]:                    # ascending order, no self/dup
                    continue
                body = current[combo] & a.body
                if len(body) < cfg.min_support:           # anti-monotone pruning
                    continue
                new_combo = combo + (a.key,)
                nxt[new_combo] = body
                chosen, runners = _select_class(prof, set(body), cfg)
                if chosen is None:
                    continue
                atom_objs = [by_key[k] for k in new_combo]
                antecedent = " & ".join(a2.text for a2 in atom_objs)
                consequent = _tau(prof, chosen.cls)
                joined = " and ".join(a2.text for a2 in atom_objs)
                gloss = f"nodes matching {joined} are typed {chosen.cls}"
                con = _emit(domain, kg, "typing_existence", "typ",
                            "_".join(a2.key for a2 in atom_objs), antecedent, consequent,
                            cfg, gloss)
                satisfied = set(body) & prof.class_instances.get(chosen.cls, set())
                report = {
                    "kind": "typing_existence", "human_gloss": gloss, "class": chosen.cls,
                    "predicate": antecedent, "support": chosen.support,
                    "body_size": chosen.body_size,
                    "standard_conf": round(chosen.standard_conf, 4),
                    "pca_conf": round(chosen.pca_conf, 4),
                    "exceptions": _exceptions(set(body), satisfied, cfg),
                    "runner_up_classes": [r.cls for r in runners[:5]],
                    "contamination": False, "contamination_class": None, "low_trust": False,
                }
                out.append(_Candidate(con, report, body, f"class:{chosen.cls}"))
        current = nxt
    return out


def _requires_candidates(prof: _Profile, domain: str, kg: str, cfg: DeriveConfig
                         ) -> List[_Candidate]:
    """instances of C must carry an outgoing P edge. PCA cannot rescue these: a missing
    edge is exactly the violation the repair engine exists to fix, so pca is reported
    equal to standard confidence and every candidate is flagged low_trust."""
    out: List[_Candidate] = []
    # only classes that are a direct type target of enough nodes, to bound the search
    direct_count: Dict[str, int] = defaultdict(int)
    for _node, classes in prof.direct_types.items():
        for c in classes:
            direct_count[c] += 1
    req_classes = sorted(c for c, n in direct_count.items() if n >= cfg.min_support)
    for cls in req_classes:
        body = prof.class_instances.get(cls, set())
        if len(body) < cfg.min_support:
            continue
        for pred in _mineable_predicates(prof):
            carriers = body & prof.src_of.get(pred, set())
            support = len(carriers)
            conf = support / len(body) if body else 0.0
            if support < cfg.min_support or conf < cfg.min_pca_confidence:
                continue
            antecedent = _tau(prof, cls)
            consequent = _has_out(pred)
            gloss = f"instances of {cls} have an outgoing {pred} edge"
            con = _emit(domain, kg, "requires_statement", "req",
                        f"{_local(cls)}.{_local(pred)}", antecedent, consequent, cfg, gloss)
            report = {
                "kind": "requires_statement", "human_gloss": gloss, "class": cls,
                "predicate": pred, "support": support, "body_size": len(body),
                "standard_conf": round(conf, 4), "pca_conf": round(conf, 4),
                "exceptions": _exceptions(body, carriers, cfg),
                "runner_up_classes": [],
                "contamination": False, "contamination_class": None,
                "low_trust": True,
                "low_trust_reason": "missing-edge ambiguity; prefer schema declaration",
            }
            out.append(_Candidate(con, report, frozenset(body), f"pred:{pred}"))
    return out


def _reduced_cover(cands: List[_Candidate]) -> Dict[str, str]:
    """Redundancy pruning by subsumption. Within a group of candidates that share a
    consequent, a candidate B is redundant when another candidate A has an antecedent
    body that is a superset of B's (A's rule is more general, so it already implies B's
    rule over B's smaller body). Return cid -> subsuming cid for every redundant B. The
    kept candidate in each group is the one carrying the more general antecedent; equal
    bodies are broken by cid so the choice is deterministic."""
    groups: Dict[str, List[_Candidate]] = defaultdict(list)
    for c in cands:
        groups[c.consequent_key].append(c)
    subsumed: Dict[str, str] = {}
    for _key, group in sorted(groups.items()):
        for b in group:
            subsumers = []
            for a in group:
                if a.constraint.cid == b.constraint.cid:
                    continue
                if a.body >= b.body and not (a.body == b.body
                                             and a.constraint.cid > b.constraint.cid):
                    subsumers.append(a)
            if subsumers:
                best = sorted(subsumers, key=lambda a: (-len(a.body), a.constraint.cid))[0]
                subsumed[b.constraint.cid] = best.constraint.cid
    return subsumed


 
# the search generator, adapted to the same result shape
 
#: cid role tag per shape, so a cid still says at a glance what kind of rule it is.
_ROLE = {"existential_domain": "dom", "existential_range": "rng",
         "typing_existence": "typ", "requires_statement": "req",
         "weakening": "wkn"}

_STEP_RE = re.compile(r"\b(down|up)\(([^)]+)\)")


def _search_config(cfg: DeriveConfig) -> "search.SearchConfig":
    """The search's floors and bounds, read off the derivation config.

    One config, two generators: a caller that lowers `min_support` lowers it for
    whichever generator runs, so the two stay comparable at the same settings.
    """
    return search.SearchConfig(min_support=cfg.min_support,
                               min_confidence=cfg.min_pca_confidence,
                               max_antecedent=cfg.max_typing_antecedent_atoms,
                               max_path=cfg.max_path_depth,
                               type_predicate=cfg.type_predicate,
                               subclass_predicate=cfg.subclass_predicate)


def _shape_of(body_key: Tuple[str, ...], head_is_class: bool) -> str:
    """Which of the four repairable shapes a scored pair is.

    The search does not generate by shape, so the shape is read back off what it
    produced. A class-test head over a single outgoing-step body is an existential
    domain rule, over a single incoming-step body an existential range rule, and
    over anything else (a conjunction, or a class test) a typing-existence rule. A
    step head is a requires-statement rule whatever its body: it says the nodes the
    body describes must carry that edge.
    """
    if head_is_class:
        if len(body_key) == 1 and body_key[0].startswith("d_"):
            return "existential_domain"
        if len(body_key) == 1 and body_key[0].startswith("u_"):
            return "existential_range"
        return "typing_existence"
    return "requires_statement"


def _atom_slug(key: str) -> str:
    return f"{key[0]}.{_local(key[2:])}"


def _head_slug(text: str, cls: Optional[str]) -> str:
    if cls is not None:
        return _local(cls)
    return "_".join(f"{d[0]}.{_local(label)}" for d, label in _STEP_RE.findall(text))


def _predicate_of(text: str) -> Optional[str]:
    """The single non-structural predicate an expression names, when there is one."""
    labels = [label for _direction, label in _STEP_RE.findall(text)]
    return labels[0] if len(labels) == 1 else None


def _search_report_row(cid: str, kind: str, gloss: str, cls: Optional[str],
                       predicate: Optional[str], support: int, body_size: int,
                       standard_conf: float, pca_conf: float,
                       exceptions: List[str], low_trust: bool) -> Dict:
    """One approval payload, with the same keys `derive_by_shapes` emits.

    Two keys the search cannot fill are carried as their empty value rather than
    dropped, so a reader of either generator's report sees one schema:
    `contamination` (the shape sweep's cross-domain flag, which has no counterpart
    here) and `runner_up_classes` (the shape sweep picks one class per body and
    lists the rest; the search scores every class as its own candidate instead, so
    the runners-up are separate rows rather than a field).
    """
    row = {"cid": cid, "kind": kind, "human_gloss": gloss, "class": cls,
           "predicate": predicate, "support": support, "body_size": body_size,
           "standard_conf": round(standard_conf, 4), "pca_conf": round(pca_conf, 4),
           "exceptions": exceptions, "runner_up_classes": [],
           "contamination": False, "contamination_class": None,
           "low_trust": low_trust}
    if low_trust:
        row["low_trust_reason"] = "missing-edge ambiguity; prefer schema declaration"
    return row


def _search_gloss(kind: str, cls: Optional[str], predicate: Optional[str],
                  body_text: str, head_text: str) -> str:
    if kind == "existential_domain":
        return f"nodes with an outgoing {predicate} edge are typed {cls}"
    if kind == "existential_range":
        return f"nodes that are the target of {predicate} are typed {cls}"
    if kind == "typing_existence":
        return f"nodes matching {body_text} are typed {cls}"
    return f"nodes matching {body_text} have {head_text}"


def _derive_by_search(graph: DataGraph, domain: str, kg: str, cfg: DeriveConfig,
                      reference_graph: Optional[DataGraph]) -> DerivationResult:
    """Run `kgrepair.search` and present what it admitted as a `DerivationResult`.

    Everything scored here is scored by the search. This function names shapes,
    writes glosses and collects exceptions; it applies no floor of its own and
    admits nothing the search did not admit, so the two pruning laws and their
    oracle remain the only account of what is in the result.

    Widenings travel as `weakening` candidates whose consequent is the disjunction
    residual profiling proposed. The original failed the confidence floor and is
    not admitted on its own; the widening is what a reviewer is asked about, and
    the gloss carries the original's numbers so the two can be compared.
    """
    source = reference_graph if reference_graph is not None else graph
    result = search.search(source, _search_config(cfg))
    vocab = result.vocabulary

    space = search.NodeSpace(source)
    ext = search.Extensions(source, space)
    class_of = {search.tau_text(vocab.type_predicate, vocab.subclass_predicate, c): c
                for c in vocab.classes}

    cs = ConstraintSet(f"mined@{domain}@{kg}")
    report: List[Dict] = []
    stats: Dict[str, int] = defaultdict(int)

    def emit(kind: str, antecedent: str, consequent: str, row: Dict) -> None:
        _assert_in_fragment(row["cid"], antecedent, consequent)
        cs.add(Constraint(cid=row["cid"], domain=domain, kg=kg, kind=kind,
                          tier="ptime_core", provenance="mined",
                          direction=cfg.direction_for(kind), antecedent=antecedent,
                          consequent=consequent, note=row["human_gloss"],
                          params={"miner": "search_v1"}))
        report.append(row)
        stats[kind] += 1

    def exceptions_of(body_text: str, head_text: str) -> List[str]:
        witnesses = space.to_nodes(ext.of(body_text) & ~ext.of(head_text)
                                   & space.universe)
        return sorted(witnesses)[: cfg.max_exceptions_listed]

    for scored in result.admitted:
        cls = class_of.get(scored.head_text)
        kind = _shape_of(scored.body_key, cls is not None)
        predicate = (_predicate_of(scored.head_text) if kind == "requires_statement"
                     else _predicate_of(scored.body_text))
        cid = (f"{domain}.{kg}.{_ROLE[kind]}."
               f"{'_'.join(_atom_slug(k) for k in scored.body_key)}"
               f"-{_head_slug(scored.head_text, cls)}.mined")
        emit(kind, scored.body_text, scored.head_text, _search_report_row(
            cid, kind, _search_gloss(kind, cls, predicate, scored.body_text,
                                     scored.head_text),
            cls, predicate, scored.support, scored.body_size,
            scored.support / scored.body_size if scored.body_size else 0.0,
            scored.confidence, exceptions_of(scored.body_text, scored.head_text),
            low_trust=(kind == "requires_statement")))

    for widening in result.widenings:
        original = widening.original
        cls = class_of.get(original.head_text)
        cid = (f"{domain}.{kg}.{_ROLE['weakening']}."
               f"{'_'.join(_atom_slug(k) for k in original.body_key)}"
               f"-{_head_slug(original.head_text, cls)}"
               f"+{_atom_slug(widening.atom_key)}.mined")
        gloss = (f"nodes matching {original.body_text} have {original.head_text}, "
                 f"or match the broader alternative recorded with this entry; the "
                 f"narrow reading held for {original.support} of "
                 f"{original.denominator} judged nodes")
        row = _search_report_row(
            cid, "weakening", gloss, cls,
            _predicate_of(original.head_text) if cls is None else None,
            widening.support, original.body_size,
            widening.support / original.body_size if original.body_size else 0.0,
            widening.confidence, exceptions_of(original.body_text, widening.head_text),
            low_trust=True)
        row["low_trust_reason"] = (
            f"a widening is a second reading of a rule that failed; the narrow "
            f"reading scored {round(original.confidence, 4)}")
        emit("weakening", original.body_text, widening.head_text, row)

    report.sort(key=lambda r: (-r["pca_conf"], -r["support"], r["cid"]))
    for row in report:
        # The search's dominance pass absorbed the shape sweep's reduced cover, so
        # nothing that reaches here has already been beaten. The keys stay so both
        # generators report one schema.
        row["pruned_redundant"] = False
        row["subsumed_by"] = None
        row["witnesses_on_target"] = None

    if reference_graph is not None:
        target_validator = Validator(graph)
        by_cid = {r["cid"]: r for r in report}
        for c in cs:
            by_cid[c.cid]["witnesses_on_target"] = target_validator.check_one(c).count

    stats["emitted"] = len(cs)
    stats["pruned_redundant"] = result.dominated
    stats["total_generated"] = len(cs) + result.dominated + result.tautologies
    stats["tautologies_blocked"] = result.tautologies
    stats["prefixes_refused"] = result.prefixes_refused
    return DerivationResult(
        constraints=cs, report=report, stats=dict(sorted(stats.items())),
        vocab={"type_predicate": vocab.type_predicate,
               "subclass_predicate": vocab.subclass_predicate})


 
# entry point
 

def derive_candidates(graph: DataGraph, domain: str, kg: str,
                      config: DeriveConfig = DeriveConfig(),
                      reference_graph: Optional[DataGraph] = None) -> DerivationResult:
    """Returns a `DerivationResult` from whichever generator `config` selects.

    Two generators produce the same shape of result and are interchangeable here:

      * `"search"` (the default since P4d) is the two-axis search in
        `kgrepair.search`: a conjunction lattice on the antecedent and a walked
        head axis on the consequent, both pruned by laws checked against an
        unpruned oracle on every build. It reaches rules the shape sweep has no
        template for, and it emits the residual widenings the shape sweep cannot
        express at all.
      * `"shapes"` is the original sweep below, one hand-written template per
        repairable shape. It keeps its own tests and stays selectable; it is the
        only one that flags cross-domain contamination and records runner-up
        classes, neither of which the search reproduces.

    The switch to `"search"` as the default is recorded with its evidence.
    A candidate file records which generator produced it.
    """
    if config.generator == SEARCH:
        return _derive_by_search(graph, domain, kg, config, reference_graph)
    if config.generator != SHAPES:
        raise ValueError(f"unknown generator {config.generator!r}; "
                         f"expected one of {list(GENERATORS)}")
    return derive_by_shapes(graph, domain, kg, config, reference_graph)


def derive_by_shapes(graph: DataGraph, domain: str, kg: str,
                     config: DeriveConfig = DeriveConfig(),
                     reference_graph: Optional[DataGraph] = None) -> DerivationResult:
    """Returns a `DerivationResult`: scored candidates, not yet reviewable.

    Profiles a graph and emits in-fragment ptime_core constraint candidates for the
    (domain, kg) slice. The result carries the emitted candidates as a ConstraintSet
    (redundant ones removed by reduced-cover), a per-candidate approval report
    (sorted by pca_conf then support), and counts. `proposals.derive_candidate_file`
    is the layer above that turns this into a reviewable file; this function is
    internal and its signature may change.

    Clean-subset baseline: when `reference_graph` is given, all profiling, generation,
    scoring, and pruning run on that curated clean graph, and each emitted candidate then
    reports witnesses_on_target: how many violation witnesses it has on the (dirtier)
    `graph`. This separates what should hold from what currently holds. The curated
    subset is supplied by the caller; this function never constructs it. When
    `reference_graph` is None the behaviour is unchanged and witnesses_on_target is null.
    """
    source = reference_graph if reference_graph is not None else graph
    type_pred, subclass_pred = _detect_vocabulary(set(source.labels), sorted(source.edges()), config)
    prof = _Profile(source, type_pred, subclass_pred)

    cands: List[_Candidate] = []
    cands += _domain_range_candidates(prof, domain, kg, config, is_range=False)
    cands += _domain_range_candidates(prof, domain, kg, config, is_range=True)
    cands += _typing_candidates(prof, domain, kg, config)
    cands += _requires_candidates(prof, domain, kg, config)

    subsumed = _reduced_cover(cands)                 # cid -> subsuming cid
    target_validator = Validator(graph) if reference_graph is not None else None

    cs = ConstraintSet(f"mined@{domain}@{kg}")
    report: List[Dict] = []
    for cand in sorted(cands, key=lambda c: c.constraint.cid):
        cid = cand.constraint.cid
        is_pruned = cid in subsumed
        row = {"cid": cid, **cand.report,
               "pruned_redundant": is_pruned,
               "subsumed_by": subsumed.get(cid),
               "witnesses_on_target": None}
        if not is_pruned:
            cs.add(cand.constraint)
            if target_validator is not None:
                row["witnesses_on_target"] = target_validator.check_one(cand.constraint).count
        report.append(row)
    report.sort(key=lambda r: (-r["pca_conf"], -r["support"], r["cid"]))

    stats: Dict[str, int] = defaultdict(int)
    for cand in cands:
        if cand.constraint.cid not in subsumed:
            stats[cand.report["kind"]] += 1
    stats["emitted"] = sum(1 for c in cands if c.constraint.cid not in subsumed)
    stats["pruned_redundant"] = len(subsumed)
    stats["total_generated"] = len(cands)

    return DerivationResult(
        constraints=cs, report=report, stats=dict(sorted(stats.items())),
        vocab={"type_predicate": type_pred, "subclass_predicate": subclass_pred},
    )


def validates_clean(graph: DataGraph, result: DerivationResult) -> bool:
    """Round-trip guard: every emitted candidate parses and runs through the Validator
    with no error. Used by the test suite and available to callers before approval."""
    Validator(graph).validate(result.constraints)
    return True
