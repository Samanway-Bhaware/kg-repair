# The inspection viewer

[← Manual index](README.md)

A local Streamlit app for loading a graph, checking it, deriving and reviewing
constraints, running either repair engine, and exporting the result — with the
neighbourhood around every witness and every change rendered inline.

```bash
pip install -e ".[viewer]"       # or: pip install "kgrepair[viewer]"
streamlit run app/main.py
```

Run it from the repository root. Streamlit is an **optional extra, never a core
dependency**, so `kgrepair check` and `kgrepair repair` work without it.

---

## What it is, architecturally

`app/` is a **skin over the public API only**. It is mechanically gated:
`tests/test_viewer_logic.py::test_viewer_reaches_only_the_public_api` walks
`app/` and fails on any `from kgrepair.<submodule> import ...` or any name
outside `__all__`.

Getting there promoted four groups of names into `api.py` rather than letting the
viewer reach in: the neighbourhood inspection primitive, a narrow run-recording
surface, `report_envelope`, and the safety caps. That is the rule working as
intended — a skin that needs something forces the library to offer it properly.

**`app/logic.py` is the testable seam.** Every knowledge-graph operation lives
there, in plain Python, with **no Streamlit import** (a test enforces that). The
screens are presentation only. This is what makes the viewer testable without a
browser.

`app/caps.py` is a **re-export shim** over `kgrepair.caps`, not a second copy —
which is why the viewer and the CLI cannot reach different cap verdicts.

### The viewer and the CLI cannot disagree

Both take their cap verdict from `check_cap` and build their report from
`report_envelope` plus the API object's own `to_dict()`.
`tests/test_viewer_logic.py` asserts the two payloads are **equal** on the same
inputs.

There is exactly one deliberate difference: the CLI adds `output_basename`,
having written a file, where the viewer offers a download.

---

## Screens

Sidebar navigation, in workflow order.

### Load

Pick a source and load it.

- **Committed fixtures** — a `fixtures/real/` or `fixtures/synthetic/` manifest,
  namespace-badged real/synthetic, with a matching constraint set. Cached.
- **Your own uploads** — any N-Triples graph, plus either a constraint file you
  wrote or one of the built-in sets.
- **A type-predicate box**, which forwards to `load_graph(type_predicates=...)`
  exactly as `--type-predicate` does on the command line.
- **An optional predicate allow-list**, off unless you supply one.

Constraint files are **compiled at load time**, so an out-of-fragment expression
is caught here and rendered as an in-app message rather than surfacing later.
Malformed uploads raise `logic.ViewerError` and render the same way.

The synthetic fixture's rules are a committed constraint file
(`fixtures/synthetic/synthetic_geoLike.constraints.json`) read via
`load_constraint_file`, with a test guarding it against drift.

### Check

The consistency report, with a **report-first cap-prevalence header** — you see
what a repair would cost before you have the option to run one.

Violations are grouped by constraint, and each witness can be expanded into its
**k-hop neighbourhood**, so you can look at why a node broke a rule rather than
just reading its identifier.

### Derive

Propose candidate constraints from the loaded graph. Presentation only — every
decision goes through `logic.start_review`, which wraps the public derivation
entry point and hands back a review queue.

**This screen chooses nothing about which candidates are good.** It cannot, and
that is the point of the airlock.

### Review

One entry at a time: the rule, the evidence for it, and the graph around a node
that breaks it. Three decisions and nothing else — **accept**, **reject**,
**weaken**.

The seal control **stays disabled until every entry has a decision**, because a
seal covering an entry nobody saw would defeat what it is for.

See [Review workflow](review-workflow.md) for the full model.

### Repair

Run `subset_repair` or `superset_repair` through the public API, respecting the
**same 20%/30% caps** the CLI and benchmark scripts use.

- An over-cap slice renders as a first-class **`ABORTED-BY-CAP` panel**, not an
  error.
- The full outcome panel shows attestations and counts.
- An ordered **`ChangeRecord` table**, with per-record **before/after
  neighbourhood diffs** — every node and edge tagged `unchanged`, `added` or
  `deleted`.
- A separate **boundary panel** for the report-only violations, kept visually
  distinct from anything an engine touched.

`logic.run_repair` takes an optional `phase=` (a `RunContext.phase` factory) so
the engine is called in exactly **one** place while the `repair_loop` timing that
`docs/evaluation.md` reads still lands in the record.

### Export

Downloads — the repaired N-Triples, the result JSON, and the run's JSONL record
— plus a **retraceability block** tying every download back to exactly which
manifest, constraint set, mode and code revision produced it.

---

## Run recording from the viewer

Interactive runs write to the real `results/` directory, tagged
`slice.params.origin = "viewer"`, so they can be told apart from benchmark runs
in the same file.

`results/runs.jsonl` — the evaluation dataset — is **untouched by the test
suite**: every viewer test monkeypatches `RESULTS_DIR` to a temporary directory.

---

## Known limitation: two result shapes

The Repair screen predates `RepairRun` and still stores a pre-`RepairRun` dict.
The practical consequence: **the bundle cannot be downloaded from the Repair
screen**. Use the Export screen, or the CLI's `--bundle`.

This known gap ("the viewer's two result shapes") is the concrete example
behind the **entry-point parity rule**:

> Every caller that runs a repair must build its report from `report_envelope`
> plus the API object's own `to_dict()`, take its cap verdict from `check_cap`,
> and attach `attach_review_attestations` when a candidate file drove the run.
> A new entry point calls `logic.run_repair`-shaped code or the CLI's
> `_cmd_repair`, and adds a parity test against one of them. It does not roll
> its own.

---

## Testing the viewer

The screens are exercised with Streamlit's `AppTest`; the knowledge-graph logic
is tested directly against `app/logic.py`, no browser involved.

```bash
pip install -e ".[dev,viewer]"
python -m pytest tests/test_viewer_logic.py -q
```

Three gates worth knowing about, all in `tests/test_viewer_logic.py`:

| Gate | Asserts |
|---|---|
| `test_viewer_reaches_only_the_public_api` | walks `app/`, fails on any import outside `kgrepair.__all__` |
| `test_logic_module_imports_no_streamlit` / `test_core_import_pulls_in_no_streamlit` | `app/logic.py` never imports streamlit, and neither does the core |
| `test_viewer_check_matches_the_cli_report` / `test_viewer_repair_matches_the_cli_report` | the viewer's and the CLI's report payloads are equal on the same inputs |
| `test_app_caps_shim_agrees_with_the_library` | `app/caps.py` really is a shim, not a copy |
| `test_committed_synthetic_constraint_file_matches_the_generator` | the committed synthetic constraint file has not drifted |

---

## Screenshots

`docs/figures/viewer/` has screenshots.

The viewer work uncovered one real bug in the library: `SupersetRepair`'s
fresh-symbol targets were being created via `add_edge`'s implicit node-add
without ever getting an `add_node` `ChangeRecord`. Fixed in
`repair/superset.py::_plan_has`.

---

Next: [CLI reference](cli-reference.md) · [Review workflow](review-workflow.md)
