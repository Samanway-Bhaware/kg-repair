"""
Authored constraint files, the untouched input, and the output bundle.

Three properties, and a user of this toolkit depends on all three:

  * a person can write constraints down and repair with them, without going
    through a review loop that exists for somebody else's proposals, and without
    any of the other gates being relaxed;
  * their input file and their in-memory graph come back exactly as they went in;
  * what they get back is enough to check the work: the repaired graph, a
    reversible record of what changed, the rules that drove it, and a report.
"""
from __future__ import annotations

import hashlib
import json
import os

import pytest

import kgrepair
from kgrepair.bundle import (CONSTRAINTS, DIFF, REPAIRED, REPORT, diff_lines,
                             reconstruct_input, zip_bundle)
from kgrepair.candidates import AUTHORED, DERIVED, Candidate, CandidateFile
from kgrepair.cli import main
from kgrepair.review import (BoundaryNotRepairable, NotSealed, OutOfFragment,
                             ReviewIncomplete, SchemaRejected)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GEO = os.path.join(ROOT, "fixtures", "real", "real_wikidata_geography_1000.nt")
MUSEUM = os.path.join(ROOT, "examples", "museum.nt")
MUSEUM_CONSTRAINTS = os.path.join(ROOT, "examples", "museum.constraints.json")

TAU_ARTWORK = '< down(rdf:type) . down(rdfs:subClassOf)* . [val("ex:Artwork")] >'


def _authored(candidates=None, **kw) -> CandidateFile:
    cf = CandidateFile(
        provenance=AUTHORED,
        source={"dataset": "hand written", "domain": "museum", "kg": "example"},
        candidates=list(candidates or [
            Candidate(cid="museum.rule.1", kind="existential_domain",
                      tier="ptime_core", direction="superset",
                      antecedent="< down(ex:displayedIn) >", consequent=TAU_ARTWORK,
                      gloss="anything displayed in a gallery is an artwork",
                      status="accepted")]))
    for key, value in kw.items():
        setattr(cf, key, value)
    return cf


 
# T1: the provenance field and what it waives
 
def test_an_authored_file_loads_with_no_seal_and_no_source_hash():
    """The whole point. A person wrote the rules down, which is the assertion the
    seal exists to record, so there is nothing left to seal."""
    cf = _authored()
    assert cf.authored and not cf.sealed
    assert not (cf.source or {}).get("content_hash")

    cs = kgrepair.reviewed_constraint_set(cf, kgrepair.load_graph(MUSEUM))
    assert len(cs) == 1
    assert list(cs)[0].provenance == AUTHORED


def test_a_derived_file_with_no_seal_is_still_refused():
    """The waiver is scoped to authored files and nothing else changed for derived
    ones. A file with no provenance field is derived, which is what keeps every
    file written before the field existed behaving as it did."""
    cf = _authored()
    cf.provenance = DERIVED
    with pytest.raises(NotSealed) as exc:
        kgrepair.reviewed_constraint_set(cf)
    assert "E-UNSEALED" in str(exc.value)

    payload = cf.to_dict()
    del payload["provenance"]
    assert CandidateFile.from_dict(payload).provenance == DERIVED


def test_an_authored_file_carrying_a_seal_is_rejected_as_malformed():
    """Two different claims about who vouched for what. A file making both hides
    which one was actually made, so it is refused rather than accepted."""
    cf = _authored()
    cf.review["seal"] = "0" * 64
    cf.review["state"] = "sealed"
    with pytest.raises(SchemaRejected) as exc:
        kgrepair.reviewed_constraint_set(cf)
    assert "E-SCHEMA" in str(exc.value)
    assert "authored" in str(exc.value)


def test_an_authored_constraint_containing_negation_is_refused_naming_the_cid():
    """The fragment guard is not relaxed for authored files. Writing a rule down
    does not make negation tractable."""
    cf = _authored(candidates=[
        Candidate(cid="museum.rule.bad", kind="existential_domain",
                  tier="ptime_core", direction="superset",
                  antecedent="< down(ex:displayedIn) >",
                  consequent='! val("ex:Artwork")', status="accepted")])
    with pytest.raises(OutOfFragment) as exc:
        kgrepair.reviewed_constraint_set(cf)
    assert "museum.rule.bad" in str(exc.value)
    assert exc.value.cid == "museum.rule.bad"


def test_an_authored_boundary_constraint_is_refused_on_the_repair_path():
    cf = _authored(candidates=[
        Candidate(cid="museum.rule.symmetric", kind="symmetric", tier="boundary",
                  direction="superset", antecedent="< down(ex:nextTo) >",
                  consequent="< up(ex:nextTo) >", status="accepted")])
    with pytest.raises(BoundaryNotRepairable) as exc:
        kgrepair.reviewed_constraint_set(cf, for_repair=True)
    assert "museum.rule.symmetric" in str(exc.value)
    # boundary tier still loads for checking, which is what it is for
    assert len(kgrepair.reviewed_constraint_set(cf, for_repair=False)) == 1


def test_an_authored_entry_left_pending_is_refused():
    """`accepted` is where an authored file states its assertion, so an entry
    nobody marked is an entry nobody asserted."""
    cf = _authored(candidates=[
        Candidate(cid="museum.rule.undecided", kind="existential_domain",
                  tier="ptime_core", direction="superset",
                  antecedent="< down(ex:displayedIn) >", consequent=TAU_ARTWORK)])
    with pytest.raises(ReviewIncomplete) as exc:
        kgrepair.reviewed_constraint_set(cf)
    assert "museum.rule.undecided" in str(exc.value)
    assert "authored file states its assertions" in str(exc.value)


def test_the_report_records_which_provenance_authorised_the_rules():
    cf = _authored()
    attestations = kgrepair.attach_review_attestations({}, cf)["attestations"]
    assert attestations["constraint_provenance"] == AUTHORED
    assert attestations["constraint_seal"] is None
    assert attestations["reviewer"] is None
    assert "no review seal applies" in attestations["authorship"]


 
# T2: the committed worked example
 
def test_the_committed_example_repairs_its_graph_end_to_end(tmp_path):
    """The example in `docs/authoring_constraints.md`, run as documented. Two rules
    over eight statements, two things missing a type, two statements added."""
    graph = kgrepair.load_graph(MUSEUM)
    cf = kgrepair.read_candidate_file(MUSEUM_CONSTRAINTS)
    assert cf.provenance == AUTHORED

    cs = kgrepair.reviewed_constraint_set(cf, graph)
    assert len(cs) == 2

    before = kgrepair.validate(graph, cs)
    assert before.by_tier()["ptime_core"] == 2

    result = kgrepair.superset_repair(graph, cs)
    assert set(result.added_edges) == {
        ("ex:vase2", "rdf:type", "ex:Artwork"),
        ("ex:galleryB", "rdf:type", "ex:Gallery"),
    }
    assert result.attestations["consistent_after"] is True


def test_the_committed_example_is_canonical_so_its_diff_reverses_to_the_file():
    """The example graph is stored in the form the toolkit writes, so the bundle's
    reversibility can be checked against the file itself rather than against a
    re-serialisation of it."""
    graph = kgrepair.load_graph(MUSEUM)
    with open(MUSEUM, encoding="utf-8") as fh:
        assert kgrepair.to_ntriples(graph) == fh.read()


def test_the_authoring_guide_documents_every_top_level_field():
    with open(os.path.join(ROOT, "docs", "authoring_constraints.md"),
              encoding="utf-8") as fh:
        guide = fh.read()
    for field in ("schema", "provenance", "toolkit_version", "source", "parameters",
                  "review", "candidates", "refused"):
        assert f"`{field}`" in guide, field
    for ignored in ("Ignored for authored files", "waived"):
        assert ignored in guide


 
# T3: the input is never touched
 
@pytest.mark.parametrize("engine", ["subset", "superset"])
def test_the_engine_leaves_the_input_file_and_the_callers_graph_alone(engine):
    """Asserted rather than assumed, for each engine separately: the file's bytes
    and the caller's graph, compared structurally after the run."""
    with open(GEO, "rb") as fh:
        digest_before = hashlib.sha256(fh.read()).hexdigest()

    graph = kgrepair.load_graph(GEO)
    cs = kgrepair.constraints.get("geography", "wikidata")
    snapshot = (sorted(graph.edges()), sorted(graph.nodes),
                {v: graph.value(v) for v in sorted(graph.nodes)})

    run = kgrepair.subset_repair if engine == "subset" else kgrepair.superset_repair
    result = run(graph, cs)

    assert result.graph is not graph, "the engine handed back the caller's own graph"
    assert (sorted(graph.edges()), sorted(graph.nodes),
            {v: graph.value(v) for v in sorted(graph.nodes)}) == snapshot

    with open(GEO, "rb") as fh:
        assert hashlib.sha256(fh.read()).hexdigest() == digest_before


 
# T4: the bundle
 
def _run_bundle(tmp_path, *extra, expect=0):
    out_dir = str(tmp_path / "bundle")
    argv = ["repair", "--in", MUSEUM, "--constraints", MUSEUM_CONSTRAINTS,
            "--mode", "superset", "--bundle", out_dir,
            "--report", str(tmp_path / "report.json")] + list(extra)
    assert main(argv) == expect
    return out_dir


def test_the_bundle_carries_all_four_files(tmp_path):
    out_dir = _run_bundle(tmp_path)
    assert sorted(os.listdir(out_dir)) == sorted([REPAIRED, DIFF, REPORT, CONSTRAINTS])


def test_the_repaired_graph_plus_the_reverse_of_the_diff_is_the_input(tmp_path):
    """What makes the diff an auditable record: it is complete, so it can be
    undone. Byte for byte against the input file, which the example is stored in
    canonical form to make possible."""
    out_dir = _run_bundle(tmp_path)
    with open(os.path.join(out_dir, REPAIRED), encoding="utf-8") as fh:
        repaired = fh.read()
    with open(os.path.join(out_dir, DIFF), encoding="utf-8") as fh:
        diff = fh.read()
    with open(MUSEUM, encoding="utf-8") as fh:
        original = fh.read()

    assert reconstruct_input(repaired, diff) == original
    assert repaired != original, "this run has to change something to mean anything"


def test_every_diff_line_carries_a_marker(tmp_path):
    out_dir = _run_bundle(tmp_path)
    with open(os.path.join(out_dir, DIFF), encoding="utf-8") as fh:
        lines = [line for line in fh.read().splitlines() if line.strip()]
    assert lines
    for line in lines:
        assert line[0] in "+-", line
        assert line[1] == " " and line.endswith(" .")


def test_the_report_states_the_engine_the_provenance_and_the_outcome(tmp_path):
    out_dir = _run_bundle(tmp_path)
    with open(os.path.join(out_dir, REPORT), encoding="utf-8") as fh:
        report = json.load(fh)
    summary = report["summary"]
    assert summary["engine"] == "superset"
    assert summary["constraint_provenance"] == AUTHORED
    assert summary["consistent_after"] is True
    assert summary["engine_ran"] is True
    assert report["result"]["attestations"]["constraint_provenance"] == AUTHORED


def test_the_bundle_copies_the_constraint_file_verbatim(tmp_path):
    out_dir = _run_bundle(tmp_path)
    with open(os.path.join(out_dir, CONSTRAINTS), encoding="utf-8") as fh:
        copied = fh.read()
    with open(MUSEUM_CONSTRAINTS, encoding="utf-8") as fh:
        assert copied == fh.read()


def test_the_zip_holds_the_same_four_files(tmp_path):
    import zipfile
    out_dir = _run_bundle(tmp_path, "--zip")
    with zipfile.ZipFile(out_dir + ".zip") as zf:
        assert sorted(zf.namelist()) == sorted([REPAIRED, DIFF, REPORT, CONSTRAINTS])


def test_two_zips_of_one_bundle_are_byte_identical(tmp_path):
    out_dir = _run_bundle(tmp_path)
    first = zip_bundle(out_dir, str(tmp_path / "a.zip"))
    second = zip_bundle(out_dir, str(tmp_path / "b.zip"))
    with open(first, "rb") as fa, open(second, "rb") as fb:
        assert fa.read() == fb.read()


def test_out_still_writes_a_single_file_and_the_exit_codes_are_unchanged(tmp_path):
    """The existing contract: `--out PATH` writes the repaired graph alone. The
    bundle is an addition, not a redefinition."""
    out = str(tmp_path / "repaired.nt")
    assert main(["repair", "--in", MUSEUM, "--constraints", MUSEUM_CONSTRAINTS,
                 "--mode", "superset", "--out", out,
                 "--report", str(tmp_path / "r.json")]) == 0
    assert os.path.exists(out)
    assert not os.path.exists(str(tmp_path / "bundle"))


def test_repair_with_neither_out_nor_bundle_is_a_usage_error(tmp_path, capsys):
    assert main(["repair", "--in", MUSEUM, "--constraints", MUSEUM_CONSTRAINTS,
                 "--mode", "superset"]) == 1
    assert "--out" in capsys.readouterr().err


def test_the_diff_is_empty_when_a_repair_changes_nothing():
    graph = kgrepair.load_graph(MUSEUM)
    assert diff_lines(graph, graph) == []


 
# T5: caps on arbitrary input
 
def test_a_cap_stops_the_run_and_still_hands_back_a_bundle(tmp_path, capsys):
    """ABORTED-BY-CAP on a user's own file, not just a committed slice: exit 3, no
    engine run, and a bundle carrying the report and the constraints rather than
    nothing at all."""
    out_dir = str(tmp_path / "capped")
    code = main(["repair", "--in", MUSEUM, "--constraints", MUSEUM_CONSTRAINTS,
                 "--mode", "superset", "--bundle", out_dir,
                 "--max-addition-fraction", "0.01",
                 "--report", str(tmp_path / "r.json")])
    assert code == 3

    assert sorted(os.listdir(out_dir)) == sorted([REPORT, CONSTRAINTS])
    with open(os.path.join(out_dir, REPORT), encoding="utf-8") as fh:
        report = json.load(fh)
    assert report["cap"]["status"] == "ABORTED-BY-CAP"
    assert report["cap"]["aborted"] is True
    assert report["result"] is None
    assert report["summary"]["engine_ran"] is False
    assert report["summary"]["consistent_after"] is None
    assert "ABORTED-BY-CAP" in report["summary"]["reason"]
    assert "cap of 0.010" in report["summary"]["reason"]


def test_the_cap_applies_to_a_user_file_the_same_way_as_to_a_committed_slice():
    """`check_cap` takes a graph and a constraint set and nothing else, so where
    the graph came from cannot change the verdict. Asserted on both."""
    museum = kgrepair.load_graph(MUSEUM)
    cs = kgrepair.reviewed_constraint_set(
        kgrepair.read_candidate_file(MUSEUM_CONSTRAINTS), museum)

    assert kgrepair.check_cap(museum, cs, "superset", cap=0.01).aborted
    assert not kgrepair.check_cap(museum, cs, "superset", cap=0.9).aborted

    slice_graph = kgrepair.load_graph(GEO)
    built_in = kgrepair.constraints.get("geography", "wikidata")
    assert kgrepair.check_cap(slice_graph, built_in, "subset", cap=0.001).aborted
