"""
D7/C2 -- byte-reproducibility gate for docs/evaluation.md.

`scripts/build_evaluation.py` computes every table from `results/runs.jsonl` and the
committed result/fixture artifacts; nothing in the doc's TEXT is hand-typed. This test
regenerates the file (preserving any guarded prose blocks already present, exactly as
`main()` does) and asserts the result is byte-identical to the committed copy -- i.e.
regenerating from the same underlying artifacts must not silently drift the doc.

Scope note: this test covers evaluation.md's TEXT only, not the 4 PNG figures.
matplotlib does not guarantee bit-identical PNG output across runs/environments even
with fixed data and suppressed metadata (font hinting, zlib compression internals,
etc. can vary) -- only the *data* each figure is built from is guaranteed deterministic
(it comes from the same table-building functions the text uses). Byte-testing the
figures would therefore be flaky by construction, so it is deliberately not attempted;
figures are covered by `test_figures_are_regenerated` below, which checks presence and
validity (a real PNG, non-trivial size), not byte content.
"""
import os

import pytest

import build_evaluation as be  # noqa: E402


ROOT = os.path.join(os.path.dirname(__file__), "..")
EVAL_MD = os.path.join(ROOT, "docs", "evaluation.md")
FIGURES = os.path.join(ROOT, "docs", "figures")

#: Table 7's only input is a cache of live-Wikidata ASK verdicts, one per added
#: (entity, class) pair. It is a fetched third-party artifact, not a computed one:
#: nothing in the repo can re-derive it offline, and re-fetching it would answer from
#: TODAY's Wikidata rather than from the capture the committed numbers and the
#: write-up were written against. It is not redistributed with this repository and
#: is not recoverable -- see DATA.md, "What is not included, and why".
#:
#: When it is absent, `build_evaluation.build()` still succeeds but emits Table 7 as
#: zeros, so a byte-comparison against the committed doc would report a missing INPUT
#: as though it were drift -- which is not what this gate is for. Skip in that case,
#: and say so in the run output rather than quietly passing.
#:
#: This is a conditional skip, not a retired test: drop the file back at this path and
#: the gate runs again unchanged. Tables 1-6 and 8 are still covered whenever it does,
#: and the other three tests in this file run unconditionally either way.
ASK_CACHE = os.path.join(ROOT, "data", "raw", "plausibility", "wikidata", "ask_cache.json")

def test_evaluation_md_exists_and_is_committed():
    assert os.path.exists(EVAL_MD), (
        "docs/evaluation.md is missing -- run `python scripts/build_evaluation.py` "
        "and commit the result before this test can guard it")


@pytest.mark.skipif(
    not os.path.exists(ASK_CACHE),
    reason="data/raw/plausibility/wikidata/ask_cache.json is absent, so Table 7 "
           "regenerates as zeros and byte-identity would fail for a missing input "
           "rather than for drift. The committed docs/evaluation.md remains the "
           "artifact of record. Restore the cache to re-arm this gate.")
def test_regenerating_evaluation_md_is_byte_identical():
    with open(EVAL_MD, "r", encoding="utf-8") as fh:
        committed = fh.read()
    preserved = be._extract_prose(committed)
    regenerated = be.build(preserved)
    assert regenerated == committed, (
        "docs/evaluation.md drifted from what scripts/build_evaluation.py produces "
        "from the current results/ and fixtures/real/ artifacts. If the artifacts "
        "genuinely changed, re-run `python scripts/build_evaluation.py` and commit "
        "the new file; if not, this is a real regression.")


def test_no_hand_typed_prose_markers_are_missing():
    """Every PROSE_KEYS section must appear exactly once, well-formed."""
    with open(EVAL_MD, "r", encoding="utf-8") as fh:
        text = fh.read()
    for key in be.PROSE_KEYS:
        assert text.count(f"<!-- PROSE:{key}:start -->") == 1, f"missing/duplicate prose block: {key}"
        assert text.count(f"<!-- PROSE:{key}:end -->") == 1, f"missing/duplicate prose block: {key}"


def test_figures_are_regenerated_as_valid_pngs():
    for name in ("fig1_loglog_scaling.png", "fig2_prevalence_bar.png",
                "fig3_subset_vs_superset.png", "fig4_precision_breakdown.png"):
        path = os.path.join(FIGURES, name)
        assert os.path.exists(path), f"missing figure: {name}"
        with open(path, "rb") as fh:
            header = fh.read(8)
        assert header == b"\x89PNG\r\n\x1a\n", f"{name} is not a valid PNG"
        assert os.path.getsize(path) > 1000, f"{name} looks empty/truncated"
