"""
Viewer seam tests.

Streamlit widgets are awkward to drive headlessly, so the viewer's knowledge-graph
work lives in `app/logic.py`, a plain-Python module with no Streamlit import, and
that is what is tested here. The screens are presentation over exactly these
functions, the same discipline the command line follows.

The point of most of these tests is agreement: the viewer and the command line
must describe the same run identically, down to the bytes.
"""
import json
import os
import re

import pytest

import kgrepair
from app import logic
from kgrepair.cli import main as cli_main

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GEO_FIXTURE = os.path.join(ROOT, "fixtures", "synthetic_geography_wd.nt")

WIKIDATA_MARKERS = re.compile(r"\bP31\b|\bP279\b|\bwd:|\bwdt:|wikidata", re.IGNORECASE)

EX_SPINE = {"ex:isa", "ex:subclassOf"}
EX_GRAPH = """\
<ex:vase1> <ex:isa> <cat:Vase> .
<cat:Vase> <ex:subclassOf> <cat:Artefact> .
<ex:vase1> <ex:madeOf> <cat:marble> .
<ex:vase1> <ex:inGallery> <ex:gallery1> .
<cat:marble> <ex:isa> <cat:Material> .
<ex:sculpture1> <ex:madeOf> <cat:marble> .
<ex:vase2> <ex:isa> <cat:Vase> .
<ex:vase2> <ex:madeOf> <cat:marble> .
"""


def _ex_constraints():
    common = dict(domain="museum", kg="example", tier="ptime_core",
                  provenance="derived", version=1)

    def tau(c):
        return f'< down(ex:isa) . down(ex:subclassOf)* . [val("{c}")] >'

    return kgrepair.ConstraintSet("museum@example", [
        kgrepair.Constraint(cid="mus.dom.madeof", kind="existential_domain",
                            direction="subset", antecedent="< down(ex:madeOf) >",
                            consequent=tau("cat:Artefact"), **common),
        kgrepair.Constraint(cid="mus.req.gallery", kind="requires_statement",
                            direction="superset", antecedent=tau("cat:Artefact"),
                            consequent="< down(ex:inGallery) >", **common),
    ])


@pytest.fixture(name="geo_session")
def _geo_session():
    return logic.Session(
        graph=kgrepair.load_graph(GEO_FIXTURE),
        constraints=kgrepair.constraints.get("geography", "wikidata"),
        graph_name=os.path.basename(GEO_FIXTURE),
        constraints_source="geography/wikidata/v1",
        type_predicates=logic.effective_type_predicates(None))


@pytest.fixture(name="ex_session")
def _ex_session():
    return logic.Session(
        graph=logic.load_graph_from_text(EX_GRAPH, "museum.nt",
                                         type_predicates=EX_SPINE),
        constraints=_ex_constraints(),
        graph_name="museum.nt",
        constraints_source="museum.constraints.json",
        type_predicates=logic.effective_type_predicates(EX_SPINE))


# ---------- the viewer and the command line agree ---------------------------

def test_viewer_check_matches_the_cli_report(geo_session, tmp_path, capsys):
    """Same graph, same constraints, same report. Byte for byte."""
    viewer = logic.run_check(geo_session, witness_limit=10)

    assert cli_main(["check", "--in", GEO_FIXTURE, "--domain", "geography",
                     "--kg", "wikidata", "--report", str(tmp_path / "c.json")]) == 2
    with open(tmp_path / "c.json", encoding="utf-8") as fh:
        cli = json.load(fh)

    assert viewer == cli
    assert json.dumps(viewer, indent=2, sort_keys=True) + "\n" == \
        open(tmp_path / "c.json", encoding="utf-8").read()


def test_viewer_repair_matches_the_cli_report(geo_session, tmp_path):
    """Compared after a JSON round trip, since JSON has no tuples: the viewer holds
    live result objects, the command line has already serialised them."""
    run = logic.run_repair(geo_session, "superset")

    assert cli_main(["repair", "--in", GEO_FIXTURE, "--domain", "geography",
                     "--kg", "wikidata", "--mode", "superset",
                     "--out", str(tmp_path / "r.nt"),
                     "--report", str(tmp_path / "r.json")]) == 0
    with open(tmp_path / "r.json", encoding="utf-8") as fh:
        cli = json.load(fh)

    viewer = json.loads(json.dumps(run.payload))
    assert viewer["result"] == cli["result"]
    assert viewer["cap"] == cli["cap"]

    # The one field that legitimately differs: the command line wrote the repaired
    # graph to a path and records its basename, while the viewer offers it as a
    # download and has no output path to name. Everything else must match.
    assert cli.pop("output_basename") == "r.nt"
    assert viewer == cli


def test_viewer_exit_codes_match_the_cli(geo_session, tmp_path):
    """The viewer knows what the command line would have returned, so an outcome
    shown in the app and an outcome in a script cannot disagree."""
    assert logic.check_exit_code(logic.run_check(geo_session)) == \
        cli_main(["check", "--in", GEO_FIXTURE, "--domain", "geography",
                  "--kg", "wikidata", "--report", str(tmp_path / "c.json")])
    assert logic.run_repair(geo_session, "subset").exit_code == \
        cli_main(["repair", "--in", GEO_FIXTURE, "--domain", "geography",
                  "--kg", "wikidata", "--mode", "subset",
                  "--out", str(tmp_path / "s.nt"), "--report", str(tmp_path / "s.json")])


def test_viewer_cap_verdict_is_the_shared_one(geo_session):
    """The viewer does not measure anything itself; it asks caps.check_cap."""
    for mode in logic.MODES:
        run = logic.run_repair(geo_session, mode)
        assert run.decision == kgrepair.check_cap(geo_session.graph,
                                                  geo_session.constraints, mode)
        assert run.payload["cap"] == run.decision.to_dict()


def test_committed_synthetic_constraint_file_matches_the_generator():
    """The viewer reads the synthetic fixture's rules from an ordinary constraint
    file rather than importing the generator. This guards the two from drifting.

    Importing the internal generator is fine here: a test may look wherever it
    needs to. The point is that the viewer does not.
    """
    from app import manifests as mf
    from kgrepair.synthetic import synthetic_constraints

    committed = logic.load_constraints_from_path(mf.SYNTHETIC_CONSTRAINTS)
    assert committed.to_dict() == synthetic_constraints().to_dict()


def test_app_caps_shim_agrees_with_the_library():
    from app import caps as app_caps
    assert app_caps.SUBSET_CAP_DEFAULT is kgrepair.SUBSET_CAP_DEFAULT
    assert app_caps.subset_witness_fraction is kgrepair.subset_witness_fraction
    assert app_caps.superset_addition_fraction is kgrepair.superset_addition_fraction


# ---------- the agnostic viewer gate ----------------------------------------

def test_viewer_path_handles_a_non_wikidata_graph(ex_session, tmp_path):
    """Load, Check, Repair and Export over a graph with an ex:isa spine and
    hand-written constraints, with no Wikidata vocabulary anywhere."""
    checked = logic.run_check(ex_session)
    assert logic.check_exit_code(checked) == 2
    fired = {c["cid"]: c["witness_count"] for c in checked["result"]["constraints"]
             if c["witness_count"]}
    assert fired == {"mus.dom.madeof": 1, "mus.req.gallery": 1}
    assert checked["type_predicates"] == sorted(EX_SPINE)

    run = logic.run_repair(ex_session, "superset")
    assert run.exit_code == 0
    assert run.payload["result"]["attestations"]["consistent_after"] is True

    downloads = logic.export_payloads(ex_session, run.payload, run.result.graph)
    reloaded = kgrepair.load_graph_string(downloads["graph"], type_predicates=EX_SPINE)
    assert kgrepair.validate(reloaded, _ex_constraints()).by_tier()["ptime_core"] == 0

    for blob in (json.dumps(checked), downloads["graph"], downloads["report"]):
        hit = WIKIDATA_MARKERS.search(blob)
        assert hit is None, f"Wikidata vocabulary leaked: {hit.group(0)!r}"


def test_viewer_and_cli_agree_on_the_non_wikidata_graph(ex_session, tmp_path):
    """The same custom-vocabulary run through both skins produces one report."""
    graph_path = str(tmp_path / "museum.nt")
    with open(graph_path, "w", encoding="utf-8") as fh:
        fh.write(EX_GRAPH)
    cs_path = str(tmp_path / "museum.constraints.json")
    kgrepair.save_constraint_file(_ex_constraints(), cs_path)

    session = logic.Session(
        graph=logic.load_graph_from_path(graph_path, type_predicates=EX_SPINE),
        constraints=logic.load_constraints_from_path(cs_path),
        graph_name="museum.nt", constraints_source="museum.constraints.json",
        type_predicates=logic.effective_type_predicates(EX_SPINE))
    viewer = logic.run_check(session, witness_limit=10)

    assert cli_main(["check", "--in", graph_path, "--constraints", cs_path,
                     "--type-predicate", "ex:isa",
                     "--type-predicate", "ex:subclassOf",
                     "--report", str(tmp_path / "c.json")]) == 2
    with open(tmp_path / "c.json", encoding="utf-8") as fh:
        assert viewer == json.load(fh)


def test_omitting_the_spine_loses_the_custom_class_test():
    """The type-predicate control is doing real work: without it the default
    vocabulary cannot see an ex:isa spine."""
    session = logic.Session(
        graph=logic.load_graph_from_text(EX_GRAPH, "museum.nt"),
        constraints=_ex_constraints(), graph_name="museum.nt",
        constraints_source="museum.constraints.json",
        type_predicates=logic.effective_type_predicates(None))
    fired = {c["cid"]: c["witness_count"]
             for c in logic.run_check(session)["result"]["constraints"]}
    assert fired["mus.req.gallery"] == 0


# ---------- inputs ----------------------------------------------------------

@pytest.mark.parametrize("text,expected", [
    ("", None),
    ("   \n  ", None),
    ("ex:isa", {"ex:isa"}),
    ("ex:isa, ex:subclassOf", {"ex:isa", "ex:subclassOf"}),
    ("ex:isa\nex:subclassOf\n", {"ex:isa", "ex:subclassOf"}),
    ("ex:isa,\n , ex:subclassOf", {"ex:isa", "ex:subclassOf"}),
])
def test_type_predicate_box_accepts_lines_or_commas(text, expected):
    assert logic.parse_type_predicates(text) == expected


def test_empty_type_predicate_box_means_the_default():
    assert logic.effective_type_predicates(logic.parse_type_predicates("")) == \
        set(kgrepair.DEFAULT_TYPE_PREDICATES)


def test_malformed_ntriples_upload_is_a_clean_error():
    with pytest.raises(logic.ViewerError, match="N-Triples"):
        logic.load_graph_from_text("this is not a triple at all", "bad.nt")


def test_malformed_constraint_upload_is_a_clean_error():
    with pytest.raises(logic.ViewerError, match="not valid JSON"):
        logic.load_constraints_from_text("{not json", "bad.json")
    with pytest.raises(logic.ViewerError, match="not a constraint file"):
        logic.load_constraints_from_text('{"nope": 1}', "bad.json")


def test_out_of_fragment_constraint_upload_is_rejected_on_load():
    payload = {"slice": "x@y", "constraints": [{
        "cid": "bad", "domain": "d", "kg": "k", "kind": "typing_existence",
        "tier": "ptime_core", "provenance": "derived", "direction": "superset",
        "containment": {"phi": "< down(ex:p) >", "psi": '! val("C")'},
    }]}
    with pytest.raises(logic.ViewerError, match="positive fragment"):
        logic.load_constraints_from_text(json.dumps(payload), "bad.json")


def test_missing_graph_file_is_a_clean_error():
    with pytest.raises(logic.ViewerError, match="could not read graph"):
        logic.load_graph_from_path("/nonexistent/nope.nt")


def test_builtin_choices_cover_the_registry():
    choices = logic.builtin_constraint_choices()
    assert "geography / wikidata (v1)" in choices
    assert choices["geography / wikidata (v1)"] == ("geography", "wikidata", 1)
    domain, kg, version = choices["anatomy / wikidata (v2)"]
    cs = logic.load_builtin_constraints(domain, kg, version)
    assert cs.to_dict() == kgrepair.constraints.get("anatomy", "wikidata",
                                                    version=2).to_dict()


def test_unknown_builtin_slice_is_a_clean_error():
    with pytest.raises(logic.ViewerError, match="no built-in constraint set"):
        logic.load_builtin_constraints("geography", "nosuchkg")


# ---------- allow-list, opt in ----------------------------------------------

def test_allowlist_is_opt_in_and_filters_when_used(ex_session):
    allowlist = json.dumps({"allowlist_id": "museum", "source": "example",
                            "predicates": ["ex:isa", "ex:subclassOf", "ex:madeOf"],
                            "prefixes": {}})
    filtered, dropped = logic.apply_user_allowlist(ex_session.graph, allowlist, "al.json")
    assert filtered.labels == {"ex:isa", "ex:subclassOf", "ex:madeOf"}
    assert dropped == 1
    assert "ex:inGallery" in ex_session.graph.labels     # the input is not mutated

    assert ex_session.allowlist_applied is False
    assert "allowlist_edges_dropped" not in logic.run_check(ex_session)


def test_allowlist_shows_up_in_the_report_when_applied(ex_session):
    ex_session.allowlist_applied = True
    ex_session.allowlist_edges_dropped = 1
    payload = logic.run_check(ex_session)
    assert payload["allowlist_applied"] is True
    assert payload["allowlist_edges_dropped"] == 1


def test_malformed_allowlist_is_a_clean_error(ex_session):
    with pytest.raises(logic.ViewerError, match="not valid JSON"):
        logic.apply_user_allowlist(ex_session.graph, "{nope", "al.json")
    with pytest.raises(logic.ViewerError, match="not an allow-list file"):
        logic.apply_user_allowlist(ex_session.graph, '{"x": 1}', "al.json")


# ---------- repair and export -----------------------------------------------

def test_cap_abort_runs_no_engine(ex_session):
    run = logic.run_repair(ex_session, "subset", cap=0.0)
    assert run.aborted is True
    assert run.exit_code == 3
    assert run.result is None
    assert run.payload["result"] is None
    assert run.payload["cap"]["status"] == "ABORTED-BY-CAP"


def test_raising_the_cap_lets_the_repair_run(ex_session):
    run = logic.run_repair(ex_session, "subset", cap=1.0)
    assert run.aborted is False
    assert run.result is not None
    assert run.payload["cap"]["status"] == "OK"


def test_unknown_mode_is_a_clean_error(ex_session):
    with pytest.raises(logic.ViewerError, match="unknown repair mode"):
        logic.run_repair(ex_session, "sideways")


def test_export_before_repair_offers_the_original_graph(ex_session):
    payload = logic.run_check(ex_session)
    downloads = logic.export_payloads(ex_session, payload)
    assert downloads["graph"] == kgrepair.to_ntriples(ex_session.graph)
    assert json.loads(downloads["report"]) == payload


def test_isolated_nodes_are_counted_for_the_export_caption(ex_session):
    run = logic.run_repair(ex_session, "subset", cap=1.0)
    assert logic.isolated_node_count(run.result.graph) >= 0
    assert logic.isolated_node_count(ex_session.graph) == 0


def test_violation_rows_join_the_constraint_text(ex_session):
    rows = logic.violation_rows(ex_session, logic.run_check(ex_session))
    by_cid = {r["cid"]: r for r in rows}
    assert by_cid["mus.dom.madeof"]["report_only"] is False
    assert "ex:madeOf" in by_cid["mus.dom.madeof"]["containment"]
    assert by_cid["mus.dom.madeof"]["provenance"] == "derived"


def test_neighbourhood_is_reachable_through_the_seam(ex_session):
    view = logic.neighbourhood(ex_session.graph, "ex:vase1", k=1)
    assert view.center == "ex:vase1"
    assert "ex:vase1" in view.node_ids()


# ---------- dependency hygiene ----------------------------------------------

def test_logic_module_imports_no_streamlit():
    """The seam is plain Python, which is why it is testable without a browser."""
    src = open(os.path.join(ROOT, "app", "logic.py"), encoding="utf-8").read()
    assert "streamlit" not in src


def test_core_import_pulls_in_no_streamlit():
    import subprocess
    import sys
    code = ("import sys, kgrepair, kgrepair.cli\n"
            "print('streamlit' in sys.modules)\n")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                         cwd=os.sep)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "False"


def test_viewer_reaches_only_the_public_api():
    """Every kgrepair import in app/ must resolve to a name on the public surface.

    This is the viewer's counterpart to the CLI's thin-skin gate: it fails the
    moment a screen starts reaching into kgrepair.validator, kgrepair.repair,
    kgrepair.neighbourhood or any other internal module.
    """
    public = set(kgrepair.__all__)
    offenders = []
    for dirpath, _dirs, files in os.walk(os.path.join(ROOT, "app")):
        for name in sorted(files):
            if not name.endswith(".py"):
                continue
            path = os.path.join(dirpath, name)
            rel = os.path.relpath(path, ROOT)
            for lineno, line in enumerate(open(path, encoding="utf-8"), 1):
                m = re.match(r"\s*from\s+kgrepair(\.[\w.]+)?\s+import\s+(.+)", line)
                if not m:
                    continue
                submodule, names = m.group(1), m.group(2)
                if submodule not in (None, ""):
                    offenders.append(f"{rel}:{lineno}: reaches into kgrepair{submodule}")
                    continue
                for sym in [s.strip().split(" as ")[0].strip("() \\")
                            for s in names.split(",")]:
                    if sym and sym != "constraints" and sym not in public:
                        offenders.append(f"{rel}:{lineno}: {sym} is not public")
    assert offenders == [], "viewer reaches past the public API:\n" + "\n".join(offenders)
