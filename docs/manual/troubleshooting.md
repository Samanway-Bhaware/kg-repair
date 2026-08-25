# Troubleshooting

[← Manual index](README.md)

Symptoms, causes, and fixes — ordered roughly by how often they come up.

---

## Everything is a violation

**Symptom.** A check reports witnesses for nearly every node, and `check_cap`
refuses to run any repair.

**By far the most likely cause: your typing spine is not declared.** Class tests
compile to `< down(type) . down(subClassOf)* . [val("C")] >`, and `val("C")`
only matches a node the loader made **self-valued** — which it does only for the
objects of `type_predicates`. If your graph uses `ex:isa` and you did not say so,
no class test matches anything, and every rule with a class consequent fails.

```bash
kgrepair check --in mine.nt --constraints mine.constraints.json \
               --type-predicate ex:isa --type-predicate ex:kindOf
```

```python
graph = kgrepair.load_graph("mine.nt", type_predicates={"ex:isa", "ex:kindOf"})
```

Confirm it worked:

```python
print(graph.value("ex:Artwork"))     # should be "ex:Artwork", not None
```

**Second cause: a predicate mismatch.** The constraint names `wdt:P31` and your
graph carries `<http://www.wikidata.org/prop/direct/P31>` — the loader preserves
both verbatim and never expands or abbreviates, so they are different labels.

```python
print(sorted(graph.labels)[:20])     # what your graph actually uses
```

**Third cause: the constraint set is for a different vocabulary.** Running
`--domain geography --kg wikidata` against a DBpedia graph produces exactly this
picture.

---

## Nothing is a violation, and that seems wrong

Same root causes in reverse. Class tests matching nothing makes rules with a
class **antecedent** vacuously satisfied — a requires-statement rule finds no
subjects and passes.

```python
report = kgrepair.validate(graph, constraints)
for v in report.violations:
    print(v.constraint.cid, v.count)     # every constraint, passing or failing
```

Check the antecedent extension directly:

```python
from kgrepair.gxpath import Evaluator
c = constraints.constraints[0]
print(len(Evaluator(graph).eval_node(c.phi)))    # 0 means the rule cannot fire
```

---

## `ParseError` on a constraint

```
ParseError: node complement (not phi) leaves Reg-GXPath_pos
ParseError: path complement (a-bar) leaves Reg-GXPath_pos
ParseError: data disequality (neq) requires negation
```

Not a bug. Those three constructs make repair intractable and are rejected on
sight. See [Constraint language § Rejected
constructs](constraint-language.md#rejected-constructs).

The usual fix is to **rewrite the rule as a containment**. "If a node is a City
it must not lack a country" becomes `τ(City) ⊑ < down(country) >`.

Fail early while developing:

```python
cs = kgrepair.load_constraint_file(path, compile_now=True)
```

Other parse errors:

| Message | Cause |
|---|---|
| `unexpected character '…' at position N` | a character outside the `NAME` set, unescaped. Quote it or check for a stray symbol |
| `expected ')', found …` | unbalanced parentheses or brackets |
| `could not parse term: '…'` | this is the **N-Triples loader**, not the expression parser — see below |

---

## `NTriplesError: could not parse term`

The loader handles a compact subset: one triple per line, `#` comments, IRIs in
`<...>` or prefixed `pre:Local` form, and simple `"..."` literals with optional
`^^type` or `@lang`.

It does **not** handle Turtle prefixes and abbreviations, N-Quads, multi-line
triples, or exotic literal escapes. Convert first:

```bash
rapper -i turtle -o ntriples in.ttl > out.nt      # if you have raptor
```

or parse with your own library and build a `DataGraph` through the API.

---

## The exit code was not what I expected

Codes are **per-subcommand**. See [CLI reference § Exit
codes](cli-reference.md#exit-codes).

| Code | `check` | `repair` | `derive` | `review` |
|---|---|---|---|---|
| `2` | `ptime_core` violations | ran, not consistent | — | entries still undecided |
| `3` | — | `ABORTED-BY-CAP` | nothing cleared the floors | — |
| `4` | — | candidate gate refused | — | — |

Two that surprise people:

**`check` exits 0 despite reported violations.** Boundary-tier violations alone
never cause exit 2, because no engine repairs them. Check `by_tier` in the
report.

**`repair` exits 2 having written a graph.** The engine ran but did not reach
consistency — `consistent_after` is false. The graph on disk is the partial
result. Read the change log to see what it managed.

---

## `ABORTED-BY-CAP` (exit 3)

Not an error. The repair would touch more of the graph than the cap allows, so
**no engine ran** and no repaired graph was written. The report still carries the
measurement.

```json
"cap": { "mode": "subset", "fraction": 0.41, "cap": 0.2,
         "witness_count": 297, "denominator": 725,
         "aborted": true, "status": "ABORTED-BY-CAP" }
```

**Diagnose before overriding.** A repair that would delete 41% of your nodes is
almost always a constraint problem. In order:

1. **Check your typing spine** — see the first entry on this page. It is the
   single most common cause of an inflated fraction.
2. **Try the other direction.** A high *deletion* fraction usually means the
   graph is incomplete, not wrong, and superset repair is the right tool. This is
   exactly what the project's own real-corpus runs found.
3. **Look at which constraint dominates.** One over-broad rule is usually
   responsible:

   ```python
   for v in kgrepair.validate(graph, constraints).failing():
       print(v.constraint.cid, v.count)
   ```

4. **Only then raise the cap**, deliberately:

   ```bash
   kgrepair repair ... --mode subset --max-deletion-fraction 0.5
   ```

   Doing so takes you outside the thresholds `results/runs.jsonl` was recorded
   under, so the run is no longer comparable with the published measurements.

---

## The candidate gate refused my file (exit 4)

| Code | Cause | Fix |
|---|---|---|
| `E-SCHEMA` | not a candidate file this toolkit writes | check `"schema": "kgrepair.candidates/v1"` |
| `E-UNSEALED` | nobody sealed it | `kgrepair review <file> --reviewer "Name"` |
| `E-PENDING` | an entry is still undecided | finish the review; skipped entries stay pending |
| `E-SEAL` | the seal does not recompute — the file changed after sealing | re-review and re-seal. **This is the tamper check working** |
| `E-DRIFT` | the graph is not the one the candidates came from | re-derive against this graph, or `--allow-graph-drift` deliberately |
| `E-FRAGMENT` | an accepted constraint leaves the positive fragment | rewrite it, or reject that entry |
| `E-BOUNDARY` | an accepted constraint is boundary tier | no engine can repair it; reject it, or use it for validation only |
| `E-EMPTY` | every entry was rejected | nothing to load — re-derive with lower floors |

`E-SEAL` after hand-editing a sealed file is expected: the seal is recomputed
from the contents, so you cannot seal a benign rule and swap in a different one.

---

## `check` refuses my constraint file

```
kgrepair: that is a candidate file. Review and seal it, then use it with
`kgrepair repair --constraints`
```

`check` and `metrics` take a **constraint set file**; only `repair` takes a
`kgrepair.candidates/v1` candidate file. See [File
formats](file-formats.md#constraint-set-files).

To check with a candidate file's rules from Python:

```python
cf = kgrepair.read_candidate_file("candidates.json")
cs = kgrepair.reviewed_constraint_set(cf, graph, for_repair=False)   # validation only
report = kgrepair.validate(graph, cs)
```

`for_repair=False` is the one case where a boundary-tier entry is allowed
through, since nothing will act on it.

---

## `kgrepair derive` wrote nothing (exit 3)

```
kgrepair: nothing cleared the support and confidence floors, so no candidate
file was written. Try a lower --min-support or --min-conf.
```

Common on small or very clean graphs — there is nothing prevalent enough to
propose. Lower the floors:

```bash
kgrepair derive --in small.nt --out c.json --min-support 2 --min-conf 0.7
```

Lowering them changes **what gets proposed**, never what gets accepted. Every
entry still needs a human decision.

---

## Nodes vanished from the repaired file

Subset repair cascades: `remove_node` deletes every incident edge, which can
leave other nodes isolated. **N-Triples cannot represent a node with no edges**,
so `to_ntriples` omits it — this is a limitation of the format, not of the
engine.

The change log is the complete record:

```python
for r in result.changelog:
    print(r.op, r.node or (r.src, r.label, r.dst), "←", r.constraint)
```

Or use the reversible diff to recover the input exactly:

```python
original = kgrepair.reconstruct_input(repaired_text, diff_text)
```

---

## What are these `fresh:...` nodes?

Superset repair minted them. When a requires-statement rule needs a target and no
named constant fits, it adds `x --P--> fresh:<cid>:<n>`. They carry no data
value, and the naming tells you which constraint is responsible.

```python
result.fresh_used                       # the ones actually minted
result.pool["fresh_bound"]              # 2 × |constraint set|
result.attestations["fresh_values_within_bound"]
```

Lots of fresh symbols means many nodes are missing a required property and the
graph offers no plausible target. Consider whether that constraint should be
`report`-only, or whether a named default belongs in the rule.

---

## The repair did not converge

`consistent_after` is false and the CLI exits 2.

Diagnose by re-validating the output:

```python
after = kgrepair.validate(result.graph, constraints)
for v in after.failing():
    print(v.constraint.cid, v.constraint.tier, v.count)
```

| What you see | Meaning |
|---|---|
| only **boundary** violations | expected and correct — no engine repairs those, and `consistent_after` only tracks `ptime_core` |
| **subset-direction** rules still failing after `--mode superset` | superset repair acts on all `ptime_core` rules, so this points at a consequent shape it could not satisfy by addition |
| **`ptime_core`** rules still failing after `--mode subset` | subset repair only handles `direction == "subset"`; superset-direction rules are Algorithm 2's job |

The last is the common one: running only subset repair on a set containing
superset-direction rules leaves those unrepaired by design. Run the other engine.

---

## `NoSupersetPlan`

A consequent shape the addition engine cannot satisfy — typically a bare
value-equality consequent, which would require rewriting `D(v)`, and the toolkit
never modifies data values. Restructure the constraint, or mark it `boundary`.

---

## Metrics report `redundant_type_edges: 0` on a graph with a hierarchy

`split_type_predicates` needs to know which of your labels is the *hierarchy*.
Given a fully custom spine it treats every label as instance-of and reports no
hierarchy — deliberately returning 0 rather than something wrong.

Name the two halves directly:

```python
kgrepair.compute_metrics(graph, constraints,
                         instance_of={"ex:isa"},
                         subclass_of={"ex:kindOf"})
```

See [Metrics § Custom vocabularies](metrics.md#custom-vocabularies-and-the-hierarchy-limitation).

---

## `ModuleNotFoundError: No module named 'kgrepair'`

The test suite and the docs assume an installed package:

```bash
pip install -e ".[dev]"
```

`tests/` deliberately does **not** insert `src/` on the path — every test imports
`kgrepair` the way a user does. The standalone runners under `app/`, `bench/` and
`scripts/` keep their own inserts and still work from a bare checkout.

## `ModuleNotFoundError: No module named 'streamlit'` / `'matplotlib'`

Optional extras:

```bash
pip install -e ".[viewer]"     # streamlit, for app/main.py
pip install -e ".[eval]"       # matplotlib, for scripts/build_evaluation.py
```

Neither is imported by anything under `src/kgrepair/`, and that must stay true.

---

## Path intersection raised instead of evaluating

`isect(a, b)` is supported only for the bounded shape the shipped constraints use
— intersection with a shared given endpoint set. Anything requiring dense `V × V`
pair enumeration **raises rather than degrading silently**, which is the design.
Restructure the constraint to avoid the unbounded intersection.

---

## Two runs produced different bytes

They should not. Every report uses sorted keys, no wall clock and basenames only;
zipped bundles use sorted entries and a fixed timestamp. If two identical
invocations differ, check:

- Did the **inputs** change? `graph_content_hash(graph)` will tell you.
- Are you comparing a **run record** (`results/runs.jsonl`)? Those *do* carry a
  timestamp and a `run_id` — they are a measurement log, not a reproducible
  artefact.
- Is one an **`--out` payload** and the other a **bundle `report.json`**? The
  bundle's copy carries an extra `summary` block.

---

## Still stuck

| Question | Where |
|---|---|
| What does this function do? | [API reference](api-reference.md) |
| What does this flag do? | [CLI reference](cli-reference.md) |
| Why is this shape not repairable? | [Concepts § Complexity routing](concepts.md#the-complexity-routing-table) |
| How does the paper map to the code? | [`docs/algorithm_fidelity.md`](../algorithm_fidelity.md) |
| What was measured, and when? | [`docs/evaluation.md`](../evaluation.md), traceable by `run_id` |

The test suite is also documentation: `tests/test_agnostic_core.py` shows a fully
custom vocabulary going through the whole loop, and `tests/test_cli.py` pins
every exit code.

---

[← Manual index](README.md)
