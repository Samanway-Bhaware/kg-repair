"""
The viewer's two paths: repair with supplied constraints, or derive, review, repair.

Everything here is `app.logic`, which is where the decisions live. The Streamlit
modules are presentation and are covered by the AppTest suites; a flow that cannot
be tested from this module is a flow with logic in the wrong place.

The properties that matter to someone using the viewer on their own data:

  * a bad upload is refused with something they can act on, before they are asked
    to choose anything;
  * both paths reach a repair, and the derive path cannot reach one without a
    person deciding every entry;
  * what they download is what the command line would have written.
"""
from __future__ import annotations

import json
import os
import zipfile

import pytest

import app.logic as logic
import kgrepair
from kgrepair.cli import main as cli_main

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GEO = os.path.join(ROOT, "fixtures", "real", "real_wikidata_geography_1000.nt")
MUSEUM = os.path.join(ROOT, "examples", "museum.nt")
MUSEUM_CONSTRAINTS = os.path.join(ROOT, "examples", "museum.constraints.json")

TURTLE = """@prefix ex: <http://example.org/> .
ex:vase1 a ex:Vase .
"""


def _text(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _museum_session():
    graph = kgrepair.load_graph(MUSEUM)
    cs, described = logic.accept_uploaded_constraints(
        _text(MUSEUM_CONSTRAINTS), "museum.constraints.json", graph)
    session = logic.Session(graph=graph, constraints=cs, graph_name="museum.nt",
                            constraints_source="museum.constraints.json",
                            type_predicates=set(kgrepair.DEFAULT_TYPE_PREDICATES))
    return session, described["candidate_file"]


 
# T1: the input screen
 
def test_an_uploaded_graph_is_measured_and_hashed_before_anything_else():
    upload = logic.accept_uploaded_graph(_text(MUSEUM), "museum.nt")
    assert (upload.nodes, upload.edges) == (9, 8)
    assert upload.content_hash == kgrepair.graph_content_hash(upload.graph)
    assert upload.isolated_nodes == 0
    assert set(upload.to_dict()) == {"name", "nodes", "edges", "content_hash",
                                     "isolated_nodes"}


def test_a_turtle_file_uploaded_as_nt_is_refused_by_name():
    """The message has to name the format the user actually has. A parse error on
    the first prefix line tells them nothing."""
    with pytest.raises(logic.ViewerError) as exc:
        logic.accept_uploaded_graph(TURTLE, "graph.nt")
    assert "Turtle" in str(exc.value)
    assert "N-Triples only" in str(exc.value)


@pytest.mark.parametrize("text,expected", [
    ('<?xml version="1.0"?>\n<rdf:RDF/>\n', "RDF/XML"),
    ("@base <http://example.org/> .\n", "Turtle"),
    ('{"@context": {}}\n', "JSON-LD"),
])
def test_other_serialisations_are_named_too(text, expected):
    with pytest.raises(logic.ViewerError) as exc:
        logic.accept_uploaded_graph(text, "graph.nt")
    assert expected in str(exc.value)


def test_an_empty_upload_is_refused():
    with pytest.raises(logic.ViewerError, match="empty"):
        logic.accept_uploaded_graph("   \n", "graph.nt")


def test_a_malformed_triple_is_refused_with_the_parse_problem():
    with pytest.raises(logic.ViewerError) as exc:
        logic.accept_uploaded_graph("<ex:a> <ex:p> .\n", "graph.nt")
    assert "graph.nt" in str(exc.value) and "N-Triples" in str(exc.value)


def test_an_authored_candidate_file_loads_with_no_seal():
    graph = kgrepair.load_graph(MUSEUM)
    cs, described = logic.accept_uploaded_constraints(
        _text(MUSEUM_CONSTRAINTS), "museum.constraints.json", graph)
    assert len(cs) == 2
    assert described["kind"] == "candidate file"
    assert described["provenance"] == "authored"
    assert described["entries"] == 2


def test_a_derived_candidate_file_with_no_seal_is_refused_with_its_code():
    """The gate is not relaxed for the viewer. The refusal reaches the screen as a
    message carrying the stable code, not as a stack trace."""
    payload = json.loads(_text(MUSEUM_CONSTRAINTS))
    payload["provenance"] = "derived"
    with pytest.raises(logic.ViewerError) as exc:
        logic.accept_uploaded_constraints(json.dumps(payload), "c.json")
    assert "E-UNSEALED" in str(exc.value)


def test_a_candidate_file_outside_the_fragment_is_refused_naming_the_cid():
    payload = json.loads(_text(MUSEUM_CONSTRAINTS))
    payload["candidates"][0]["consequent"] = '! val("ex:Artwork")'
    cid = payload["candidates"][0]["cid"]
    with pytest.raises(logic.ViewerError) as exc:
        logic.accept_uploaded_constraints(json.dumps(payload), "c.json")
    assert "E-FRAGMENT" in str(exc.value) and cid in str(exc.value)


def test_a_boundary_tier_entry_is_refused_on_the_repair_path():
    payload = json.loads(_text(MUSEUM_CONSTRAINTS))
    payload["candidates"][0]["tier"] = "boundary"
    with pytest.raises(logic.ViewerError) as exc:
        logic.accept_uploaded_constraints(json.dumps(payload), "c.json")
    assert "E-BOUNDARY" in str(exc.value)


def test_a_constraint_file_that_is_not_json_is_refused():
    with pytest.raises(logic.ViewerError, match="not valid JSON"):
        logic.accept_uploaded_constraints("not json at all", "c.json")


def test_a_plain_constraint_file_still_loads():
    """The other shape, which the committed fixtures use and which
    `save_constraint_file` writes."""
    path = os.path.join(ROOT, "fixtures", "synthetic",
                        "synthetic_geoLike.constraints.json")
    cs, described = logic.accept_uploaded_constraints(_text(path), "synthetic.json")
    assert len(cs) > 0 and described["kind"] == "constraint file"


 
# T2: both paths
 
@pytest.mark.parametrize("mode", ["subset", "superset"])
def test_the_supplied_constraints_path_reaches_a_repair(mode):
    session, cf = _museum_session()
    run = logic.run_repair(session, mode, candidate_file=cf)
    assert not run.aborted
    assert run.exit_code in (0, 2)
    assert run.payload["mode"] == mode


def test_the_derive_path_needs_every_entry_decided_before_it_can_repair():
    """The airlock, from the viewer. A queue part way through review cannot produce
    a constraint set, and the message says how many are left."""
    graph = kgrepair.load_graph(GEO)
    queue = logic.start_review(graph, "geography", "wikidata")
    assert queue.pending(), "the fixture has to yield candidates for this to test"
    assert not queue.sealed

    with pytest.raises(logic.ViewerError) as exc:
        queue.seal("a reviewer")
    assert "still undecided" in str(exc.value)

    with pytest.raises(logic.ViewerError) as exc:
        queue.constraint_set()
    assert "E-UNSEALED" in str(exc.value)


def _accept_everything(queue, reviewer: str = "a reviewer"):
    for entry in queue.entries():
        queue.decide(entry.cid, "accepted")
    queue.seal(reviewer)
    return queue.constraint_set()


def _session_over(graph, cs):
    return logic.Session(graph=graph, constraints=cs, graph_name="geo.nt",
                         constraints_source="reviewed candidates",
                         type_predicates=set(kgrepair.DEFAULT_TYPE_PREDICATES))


def test_the_derive_path_runs_end_to_end_on_a_committed_slice():
    """Derive, decide every entry, seal, repair.

    Pinned to the shape-driven generator explicitly. Since P4d the default is the
    two-axis search, whose candidate volume on this slice puts an accept-everything
    repair over the cap; that is measured in its own test below rather than by
    loosening the cap here.
    """
    graph = kgrepair.load_graph(GEO)
    queue = logic.start_review(graph, "geography", "wikidata", generator="shapes")

    cs = _accept_everything(queue)
    assert queue.sealed
    assert len(cs) == len(queue.entries())
    run = logic.run_repair(_session_over(graph, cs), "superset", cap=1.0)
    assert not run.aborted


def test_accepting_every_search_candidate_on_the_real_slice_hits_the_cap():
    """The P4d volume finding, as a test rather than a paragraph.

    The search proposes several times as many rules on this slice as the shape
    sweep, and a reviewer who waved all of them through would ask the superset
    engine to add more edges than the slice has nodes. The cap catches it before an
    engine runs, which is what the report-first cap is for.

    This is not an argument that the candidates are wrong. It is what an
    accept-everything review costs, and it is why the switch is recorded with a
    volume comparison.
    """
    graph = kgrepair.load_graph(GEO)
    queue = logic.start_review(graph, "geography", "wikidata")
    assert queue.candidate_file.parameters["generator"] == "search"

    cs = _accept_everything(queue)
    run = logic.run_repair(_session_over(graph, cs), "superset", cap=1.0)
    assert run.aborted and run.result is None
    assert run.decision.fraction > 1.0


def test_the_derive_path_runs_on_an_uploaded_graph():
    upload = logic.accept_uploaded_graph(_text(MUSEUM), "museum.nt")
    queue = logic.start_review(upload.graph, "museum", "example",
                               config=_low_floor_config())
    assert queue.pending()
    for entry in queue.entries():
        queue.decide(entry.cid, "accepted")
    queue.seal("a curator")
    assert len(queue.constraint_set()) >= 1


def _low_floor_config():
    from kgrepair.derive import DeriveConfig
    return DeriveConfig(min_support=2, min_pca_confidence=0.5)


def test_a_rejection_is_recorded_and_keeps_the_rule_out():
    graph = kgrepair.load_graph(GEO)
    queue = logic.start_review(graph, "geography", "wikidata")
    entries = queue.entries()
    queue.decide(entries[0].cid, "rejected")
    for entry in entries[1:]:
        queue.decide(entry.cid, "accepted")
    queue.seal("a reviewer")

    loaded = {c.cid for c in queue.constraint_set()}
    assert entries[0].cid not in loaded
    assert entries[0].cid in queue.candidate_file.refused


def test_an_unknown_decision_is_refused():
    graph = kgrepair.load_graph(GEO)
    queue = logic.start_review(graph, "geography", "wikidata")
    with pytest.raises(logic.ViewerError, match="accept, reject or weaken"):
        queue.decide(queue.entries()[0].cid, "maybe")


def test_impact_is_computed_per_entry_at_review_time_not_up_front():
    """The measured reason: impact is 96 to 99 percent of a derivation's cost, so a
    reviewer pays for the entries they open and no others."""
    graph = kgrepair.load_graph(GEO)
    queue = logic.start_review(graph, "geography", "wikidata")
    entries = queue.entries()

    assert all(e.impact.get("measured") is False for e in entries)

    shown = queue.show(entries[0].cid)
    assert shown["impact"]["measured"] is True
    assert shown["cid"] == entries[0].cid
    assert all(e.impact.get("measured") is False for e in entries[1:]), \
        "opening one entry measured the others too"


def test_a_witness_view_is_offered_for_an_entry_that_has_one():
    graph = kgrepair.load_graph(GEO)
    queue = logic.start_review(graph, "geography", "wikidata")
    with_witness = next((e for e in queue.entries() if e.witness_sample), None)
    if with_witness is None:
        pytest.skip("no candidate on this fixture carries a witness sample")
    view = queue.witness_view(with_witness.cid)
    assert view is not None and view.nodes


def test_an_unknown_cid_is_refused_rather_than_raising_a_key_error():
    graph = kgrepair.load_graph(GEO)
    queue = logic.start_review(graph, "geography", "wikidata")
    for call in (lambda: queue.show("nope"), lambda: queue.decide("nope", "accepted"),
                 lambda: queue.witness_view("nope")):
        with pytest.raises(logic.ViewerError, match="no candidate"):
            call()


 
# T3: the download
 
def test_the_bundle_offered_matches_the_one_the_cli_writes(tmp_path):
    """The parity that matters for a downloadable artifact: the same inputs give
    the same files with the same bytes, whichever skin produced them."""
    session, cf = _museum_session()
    run = logic.run_repair(session, "superset", candidate_file=cf)
    offered = logic.bundle_payloads(session, run,
                                    constraints_json=_text(MUSEUM_CONSTRAINTS))

    cli_dir = str(tmp_path / "cli")
    assert cli_main(["repair", "--in", MUSEUM, "--constraints", MUSEUM_CONSTRAINTS,
                     "--mode", "superset", "--bundle", cli_dir,
                     "--report", str(tmp_path / "r.json")]) == 0

    assert sorted(offered) == sorted(os.listdir(cli_dir))
    for name in ("repaired.nt", "changes.nt.diff", "constraints.used.json"):
        with open(os.path.join(cli_dir, name), encoding="utf-8") as fh:
            assert offered[name] == fh.read(), name

    # The report differs in one field only: the command line names the file it
    # wrote, and the viewer offers a download and has no path to name.
    with open(os.path.join(cli_dir, "report.json"), encoding="utf-8") as fh:
        cli_report = json.load(fh)
    viewer_report = json.loads(offered["report.json"])
    cli_report.pop("bundle", None)
    assert cli_report.pop("output_basename", None) is None
    assert viewer_report["result"] == cli_report["result"]
    assert viewer_report["summary"]["engine"] == "superset"
    assert viewer_report["summary"]["consistent_after"] is True


def test_the_repaired_graph_and_the_diff_are_offered_separately():
    session, cf = _museum_session()
    run = logic.run_repair(session, "superset", candidate_file=cf)
    offered = logic.bundle_payloads(session, run)
    assert offered["repaired.nt"].strip()
    assert offered["changes.nt.diff"].strip()
    assert kgrepair.reconstruct_input(offered["repaired.nt"],
                                      offered["changes.nt.diff"]) == _text(MUSEUM)


def test_the_archive_holds_every_offered_file(tmp_path):
    session, cf = _museum_session()
    run = logic.run_repair(session, "superset", candidate_file=cf)
    offered = logic.bundle_payloads(session, run,
                                    constraints_json=_text(MUSEUM_CONSTRAINTS))
    archive = logic.bundle_archive(offered, str(tmp_path / "session"))
    with zipfile.ZipFile(archive) as zf:
        assert sorted(zf.namelist()) == sorted(offered)


def test_a_capped_run_still_offers_a_bundle_saying_why():
    session, cf = _museum_session()
    run = logic.run_repair(session, "superset", cap=0.01, candidate_file=cf)
    assert run.aborted and run.exit_code == 3

    offered = logic.bundle_payloads(session, run)
    assert "repaired.nt" not in offered and "changes.nt.diff" not in offered
    report = json.loads(offered["report.json"])
    assert report["summary"]["engine_ran"] is False
    assert "ABORTED-BY-CAP" in report["summary"]["reason"]


def test_the_change_list_shows_plain_names_where_the_graph_has_them():
    graph = kgrepair.load_graph_string(
        '<ex:vase2> <ex:displayedIn> <ex:galleryB> .\n'
        '<ex:vase2> <rdfs:label> "the blue vase" .\n')
    cs, described = logic.accept_uploaded_constraints(
        _text(MUSEUM_CONSTRAINTS), "museum.constraints.json", graph)
    session = logic.Session(graph=graph, constraints=cs, graph_name="g.nt",
                            constraints_source="museum.constraints.json",
                            type_predicates=set(kgrepair.DEFAULT_TYPE_PREDICATES))
    run = logic.run_repair(session, "superset", cap=1.0,
                           candidate_file=described["candidate_file"])

    rows = logic.change_rows(session, run)
    assert rows
    assert any(row["subject"] == "the blue vase" for row in rows), \
        "a labelled node has to be shown by its label"
    counts = logic.change_counts(run)
    assert counts["add_edge"] == len(run.result.added_edges)


def test_the_change_counts_are_reported_even_when_the_list_is_not():
    session, cf = _museum_session()
    run = logic.run_repair(session, "superset", candidate_file=cf)
    assert sum(logic.change_counts(run).values()) == len(run.result.changelog)
    assert logic.change_rows(session, run, limit=1) == \
        logic.change_rows(session, run)[:1]


def test_a_capped_run_has_no_change_rows_and_zero_counts():
    session, cf = _museum_session()
    run = logic.run_repair(session, "superset", cap=0.01, candidate_file=cf)
    assert logic.change_rows(session, run) == []
    assert set(logic.change_counts(run).values()) == {0}
