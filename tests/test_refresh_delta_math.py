"""
Offline unit test for the pass-2 refresh comparison arithmetic.

`bench/refresh_pass2.py` is a diagnostic that reaches the network, and it is
deliberately NOT a gate: it has no pass/fail and no expected refreshed values.
Its comparison stage, though, is pure arithmetic over two count sets, and that
part is worth pinning, because a sign error in a delta or a wrong denominator in
a prevalence figure would quietly misreport drift.

So this file tests part B only, on synthetic count sets built in memory. It never
fetches, never reads a refreshed artifact, and never asserts anything about what
the live sources currently hold.
"""
import sys
import os

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "bench"))

import refresh_pass2 as refresh


def _counts(per_cid, V=100, E=1000, core_cids=()):
    """A synthetic Counts, splitting tiers by an explicit cid list."""
    core = sum(n for cid, n in per_cid.items() if cid in core_cids)
    boundary = sum(n for cid, n in per_cid.items() if cid not in core_cids)
    return refresh.Counts(total=core + boundary, core=core, boundary=boundary,
                          per_cid=dict(per_cid), V=V, E=E)


CORE = ("c.dom", "c.rng", "c.req")


# ---------- prevalence ------------------------------------------------------

@pytest.mark.parametrize("core,edges,expected", [
    (67, 1000, 67.0),          # the geography-1000 shape: per 1000 edges
    (1586, 10000, 158.6),      # the geography-10000 shape
    (0, 1000, 0.0),
    (5, 500, 10.0),            # half the edges, so double the rate
    (7, 0, 0.0),               # no edges: report zero rather than dividing by it
])
def test_prevalence_is_violations_per_thousand_edges(core, edges, expected):
    assert refresh.prevalence(core, edges) == expected


def test_prevalence_separates_a_size_change_from_a_data_change():
    """The reason prevalence is reported at all: the same count on a different
    edge base is a different finding."""
    same_rate = refresh.prevalence(100, 1000) == refresh.prevalence(200, 2000)
    assert same_rate
    assert refresh.prevalence(50, 1000) < refresh.prevalence(100, 1000)


# ---------- per-constraint deltas -------------------------------------------

def test_cid_deltas_cover_both_sides_and_sort():
    baseline = _counts({"c.rng": 9, "c.dom": 41}, core_cids=CORE)
    refreshed = _counts({"c.dom": 38, "b.sym": 4}, core_cids=CORE)
    rows = refresh.cid_deltas(baseline, refreshed)

    assert [r["cid"] for r in rows] == ["b.sym", "c.dom", "c.rng"]
    by_cid = {r["cid"]: r for r in rows}
    assert by_cid["c.dom"] == {"cid": "c.dom", "frozen": 41, "refreshed": 38, "delta": -3}
    assert by_cid["c.rng"] == {"cid": "c.rng", "frozen": 9, "refreshed": 0, "delta": -9}
    assert by_cid["b.sym"] == {"cid": "b.sym", "frozen": 0, "refreshed": 4, "delta": 4}


def test_a_constraint_that_did_not_move_reports_zero():
    counts = _counts({"c.dom": 12}, core_cids=CORE)
    assert refresh.cid_deltas(counts, counts) == [
        {"cid": "c.dom", "frozen": 12, "refreshed": 12, "delta": 0}]


# ---------- edge drift ------------------------------------------------------

@pytest.mark.parametrize("base_e,live_e,expected", [
    (1000, 1000, 0.0),
    (1000, 1020, 0.02),
    (1000, 900, -0.1),
    (0, 1000, 0.0),            # no baseline edges: report zero rather than dividing
])
def test_edge_drift_is_the_fractional_change(base_e, live_e, expected):
    baseline = _counts({}, E=base_e)
    refreshed = _counts({}, E=live_e)
    assert refresh.edge_drift(baseline, refreshed) == expected


def test_composition_shift_flags_only_a_material_edge_move():
    """The target edge count is pinned, so E should barely move. A real move means
    the slice population changed and the count comparison needs reading with care."""
    baseline = _counts({"c.dom": 10}, E=1000, core_cids=CORE)
    steady = refresh.compare_cell("x", baseline, _counts({"c.dom": 10}, E=1000,
                                                         core_cids=CORE))
    nudged = refresh.compare_cell("x", baseline, _counts({"c.dom": 10}, E=1010,
                                                         core_cids=CORE))
    shifted = refresh.compare_cell("x", baseline, _counts({"c.dom": 10}, E=1200,
                                                           core_cids=CORE))
    assert steady["composition_shifted"] is False
    assert nudged["composition_shifted"] is False      # 1% is inside tolerance
    assert shifted["composition_shifted"] is True      # 20% is not


# ---------- the assembled comparison ----------------------------------------

def test_compare_cell_reports_every_figure_the_report_needs():
    baseline = _counts({"c.dom": 41, "c.rng": 9, "b.sym": 24}, V=725, E=1000,
                       core_cids=CORE)
    refreshed = _counts({"c.dom": 30, "c.rng": 9, "b.sym": 24}, V=730, E=1000,
                        core_cids=CORE)
    row = refresh.compare_cell("real_wikidata_geography_1000", baseline, refreshed)

    assert row["status"] == "ok"
    assert row["frozen"]["core"] == 50 and row["frozen"]["boundary"] == 24
    assert row["frozen"]["total"] == 74
    assert row["refreshed"]["core"] == 39
    assert row["core_delta"] == -11
    assert row["total_delta"] == -11
    assert row["frozen_prevalence_per_1k_edges"] == 50.0
    assert row["refreshed_prevalence_per_1k_edges"] == 39.0
    assert row["prevalence_delta"] == -11.0
    assert row["edge_drift_fraction"] == 0.0
    assert row["moved"] is True


def test_an_unmoved_cell_reports_moved_false():
    """The YAGO case: a fixed release re-read from the same dump should come back
    identical, and the report should say so rather than showing noise."""
    counts = _counts({}, V=515, E=1000, core_cids=CORE)
    row = refresh.compare_cell("real_yago_taxa_1000", counts, counts)
    assert row["moved"] is False
    assert row["core_delta"] == 0
    assert row["prevalence_delta"] == 0.0
    assert row["cid_deltas"] == []


def test_compare_cell_does_no_io_and_keeps_no_clock():
    """Part B is re-runnable: the same inputs give the same row every time, with no
    timestamp baked in."""
    baseline = _counts({"c.dom": 5}, core_cids=CORE)
    refreshed = _counts({"c.dom": 3}, core_cids=CORE)
    first = refresh.compare_cell("x", baseline, refreshed)
    second = refresh.compare_cell("x", baseline, refreshed)
    assert first == second


def test_failed_cell_keeps_the_baseline_and_names_the_reason():
    baseline = _counts({"c.dom": 5}, core_cids=CORE)
    row = refresh.failed_cell("real_dbpedia_geography_1000", "HTTPError: 504", baseline)
    assert row["status"] == "fetch_failed"
    assert row["reason"] == "HTTPError: 504"
    assert row["frozen"]["core"] == 5
    assert row["refreshed"] == {}
    assert row["moved"] is None


# ---------- report text -----------------------------------------------------

def test_report_labels_keep_frozen_and_refreshed_apart():
    """The two sets of numbers must never read as one. The report says which is
    the reported figure and which is the release candidate."""
    baseline = _counts({"c.dom": 41}, E=1000, core_cids=CORE)
    refreshed = _counts({"c.dom": 30}, E=1000, core_cids=CORE)
    rows = [refresh.compare_cell("cell_a", baseline, refreshed),
            refresh.failed_cell("cell_b", "timeout", baseline)]
    text = refresh.render_markdown(rows, "20260801")

    assert "frozen (as-reported)" in text
    assert "live (D8-release candidate, fetched 20260801)" in text
    assert "never merged" in text
    assert "cell_a" in text and "cell_b" in text
    assert "timeout" in text
    assert "1 cell(s) moved" in text


def test_report_offers_both_readings_of_a_drop_without_choosing():
    """A fallen count has two explanations and the report presents both."""
    baseline = _counts({"c.dom": 41}, E=1000, core_cids=CORE)
    refreshed = _counts({"c.dom": 30}, E=1000, core_cids=CORE)
    text = refresh.render_markdown(
        [refresh.compare_cell("cell_a", baseline, refreshed)], "20260801")
    assert "upstream corrected genuine errors" in text
    assert "slice composition shifted" in text


def test_report_has_no_banned_wording():
    baseline = _counts({"c.dom": 41}, E=1000, core_cids=CORE)
    refreshed = _counts({"c.dom": 55}, E=1400, core_cids=CORE)
    text = refresh.render_markdown(
        [refresh.compare_cell("cell_a", baseline, refreshed)], "20260801").lower()
    for word in ("minimal", "maximal", "—", "–"):
        assert word not in text


# ---------- the frozen tree is read-only here -------------------------------

def test_refresh_writes_outside_the_frozen_tree():
    """The output directories are separate from the committed corpus, so a refresh
    cannot overwrite a number the write-up reports."""
    root = os.path.abspath(refresh.ROOT)
    frozen = os.path.abspath(refresh.FROZEN_DIR)
    for target in (refresh.REFRESH_ROOT, refresh.CACHE_ROOT):
        target = os.path.abspath(target)
        assert os.path.commonpath([target, frozen]) != frozen
        assert os.path.commonpath([target, root]) == root


def test_cells_come_from_the_pass_1_gate():
    """One source for which cells exist and how they are pinned, shared with
    `tests/test_regression_pass1.py` rather than copied."""
    from test_regression_pass1 import CELLS
    assert refresh.CELLS is CELLS
