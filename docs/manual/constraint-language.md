# The constraint language — Reg-GXPath_pos

[← Manual index](README.md)

Constraint expressions are written in **Reg-GXPath_pos**, the positive fragment
of Reg-GXPath: a two-sorted regular path language over data-graphs, with node
expressions denoting *sets of nodes* and path expressions denoting *binary
relations on nodes*.

This page is the complete specification of the surface syntax you write in a
constraint file, the abstract syntax it compiles to, and how it is evaluated.

---

## Surface syntax

The concrete syntax is deliberately ASCII and paste-safe, so it survives being
embedded in JSON without escaping games.

```
node   := disj
disj   := conj ( '|' conj )*                    # union
conj   := atom ( '&' atom )*                    # intersection
atom   := 'T'                                   # all nodes
        | 'val(' STRING ')'                     # data value equals a constant
        | '<' path '>'                          # a path departs from here
        | '(' node ')'

path   := seqp
seqp   := altp ( '.' altp )*                    # composition
altp   := unary ( '+' unary )*                  # union
unary  := postfix
postfix:= prim ( '*' )?                         # Kleene star
prim   := 'eps'                                 # identity
        | 'down(' NAME ')'   |  '>' NAME        # one forward hop
        | 'up('   NAME ')'   |  '<' NAME        # one backward hop
        | '[' node ']'                          # node test
        | '(' path ')'
        | 'isect(' path ',' path ')'            # bounded intersection
```

- **`STRING`** is a single- or double-quoted literal.
- **`NAME`** is a bareword edge label matching `[A-Za-z0-9_:/.#-]+`, which covers
  prefixed IRIs such as `wdt:P31` and `rdfs:subClassOf`.
- Whitespace is insignificant. `#` inside a `NAME` is a label character, not a
  comment — the constraint language has no comments (use the `note` field).

### Precedence

From loosest to tightest:

| Sort | Operator | Associativity |
|---|---|---|
| node | `\|` (union) | left |
| node | `&` (intersection) | left |
| path | `.` (composition) | left |
| path | `+` (union) | left |
| path | `*` (Kleene star) | postfix |

Parenthesise anything you would otherwise have to think about.

### Operator reference

**Node expressions** — each denotes a set of nodes.

| Syntax | Denotes | Example |
|---|---|---|
| `T` | every node in the graph | `T` |
| `val("c")` | nodes whose data value is exactly `c` | `val("wd:Q515")` |
| `< path >` | nodes from which at least one `path` departs | `< down(wdt:P17) >` |
| `φ & ψ` | intersection | `< down(wdt:P17) > & < down(wdt:P131) >` |
| `φ \| ψ` | union | `< down(wdt:P780) > \| < down(wdt:P828) >` |
| `( φ )` | grouping | |

**Path expressions** — each denotes a binary relation on nodes.

| Syntax | Shorthand | Denotes |
|---|---|---|
| `eps` | | identity: every node related to itself |
| `down(a)` | `>a` | one forward hop along label `a` |
| `up(a)` | `<a` | one backward hop along label `a` |
| `a . b` | | composition: follow `a`, then `b` |
| `a + b` | | union: either `a` or `b` |
| `a*` | | Kleene star: zero or more repetitions |
| `[ φ ]` | | node test: identity restricted to nodes satisfying `φ` |
| `isect(a, b)` | | intersection of two path relations (**bounded shapes only**) |
| `( a )` | | grouping |

The `>a` / `<a` shorthands exist because the fixtures use them; `down(...)` and
`up(...)` are clearer in a constraint file and are what the built-in sets use.

---

## Rejected constructs

Three constructs are refused by the lexer/parser **on sight**, before any
evaluation, each with a diagnostic naming the reason:

| Written as | Rejected because |
|---|---|
| `!` or `not` | node complement `¬φ` leaves Reg-GXPath_pos |
| `~` or `compl` | path complement `ā` leaves Reg-GXPath_pos |
| `#` or `neq` | data disequality requires negation |

```python
>>> from kgrepair.gxpath import parse_node, ParseError
>>> parse_node("not < down(wdt:P17) >")
ParseError: node complement (not phi) leaves Reg-GXPath_pos
```

This is not stylistic. Node complement makes subset repair NP-complete (Thm 12)
and path complement makes superset repair undecidable (Thm 19). Rejecting them
at the surface is how the toolkit guarantees that anything it accepts, it can
repair in polynomial time.

Where the refusal surfaces depends on the path:

| Path | When it raises |
|---|---|
| `load_constraint_file(path, compile_now=True)` | at load |
| `load_constraint_file(path)` | at first evaluation of that constraint |
| `ConstraintSet.compile_all()` | immediately, for the whole set |
| `Constraint.compile()` | immediately, for one constraint |
| the review gate (`reviewed_constraint_set`) | before any engine, as `E-FRAGMENT` |
| the viewer's Load screen | at load, rendered as an in-app message |

---

## Abstract syntax

The parser produces frozen dataclasses in `kgrepair.gxpath.ast`. This module is
**internal and unstable** — it is documented because reading constraint code
requires it, not because it is a supported surface.

```
Path ::= Eps                       identity
       | Down(label)               forward hop
       | Up(label)                 backward hop
       | Seq(left, right)          a . b
       | Alt(left, right)          a + b
       | Star(inner)               a*
       | Isect(left, right)        a ∩ b     [bounded]
       | Test(node)                [φ]

Node ::= Top                       T
       | Has(path)                 <a>
       | ValueEq(const)            val("c")
       | Conj(left, right)         φ & ψ
       | Disj(left, right)         φ | ψ
```

Note what is **absent**: there is no `Not` and no `Compl` constructor. The
fragment's positivity is enforced by the type of the AST itself, not only by the
parser. An out-of-fragment expression is literally unrepresentable.

### Convenience builders

| Builder | Produces |
|---|---|
| `ast.seq_all(*parts)` | left-folds a chain of steps into nested `Seq` |
| `ast.type_test(type_label, subclass_label, class_value)` | the core type test `τ_C` |
| `ast.has_edge(label)` | `< down(label) >` |
| `ast.is_target_of(label)` | `< up(label) >` |

---

## The core type test

The single most important idiom in the language:

```
τ_C  =  < down(type) . down(subClassOf)* . [val("C")] >
```

In Wikidata vocabulary:

```
< down(wdt:P31) . down(wdt:P279)* . [val("wd:Q2221906")] >
```

Read left to right: *follow one typing edge, then zero or more subclass edges,
and check that where you land has data value `wd:Q2221906`.*

The `*` is what makes this work in practice. Without it the test would only
match nodes typed *exactly* `C`; with it, a node typed `City` satisfies
`τ_GeographicLocation` as long as a `City --subClassOf--> GeographicLocation`
chain exists in the graph, of any length.

Two things must line up for it to match anything:

1. The typing predicate in the expression (`wdt:P31`) must be a real label in
   your graph.
2. That predicate must be in the loader's `type_predicates` set, so the class
   node is self-valued and `val("...")` can reach it. See
   [Concepts § The typing spine](concepts.md#the-typing-spine-and-self-valued-class-nodes).

Miss the second and the test matches nothing, silently, and every node looks
like a violation.

---

## Evaluation semantics

Node expressions are evaluated to sets; path expressions are evaluated by
**backward pre-image** against a set of allowed endpoints. The full `V × V`
relation is never built.

```
pre(a, T) = { x : ∃ y ∈ T with (x, y) ∈ ⟦a⟧ }
⟦ <a> ⟧   = pre(a, V)
```

| Expression | Rule |
|---|---|
| `pre(eps, T)` | `T` |
| `pre(down_a, T)` | the `a`-predecessors of `T` |
| `pre(up_a, T)` | the `a`-successors of `T` |
| `pre(b . c, T)` | `pre(b, pre(c, T))` |
| `pre(b + c, T)` | `pre(b, T) ∪ pre(c, T)` |
| `pre(a*, T)` | least fixpoint of `X = T ∪ pre(a, X)` |
| `pre([φ], T)` | `T ∩ ⟦φ⟧` |
| `pre(b ∩ c, T)` | bounded endpoint-tagged reach — see below |

| Node expression | Rule |
|---|---|
| `⟦T⟧` | all of `V` |
| `⟦val("c")⟧` | `{ x : D(x) = c }` — a sparse scan of the value map alone |
| `⟦<a>⟧` | `pre(a, V)` |
| `⟦φ & ψ⟧` | `⟦φ⟧ ∩ ⟦ψ⟧` |
| `⟦φ \| ψ⟧` | `⟦φ⟧ ∪ ⟦ψ⟧` |

Every rule is set-at-a-time. The Kleene-star fixpoint terminates because `V` is
finite and `X` only grows; each round either adds a node or stops.

### Path intersection is restricted

`isect(a, b)` is the one construct that can force reasoning over *pairs* of
nodes, which is where a dense `V × V` blow-up would come from. Only the bounded
shape the shipped constraints use is supported — intersection where the two
sides share a given endpoint set, evaluated by endpoint-tagged reach. Anything
that would require dense pair enumeration **raises** rather than degrading
silently. If you hit this, restructure the constraint.

### Subclass-closure memoisation (`use_closure`)

`Evaluator`, `Validator`, `validate`, `subset_repair` and `superset_repair` all
accept `use_closure`. It memoises the pre-image of `Star(Down(label))` — in
practice the `subClassOf*` walk inside every `τ_C` — turning a per-witness
fixpoint into a cached lookup.

It is a **pure performance knob**: results are identical either way, which the
test suite verifies differentially. The cache is keyed by
`(label, target-set)` and guarded by the graph's per-label version counter, so
mutating the class spine transparently rebuilds it.

Measured payoff: about **4×** on deep-hierarchy repeated evaluations
(24.8 ms → 6.1 ms over 200 evaluations). Defaults differ by entry point:
`superset_repair` defaults to `True`, everything else to `False`. See
[Performance](performance.md).

---

## Worked examples

Every shipped constraint follows one of these five shapes.

### Existential domain — *"anything with an outgoing P is a C"*

```
φ:  < down(wdt:P17) >
ψ:  < down(wdt:P31) . down(wdt:P279)* . [val("wd:Q2221906")] >
```

*Every subject of `P17` (country) is a geographic location.* Witnesses: nodes
with a country edge that are not typed as, or as a subclass of, a geographic
location.

### Existential range — *"anything with an incoming P is a C"*

```
φ:  < up(wdt:P17) >
ψ:  < down(wdt:P31) . down(wdt:P279)* . [val("wd:Q6256")] >
```

*Every value of `P17` is a country.* Note `up(...)`: the antecedent selects
edge **targets**.

### Typing existence — *"anything shaped like a C should be typed C"*

```
φ:  < down(wdt:P17) > & < down(wdt:P131) >
ψ:  < down(wdt:P31) . down(wdt:P279)* . [val("wd:Q515")] >
```

*Anything with both a country and a located-in edge is a city.* The antecedent
conjunction is the structural signature; the consequent is the type it implies.

### Requires-statement — *"anything typed C must have a P"*

```
φ:  < down(wdt:P31) . down(wdt:P279)* . [val("wd:Q515")] >
ψ:  < down(wdt:P17) >
```

*Every city has a country.* The mirror image of typing existence, and the shape
superset repair fixes by minting a fresh target when no named one exists.

### Disjunctive requires-statement

```
φ:  < down(wdt:P31) . down(wdt:P279)* . [val("wd:Q12136")] >
ψ:  < down(wdt:P780) > | < down(wdt:P828) >
```

*Every disease states at least a symptom or a cause.* Superset repair satisfies
the **left** disjunct — here `P780` — a deterministic, documented choice.

### Typing inheritance

```
φ:  < down(wdt:P31) . down(wdt:P279)* . [val("wd:Q16521")] >
ψ:  < down(wdt:P31) . [val("wd:Q16521")] >
```

*If `x` is an instance of some subclass of Taxon, materialise the direct
`instance-of Taxon` edge* — collapsing `P31 . P279*` to a direct `P31`.

---

## Compiling and inspecting expressions

```python
from kgrepair.gxpath import parse_node, parse_path, ParseError, Evaluator

expr = parse_node('< down(wdt:P31) . down(wdt:P279)* . [val("wd:Q515")] >')

import kgrepair
graph = kgrepair.load_graph("slice.nt")
cities = Evaluator(graph, use_closure=True).eval_node(expr)
```

On a `Constraint`, the compiled sides are cached lazily on first access:

```python
c = constraint_set.constraints[0]
c.phi          # compiled antecedent AST (parses on first access)
c.psi          # compiled consequent AST
c.compile()    # force both now; raises ParseError if either leaves the fragment
```

`kgrepair.gxpath` is **not** part of the public API. `parse_node`, `Evaluator`
and the AST may change without notice. Anything you can express through a
constraint file is stable; reaching into the parser is not.

---

## Authoring checklist

Before shipping a constraint, check all seven:

1. **Both sides are node expressions.** `phi` and `psi` each denote a *set of
   nodes*, not a relation. A bare path is not a constraint side.
2. **It is a containment, not an implication.** Write "the nodes matching this
   shape are among the nodes matching that shape."
3. **No negation, complement, or disequality.** The parser will tell you, but
   knowing why saves a redesign.
4. **The typing predicate is in your loader's `type_predicates`.** Otherwise
   `val("C")` matches nothing.
5. **The tier is honest.** Anything with an upper bound, a pairwise condition, or
   a symmetry requirement is `boundary`, not `ptime_core`. Misclassifying it
   means an engine tries to repair something it provably cannot repair in
   polynomial time.
6. **`compile_now=True` while developing.** Fail at load, not at first
   evaluation.
7. **Check the cap fraction before trusting it.** A constraint that flags 40% of
   your nodes is a modelling error, and `check_cap` will refuse to act on it.

For the file format around these expressions, see
[File formats § Constraint set files](file-formats.md#constraint-set-files) and
[`docs/authoring_constraints.md`](../authoring_constraints.md).

---

Next: [Built-in constraint catalogue](constraint-catalogue.md) ·
[The repair engines](repair-engines.md)
