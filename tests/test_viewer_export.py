"""
V4 gate -- Export screen tests: N-Triples round-trip, result-JSON round-trip,
retraceability, the grep gate for forbidden "maximal"/"minimal" wording, and
AppTest smoke tests for both the pre-repair and post-repair Export states.

Same test-pollution discipline as V3: `repair_mod.RESULTS_DIR` is always
monkeypatched to a tmp directory here.
"""
import json
import os

from streamlit.testing.v1 import AppTest

from app import manifests as mf
from app.screens import repair as repair_mod
from kgrepair.ntriples import load_ntriples, to_ntriples
from kgrepair.validator import Validator


APP = os.path.join(os.path.dirname(__file__), "..", "app", "main.py")
APP_DIR = os.path.join(os.path.dirname(__file__), "..", "app")


def _entry_and_cs(name: str):
    entries = mf.discover_manifests()
    entry = next(e for e in entries if e.name == name)
    cs = next(iter(mf.matching_constraint_sets(entry).values()))
    return entry, cs


def _entry_and_cs_labelled(name: str):
    """(entry, cs, label) for `mf.session_for`, which the screens take now."""
    entries = mf.discover_manifests()
    entry = next(e for e in entries if e.name == name)
    label, cs = next(iter(mf.matching_constraint_sets(entry).items()))
    return entry, cs, label


def test_exported_ntriples_reloads_and_revalidates_subset(tmp_path, monkeypatch):
    monkeypatch.setattr(repair_mod, "RESULTS_DIR", str(tmp_path))
    session = mf.session_for(*_entry_and_cs_labelled("real_wikidata_geography_1000"))
    cs, graph = session.constraints, session.graph
    result = repair_mod._run_subset(session, strategy="full", cap=0.20, use_closure=True)
    res = result["result"]

    nt_text = to_ntriples(res.graph)
    reloaded = load_ntriples(nt_text.splitlines())
    assert set(reloaded.edges()) == set(res.graph.edges())
    # Edge-bearing nodes must round-trip exactly; edge-less survivors of the
    # cascade (real for this fixture -- SubsetRepair leaves many isolated
    # nodes) are the one documented N-Triples limitation and are expected to
    # be dropped, not a bug (see ntriples.py::to_ntriples docstring).
    edge_bearing = {n for e in res.graph.edges() for n in (e[0], e[2])}
    assert edge_bearing <= reloaded.nodes
    assert len(reloaded.nodes) <= len(res.graph.nodes)

    report = Validator(reloaded, use_closure=True).validate(cs)
    core = [v for v in report.violations if v.constraint.tier == "ptime_core"
           and v.constraint.direction == "subset"]
    assert all(v.count == 0 for v in core)


def test_exported_ntriples_reloads_and_revalidates_superset_with_fresh_symbol(tmp_path, monkeypatch):
    monkeypatch.setattr(repair_mod, "RESULTS_DIR", str(tmp_path))
    session = mf.session_for(*_entry_and_cs_labelled("synthetic_geoLike_1k_s0"))
    cs, graph = session.constraints, session.graph
    result = repair_mod._run_superset(session, prune=True, cap=0.30, use_closure=True)
    res = result["result"]
    assert res.fresh_used, "fixture should exercise at least one fresh symbol"

    nt_text = to_ntriples(res.graph)
    reloaded = load_ntriples(nt_text.splitlines())
    assert set(reloaded.edges()) == set(res.graph.edges())
    for fresh_node in res.fresh_used:
        assert fresh_node in reloaded.nodes

    report = Validator(reloaded, use_closure=True).validate(cs)
    core = [v for v in report.violations if v.constraint.tier == "ptime_core"]
    assert all(v.count == 0 for v in core)


def test_result_json_round_trips_and_matches_to_dict(tmp_path, monkeypatch):
    monkeypatch.setattr(repair_mod, "RESULTS_DIR", str(tmp_path))
    session = mf.session_for(*_entry_and_cs_labelled("real_wikidata_geography_1000"))
    cs, graph = session.constraints, session.graph
    result = repair_mod._run_subset(session, strategy="full", cap=0.20, use_closure=True)
    res = result["result"]

    text = res.to_json()
    parsed = json.loads(text)
    assert parsed == res.to_dict()
    assert parsed["changelog"] == res.changelog_dicts()
    assert parsed["attestations"] == res.attestations


def test_grep_gate_maximal_minimal_absent_from_viewer_code():
    for root, _dirs, files in os.walk(APP_DIR):
        for name in files:
            if not name.endswith(".py"):
                continue
            path = os.path.join(root, name)
            with open(path, "r", encoding="utf-8") as fh:
                text = fh.read().lower()
            assert "maximal" not in text, f"{path} contains 'maximal'"
            assert "minimal" not in text, f"{path} contains 'minimal'"


def test_export_screen_before_repair_offers_original_graph_download(tmp_path, monkeypatch):
    monkeypatch.setattr(repair_mod, "RESULTS_DIR", str(tmp_path))
    at = AppTest.from_file(APP)
    at.run(timeout=30)
    labels = list(at.selectbox[0].options)
    at.selectbox[0].select_index(
        labels.index("[real] real_wikidata_geography_1000")).run(timeout=30)
    at.sidebar.radio[0].set_value("Export").run(timeout=30)
    assert not at.exception
    assert any("no repair result" in i.value.lower() for i in at.info)
    assert len(at.dataframe) == 1   # retraceability block


def test_export_screen_after_repair_shows_retraceability_and_downloads(tmp_path, monkeypatch):
    monkeypatch.setattr(repair_mod, "RESULTS_DIR", str(tmp_path))
    at = AppTest.from_file(APP)
    at.run(timeout=30)
    labels = list(at.selectbox[0].options)
    at.selectbox[0].select_index(
        labels.index("[real] real_wikidata_geography_1000")).run(timeout=30)
    at.sidebar.radio[0].set_value("Repair").run(timeout=30)
    at.button[0].click().run(timeout=60)
    at.sidebar.radio[0].set_value("Export").run(timeout=30)
    assert not at.exception
    assert len(at.dataframe) == 1
    assert not any("no repair result" in i.value.lower() for i in at.info)


def test_synthetic_slice_export_path_has_no_exception(tmp_path, monkeypatch):
    monkeypatch.setattr(repair_mod, "RESULTS_DIR", str(tmp_path))
    at = AppTest.from_file(APP)
    at.run(timeout=30)
    labels = list(at.selectbox[0].options)
    at.selectbox[0].select_index(
        labels.index("[synthetic] synthetic_geoLike_1k_s0")).run(timeout=30)
    at.sidebar.radio[0].set_value("Repair").run(timeout=30)
    eng = [r for r in at.radio if r.label == "Engine"][0]
    eng.set_value("SupersetRepair (addition)").run(timeout=30)
    at.button[0].click().run(timeout=60)
    at.sidebar.radio[0].set_value("Export").run(timeout=30)
    assert not at.exception


def test_yago_taxa_consistent_slice_export_path_has_no_exception(tmp_path, monkeypatch):
    """Consistent slice -> no repair result exists, but Export must still
    render (original-graph download only), matching the empty state elsewhere."""
    monkeypatch.setattr(repair_mod, "RESULTS_DIR", str(tmp_path))
    at = AppTest.from_file(APP)
    at.run(timeout=30)
    labels = list(at.selectbox[0].options)
    at.selectbox[0].select_index(
        labels.index("[real] real_yago_taxa_1000")).run(timeout=30)
    at.sidebar.radio[0].set_value("Export").run(timeout=30)
    assert not at.exception
    assert any("no repair result" in i.value.lower() for i in at.info)
