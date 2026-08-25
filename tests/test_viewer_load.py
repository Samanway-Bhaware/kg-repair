"""
V1 gate -- Load screen smoke tests via Streamlit's AppTest harness.

Drives every discoverable manifest (real/ and synthetic/) and every constraint
set the Load screen offers for it, asserting the screen renders with no
exception and no error box. This is the "every existing manifest loads with
stats matching its manifest file ... namespace badges correct" gate from the
viewer build prompt, run headless (no browser, no server socket).
"""
import os

from streamlit.testing.v1 import AppTest

import kgrepair

from app import manifests as mf


APP = os.path.join(os.path.dirname(__file__), "..", "app", "main.py")


def _fresh():
    at = AppTest.from_file(APP)
    at.run(timeout=30)
    assert not at.exception
    return at


def test_load_screen_default_render_has_no_exception():
    at = _fresh()
    assert not at.exception
    assert len(at.selectbox) >= 1


def test_manifest_picker_lists_both_namespaces():
    at = _fresh()
    labels = list(at.selectbox[0].options)
    assert any(l.startswith("[real] ") for l in labels)
    assert any(l.startswith("[synthetic] ") for l in labels)
    # exactly one option per manifest actually on disk
    assert len(labels) == len(mf.discover_manifests())


def test_every_manifest_and_constraint_set_renders_cleanly():
    at = _fresh()
    manifest_labels = list(at.selectbox[0].options)
    assert manifest_labels, "no manifests discovered"

    for i, mlabel in enumerate(manifest_labels):
        at_m = _fresh()
        at_m.selectbox[0].select_index(i).run(timeout=30)
        assert not at_m.exception, f"{mlabel}: {at_m.exception}"
        assert not at_m.error, f"{mlabel}: unexpected error box(es)"

        cs_labels = list(at_m.selectbox[1].options) if len(at_m.selectbox) > 1 else []
        assert cs_labels, f"{mlabel}: no constraint set offered"
        for j, clabel in enumerate(cs_labels):
            at_c = _fresh()
            at_c.selectbox[0].select_index(i).run(timeout=30)
            at_c.selectbox[1].select_index(j).run(timeout=30)
            assert not at_c.exception, f"{mlabel} / {clabel}: {at_c.exception}"
            assert not at_c.error, f"{mlabel} / {clabel}: unexpected error box(es)"


def test_stats_panel_matches_manifest_no_mismatch_warning():
    """Every committed fixture's .nt must reload to the exact stats its own
    manifest records -- a real regression, not just a UI nicety, since the
    manifests are supposed to be the graphs' own retraceability record."""
    at = _fresh()
    manifest_labels = list(at.selectbox[0].options)
    for i, mlabel in enumerate(manifest_labels):
        at_m = _fresh()
        at_m.selectbox[0].select_index(i).run(timeout=30)
        warning_texts = [w.value for w in at_m.warning]
        assert not any("do not match" in w for w in warning_texts), \
            f"{mlabel}: stats mismatch warning shown"


def test_boundary_constraints_never_labelled_repairable():
    """Cross-check the Load screen's constraint-list grouping against the
    ConstraintSet directly (not just eyeballing the UI)."""
    entries = mf.discover_manifests()
    wd_geo = next(e for e in entries if e.name == "real_wikidata_geography_1000")
    choices = mf.matching_constraint_sets(wd_geo)
    cs = next(iter(choices.values()))
    boundary = [c for c in cs if c.tier == "boundary"]
    core = [c for c in cs if c.tier == "ptime_core"]
    assert boundary and core
    assert {c.tier for c in boundary} == {"boundary"}


 
# the upload branch: bring your own graph and your own rules
 

def _upload_mode():
    at = _fresh()
    source = [r for r in at.radio if r.label == "Input source"][0]
    source.set_value("Upload your own").run(timeout=30)
    return at


def test_load_screen_offers_an_upload_source():
    at = _fresh()
    source = [r for r in at.radio if r.label == "Input source"][0]
    assert list(source.options) == ["Project fixture", "Upload your own"]
    assert source.value == "Project fixture"        # fixtures stay the default


def test_upload_branch_renders_its_controls():
    at = _upload_mode()
    assert not at.exception
    labels = [t.label for t in at.text_area]
    assert "Type predicates (one per line, or comma separated)" in labels
    assert any(r.label == "Constraints" for r in at.radio)
    assert any("Upload an N-Triples graph" in i.value for i in at.info)


def test_upload_branch_defaults_to_the_default_type_predicates():
    at = _upload_mode()
    captions = " ".join(c.value for c in at.caption)
    for label in kgrepair.DEFAULT_TYPE_PREDICATES:
        assert label in captions


def test_upload_branch_can_switch_to_a_builtin_constraint_set():
    at = _upload_mode()
    kind = [r for r in at.radio if r.label == "Constraints"][0]
    kind.set_value("Use a built-in set").run(timeout=30)
    assert not at.exception
    options = list(at.selectbox[0].options)
    assert "geography / wikidata (v1)" in options


def test_upload_branch_help_text_makes_no_ethics_claim():
    """Same discipline as the command line: the allow-list is an opt-in filter,
    and nothing in the viewer describes it as a guarantee."""
    src = open(os.path.join(os.path.dirname(__file__), "..", "app", "screens",
                            "load.py"), encoding="utf-8").read().lower()
    for word in ("ethic", "personal data", "gdpr", "guarantee"):
        assert word not in src
