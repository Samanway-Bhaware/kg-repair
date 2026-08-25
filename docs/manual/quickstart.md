# Quickstart

[← Manual index](README.md)

A complete cycle — check, repair, inspect the changes, export an auditable
bundle — in about five minutes. Everything here is offline; nothing fetches.

```bash
pip install -e .
```

---

## 1. Check a graph

The repository ships a tiny worked example: a museum graph and a hand-written
constraint file for it.

```bash
cat examples/museum.nt
```

```
<ex:Painting>  <rdfs:subClassOf> <ex:Artwork> .
<ex:Vase>      <rdfs:subClassOf> <ex:Artwork> .
<ex:galleryA>  <rdf:type>        <ex:Gallery> .
<ex:painting1> <ex:displayedIn>  <ex:galleryA> .
<ex:painting1> <rdf:type>        <ex:Painting> .
<ex:vase1>     <ex:displayedIn>  <ex:galleryA> .
<ex:vase1>     <rdf:type>        <ex:Vase> .
<ex:vase2>     <ex:displayedIn>  <ex:galleryB> .
```

Two things are wrong with it, given the rules in
`examples/museum.constraints.json`: `ex:vase2` is displayed somewhere but is
not typed as an artwork, and `ex:galleryB` has something displayed in it but is
not typed as a gallery.

To see violations without changing anything, use `check`. Here it is against one
of the **built-in** constraint sets and a committed fixture, since `check`
deliberately refuses candidate files (see [step 5](#5-bring-your-own-constraints)):

```bash
kgrepair check --in fixtures/synthetic_geography_wd.nt \
               --domain geography --kg wikidata \
               --witness-limit 3
```

```json
{
  "allowlist_applied": false,
  "constraints_source": "geography/wikidata/v1",
  "input_basename": "synthetic_geography_wd.nt",
  "result": {
    "by_tier": { "boundary": 1, "ptime_core": 4 },
    "consistent": false,
    "constraints": [
      {
        "cid": "geo.wd.dom.country",
        "direction": "subset",
        "kind": "existential_domain",
        "tier": "ptime_core",
        "witness_count": 1,
        "witnesses": ["wd:Q999001"],
        "witnesses_truncated": false
      }
      // ... one entry per constraint, including the ones that pass
    ],
    "failing_count": 5,
    "total_witnesses": 5
  },
  "subcommand": "check",
  "tool_version": "0.5.0",
  "type_predicates": ["rdf:type", "rdfs:subClassOf", "schema:subClassOf",
                      "wdt:P279", "wdt:P31"]
}
```

Three things to notice, because they recur everywhere:

- **Every constraint appears**, passing or failing. A `witness_count` of 0 means
  the rule holds. This makes reports diffable across runs.
- **`by_tier`** splits the failures. Only the 4 `ptime_core` failures are ones an
  engine will act on; the 1 `boundary` failure is reported and left alone.
- **The exit code is 2**, because `ptime_core` violations are present. Boundary
  violations alone never produce exit 2. See [CLI reference § Exit codes](cli-reference.md#exit-codes).

## 2. Repair it

Two engines, two directions. Pick the one whose changes you can live with.

```bash
# Repair by ADDING the missing structure (Algorithm 2)
kgrepair repair --in examples/museum.nt \
                --constraints examples/museum.constraints.json \
                --mode superset --bundle out/museum
```

The interesting part of the report:

```json
{
  "cap": { "aborted": false, "cap": 0.3, "denominator": 8,
           "fraction": 0.25, "mode": "superset",
           "status": "OK", "witness_count": 2 },
  "mode": "superset",
  "result": {
    "added_edges": [["ex:galleryB", "rdf:type", "ex:Gallery"],
                    ["ex:vase2",    "rdf:type", "ex:Artwork"]],
    "added_nodes": [],
    "attestations": {
      "consistent_after": true,
      "data_values_unmodified": true,
      "fresh_values_within_bound": true,
      "superset_only_added": true,
      "constraint_provenance": "authored",
      "constraint_seal": null,
      "reviewer": null
    },
    "pool": { "fresh_bound": 4, "fresh_used": 0,
              "graph_values": 4, "named_constants": 2 },
    "pruned_edges": 0, "rounds": 2
  }
}
```

Read that as: the engine measured that the repair would add 2 edges against 8
existing ones (25%, under the 30% cap), so it ran; it added exactly the two
missing type edges; it needed no fresh symbols; and it verified afterwards that
it only added, never touched a data value, and left the graph consistent.

The other direction deletes instead:

```bash
# Repair by DELETING the offending nodes (Algorithm 1)
kgrepair repair --in examples/museum.nt \
                --constraints examples/museum.constraints.json \
                --mode subset --out repaired.nt
```

Which one is right is a modelling question, not a technical one. Deletion loses
data; addition invents it. See [Repair engines § Choosing a direction](repair-engines.md#choosing-a-direction).

## 3. Read what changed

The `--bundle` flag writes four files instead of one:

```bash
ls out/museum/
# changes.nt.diff  constraints.used.json  repaired.nt  report.json
```

```bash
cat out/museum/changes.nt.diff
```

```
+ <ex:galleryB> <rdf:type> <ex:Gallery> .
+ <ex:vase2> <rdf:type> <ex:Artwork> .
```

The diff is **reversible**: apply it backwards to `repaired.nt` and you get the
input back, byte for byte. That is what makes the bundle an audit record rather
than a summary. Add `--zip` to pack it into one deterministic archive.

```python
import kgrepair
original = kgrepair.reconstruct_input(open("out/museum/repaired.nt").read(),
                                      open("out/museum/changes.nt.diff").read())
```

For per-change provenance — which constraint caused each edit, which witness it
served, which round it happened in — read `changelog` in `report.json`. See
[File formats § Change log](file-formats.md#the-change-log).

## 4. Do the same from Python

```python
import kgrepair

graph       = kgrepair.load_graph("examples/museum.nt")
constraints = kgrepair.load_constraint_file("my.constraints.json")

# Check
report = kgrepair.validate(graph, constraints)
print(report.summary())
print(report.consistent, report.by_tier(), report.total_witnesses())

for violation in report.failing():
    print(violation.constraint.cid, violation.count, sorted(violation.witnesses)[:5])

# Decide whether to repair at all
decision = kgrepair.check_cap(graph, constraints, "superset")
if decision.aborted:
    raise SystemExit(f"{decision.status}: would touch {decision.fraction:.1%}")

# Repair
result = kgrepair.superset_repair(graph, constraints)
assert result.attestations["consistent_after"]
assert result.attestations["data_values_unmodified"]

kgrepair.write_ntriples(result.graph, "repaired.nt")
```

The input graph is never mutated unless you pass `in_place=True`. `result.graph`
is a new `DataGraph`.

## 5. Bring your own constraints

Nothing about Wikidata is baked into the engines. To repair your own graph with
your own vocabulary, write a constraint file naming your own predicates and tell
the loader what your typing spine is:

```python
graph = kgrepair.load_graph("mine.nt", type_predicates={"ex:isa", "ex:kindOf"})
```

```bash
kgrepair check --in mine.nt --constraints mine.constraints.json \
               --type-predicate ex:isa --type-predicate ex:kindOf
```

There are two accepted constraint-file shapes, and they behave differently:

| Shape | Written by | `check` | `repair` |
|---|---|---|---|
| **Constraint set** (`{"slice": ..., "constraints": [...]}`) | `save_constraint_file`, `constraints.export_json` | accepted | accepted |
| **Candidate file** (`kgrepair.candidates/v1`) | `kgrepair derive`, or hand-written with `"provenance": "authored"` | **refused**, exit 1 | accepted, through the review gate |

The museum example is the second shape with `"provenance": "authored"`, which is
why `check` refuses it while `repair` takes it. An authored file needs no review
seal — writing the rules down *is* the assertion — but a **derived** one does.
See [File formats](file-formats.md) and [`docs/authoring_constraints.md`](../authoring_constraints.md).

## 6. If you have no constraints at all

Let the toolkit propose some, then decide on each one yourself:

```bash
kgrepair derive --in mine.nt --out candidates.json --domain mydomain --kg mykg
kgrepair review candidates.json --reviewer "Your Name" --graph mine.nt
kgrepair repair --in mine.nt --constraints candidates.json --mode superset --out repaired.nt
```

Every derived entry starts `pending`. The third command will refuse the file
outright until every entry has a recorded decision and a named person has sealed
it. There is no confidence threshold that skips this and no accept-all flag.
See [Review workflow](review-workflow.md).

## 7. Look at it in a browser

```bash
pip install -e ".[viewer]"
streamlit run app/main.py
```

Six screens — Load, Check, Derive, Review, Repair, Export — over the same public
API the command line uses. See [Viewer](viewer.md).

---

## Where to go next

| If you want to… | Read |
|---|---|
| Understand containments, tiers, and why negation is banned | [Concepts](concepts.md) |
| Write constraint expressions | [Constraint language](constraint-language.md) |
| Know exactly what each engine guarantees | [Repair engines](repair-engines.md) |
| Look up a function | [API reference](api-reference.md) |
| Look up a flag or exit code | [CLI reference](cli-reference.md) |
