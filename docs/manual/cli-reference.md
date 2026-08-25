# CLI reference

[← Manual index](README.md)

```
kgrepair {check,repair,metrics,derive,review} ...
python -m kgrepair {check,repair,metrics,derive,review} ...
```

Installing the package registers `kgrepair` as a console script
(`[project.scripts] kgrepair = "kgrepair.cli:main"`). `python -m kgrepair` is
identical.

**The command line is a thin skin.** It contains argparse and file I/O and
nothing else — no repair, validation, cap, or serialisation logic. The body
under `result` in every report is the API object's own `to_dict()` verbatim; the
CLI adds only an envelope. `tests/test_cli.py::test_cli_holds_no_repair_or_validation_logic`
enforces this mechanically by grepping `cli.py` for `.edges()`, `Evaluator`,
`add_edge` and friends.

`main(argv=None) -> int` never calls `sys.exit`, so the CLI is callable from
Python:

```python
from kgrepair.cli import main
code = main(["check", "--in", "slice.nt", "--domain", "geography", "--kg", "wikidata"])
```

---

## Subcommands at a glance

| Subcommand | Reads | Writes | Runs an engine |
|---|---|---|---|
| [`check`](#kgrepair-check) | graph + constraints | a JSON violation report | no |
| [`repair`](#kgrepair-repair) | graph + constraints | repaired graph, report, optional bundle | **yes** |
| [`metrics`](#kgrepair-metrics) | graph + optional constraints | a JSON metrics report | no |
| [`derive`](#kgrepair-derive) | graph | a candidate file, every entry `pending` | no |
| [`review`](#kgrepair-review) | a candidate file | the same file, decided and sealed | no |

---

## Common options

`check`, `repair` and `metrics` share these.

### Input

| Flag | Meaning |
|---|---|
| `--in PATH` | **required.** The N-Triples graph to read |

### Constraints — pick exactly one source

| Flag | Meaning |
|---|---|
| `--constraints PATH` | your own JSON constraint file |
| `--domain D` `--kg K` | a built-in set. `D` ∈ geography, taxa, anatomy, disease, medication; `K` ∈ wikidata, dbpedia, yago. **Must be given together** |
| `--version N` | built-in constraint set version (default `1`; see [catalogue](constraint-catalogue.md#constraint-set-versions)) |

`--constraints` and `--kg` are alternatives; giving both is an error.
`metrics` may be run with neither, which leaves the consistency block `null`.

Automatic constraint derivation is **deliberately not wired in here**. With no
constraint source, the error message says so and points at `--constraints` and
`--domain`/`--kg`.

**`--constraints` accepts two file shapes:**

| Shape | `check` / `metrics` | `repair` |
|---|---|---|
| constraint set file (`{"slice": …, "constraints": […]}`) | accepted | accepted |
| candidate file (`kgrepair.candidates/v1`) | **refused, exit 1** | accepted, through the review gate |

The refusal message on `check` is *"that is a candidate file. Review and seal
it, then use it with `kgrepair repair --constraints`"*.

### Vocabulary and filtering

| Flag | Meaning |
|---|---|
| `--type-predicate LABEL` | **repeatable.** An edge label that types a node. Names the typing spine of *your* graph (for example `ex:isa`) so class tests can reach it. Omitted, `DEFAULT_TYPE_PREDICATES` applies, covering `rdf:type`/`rdfs:subClassOf` and the Wikidata spine |
| `--allowlist PATH` | **opt-in.** Drop every edge whose predicate is not in this allow-list file of yours, before checking or repairing. Off unless given |

`--allowlist` filters predicate names you chose and nothing more. Its help text
makes no ethics claim, and a test enforces that.

### Output

| Flag | Meaning |
|---|---|
| `--report PATH` | write the JSON report here (default: stdout) |
| `--indent N` | JSON indent for the report (default `2`) |

---

## `kgrepair check`

Load a graph, check it against a constraint set, and write a JSON violation
report. **Writes no graph and runs no engine.**

```bash
kgrepair check --in slice.nt --domain geography --kg wikidata
kgrepair check --in mine.nt --constraints mine.constraints.json \
               --type-predicate ex:isa --witness-limit -1
```

| Flag | Meaning |
|---|---|
| `--witness-limit N` | how many witnesses to list per constraint (default `10`; negative for all). The true `witness_count` is always reported |

**Exit codes:** `0` clean · `2` `ptime_core` violations present · `1` usage or
I/O error.

Boundary-tier violations are reported but are **never on their own** a reason to
exit 2, because no engine repairs them.

The report lists **every** constraint, passing or failing, so two runs are
diffable. See [File formats § Check report](file-formats.md#check-report).

---

## `kgrepair repair`

Load a graph, repair it under the `ptime_core` constraints, write the repaired
graph as N-Triples, and write a JSON change report.

```bash
# addition repair to a single file
kgrepair repair --in slice.nt --domain geography --kg wikidata \
                --mode superset --out repaired.nt --report run.json

# deletion repair, full auditable bundle, zipped
kgrepair repair --in slice.nt --constraints mine.constraints.json \
                --mode subset --bundle out/run --zip
```

| Flag | Meaning |
|---|---|
| `--mode {subset,superset}` | **required.** `subset` repairs by deleting nodes, `superset` by adding structure |
| `--out PATH` | write the repaired graph here, as N-Triples |
| `--bundle DIR` | write a bundle directory: repaired graph, reversible statement-level diff, JSON report, and a copy of the constraint file that drove the run |
| `--zip` | also pack the bundle directory into one deterministic archive |
| `--max-deletion-fraction F` | **subset only.** Refuse to run when the repair would delete more than this fraction of the nodes (default `0.2`) |
| `--max-addition-fraction F` | **superset only.** Refuse to run when the repair would add more than this fraction of the edge count (default `0.3`) |
| `--no-prune` | **superset only.** Skip the redundancy-pruning pass |
| `--strategy {full,incremental}` | **subset only.** Re-check policy; both compute the same repair (default `full`) |
| `--allow-graph-drift` | proceed even when a candidate file was derived from a different graph than the one being repaired. Recorded in the report when used |

**Either `--out` or `--bundle` is required** — otherwise the command has nothing
to write and refuses with exit 1.

### Exit codes

| Code | Meaning |
|---|---|
| `0` | repaired, and `consistent_after` is true |
| `2` | an engine ran but did not reach consistency |
| `3` | **`ABORTED-BY-CAP`** — no engine ran |
| `1` | usage or I/O error |
| `4` | the candidate-file gate refused before any engine ran |

### Exit 3 — the safety cap

Before calling an engine, the command measures what fraction of the graph the
repair would touch and refuses when it exceeds the cap. **Nothing is written**
as a repaired graph — but the report still carries the measurement, and a bundle
is still produced if `--bundle` was given, carrying the report and the
constraints with a `summary` explaining the refusal.

These are the same thresholds `bench/` and the viewer use, so runs stay
comparable with the recorded evaluation dataset.

### Exit 4 — the candidate-file gate

When `--constraints` points at a `kgrepair.candidates/v1` file, the run goes
through `reviewed_constraint_set`, which refuses unsealed, incomplete, tampered,
drifted, out-of-fragment and boundary-tier files. The message carries a stable
code:

| Code | Cause |
|---|---|
| `E-SCHEMA` | not a candidate file this toolkit understands |
| `E-UNSEALED` | nobody sealed it |
| `E-PENDING` | a reviewer has not decided every entry |
| `E-SEAL` | the recorded seal does not recompute — the file changed after sealing |
| `E-DRIFT` | the graph is not the one the candidates were derived from |
| `E-FRAGMENT` | an accepted constraint leaves the positive fragment |
| `E-BOUNDARY` | an accepted constraint is boundary tier and cannot be repaired |
| `E-EMPTY` | nothing was accepted, so there is nothing to load |

`E-DRIFT` is the one you can override, with `--allow-graph-drift`, and doing so
is recorded in the report. An **authored** file (`"provenance": "authored"`)
waives exactly two checks — the review seal and the source-graph hash — because
neither makes sense for a rule a person asserted directly. Everything else
applies unchanged.

### Report contents

| Key | Present |
|---|---|
| `tool_version`, `subcommand`, `constraints_source`, `input_basename`, `type_predicates`, `allowlist_applied` | always (the envelope) |
| `mode` | always |
| `cap` | always — the `CapDecision`, whether or not it tripped |
| `result` | the engine result's `to_dict()`, or `null` when capped |
| `metrics` | always — `before`, `after`, `changes`; `after` is null when capped |
| `output_basename` | when `--out` was given |
| `bundle` | when `--bundle` was given: `{"directory": …, "files": [...]}` |
| `summary` | **only inside the bundle's own `report.json`**, not in the stdout payload |

---

## `kgrepair metrics`

Load a graph and write a JSON quality-metrics report: size and conciseness, type
and property coverage, and — when a constraint set is given — consistency and
constraint satisfaction. **Reads only.** It writes no graph and runs no engine.

```bash
kgrepair metrics --in slice.nt
kgrepair metrics --in slice.nt --domain geography --kg wikidata --report m.json
```

Takes the [common options](#common-options) and nothing else. The constraint
source is optional; without it the consistency block is `null`, which is a real
state distinct from zero violations.

**Exit codes:** `0` always, unless the input cannot be read (`1`). A graph with
poor metrics is a finding, not an error.

[`docs/quality_metrics.md`](../quality_metrics.md) defines every metric and says
what each is blind to.

---

## `kgrepair derive`

Profile a graph offline and write constraint candidates to a file for a person
to review.

```bash
kgrepair derive --in slice.nt --out candidates.json --domain geography --kg wikidata
kgrepair derive --in slice.nt --out candidates.json --reference other.nt --delta 0.05
```

> **Nothing written here can repair anything.** Every entry starts `pending`, and
> only `kgrepair review` can seal the file so that `kgrepair repair
> --constraints` will take it.

| Flag | Meaning |
|---|---|
| `--in PATH` | **required.** N-Triples graph to profile |
| `--out PATH` | **required.** Candidate file to write, or merge into if it exists |
| `--domain D` / `--kg K` | names recorded on the candidates |
| `--reference PATH` | a second graph to score against, for the stability gate |
| `--generator {search,shapes}` | which generator proposes the candidates (default `search`, the two-axis search; `shapes` is the earlier sweep of one template per repairable shape). The choice is recorded in the file |
| `--min-support N` | how many nodes a rule needs behind it (default `5`) |
| `--min-conf F` | confidence floor a rule has to clear (default `0.9`). **Decides what is worth proposing, never what is accepted** — there is no threshold that skips review |
| `--delta F` | with `--reference`, drop a rule whose confidence on the two graphs differs by more than this |
| `--max-antecedent K` | how many atoms an antecedent may conjoin |
| `--max-path K` | how long a consequent path may be |
| `--type-predicate LABEL` | repeatable, as elsewhere |

**Merging.** Pointing `--out` at an existing file merges: decisions already
recorded are kept, rejected cids are never re-proposed, and genuinely new
entries are appended as `pending`. A merge that brings in new pending entries
drops the file back to open.

**Exit codes:** `0` written · `3` nothing cleared the support and confidence
floors, so no file was written · `1` usage or I/O error.

Impact measurement is deferred by default — each candidate carries its witness
count, and the engine numbers stay `null` until review. Measuring up front is
95–99% of the total cost on the measured ladder.

---

## `kgrepair review`

Walk the candidates in review order, record a decision on each, and seal the file
once nothing is pending.

```bash
kgrepair review candidates.json --reviewer "Your Name" --graph slice.nt
```

| Flag | Meaning |
|---|---|
| `PATH` | **positional, required.** The candidate file to review |
| `--reviewer NAME` | name recorded in the seal. Prompted for if omitted |
| `--graph PATH` | the graph the candidates were derived from. Given, what repairing each entry would change is worked out **as you reach it**, rather than for every candidate up front |

Interactive. For each pending entry it prints the rule, its gloss, the evidence
(support, confidence, and the reference-graph confidence and stability where
present), the impact, and a witness sample, then prompts:

```
  a/r/w/s/q >
```

| Key | Action |
|---|---|
| `a` | accept |
| `r` | reject — the cid enters `refused`, so re-deriving never re-proposes it |
| `w` | weaken — prompts for what you weakened it to, recorded as the note |
| `s` | skip, leaving it pending |
| `q` | quit without sealing |

The file is saved after **every** decision, so an interrupted session loses
nothing.

Sealing requires a reviewer name, because the seal records who made the
decisions. If any entry is still pending, or no reviewer name is given, the file
is not sealed.

**Exit codes:** `0` sealed · `2` entries still undecided (or no reviewer name) ·
`1` usage or I/O error.

---

## Exit codes

Codes are per-subcommand. Only `0` and `1` mean the same thing everywhere.

| Code | `check` | `repair` | `metrics` | `derive` | `review` |
|---|---|---|---|---|---|
| `0` | clean | repaired and consistent | written | written | sealed |
| `1` | usage / I/O | usage / I/O | usage / I/O | usage / I/O | usage / I/O |
| `2` | `ptime_core` violations | ran, not consistent | — | — | entries still undecided |
| `3` | — | `ABORTED-BY-CAP` | — | nothing cleared the floors | — |
| `4` | — | candidate gate refused | — | — | — |

Scripting example:

```bash
kgrepair check --in slice.nt --domain geography --kg wikidata --report check.json
case $? in
  0) echo "clean" ;;
  2) kgrepair repair --in slice.nt --domain geography --kg wikidata \
                     --mode superset --bundle out/run
     case $? in
       0) echo "repaired" ;;
       3) echo "over cap — review the constraints, not the graph" ;;
       *) echo "repair did not converge"; exit 1 ;;
     esac ;;
  *) echo "could not check"; exit 1 ;;
esac
```

---

## Report determinism

Every report uses `sort_keys=True`, reads no wall clock, and carries **basenames
only** — never an absolute path. Two identical invocations therefore produce
byte-identical output, which the test suite verifies. The same holds for zipped
bundles: entries are added in sorted order with a fixed timestamp.

The envelope the CLI adds around the API object's `to_dict()`:

```json
{
  "tool_version":       "0.5.0",
  "subcommand":         "repair",
  "constraints_source": "geography/wikidata/v1",
  "input_basename":     "slice.nt",
  "type_predicates":    ["rdf:type", "rdfs:subClassOf", "..."],
  "allowlist_applied":  false
}
```

`allowlist_edges_dropped` appears only when an allow-list was applied.
`output_basename` appears only on a repair that wrote a graph — and it is the
**one** deliberate difference between the CLI's report and the viewer's, since
the viewer offers a download rather than writing a file.

---

Next: [File formats](file-formats.md) · [Review workflow](review-workflow.md)
