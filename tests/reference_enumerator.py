"""
The reference enumerator: an exhaustive, unpruned oracle for the candidate search.

This is a permanent part of the test tree, not scaffolding for one phase. Its job
is to score the whole candidate space with nothing pruned, so that any pruning
rule anywhere in `kgrepair.search` can be checked by asserting the pruned search
admits exactly what this admits. A pruning rule that is not checked against this
is not finished.

What it shares with the search, and what it does not
---------------------------------------------------
It shares the **space**: the same atom and head vocabulary, from
`search.vocabulary`. If the two disagreed about which expressions exist, agreeing
about which ones are admitted would mean nothing.

It shares nothing else. In particular it does not import the bitset machinery,
the lattice, the head axis, `search.score`, `search.admits` or `search.lead`:

  * extensions are node **sets**, from the parser and the evaluator on the
    expression text, not bitsets over a node ordering;
  * the denominator is derived here from the definition, by taking the head's
    first step from the step tuple this module built, rather than by walking an
    abstract syntax tree;
  * the three admission comparisons are written out inline, so a threshold that
    changed on one side and not the other shows up as a disagreement.

That independence is the point. Two implementations of one definition, one of
them obviously correct and far too slow, is what makes the fast one testable.

Cost
----
Exhaustive means exhaustive: every conjunction to `max_antecedent` against every
head to `max_path`, each evaluated from its text. That is fine on the hand-built
graphs and workable on a real slice only with the floors set high and the bounds
set low. Callers pick a config they can afford; nothing here is tuned.
"""
from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from typing import Dict, FrozenSet, List, Optional, Set, Tuple

from kgrepair import gxpath
from kgrepair.search import (SearchConfig, Vocabulary, head_text, step_text,
                             tau_text, vocabulary)

#: What the oracle and the search compare on: (antecedent atom keys, head text).
Identity = Tuple[Tuple[str, ...], str]


@dataclass
class Enumerated:
    """Everything the oracle scored, what cleared the floors, and what survives
    dominance.

    `admitted` is the floors alone over the pairs that are candidates at all, which
    is what the two pruning laws of P4a are checked against. A pair whose head
    restates an antecedent atom is not one: it is refused at generation on both
    sides, so it appears in neither `scored` nor `admitted`. `dominant` is
    `admitted` after the same shaping filter the search applies, which is what the
    search's own output is compared with.
    """
    admitted: Dict[Identity, Tuple[int, int, float]] = field(default_factory=dict)
    dominant: Dict[Identity, Tuple[int, int, float]] = field(default_factory=dict)
    scored: Dict[Identity, Tuple[int, int, float]] = field(default_factory=dict)
    bodies: int = 0
    heads: int = 0

    @property
    def identities(self) -> FrozenSet[Identity]:
        return frozenset(self.dominant)

    @property
    def admitted_identities(self) -> FrozenSet[Identity]:
        return frozenset(self.admitted)


def all_bodies(vocab: Vocabulary, max_antecedent: int) -> List[Tuple[Tuple[str, ...], str]]:
    """Every conjunction of one to `max_antecedent` atoms, nothing dropped.

    `vocab.atoms` is sorted by key and `combinations` preserves that order, so a
    body's key is ascending and each combination appears once. No support floor is
    applied: the floor is the search's pruning rule, and this is what it is
    checked against.
    """
    out: List[Tuple[Tuple[str, ...], str]] = []
    for size in range(1, max_antecedent + 1):
        for combo in itertools.combinations(vocab.atoms, size):
            out.append((tuple(a.key for a in combo),
                        " & ".join(a.text for a in combo)))
    return out


def all_heads(vocab: Vocabulary, max_path: int) -> List[Tuple[str, str]]:
    """Every head, as `(head text, lead text)`, nothing refused.

    The lead is read straight off the definition rather than off the syntax tree:
    a class test leads with having a type edge at all, and a step chain leads with
    its first step. `search.lead` computes the same thing by a different route,
    which is what makes it testable here.
    """
    out: List[Tuple[str, str]] = []
    type_lead = f"< down({vocab.type_predicate}) >"
    for cls in vocab.classes:
        out.append((tau_text(vocab.type_predicate, vocab.subclass_predicate, cls),
                    type_lead))
    for length in range(1, max_path + 1):
        for steps in itertools.product(vocab.steps, repeat=length):
            out.append((head_text(steps), f"< {step_text(steps[0])} >"))
    return out


def enumerate_all(graph, cfg: SearchConfig = SearchConfig(),
                  vocab: Optional[Vocabulary] = None) -> Enumerated:
    """Score every body against every head. Nothing is pruned and nothing is
    generated lazily, so the result is the whole truth about this space."""
    vocab = vocab if vocab is not None else vocabulary(graph, cfg)
    ev = gxpath.Evaluator(graph, use_closure=True)
    cache: Dict[str, Set[str]] = {}

    def extension(text: str) -> Set[str]:
        got = cache.get(text)
        if got is None:
            got = ev.eval_node(gxpath.parse_node(text))
            cache[text] = got
        return got

    bodies = all_bodies(vocab, cfg.max_antecedent)
    heads = all_heads(vocab, cfg.max_path)
    result = Enumerated(bodies=len(bodies), heads=len(heads))
    body_extension: Dict[Tuple[str, ...], Set[str]] = {}
    atom_text = {a.key: a.text for a in vocab.atoms}

    for body_key, body_text in bodies:
        body = extension(body_text)
        body_extension[body_key] = body
        own_atoms = {atom_text[k] for k in body_key}
        for head, lead in heads:
            if head in own_atoms:
                # The same generation-time block the search applies: a head that
                # restates one of its own antecedent atoms is not a candidate.
                # Written out here rather than imported, like the rest of this
                # module, so a block that changed on one side shows up as a
                # disagreement. `search.is_tautology` says why it is blocked.
                continue
            support = len(body & extension(head))
            denominator = len(body & extension(lead))
            confidence = (support / denominator) if denominator else 0.0
            identity = (body_key, head)
            result.scored[identity] = (support, denominator, confidence)
            if (denominator >= 1
                    and support >= cfg.min_support
                    and confidence >= cfg.min_confidence):
                result.admitted[identity] = (support, denominator, confidence)

    result.dominant = dominance_filter(result.admitted, body_extension, atom_text)
    return result


def dominance_filter(admitted: Dict[Identity, Tuple[int, int, float]],
                     body_extension: Dict[Tuple[str, ...], Set[str]],
                     atom_text: Dict[str, str]
                     ) -> Dict[Identity, Tuple[int, int, float]]:
    """The search's shaping rule, applied here as a plain pass over everything.

    A candidate goes when another admitted candidate under the same head has an
    antecedent that is at least as general and a confidence at least as high.
    "At least as general" is containment of the node sets, and equal node sets are
    broken on atom count and then on the key, so exactly one of two interchangeable
    candidates survives.

    Written as a post-pass over the whole admitted set, against the search's
    online version which only ever compares with what it has already kept. The two
    have to agree, and a test asserts they do: dominance is transitive, so if
    anything dominates a candidate then something the online pass kept does too.
    """
    # A rule that restates one of its own atoms goes first, and goes entirely: it
    # cannot survive and it cannot dominate anything either. Leaving it in the
    # dominating set would let it suppress the rules that do say something, which
    # is the failure it was removed for.
    #
    # Second line of defence. `enumerate_all` already refuses these at generation,
    # the way the search does, so this pass should never have one to remove. It is
    # kept because it costs one set comprehension and because a tautology reaching
    # the dominating set is the specific failure that silently empties a head.
    eligible = {identity: numbers for identity, numbers in admitted.items()
                if identity[1] not in {atom_text[k] for k in identity[0]}}

    out: Dict[Identity, Tuple[int, int, float]] = {}
    for (body_key, head), (support, denominator, confidence) in eligible.items():
        body = body_extension[body_key]
        beaten = False
        for (other_key, other_head), (_s, _d, other_conf) in eligible.items():
            if other_head != head or other_key == body_key:
                continue
            other = body_extension[other_key]
            if other_conf < confidence or not body <= other:
                continue
            if other != body or (len(other_key), other_key) < (len(body_key), body_key):
                beaten = True
                break
        if not beaten:
            out[(body_key, head)] = (support, denominator, confidence)
    return out


def witnesses(graph, body_text: str, head_text_: str) -> Set[str]:
    """`[[phi]] \\ [[psi]]`: the violation set, silent nodes included.

    Deliberately not the confidence denominator. Kept here so a test can hold the
    two definitions side by side in one file.
    """
    ev = gxpath.Evaluator(graph, use_closure=True)
    return (ev.eval_node(gxpath.parse_node(body_text))
            - ev.eval_node(gxpath.parse_node(head_text_)))
