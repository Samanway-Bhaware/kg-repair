"""
P8a/F6: the dataset refetch report regenerates byte for byte.

`scripts/build_dataset_refetch.py` renders `eval/dataset_refetch.md` from the three
measurement artifacts the phase produced. It has to be a pure function of those
files: a document that quietly changes between runs cannot be cited from the
corpus section of the write-up.

Also holds the wording gate for this document: the project's wording rules apply to
it like any other prose.
"""
from __future__ import annotations

import json
import os

import build_dataset_refetch as bdr

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
MD = os.path.join(ROOT, "eval", "dataset_refetch.md")
JSON_PATH = os.path.join(ROOT, "eval", "dataset_refetch.json")

#: Words the project does not allow as a claim about its own output.
BANNED = ("maximal", "minimal", "unique")


def test_the_artifacts_are_committed():
    assert os.path.exists(MD), "run `python scripts/build_dataset_refetch.py`"
    assert os.path.exists(JSON_PATH)


def test_regenerating_is_byte_identical():
    with open(MD, encoding="utf-8") as fh:
        committed = fh.read()
    assert bdr.build(bdr.collect()) == committed, (
        "eval/dataset_refetch.md drifted; re-run scripts/build_dataset_refetch.py")


def test_two_collections_agree():
    """The collection step reads files and does no wall-clock or network work, so two
    calls in one process have to return the same thing."""
    assert bdr.collect() == bdr.collect()


def test_the_json_matches_what_the_markdown_was_built_from():
    with open(JSON_PATH, encoding="utf-8") as fh:
        committed = json.load(fh)
    assert bdr.collect() == committed


def test_the_document_passes_the_wording_gate():
    with open(MD, encoding="utf-8") as fh:
        text = fh.read()
    assert "—" not in text, "em dash in the report"
    assert "–" not in text, "en dash in the report"
    lowered = text.lower()
    for word in BANNED:
        assert word not in lowered, f"banned word {word!r} in the report"


def test_the_document_makes_no_claim_about_repair():
    """This phase ran no engine, so the report must not describe repair behaviour."""
    with open(MD, encoding="utf-8") as fh:
        lowered = fh.read().lower()
    for phrase in ("subset repair", "superset repair", "repaired graph",
                   "aborted-by-cap"):
        assert phrase not in lowered, f"{phrase!r} appears in a fetch-only report"
