"""
P9/T5: every number in the campaign tables traces to a line of the campaign log.

The write-up cites `eval/campaign_objective4.md` and its siblings. Those tables
are worth citing only if a reader can follow any figure in them back to a record in
`results/campaign.jsonl` that carries a slice content hash, a constraint set name and
a code revision. These tests hold that chain.

They also hold the matrix: every cell the campaign script enumerates has a record, and
no record has a stop reason the tables would silently drop.

No network and no repairs. Everything runs from the committed artifacts.
"""
from __future__ import annotations

import json
import os

import pytest

import build_campaign_tables as bct
import run_campaign as rc

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
CAMPAIGN = os.path.join(ROOT, "results", "campaign.jsonl")
EVAL = os.path.join(ROOT, "eval")

TABLES = ["campaign_objective4.md", "campaign_objective5.md",
          "campaign_predictions.md"]


@pytest.fixture(scope="module")
def records():
    assert os.path.exists(CAMPAIGN), "run `python scripts/run_campaign.py` first"
    return bct._read_jsonl(CAMPAIGN)


 
# the matrix
 
def test_every_enumerated_cell_has_a_record(records):
    """No silent skips. The matrix is fixed in the script, so a cell that vanished
    between enumeration and the log is a defect, not a data property."""
    expected = {f"{s}:{d}:{t}{':' + v if v else ''}:{m}"
                for (s, d, t, v, m) in rc.matrix()}
    got = {r["cell"] for r in records}
    assert got == expected, f"missing {expected - got}, unexpected {got - expected}"
    assert len(records) == len(rc.matrix()) == 24


def test_every_record_states_an_outcome(records):
    for rec in records:
        assert rec["stop_reason"] in ("completed", "ABORTED-BY-CAP", "FAILED"), rec["cell"]
        assert rec.get("error") is None, f"{rec['cell']}: {rec.get('error')}"


def test_every_record_is_traceable(records):
    """A record with no revision or no constraint set cannot be cited."""
    for rec in records:
        assert rec["code_revision"], rec["cell"]
        assert rec["constraint_set"], rec["cell"]
        assert rec["cap"]["cap"] and rec["cap"]["mode"] == rec["mode"]


def test_the_typed_slices_are_the_only_ones_without_a_content_hash(records):
    """The typing-completed slices were derived rather than sliced from a cache, so
    their manifests carry no content hash. That gap is named here rather than papered
    over, and any OTHER cell losing its hash fails this test."""
    missing = sorted({r["slice"] for r in records if not r["slice_content_hash"]})
    assert missing == ["real_wikidata_anatomy_1000_typed",
                       "real_wikidata_medication_1000_typed"]


 
# the chain from table to log
 
def test_the_tables_are_a_pure_function_of_the_committed_artifacts():
    assert bct.build() == bct.build()


def test_regenerating_every_table_is_byte_identical():
    built = bct.build()
    for name, key in zip(TABLES, ("objective4.md", "objective5.md", "predictions.md")):
        path = os.path.join(EVAL, name)
        assert os.path.exists(path), f"run scripts/build_campaign_tables.py: {name}"
        with open(path, encoding="utf-8") as fh:
            assert fh.read() == built[key], f"{name} drifted from the log"


def test_objective4_numbers_come_from_the_log(records):
    """Spot the chain directly: every consistency figure in the Objective 4 table is
    a field of a record, so a transcription error is impossible by construction."""
    text = bct.objective4(records)
    for rec in records:
        if rec["stop_reason"] != "completed":
            continue
        before = rec["metrics_before"]["violations_by_tier"]
        after = rec["metrics_after"]["violations_by_tier"]
        row = [line for line in text.splitlines()
               if line.startswith(f"| {rec['slice']} | {rec['mode']} |")]
        assert row, f"{rec['cell']} has no row"
        cells = [c.strip() for c in row[0].split("|")]
        assert str(before["ptime_core"]) in cells
        assert str(after["ptime_core"]) in cells


def test_every_prediction_has_a_verdict(records):
    """T3's gate: none is quietly dropped because its metric went unscored."""
    for row in bct.verdicts(records):
        total = sum(row["tally"].values())
        assert total > 0, f"{row['statement']} ({row['mode']}) scored no cell"
        assert row["statement"] and row["metric"]


def test_the_cap_abort_is_reported_and_was_not_retried(records):
    """A cap abort is a result. If one were quietly re-run at a higher cap the
    recorded cap would differ from the library default."""
    import kgrepair
    aborted = [r for r in records if r["stop_reason"] == "ABORTED-BY-CAP"]
    assert aborted, "expected at least one cap abort on this corpus"
    for rec in aborted:
        expected = (kgrepair.SUBSET_CAP_DEFAULT if rec["mode"] == "subset"
                    else kgrepair.SUPERSET_CAP_DEFAULT)
        assert rec["cap"]["cap"] == expected
        assert rec["cap"]["fraction"] > expected
        assert rec["metrics_after"] is None
    assert "ABORTED-BY-CAP" in bct.objective4(records)


def test_completed_cells_carry_their_engine_attestation(records):
    for rec in records:
        if rec["stop_reason"] != "completed":
            continue
        assert rec["attestations"].get("consistent_after") is True, rec["cell"]


def test_routed_violations_reach_zero_wherever_the_engine_acted(records):
    """The engine's own claim, which is about the constraints it is routed to and not
    about every ptime_core constraint. This is the distinction the campaign found the
    P8b prediction had missed."""
    for rec in records:
        if rec["stop_reason"] != "completed":
            continue
        after = (rec.get("routed_after") or {}).get("violations")
        if after is None:
            assert rec["routed_before"]["constraints"] == 0, rec["cell"]
            continue
        assert after == 0, f"{rec['cell']} left {after} routed violation(s)"
