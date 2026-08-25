"""
The derive, review, repair loop at the command line.

Covers the walk a person actually takes: derive candidates, decide them, seal the
file, repair with it. And the refusals, since the value of the gate is what it
turns away rather than what it lets through.

Exit codes under test
---------------------
    derive   0 candidates written, 3 nothing cleared the floors
    review   0 sealed, 2 quit or finished with entries undecided
    repair   0 repaired, 4 the gate refused before any engine ran

Exit 4 covers the whole pre-flight refusal class. The specific cause is the error
code in the message (E-UNSEALED, E-PENDING, E-SEAL, E-DRIFT, E-FRAGMENT,
E-BOUNDARY, E-EMPTY), which is what these tests assert on.
"""
import json
import os

import pytest

import kgrepair
from kgrepair.cli import (EXIT_GATE_REFUSED, EXIT_NO_CANDIDATES, EXIT_OK,
                          EXIT_REVIEW_PENDING, EXIT_USAGE, main)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GEO = os.path.join(ROOT, "fixtures", "real", "real_wikidata_geography_1000.nt")
TAXA = os.path.join(ROOT, "fixtures", "real", "real_wikidata_taxa_1000.nt")


def _derive(out, extra=()):
    return main(["derive", "--in", GEO, "--out", out, "--domain", "geography",
                 "--kg", "wikidata", "--min-support", "8", "--min-conf", "0.95",
                 *extra])


def _decide(path, accept=2):
    """Accept the first `accept` entries in review order, reject the rest, seal."""
    cf = kgrepair.read_candidate_file(path)
    keep = set(cf.review["review_order"][:accept])
    for c in list(cf.candidates):
        kgrepair.set_status(cf, c.cid, "accepted" if c.cid in keep else "rejected")
    kgrepair.seal_candidates(cf, "reviewer-1", sealed_at="2026-01-01T00:00:00Z")
    kgrepair.write_canonical(cf, path)
    return cf


# ---------- derive ----------------------------------------------------------

def test_derive_writes_a_file_of_pending_candidates(tmp_path, capsys):
    out = str(tmp_path / "c.json")
    assert _derive(out) == EXIT_OK
    cf = kgrepair.read_candidate_file(out)
    assert cf.candidates
    assert all(c.status == "pending" for c in cf.candidates)
    assert not cf.sealed
    assert "pending" in capsys.readouterr().out


def test_derive_says_the_file_cannot_repair_anything_yet(tmp_path, capsys):
    """The output has to make the airlock obvious, not leave a user assuming a
    derived file is ready to use."""
    _derive(str(tmp_path / "c.json"))
    out = capsys.readouterr().out
    assert "cannot repair anything yet" in out.lower() or "nothing here can repair" in out.lower()
    assert "kgrepair review" in out


def test_derive_exits_3_when_nothing_clears_the_floors(tmp_path, capsys):
    out = str(tmp_path / "c.json")
    code = main(["derive", "--in", GEO, "--out", out, "--domain", "geography",
                 "--kg", "wikidata", "--min-support", "100000"])
    assert code == EXIT_NO_CANDIDATES
    assert not os.path.exists(out)
    assert "min-support" in capsys.readouterr().err


def test_derive_merges_and_keeps_decisions(tmp_path):
    out = str(tmp_path / "c.json")
    _derive(out)
    cf = kgrepair.read_candidate_file(out)
    first = cf.review["review_order"][0]
    kgrepair.set_status(cf, first, "accepted", note="checked")
    kgrepair.write_canonical(cf, out)

    assert _derive(out) == EXIT_OK                 # same run again, merged
    merged = kgrepair.read_candidate_file(out)
    assert merged.by_cid(first).status == "accepted"
    assert merged.by_cid(first).note == "checked"


def test_derive_does_not_re_propose_a_rejected_rule(tmp_path):
    out = str(tmp_path / "c.json")
    _derive(out)
    cf = kgrepair.read_candidate_file(out)
    rejected = cf.review["review_order"][0]
    kgrepair.set_status(cf, rejected, "rejected")
    kgrepair.write_canonical(cf, out)

    _derive(out)
    merged = kgrepair.read_candidate_file(out)
    assert merged.by_cid(rejected).status == "rejected"
    assert rejected in merged.refused


def test_two_derive_runs_write_byte_identical_files(tmp_path):
    a, b = str(tmp_path / "a.json"), str(tmp_path / "b.json")
    _derive(a)
    _derive(b)
    assert open(a, "rb").read() == open(b, "rb").read()


# ---------- review ----------------------------------------------------------

def _answers(*items):
    it = iter(items)

    def read_line(_prompt=""):
        try:
            return next(it)
        except StopIteration:
            raise EOFError
    return read_line


def test_review_seals_when_every_entry_is_decided(tmp_path, capsys):
    from kgrepair.cli import _cmd_review
    out = str(tmp_path / "c.json")
    _derive(out)
    n = len(kgrepair.read_candidate_file(out).candidates)

    args = type("A", (), {"path": out, "reviewer": "reviewer-1"})()
    assert _cmd_review(args, read_line=_answers(*(["a"] + ["r"] * (n - 1)))) == EXIT_OK

    cf = kgrepair.read_candidate_file(out)
    assert cf.sealed and cf.review["reviewer"] == "reviewer-1"
    assert len(cf.accepted()) == 1
    assert "Sealed by reviewer-1" in capsys.readouterr().out


def test_review_quitting_leaves_the_file_unsealed(tmp_path):
    from kgrepair.cli import _cmd_review
    out = str(tmp_path / "c.json")
    _derive(out)
    args = type("A", (), {"path": out, "reviewer": "reviewer-1"})()
    assert _cmd_review(args, read_line=_answers("a", "q")) == EXIT_REVIEW_PENDING
    cf = kgrepair.read_candidate_file(out)
    assert not cf.sealed
    assert cf.by_cid(cf.review["review_order"][0]).status == "accepted"   # kept


def test_review_refuses_to_seal_without_a_reviewer_name(tmp_path, capsys):
    from kgrepair.cli import _cmd_review
    out = str(tmp_path / "c.json")
    _derive(out)
    n = len(kgrepair.read_candidate_file(out).candidates)
    args = type("A", (), {"path": out, "reviewer": None})()
    code = _cmd_review(args, read_line=_answers(*(["r"] * n + ["   "])))
    assert code == EXIT_REVIEW_PENDING
    assert not kgrepair.read_candidate_file(out).sealed
    assert "reviewer name" in capsys.readouterr().err


def test_review_skipping_leaves_the_entry_pending(tmp_path):
    from kgrepair.cli import _cmd_review
    out = str(tmp_path / "c.json")
    _derive(out)
    n = len(kgrepair.read_candidate_file(out).candidates)
    args = type("A", (), {"path": out, "reviewer": "reviewer-1"})()
    assert _cmd_review(args, read_line=_answers(*(["s"] + ["r"] * (n - 1)))) \
        == EXIT_REVIEW_PENDING
    assert len(kgrepair.read_candidate_file(out).pending()) == 1


# ---------- repair through the gate -----------------------------------------

def test_the_whole_loop_derive_decide_seal_repair(tmp_path, capsys):
    """The walkthrough: derive, decide, seal, repair, and the three attestations
    that record who authorised the rules."""
    cpath, out = str(tmp_path / "c.json"), str(tmp_path / "r.nt")
    report = str(tmp_path / "rep.json")
    assert _derive(cpath) == EXIT_OK

    # unsealed: refused before any engine runs
    assert main(["repair", "--in", GEO, "--constraints", cpath, "--mode", "superset",
                 "--out", out, "--report", report]) == EXIT_GATE_REFUSED
    assert not os.path.exists(out)

    _decide(cpath, accept=2)
    assert main(["repair", "--in", GEO, "--constraints", cpath, "--mode", "superset",
                 "--out", out, "--report", report]) == EXIT_OK

    with open(report, encoding="utf-8") as fh:
        attest = json.load(fh)["result"]["attestations"]
    cf = kgrepair.read_candidate_file(cpath)
    assert attest["constraint_seal"] == cf.review["seal"]
    assert attest["reviewer"] == "reviewer-1"
    assert attest["constraint_source"]
    # the engine's own attestations are untouched by the review machinery
    assert attest["superset_only_added"] is True
    assert attest["data_values_unmodified"] is True


@pytest.mark.parametrize("mutate,code_marker", [
    ("unsealed", "E-UNSEALED"),
    ("pending", "E-PENDING"),
    ("tampered", "E-SEAL"),
    ("fragment", "E-FRAGMENT"),
    ("boundary", "E-BOUNDARY"),
    ("empty", "E-EMPTY"),
])
def test_every_refusal_exits_4_and_names_its_cause(tmp_path, capsys, mutate, code_marker):
    cpath, out = str(tmp_path / "c.json"), str(tmp_path / "r.nt")
    _derive(cpath)
    cf = _decide(cpath, accept=2)

    if mutate == "unsealed":
        cf.review["state"] = "open"
    elif mutate == "pending":
        cf.candidates[0].status = "pending"
    elif mutate == "tampered":
        cf.accepted()[0].antecedent = "< down(wdt:P17) >"
    elif mutate == "fragment":
        cf.accepted()[0].consequent = '! val("wd:Q515")'
        kgrepair.seal_candidates(cf, "reviewer-1", sealed_at="2026-01-01T00:00:00Z")
    elif mutate == "boundary":
        cf.accepted()[0].tier = "boundary"
        kgrepair.seal_candidates(cf, "reviewer-1", sealed_at="2026-01-01T00:00:00Z")
    elif mutate == "empty":
        for c in cf.candidates:
            c.status = "rejected"
        kgrepair.seal_candidates(cf, "reviewer-1", sealed_at="2026-01-01T00:00:00Z")
    kgrepair.write_canonical(cf, cpath)

    code = main(["repair", "--in", GEO, "--constraints", cpath, "--mode", "superset",
                 "--out", out, "--report", "/dev/null"])
    assert code == EXIT_GATE_REFUSED
    assert code_marker in capsys.readouterr().err
    assert not os.path.exists(out)


def test_a_sealed_file_against_the_wrong_graph_is_refused(tmp_path, capsys):
    cpath, out = str(tmp_path / "c.json"), str(tmp_path / "r.nt")
    _derive(cpath)
    _decide(cpath, accept=2)
    code = main(["repair", "--in", TAXA, "--constraints", cpath, "--mode", "superset",
                 "--out", out, "--report", "/dev/null"])
    assert code == EXIT_GATE_REFUSED
    assert "E-DRIFT" in capsys.readouterr().err
    assert not os.path.exists(out)


def test_drift_can_be_allowed_and_is_recorded(tmp_path):
    cpath, out = str(tmp_path / "c.json"), str(tmp_path / "r.nt")
    report = str(tmp_path / "rep.json")
    _derive(cpath)
    _decide(cpath, accept=2)
    assert main(["repair", "--in", TAXA, "--constraints", cpath, "--mode", "superset",
                 "--out", out, "--report", report, "--allow-graph-drift"]) == EXIT_OK
    with open(report, encoding="utf-8") as fh:
        assert json.load(fh)["result"]["attestations"]["allow_graph_drift"] is True


def test_check_refuses_a_candidate_file_and_says_where_to_take_it(tmp_path, capsys):
    cpath = str(tmp_path / "c.json")
    _derive(cpath)
    assert main(["check", "--in", GEO, "--constraints", cpath]) == EXIT_USAGE
    err = capsys.readouterr().err.lower()
    assert "candidate file" in err and "review" in err


def test_a_plain_constraint_file_still_works_unchanged(tmp_path):
    """The candidate route is additive: an ordinary constraint file is unaffected."""
    plain = str(tmp_path / "plain.json")
    kgrepair.save_constraint_file(kgrepair.constraints.get("geography", "wikidata"), plain)
    assert main(["repair", "--in", GEO, "--constraints", plain, "--mode", "superset",
                 "--out", str(tmp_path / "r.nt"),
                 "--report", str(tmp_path / "rep.json")]) == EXIT_OK
    with open(tmp_path / "rep.json", encoding="utf-8") as fh:
        attest = json.load(fh)["result"]["attestations"]
    assert "constraint_seal" not in attest         # no review, so nothing to attest
