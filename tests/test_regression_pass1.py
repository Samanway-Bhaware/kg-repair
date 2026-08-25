"""
Frozen-cache reproduction gate for `docs/evaluation.md` Table 5.

Every cell of the real corpus is a committed slice under `fixtures/real/`: a
frozen `.nt` file plus the manifest that recorded what checking it produced. The
inputs cannot change, so the violation counts cannot legitimately change either.
Running `kgrepair check` over each cell and asserting the recorded numbers come
back is therefore a direct test that a refactor did not quietly move a result.

Offline and deterministic: reads committed fixtures only, never the network.

Counting rule, and a correction to note
---------------------------------------
Table 5's `n_violations` is the sum across BOTH tiers, not the ptime_core
subtotal. Four cells make the difference visible, because they are the only ones
with boundary-tier violations at all:

    anatomy_1000_typed     165 = 134 ptime_core + 31 boundary (ana.wd.inv.part_haspart)
    geography_1000         101 =  67 ptime_core + 34 boundary (sym.border, inv.capital)
    geography_10000       1972 = 1586 ptime_core + 386 boundary (sym.border, inv.capital)
    medication_1000_typed  133 = 132 ptime_core +  1 boundary (med.wd.safety.interaction)

The manifests are authoritative and they record every constraint that fired
regardless of tier, so `TABLE_5_TOTAL` below is the both-tier sum. The
ptime_core subtotal is pinned separately as `PTIME_CORE` so the repairable count
and the tier assignment behind it are both guarded; a change that reclassified a
constraint between tiers would move `PTIME_CORE` while leaving the total alone,
and this file would catch it.

Constraint versions
-------------------
The biomedical cells (anatomy, disease, medication) are pinned to **version 1**.
Table 5 is the corpus under the original constraints. Version 2 is the D7/C1 fix,
which deliberately drives disease to zero and changes anatomy and medication, so
checking these cells at v2 would report failures that are not regressions.
"""
import contextlib
import io
import json
import os

import pytest

import kgrepair
from kgrepair.cli import main

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURES = os.path.join(ROOT, "fixtures", "real")

_HINT = ("the input is a frozen committed slice, so a mismatch here is a "
         "regression rather than new data; check the tier filter and the "
         "constraint version first")

# One row per Table 5 cell: (slice, cli args, both-tier total, ptime_core subtotal).
# The single source of truth for this module; no count appears anywhere else in it.
# Each total is cross-checked against the cell's own manifest by
# `test_table_5_total_agrees_with_the_manifest`, so these literals cannot drift
# away from the committed record without a failure.
CELLS = [
    # slice / cli args / both-tier total / ptime_core subtotal
    ("real_dbpedia_geography_1000",
     ["--domain", "geography", "--kg", "dbpedia"], 2, 2),
    ("real_wikidata_anatomy_1000_typed",
     ["--domain", "anatomy", "--kg", "wikidata", "--version", "1"], 165, 134),
    ("real_wikidata_disease_1000",
     ["--domain", "disease", "--kg", "wikidata", "--version", "1"], 7, 7),
    ("real_wikidata_geography_1000",
     ["--domain", "geography", "--kg", "wikidata"], 101, 67),
    ("real_wikidata_geography_10000",
     ["--domain", "geography", "--kg", "wikidata"], 1972, 1586),
    ("real_wikidata_medication_1000_typed",
     ["--domain", "medication", "--kg", "wikidata", "--version", "1"], 133, 132),
    ("real_wikidata_taxa_1000",
     ["--domain", "taxa", "--kg", "wikidata"], 15, 15),
    ("real_wikidata_taxa_10000",
     ["--domain", "taxa", "--kg", "wikidata"], 15, 15),
    ("real_yago_taxa_1000",
     ["--domain", "taxa", "--kg", "yago"], 0, 0),
    ("real_yago_taxa_10000",
     ["--domain", "taxa", "--kg", "yago"], 0, 0),
]

IDS = [c[0] for c in CELLS]


def _paths(slice_name):
    return (os.path.join(FIXTURES, f"{slice_name}.nt"),
            os.path.join(FIXTURES, f"{slice_name}.manifest.json"))


def _require_fixture(slice_name):
    """Skip a cell whose slice is not in this checkout, so a partial clone still
    runs the rest. A count mismatch is never skipped; that has to fail."""
    nt_path, manifest_path = _paths(slice_name)
    for path in (nt_path, manifest_path):
        if not os.path.exists(path):
            pytest.skip(f"fixture not present in this checkout: "
                        f"{os.path.relpath(path, ROOT)}")
    return nt_path, manifest_path


def _version_of(args):
    """The constraint version a cell runs at, for the failure message."""
    return args[args.index("--version") + 1] if "--version" in args else "1 (default)"


def _check(nt_path, args):
    """Run `kgrepair check` in process and return (exit_code, result_body).

    Goes through the command line rather than calling the validator directly so
    the gate covers the report shape a user actually receives. The body under
    `result` is `ValidationReport.to_dict()` verbatim.
    """
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = main(["check", "--in", nt_path, *args])
    return code, json.loads(buf.getvalue())["result"]


def _by_tier(result, tier):
    """Witnesses summed over the constraints of one tier, filtered explicitly."""
    return sum(c["witness_count"] for c in result["constraints"]
               if c["tier"] == tier)


def _fired(result):
    """cid -> witness count, for the constraints that fired. Matches the shape the
    manifests record, so the two can be compared directly."""
    return {c["cid"]: c["witness_count"] for c in result["constraints"]
            if c["witness_count"]}


 
# the gate
 

@pytest.mark.parametrize("slice_name,args,total,core", CELLS, ids=IDS)
def test_table_5_violation_count(slice_name, args, total, core):
    """The headline number: violations across both tiers, as Table 5 records it."""
    nt_path, _manifest = _require_fixture(slice_name)
    _code, result = _check(nt_path, args)
    got = _by_tier(result, "ptime_core") + _by_tier(result, "boundary")
    assert got == total, (
        f"{slice_name}: Table 5 expects {total} violation(s), got {got} "
        f"(constraints v{_version_of(args)}, both tiers). {_HINT}")


@pytest.mark.parametrize("slice_name,args,total,core", CELLS, ids=IDS)
def test_ptime_core_subtotal(slice_name, args, total, core):
    """The repairable subtotal, with the tier filter written out.

    Pinned separately from the total so a constraint moving between tiers is
    caught even though it would leave the headline number untouched.
    """
    nt_path, _manifest = _require_fixture(slice_name)
    _code, result = _check(nt_path, args)
    got = _by_tier(result, "ptime_core")
    assert got == core, (
        f"{slice_name}: expected {core} ptime_core violation(s), got {got} "
        f"(constraints v{_version_of(args)}). {_HINT}")


@pytest.mark.parametrize("slice_name,args,total,core", CELLS, ids=IDS)
def test_per_constraint_counts_match_the_manifest(slice_name, args, total, core):
    """Every constraint's own count, against the manifest that recorded it.

    Stronger than the sums above and far more useful when it breaks: it names
    the constraint that moved instead of only the cell.
    """
    nt_path, manifest_path = _require_fixture(slice_name)
    with open(manifest_path, encoding="utf-8") as fh:
        recorded = json.load(fh)["violations"]
    _code, result = _check(nt_path, args)
    got = _fired(result)
    assert got == recorded, (
        f"{slice_name}: per-constraint counts differ from the manifest "
        f"(constraints v{_version_of(args)}).\n"
        f"  manifest: {json.dumps(recorded, sort_keys=True)}\n"
        f"  got     : {json.dumps(got, sort_keys=True)}\n{_HINT}")


@pytest.mark.parametrize("slice_name,args,total,core", CELLS, ids=IDS)
def test_table_5_total_agrees_with_the_manifest(slice_name, args, total, core):
    """The literals in this file against the committed manifests.

    Keeps `CELLS` honest: if a manifest is ever regenerated with different
    numbers, this fails rather than letting the table and the record disagree
    silently.
    """
    _nt, manifest_path = _require_fixture(slice_name)
    with open(manifest_path, encoding="utf-8") as fh:
        recorded = json.load(fh)["violations"]
    assert sum(recorded.values()) == total, (
        f"{slice_name}: this file expects {total} but the manifest sums to "
        f"{sum(recorded.values())}. The manifest is authoritative; update CELLS.")


@pytest.mark.parametrize("slice_name,args,total,core", CELLS, ids=IDS)
def test_check_exit_code_follows_the_ptime_core_count(slice_name, args, total, core):
    """Exit 2 when there is anything repairable to fix, 0 when there is not.

    The yago cells are the clean ones, so they are the only cells that exit 0,
    and the geography cells confirm that boundary violations on their own do not
    force a non-zero exit.
    """
    nt_path, _manifest = _require_fixture(slice_name)
    code, _result = _check(nt_path, args)
    assert code == (2 if core else 0), (
        f"{slice_name}: exit {code} with {core} ptime_core violation(s) "
        f"(constraints v{_version_of(args)}). {_HINT}")


 
# closure invariance
 

def test_closure_does_not_change_the_counts():
    """The subclass-closure memoisation changes running time, never results.

    Run through the public `validate` rather than the command line because the
    command line deliberately exposes no closure flag: it is a performance knob,
    not a semantic choice, so there is nothing for a user to decide. A divergence
    here would be its own regression, separate from the counts above.
    """
    slice_name, args, total, core = next(c for c in CELLS
                                         if c[0] == "real_wikidata_geography_1000")
    nt_path, _manifest = _require_fixture(slice_name)
    graph = kgrepair.load_graph(nt_path)
    cs = kgrepair.constraints.get("geography", "wikidata")

    off = kgrepair.validate(graph, cs, use_closure=False).to_dict(witness_limit=-1)
    on = kgrepair.validate(graph, cs, use_closure=True).to_dict(witness_limit=-1)

    assert off == on, f"{slice_name}: closure changed the report. {_HINT}"
    assert off["by_tier"]["ptime_core"] == core
    assert off["by_tier"]["ptime_core"] + off["by_tier"]["boundary"] == total


def test_the_gate_reads_only_committed_fixtures():
    """No network, no generated artifact: every path this module touches is a
    committed file under fixtures/real/."""
    for slice_name, _args, _total, _core in CELLS:
        for path in _paths(slice_name):
            assert os.path.commonpath([os.path.abspath(path), FIXTURES]) == FIXTURES
