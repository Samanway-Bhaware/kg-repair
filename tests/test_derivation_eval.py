"""
The P4c evaluation artifacts: committed, traceable, and internally consistent.

The chapter cites `eval/derivation_search_evaluation.md`, so the numbers in it have
to trace back to a results file, and that file has to say which slice and which code
revision produced them. These tests hold that chain rather than re-running the
evaluation, which takes long enough that putting it on every build would not pay for
itself. Regenerate the artifacts with `python scripts/eval_derivation_search.py`.

Runtimes are the one thing here that is deliberately not reproducible, and the
reproducibility test excludes them by name rather than by rounding.
"""
from __future__ import annotations

import json
import os
import re

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MD = os.path.join(ROOT, "eval", "derivation_search_evaluation.md")
JSON = os.path.join(ROOT, "eval", "derivation_search_evaluation.json")
JSONL = os.path.join(ROOT, "results", "derivation_eval.jsonl")
P2302 = os.path.join(ROOT, "data", "raw", "constraints", "wikidata_p2302.json")


@pytest.fixture(scope="module")
def report():
    with open(JSON, encoding="utf-8") as fh:
        return json.load(fh)


@pytest.fixture(scope="module")
def records():
    with open(JSONL, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


@pytest.fixture(scope="module")
def markdown():
    with open(MD, encoding="utf-8") as fh:
        return fh.read()


def test_the_artifacts_are_committed():
    for path in (MD, JSON, JSONL, P2302):
        assert os.path.exists(path), f"{os.path.relpath(path, ROOT)} is missing"


def test_every_record_names_its_slice_and_its_code_revision(records):
    """T6's gate: a number traces to a record, and a record traces to a graph and a
    revision. A record with no content hash anywhere in it cannot be traced back to
    the data it describes."""
    assert {r["task"] for r in records} == {"T1", "T2", "T3", "T4", "T5"}
    for record in records:
        assert record["code_revision"], record["task"]
        blob = json.dumps(record)
        assert "content_hash" in blob or "target_hash" in blob, record["task"]


def test_the_pruning_ablation_lost_nothing_above_the_floor(report):
    """The claim the two pruning laws make, read back off the committed table. A
    loss here is a defect in the search, not a threshold to adjust."""
    t1 = report["T1"]
    assert t1["any_loss"] is False
    assert len(t1["rows"]) == 4
    for row in t1["rows"]:
        assert row["lost_above_min_conf"] == [], row["configuration"]
        assert row["admitted"] == t1["oracle_admitted"], row["configuration"]


def test_third_party_recovery_reports_both_counts_and_the_inexpressible_separately(report):
    """Never one count: expressible-and-found and expressible-and-missed are
    reported apart from each other, and both apart from what the fragment cannot
    state at all."""
    t2 = report["T2"]
    assert t2["available"] is True
    assert (t2["expressible_and_found"] + t2["expressible_and_missed"]
            == t2["expressible_in_scope"])
    assert t2["not_expressible_total"] > 0
    assert all(entry["reason"] for entry in t2["not_expressible"])
    assert t2["expressible_total"] + t2["not_expressible_total"] == t2["statements_total"]


def test_transfer_is_reported_in_both_vocabularies(report):
    """The as-derived rows are the finding that nothing transfers without a map; the
    translated rows are the distribution the phase asks for. Both are needed, so
    both have to be present."""
    pairs = report["T3"]["pairs"]
    vocabularies = {(p["domain"], p["vocabulary"]) for p in pairs}
    for domain in ("geography", "taxa"):
        assert (domain, "as derived") in vocabularies
        assert (domain, "translated") in vocabularies
    translated = [p for p in pairs if p["vocabulary"] == "translated"]
    assert any(p["comparable"] > 0 for p in translated), \
        "no candidate survived translation, so no distribution was measured"


def test_the_rc1_cases_are_named_individually(report):
    probes = report["T3"]["rc1_probes"]
    assert len(probes) >= 3
    assert all(p["cid"] and p["why"] for p in probes)
    discarded = {p["cid"] for p in probes if p["would_be_discarded"]}
    assert "ana.wd.dom.partof" in discarded, \
        "the over-broad v1 rule is the case this experiment exists for"
    assert "ana.wd.dom.partof.v2" not in discarded, \
        "the fixed rule must not be discarded alongside the one it fixed"


def test_every_unrecovered_authored_constraint_has_a_classification(report):
    """The gate on T4: none left unexplained."""
    known = ("outside the search space", "below the support floor", "a genuine gap")
    for entry in report["T4"]["unrecovered"]:
        assert entry["classification"].startswith(known), entry["cid"]


def test_the_reviewer_curves_are_both_present_with_the_limitation(report, markdown):
    t5 = report["T5"]
    assert t5["by_confidence"] and t5["by_impact"]
    assert t5["by_confidence"][-1]["accepted"] == t5["oracle_accepts"]
    assert t5["by_impact"][-1]["accepted"] == t5["oracle_accepts"]
    assert "authored v2" in t5["limitation"]
    # the limitation is stated with the result, not filed somewhere else
    section = markdown.split("## T5. Reviewer effort", 1)[1]
    assert "Limitation" in section


def test_the_headline_numbers_in_the_markdown_come_from_the_results_file(report, markdown):
    """Spot-check the traceability claim the document opens with: a number in a
    table is the number in the results file, not a transcription of one."""
    t1, t2, t5 = report["T1"], report["T2"], report["T5"]
    for value in (t1["oracle_admitted"], t2["statements_total"],
                  t2["expressible_and_found"], t2["expressible_and_missed"],
                  t5["oracle_accepts"], t5["candidates"]):
        assert re.search(rf"\b{value}\b", markdown), value


def test_the_p2302_cache_is_third_party_and_complete():
    """The evaluation reads a cache rather than the network, so the study repeats
    offline. An empty cache would silently turn T2 into a no-op."""
    with open(P2302, encoding="utf-8") as fh:
        cache = json.load(fh)
    assert cache["failed"] == []
    assert len(cache["constraints"]) >= 10
    assert sum(len(v) for v in cache["constraints"].values()) > 50
