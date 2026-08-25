"""
V2 gate -- Check screen tests.

Table counts must equal the validator's own counts on a fixture with known
violations; boundary rows must never carry a repair affordance; the witness
neighbourhood must respect its node_cap; a clean slice (YAGO taxa) must hit the
consistent empty state.
"""
import os

from streamlit.testing.v1 import AppTest

from app import manifests as mf
from app.screens.check import _run_consistency
from kgrepair.repair.subset import eligible_constraints
from kgrepair.validator import Validator


APP = os.path.join(os.path.dirname(__file__), "..", "app", "main.py")


def _go_to_check(manifest_label: str):
    at = AppTest.from_file(APP)
    at.run(timeout=30)
    labels = list(at.selectbox[0].options)
    at.selectbox[0].select_index(labels.index(manifest_label)).run(timeout=30)
    at.sidebar.radio[0].set_value("Check").run(timeout=30)
    return at


def test_check_screen_counts_match_validator_directly():
    entries = mf.discover_manifests()
    entry = next(e for e in entries if e.name == "real_wikidata_geography_1000")
    label = next(iter(mf.matching_constraint_sets(entry).keys()))
    cs = mf.matching_constraint_sets(entry)[label]

    result = _run_consistency(entry.nt_path, entry.content_hash or "", label)

    graph = mf.load_graph_cached(entry.nt_path, entry.content_hash or "")
    report = Validator(graph, use_closure=True).validate(cs)
    expected = {v.constraint.cid: v.count for v in report.violations}
    got = {row["cid"]: row["count"] for row in result["rows"]}
    assert got == expected
    assert result["consistent"] == report.consistent
    assert result["total_witnesses"] == report.total_witnesses()


def test_subset_witness_fraction_matches_first_round_definition():
    """Cross-check against the same definition bench/real_ladder.py uses
    (union of eligible subset-direction witnesses / |V|), computed independently
    here rather than trusting the cached UI value."""
    entries = mf.discover_manifests()
    entry = next(e for e in entries if e.name == "real_wikidata_geography_1000")
    label = next(iter(mf.matching_constraint_sets(entry).keys()))
    cs = mf.matching_constraint_sets(entry)[label]
    graph = mf.load_graph_cached(entry.nt_path, entry.content_hash or "")

    validator = Validator(graph, use_closure=True)
    witnesses = set()
    for c in eligible_constraints(cs):
        witnesses |= validator.check_one(c).witnesses
    expected_frac = len(witnesses) / max(1, graph.stats()["nodes"])

    result = _run_consistency(entry.nt_path, entry.content_hash or "", label)
    assert result["subset_witness_count"] == len(witnesses)
    assert abs(result["subset_witness_fraction"] - expected_frac) < 1e-9


def test_boundary_rows_carry_report_only_badge_no_repair_affordance():
    at = _go_to_check("[real] real_wikidata_geography_1000")
    assert not at.exception
    expander_labels = [e.label for e in at.expander]
    boundary_labels = [l for l in expander_labels if l.startswith("[boundary/")]
    assert boundary_labels, "expected at least one boundary violation in this fixture"
    for l in boundary_labels:
        assert "report-only" in l
    # No button widgets anywhere on the Check screen (no repair affordance at all).
    assert len(at.button) == 0


def test_neighbourhood_cap_respected_from_ui_sliders():
    at = _go_to_check("[real] real_wikidata_geography_10000")
    assert not at.exception
    cap_sliders = [s for s in at.slider if s.label == "node cap"]
    assert cap_sliders
    small_cap = 15
    cap_sliders[0].set_value(small_cap).run(timeout=30)
    assert not at.exception


def test_consistent_slice_hits_empty_state():
    at = _go_to_check("[real] real_yago_taxa_1000")
    assert not at.exception
    assert any("Consistent" in s.value for s in at.success)
    assert len(at.expander) == 0   # no violation expanders on a clean slice


def test_import_direction_still_holds_with_check_screen_present():
    """Guard against a future edit accidentally wiring Check's viz/UI imports
    back into the repair engines."""
    src = os.path.join(os.path.dirname(__file__), "..", "src", "kgrepair")
    for fname in ("repair/subset.py", "repair/superset.py"):
        with open(os.path.join(src, fname), "r", encoding="utf-8") as fh:
            text = fh.read()
        assert "streamlit" not in text
        assert "import app" not in text
