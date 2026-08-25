"""
V3 gate -- Repair screen tests.

IMPORTANT: every test monkeypatches `app.screens.repair.RESULTS_DIR` to a tmp
directory before triggering a run. The real `results/runs.jsonl` is the D7
evaluation dataset (`docs/evaluation.md` is built from it); a pytest run must
never append test-fixture records into it, even though "viewer-initiated runs
are logged like any other run" is correct behaviour for real interactive use
(the default `RESULTS_DIR` there is the real `results/` directory).
"""
import json
import os

from streamlit.testing.v1 import AppTest

from app import manifests as mf
from app.screens import repair as repair_mod
from kgrepair.instrument import validate_record
from kgrepair.validator import Validator


APP = os.path.join(os.path.dirname(__file__), "..", "app", "main.py")


def _entry_and_cs(name: str, label_prefix: str = ""):
    entries = mf.discover_manifests()
    entry = next(e for e in entries if e.name == name)
    choices = mf.matching_constraint_sets(entry)
    label = next(l for l in choices if l.startswith(label_prefix)) if label_prefix else next(iter(choices))
    return entry, choices[label]


def _session(name: str, label_prefix: str = ""):
    """The `logic.Session` the Load screen would build for this fixture. The screen
    runners take a session now, whichever way the graph was loaded."""
    entries = mf.discover_manifests()
    entry = next(e for e in entries if e.name == name)
    choices = mf.matching_constraint_sets(entry)
    label = (next(l for l in choices if l.startswith(label_prefix)) if label_prefix
             else next(iter(choices)))
    return mf.session_for(entry, choices[label], label)


 
# direct (non-AppTest) tests -- fast, precise fixture assertions
 

def test_subset_run_post_repair_count_matches_fresh_validator_call(tmp_path, monkeypatch):
    monkeypatch.setattr(repair_mod, "RESULTS_DIR", str(tmp_path))
    session = _session("real_wikidata_geography_1000")
    cs, graph = session.constraints, session.graph

    result = repair_mod._run_subset(session, strategy="full", cap=0.20, use_closure=True)
    assert result["status"] == "OK"
    res = result["result"]

    fresh = Validator(res.graph, use_closure=True).validate(cs)
    assert fresh.total_witnesses() == result["after"].total_witnesses()
    core_after = [v for v in fresh.violations if v.constraint.tier == "ptime_core"
                 and v.constraint.direction == "subset"]
    assert all(v.count == 0 for v in core_after)


def test_superset_run_resolves_all_synthetic_ground_truth_witnesses(tmp_path, monkeypatch):
    monkeypatch.setattr(repair_mod, "RESULTS_DIR", str(tmp_path))
    session = _session("synthetic_geoLike_1k_s0")
    cs, graph = session.constraints, session.graph

    before = Validator(graph, use_closure=True).validate(cs)
    result = repair_mod._run_superset(session, prune=True, cap=0.30, use_closure=True)
    assert result["status"] == "OK"
    res = result["result"]
    assert res.attestations["consistent_after"]
    assert res.attestations["superset_only_added"]
    assert res.attestations["data_values_unmodified"]

    after = Validator(res.graph, use_closure=True).validate(cs)
    core_after = [v for v in after.violations if v.constraint.tier == "ptime_core"]
    assert all(v.count == 0 for v in core_after), "not every ptime_core witness was resolved"
    assert before.total_witnesses() > 0, "fixture must actually have violations to be meaningful"


def test_every_changelog_record_renders_a_neighbourhood_without_error(tmp_path, monkeypatch):
    """Drives extract_neighbourhood over every record's center on the reference
    graph the Repair screen itself picks (pre-graph for subset, post-graph for
    superset) -- the same logic `_render_changelog_and_diffs` uses."""
    from kgrepair.neighbourhood import change_record_center, extract_neighbourhood

    monkeypatch.setattr(repair_mod, "RESULTS_DIR", str(tmp_path))
    session = _session("synthetic_geoLike_1k_s0")
    cs, graph = session.constraints, session.graph
    result = repair_mod._run_superset(session, prune=True, cap=0.30, use_closure=True)
    res = result["result"]
    assert res.changelog

    for rec in res.changelog:
        center = change_record_center(rec)
        assert center in res.graph.nodes
        view = extract_neighbourhood(res.graph, center, k=1, changelog=res.changelog)
        assert view.nodes


def test_repair_is_deterministic_two_runs_identical_log_and_nodes(tmp_path, monkeypatch):
    monkeypatch.setattr(repair_mod, "RESULTS_DIR", str(tmp_path))
    session = _session("real_wikidata_geography_1000")
    cs, graph = session.constraints, session.graph

    r1 = repair_mod._run_subset(session, strategy="full", cap=0.20, use_closure=True)
    r2 = repair_mod._run_subset(session, strategy="full", cap=0.20, use_closure=True)
    assert r1["result"].changelog_dicts() == r2["result"].changelog_dicts()
    assert r1["result"].deleted_nodes == r2["result"].deleted_nodes


def test_results_jsonl_record_is_schema_valid_and_tagged_origin_viewer(tmp_path, monkeypatch):
    monkeypatch.setattr(repair_mod, "RESULTS_DIR", str(tmp_path))
    session = _session("real_wikidata_geography_1000")
    cs, graph = session.constraints, session.graph
    repair_mod._run_subset(session, strategy="full", cap=0.20, use_closure=True)

    path = tmp_path / "runs.jsonl"
    assert path.exists()
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert validate_record(record) == []
    assert record["slice"]["params"]["origin"] == "viewer"


def test_cap_abort_does_not_call_the_engine_or_mutate_the_graph(tmp_path, monkeypatch):
    monkeypatch.setattr(repair_mod, "RESULTS_DIR", str(tmp_path))
    session = _session("real_wikidata_geography_10000")   # known 23.8% > 20% cap
    cs, graph = session.constraints, session.graph
    nodes_before = set(graph.nodes)

    result = repair_mod._run_subset(session, strategy="full", cap=0.20, use_closure=True)
    assert result["status"] == "ABORTED-BY-CAP"
    assert "result" not in result
    assert set(graph.nodes) == nodes_before   # the shared cached graph was never touched

    path = tmp_path / "runs.jsonl"
    record = json.loads(path.read_text(encoding="utf-8").strip())
    assert record["status"] == "ABORTED-BY-CAP"


 
# AppTest end-to-end smoke tests
 

def _goto_repair(manifest_label: str, tmp_dir: str):
    repair_mod.RESULTS_DIR = tmp_dir
    at = AppTest.from_file(APP)
    at.run(timeout=30)
    labels = list(at.selectbox[0].options)
    at.selectbox[0].select_index(labels.index(manifest_label)).run(timeout=30)
    at.sidebar.radio[0].set_value("Repair").run(timeout=30)
    return at


def test_ui_subset_happy_path_renders_outcome_and_changelog(tmp_path, monkeypatch):
    monkeypatch.setattr(repair_mod, "RESULTS_DIR", str(tmp_path))
    at = _goto_repair("[real] real_wikidata_geography_1000", str(tmp_path))
    at.button[0].click().run(timeout=60)
    assert not at.exception
    assert any("Repaired in" in s.value for s in at.success)
    assert len(at.dataframe) >= 1


def test_ui_cap_abort_renders_report_panel_not_error(tmp_path, monkeypatch):
    monkeypatch.setattr(repair_mod, "RESULTS_DIR", str(tmp_path))
    at = _goto_repair("[real] real_wikidata_geography_10000", str(tmp_path))
    at.button[0].click().run(timeout=60)
    assert not at.exception
    assert any("ABORTED-BY-CAP" in e.value for e in at.error)
    assert any("report-first" in i.value for i in at.info)


def test_ui_superset_happy_path_shows_additions_and_changelog(tmp_path, monkeypatch):
    monkeypatch.setattr(repair_mod, "RESULTS_DIR", str(tmp_path))
    at = _goto_repair("[real] real_wikidata_geography_1000", str(tmp_path))
    eng = [r for r in at.radio if r.label == "Engine"][0]
    eng.set_value("SupersetRepair (addition)").run(timeout=30)
    at.button[0].click().run(timeout=60)
    assert not at.exception
    assert any("Repaired in" in s.value for s in at.success)


def test_import_direction_still_holds_with_repair_screen_present():
    src = os.path.join(os.path.dirname(__file__), "..", "src", "kgrepair")
    for fname in ("repair/subset.py", "repair/superset.py"):
        with open(os.path.join(src, fname), "r", encoding="utf-8") as fh:
            text = fh.read()
        assert "streamlit" not in text
        assert "import app" not in text
