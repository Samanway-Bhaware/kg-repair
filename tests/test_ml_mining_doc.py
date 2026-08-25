"""
CM sprint / E5 -- byte-reproducibility gate for docs/ml_mining.md, mirroring
tests/test_evaluation_reproducible.py's pattern for docs/evaluation.md.
"""
import os

import build_ml_mining_doc as bmd  # noqa: E402


ROOT = os.path.join(os.path.dirname(__file__), "..")
DOC_PATH = os.path.join(ROOT, "docs", "ml_mining.md")

def test_ml_mining_md_exists_and_is_committed():
    assert os.path.exists(DOC_PATH), (
        "docs/ml_mining.md is missing -- run `python scripts/build_ml_mining_doc.py` "
        "and commit the result before this test can guard it")


def test_regenerating_ml_mining_md_is_byte_identical():
    with open(DOC_PATH, "r", encoding="utf-8") as fh:
        committed = fh.read()
    preserved = bmd._extract_prose(committed)
    regenerated = bmd.build(preserved)
    assert regenerated == committed, (
        "docs/ml_mining.md drifted from what scripts/build_ml_mining_doc.py produces "
        "from the current experimental/mining/results/ artifacts. If the artifacts "
        "genuinely changed, re-run the script and commit the new file; if not, this "
        "is a real regression.")


def test_no_prose_markers_are_missing():
    with open(DOC_PATH, "r", encoding="utf-8") as fh:
        text = fh.read()
    for key in bmd.PROSE_KEYS:
        assert text.count(f"<!-- PROSE:{key}:start -->") == 1, f"missing/duplicate prose block: {key}"
        assert text.count(f"<!-- PROSE:{key}:end -->") == 1, f"missing/duplicate prose block: {key}"
