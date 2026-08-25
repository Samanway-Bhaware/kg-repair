"""Guards for the constraint-derivation evaluation harness (scripts/eval_derivation.py):
determinism, byte-reproducibility of the committed table, and a substantive sanity
check that the scoring distinguishes v1 from v2."""
from __future__ import annotations

import json
import os

import eval_derivation as ed  # noqa: E402

ROOT = os.path.join(os.path.dirname(__file__), "..")
MD = os.path.join(ROOT, "eval", "constraint_derivation.md")
JSON = os.path.join(ROOT, "eval", "constraint_derivation.json")

def test_outputs_exist_and_are_committed():
    assert os.path.exists(MD), "run `python scripts/eval_derivation.py` and commit its output"
    assert os.path.exists(JSON)

def test_evaluation_is_deterministic():
    a = ed.evaluate()
    b = ed.evaluate()
    assert a == b
    assert ed.build(a) == ed.build(b)

def test_committed_markdown_is_byte_identical_on_regeneration():
    with open(MD, encoding="utf-8") as fh:
        committed = fh.read()
    assert ed.build(ed.evaluate()) == committed, (
        "eval/constraint_derivation.md drifted; re-run scripts/eval_derivation.py and commit")

def test_committed_json_is_identical_on_regeneration():
    with open(JSON, encoding="utf-8") as fh:
        committed = json.load(fh)
    assert ed.evaluate() == committed

def test_scoring_separates_v1_from_v2_on_a_biomedical_domain():
    """The harness must actually distinguish the two authored versions. Disease v2 widens
    the disease class test, so at least one biomedical domain must show a v2 relaxed
    recall strictly above its v1 relaxed recall."""
    data = ed.evaluate()
    improved = False
    for domain in ("disease", "medication", "anatomy"):
        cell = data["cells"].get(domain, {})
        if cell.get("status") != "ok":
            continue
        r1 = cell["versions"]["v1"]["overall"]["relaxed"]["recall"]
        r2 = cell["versions"]["v2"]["overall"]["relaxed"]["recall"]
        if r2 > r1:
            improved = True
    assert improved, "expected at least one biomedical domain with v2 relaxed recall > v1"

def test_every_cell_reports_a_fixture_and_vocab():
    data = ed.evaluate()
    for domain, _kg, _fx in ed.CELLS:
        cell = data["cells"][domain]
        assert cell["status"] == "ok", f"{domain} fixture missing"
        assert cell["vocab"]["type_predicate"] and cell["vocab"]["subclass_predicate"]
