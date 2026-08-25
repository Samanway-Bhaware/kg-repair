# Review workflow — the airlock

[← Manual index](README.md)

If you have no constraints, the toolkit can propose some. It cannot decide
whether they are right. That decision is a person's, and the toolkit is built so
you cannot skip it.

> **Derivation proposes, a person decides, only a sealed file repairs.**
> There is **no confidence score that authorises a repair** — no threshold that
> skips review, no accept-all flag, no `--yes`.

```
kgrepair derive   →   candidates.json (every entry pending)
kgrepair review   →   candidates.json (every entry decided, sealed by a named person)
kgrepair repair   →   the gate checks the seal, then the engine runs
```

---

## Why a gate at all

A derived rule is a statistical observation, not a claim about the domain.
*"96.8% of things with a P206 edge also have a P17 edge"* is a fact about one
graph on one day. Turning it into a repair means asserting it should hold — and
then a machine starts adding edges to your data on the strength of it.

The project measured what happens without that step. In an early superset repair
run, 453 added type edges were checked against live Wikidata: 156 corroborated,
279 contradicted, 18 plausible — **34.4% precision**. Tracing the contradictions
showed they were overwhelmingly a constraint-scoping problem: predicate reuse
across domains, and meta-class idioms the type test structurally could not see
through. A human looking at the rules would have caught both. A confidence
number would not have.

Hence: derivation is allowed to be noisy, because a person reads every entry
before anything runs.

---

## Step 1 — derive

```bash
kgrepair derive --in slice.nt --out candidates.json \
                --domain geography --kg wikidata \
                --min-support 5 --min-conf 0.9
```

```
259 candidate(s) in candidates.json (259 new, 259 pending)
Nothing here can repair anything yet. Run `kgrepair review candidates.json`
to decide each entry and seal the file.
```

Offline — the graph is already loaded and nothing fetches. Every entry comes back
`pending`.

| Flag | Effect |
|---|---|
| `--min-support N` | how many nodes a rule needs behind it (default 5) |
| `--min-conf F` | the confidence floor (default 0.9) |
| `--generator {search,shapes}` | `search` is the two-axis search (default); `shapes` is the earlier per-shape template sweep. Recorded in the file |
| `--max-antecedent K` / `--max-path K` | search bounds |
| `--reference PATH` + `--delta F` | the stability gate, below |

**The floors decide what is worth proposing, never what is accepted.** Lowering
`--min-conf` gets you more entries to read, not more automatic repairs.

Exit 3 means nothing cleared the floors and no file was written.

### The stability gate

```bash
kgrepair derive --in slice_a.nt --reference slice_b.nt --delta 0.05 \
                --out candidates.json
```

Drops any candidate whose confidence on the two graphs differs by more than
`--delta`. The reasoning: a rule that holds on one graph and not the other is a
fact about *that graph*, not about the domain. Both numbers are recorded in the
candidate's evidence either way, so you can see what was measured even for the
survivors.

### Deferred impact

By default each candidate carries only its **witness count** — one evaluation.
The two engine numbers (`subset_deletions`, `superset_additions`) stay `null`
until someone actually reviews the entry.

This is not laziness. Measuring impact for every candidate up front runs both
engines per candidate, which on the measured ladder is **95–99% of the total
cost** — 1.9 s of 2.0 s at the 1k rung, 747.9 s of 748.4 s at 100k. Deferring it
turns a derive run from minutes into seconds. Pass `--graph` to `review` and the
number is computed for one entry at the moment you look at it, or set
`measure=True` in `derive_candidate_file` to restore the eager behaviour.

### Merging into an existing file

Pointing `--out` at a file that already exists merges rather than overwriting,
under three rules in order:

1. **A recorded decision is kept** and the fresh version of that entry
   discarded. Re-deriving must never overwrite a person's verdict.
2. **A fresh candidate whose cid is in `refused` is dropped**, so a rejection
   stays rejected across runs.
3. **Anything genuinely new is appended as `pending`.**

Merging never seals. If the merge brings in new pending entries the file drops
back to `open`, because a seal covering entries nobody has seen would be a lie.

This works because a `cid` is a **content hash** over
`(domain, kg, canonical antecedent, canonical consequent)`, not a counter. A
decision therefore stays attached to the rule it was made about, even if earlier
candidates disappear from a later run.

---

## Step 2 — review

```bash
kgrepair review candidates.json --reviewer "Your Name" --graph slice.nt
```

```
259 entry(ies) to decide. a accept, r reject, w weaken, s skip, q quit without sealing.

[1/259] geography.wikidata.derived.8e19c69b   (typing_existence, ptime_core, repairs by superset)
  everything with a country and a located-in edge should be a city
  rule      < down(wdt:P17) > & < down(wdt:P131) >
            is contained in < down(wdt:P31) . down(wdt:P279)* . [val("wd:Q515")] >
  evidence  support 412, confidence 0.981
  impact    37 node(s) break it; accepting it means 37 deletion(s) or 37 addition(s)
  for example  wd:Q999001, wd:Q999002
  a/r/w/s/q >
```

| Key | Action |
|---|---|
| `a` | **accept** — the rule can drive an engine |
| `r` | **reject** — the cid enters `refused`, so re-deriving never re-proposes it |
| `w` | **weaken** — prompts for what you weakened it to; loadable, with the note recording the change |
| `s` | **skip** — stays `pending`, and blocks sealing |
| `q` | **quit** without sealing |

**The file is saved after every decision.** An interrupted session loses nothing;
re-running picks up where you left off, because decided entries are no longer
pending.

`--graph` is worth passing. Without it the impact line reads *"what repairing it
would change has not been computed"*; with it, each entry's cost is computed as
you reach it.

### Sealing

Once nothing is pending, the file is sealed with the reviewer's name:

```
Sealed by Your Name. 12 accepted, 247 rejected.
Use it with: kgrepair repair --constraints candidates.json ...
```

Sealing requires a name, because the seal records *who* made the decisions. If
any entry is still pending, or no name is given, the file is not sealed and the
command exits 2.

The `review` block then reads:

```json
"review": { "state": "sealed", "reviewer": "Your Name",
            "sealed_at": "…", "seal": "…", "review_order": [ … ] }
```

**Any subsequent change reopens it.** `set_status` on a sealed file drops it back
to open, because a seal covers a specific set of decisions and changing one has
to invalidate it rather than silently outlive it.

---

## Step 3 — repair through the gate

```bash
kgrepair repair --in slice.nt --constraints candidates.json \
                --mode superset --bundle out/run
```

`reviewed_constraint_set` is the **only** route from a candidate file to an
engine, and every refusal happens before a single constraint is handed anywhere.

| Code | Refusal |
|---|---|
| `E-SCHEMA` | not a candidate file this toolkit understands |
| `E-UNSEALED` | nobody sealed it |
| `E-PENDING` | a reviewer has not decided every entry |
| `E-SEAL` | the seal does not recompute — the file changed after sealing |
| `E-DRIFT` | the graph is not the one the candidates were derived from |
| `E-FRAGMENT` | an accepted constraint leaves the positive fragment |
| `E-BOUNDARY` | an accepted constraint is boundary tier and no engine may act on it |
| `E-EMPTY` | every entry was rejected, so there is nothing to load |

All of them exit **4** on the command line and raise a `CandidateGateError`
subclass in Python, each carrying its stable `code` and the offending `cid` where
the refusal is about one entry.

`E-SEAL` is worth dwelling on: the seal is recomputed from the file's contents,
so editing a constraint's expression after sealing invalidates it. You cannot
seal a benign rule and then swap in a different one.

`E-DRIFT` is the only overridable refusal:

```bash
kgrepair repair ... --allow-graph-drift
```

Use of the flag is recorded in the report, and the caller is then responsible for
having recorded *why*.

### What lands in the report

A repair driven by a candidate file carries the provenance of its rules in the
attestations, alongside the engine's own:

```json
"attestations": {
  "superset_only_added": true,
  "consistent_after": true,
  "data_values_unmodified": true,
  "fresh_values_within_bound": true,

  "constraint_provenance": "derived",
  "constraint_seal": "…",
  "constraint_source": "candidates.json",
  "reviewer": "Your Name"
}
```

That is the point of the whole mechanism: a repaired graph carries, in its own
report, the name of the person who authorised the rules that changed it.

---

## Authored files — the short path

If you already know your rules, you do not need any of this. Write them into a
`kgrepair.candidates/v1` file with `"provenance": "authored"` and every entry
`"status": "accepted"`, and the two review-specific checks are waived:

| Check | Authored | Derived |
|---|---|---|
| review seal | **waived** — writing the rule down is the assertion | required |
| source-graph hash | **waived** — an authored rule is a claim about the domain, not a measurement of one graph | required |
| positive-fragment parse | required | required |
| boundary tier refused for repair | required | required |

A file with **no** `provenance` field is treated as `derived`, so files written
before the field existed keep exactly the behaviour they had.

Worked example: [`examples/museum.constraints.json`](../../examples/museum.constraints.json).
Full guide: [`docs/authoring_constraints.md`](../authoring_constraints.md).

Alternatively, skip candidate files entirely and use a plain
[constraint set file](file-formats.md#constraint-set-files) — that is the
`load_constraint_file` path, and it works with `check` and `metrics` too.

---

## From Python

```python
import kgrepair

graph = kgrepair.load_graph("slice.nt")

# derive
cf = kgrepair.derive_candidate_file(graph, "geography", "wikidata")
print(len(cf.candidates), "proposed;", len(cf.pending()), "pending")

# review, entry by entry
for cand in cf.ordered_for_review():
    kgrepair.fill_impact(graph, cand)          # compute cost at the point of decision
    print(cand.cid, cand.gloss, cand.evidence["confidence"], cand.impact)
    kgrepair.set_status(cf, cand.cid, "accepted" if good(cand) else "rejected")

# seal
kgrepair.seal_candidates(cf, reviewer="Your Name")
kgrepair.write_canonical(cf, "candidates.json")

# load through the gate
try:
    cs = kgrepair.reviewed_constraint_set(cf, graph)
except kgrepair.CandidateGateError as exc:
    raise SystemExit(f"{exc.code}: {exc}")

result  = kgrepair.superset_repair(graph, cs)
payload = kgrepair.attach_review_attestations(result.to_dict(), cf)
```

To merge a later derive run into a reviewed file:

```python
fresh  = kgrepair.derive_candidate_file(graph, "geography", "wikidata")
merged = kgrepair.merge_candidates(kgrepair.read_candidate_file("candidates.json"), fresh)
kgrepair.write_canonical(merged, "candidates.json")
```

---

## In the viewer

The **Derive** and **Review** screens are the same workflow with a UI: propose,
decide every entry, seal, and only then repair. See [Viewer](viewer.md).

---

## What derivation is, and is not

`kgrepair derive` is a **profiling** step. It looks at what is prevalent in your
graph and proposes rules matching the repairable shapes. It has no knowledge of
your domain and no way to tell a real invariant from a sampling artefact.

Separately, the project ran a time-boxed sprint on
**constraint mining** (`experimental/mining/`, written up in
[`docs/ml_mining.md`](../ml_mining.md)) — a prevalence miner, recovery
evaluation against the shipped v1/v2 sets, closed-loop live-Wikidata vetting, and
a PCA-confidence miner.

The outcome was mixed and it was **not adopted**: 1/10 recovery on the real
corpus. But the live-vetting loop independently caught two genuine defects with
nobody pointing it at them — a `P206`/"body of water" cross-domain contamination
in anatomy, and a second independent confirmation of the P2175 symptom/disease
conflation the v2 work had already traced. The recommendation is future-work
material, pending a specificity-ranking stage the evidence repeatedly asks for.

Isolation is test-enforced: `experimental/` imports *from* `src/kgrepair` and
never the reverse, no engine or shipped constraint file was changed, and every
mined artifact stays `provenance="mined"` and is never promoted.

---

Next: [CLI reference § derive](cli-reference.md#kgrepair-derive) ·
[File formats § Candidate files](file-formats.md#candidate-files)
