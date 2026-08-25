"""T1 gate: the instrumentation harness emits schema-valid JSONL and summarises."""
import json
import os

from kgrepair import constraints
from kgrepair.instrument import (
    RunContext, constraints_meta, slice_meta_from_graph, validate_record,
    summarise_timing, summarise_strategies, render_table, code_revision,
)
from kgrepair.ntriples import load_ntriples_file
from kgrepair.repair import subset_repair
from kgrepair.validator import Validator


FIXTURES = os.path.join(os.path.dirname(__file__), "..", "fixtures")

def _run_fixture(results_dir, fixture, domain, mode, strategy):
    cs = constraints.get(domain, "wikidata")
    with RunContext(results_dir, slice={}, constraints=constraints_meta(cs), mode=mode) as run:
        with run.phase("load"):
            g = load_ntriples_file(os.path.join(FIXTURES, fixture))
        run.slice = slice_meta_from_graph(g, source="fixture", manifest_hash="test")
        with run.phase("consistency_initial"):
            before = Validator(g).validate(cs)
        with run.phase("repair_loop"):
            res = subset_repair(g, cs, strategy=strategy)
        with run.phase("consistency_final"):
            after = Validator(res.graph).validate(cs)
        run.set_repair_result(res, before, after)
    return run.record


def test_run_context_emits_schema_valid_record(tmp_path):
    rec = _run_fixture(str(tmp_path), "synthetic_geography_wd.nt", "geography",
                       "subset_full", "full")
    problems = validate_record(rec)
    assert problems == [], f"schema problems: {problems}"
    assert rec["status"] == "OK"
    assert rec["slice"]["source"] == "fixture"
    assert rec["repair"]["strategy"] == "full"
    assert rec["attestations"]["consistent_after"] is True
    # the JSONL file has exactly one line, and it round-trips
    line = (tmp_path / "runs.jsonl").read_text().strip()
    assert json.loads(line) == rec


def test_code_revision_is_retraceable():
    rev = code_revision()
    assert rev and (len(rev) >= 12)  # git SHA or nogit:<hash>


def test_summariser_builds_tables_from_multiple_records(tmp_path):
    results = str(tmp_path)
    _run_fixture(results, "synthetic_geography_wd.nt", "geography", "subset_full", "full")
    _run_fixture(results, "synthetic_geography_wd.nt", "geography", "subset_incremental", "incremental")
    _run_fixture(results, "synthetic_anatomy_wd.nt", "anatomy", "subset_full", "full")

    path = os.path.join(results, "runs.jsonl")
    timing = summarise_timing(path)
    assert len(timing) >= 2
    assert all("t_load" in row and "t_repair_loop" in row for row in timing)
    assert render_table(timing).count("\n") >= 3  # header + sep + >=2 body rows

    strat = summarise_strategies(path)
    assert len(strat) >= 1
    row = strat[0]
    assert row["recheck_full"] >= row["recheck_incr"]
    assert "recheck_reduction_%" in row


def test_failed_attestation_marks_record_failed(tmp_path):
    cs = constraints.get("geography", "wikidata")
    with RunContext(str(tmp_path), slice=slice_meta_from_graph(
            load_ntriples_file(os.path.join(FIXTURES, "synthetic_geography_wd.nt")),
            source="fixture"), constraints=constraints_meta(cs), mode="consistency") as run:
        run.set_attestations({"consistent_after": False})
    assert run.record["status"] == "FAILED"
    assert validate_record(run.record) == []
