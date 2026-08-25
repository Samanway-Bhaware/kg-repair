"""
Command-line interface tests.

`main([...])` is called in process and its return value is the exit code, so no
subprocess is needed and stdout can be captured directly. The one exception is
the `python -m kgrepair` check, which has to spawn an interpreter to mean
anything.
"""
import json
import os
import re
import subprocess
import sys

import pytest

import kgrepair
from kgrepair.cli import (EXIT_CAPPED, EXIT_OK, EXIT_USAGE, EXIT_VIOLATIONS, build_parser,
                          main)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GEO_FIXTURE = os.path.join(ROOT, "fixtures", "synthetic_geography_wd.nt")

# A graph with an entirely custom typing spine, for the agnostic gate.
EX_TYPE_PREDICATES = ["ex:isa", "ex:subclassOf"]
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

WIKIDATA_MARKERS = re.compile(r"\bP31\b|\bP279\b|\bwd:|\bwdt:|wikidata", re.IGNORECASE)


def _ex_constraints():
    """A constraint set naming only the custom museum vocabulary."""
    common = dict(domain="museum", kg="example", tier="ptime_core",
                  provenance="derived", version=1)
    tau = lambda c: f'< down(ex:isa) . down(ex:subclassOf)* . [val("{c}")] >'
    return kgrepair.ConstraintSet("museum@example", [
        kgrepair.Constraint(cid="mus.dom.madeof", kind="existential_domain",
                            direction="subset", antecedent="< down(ex:madeOf) >",
                            consequent=tau("cat:Artefact"), **common),
        kgrepair.Constraint(cid="mus.req.gallery", kind="requires_statement",
                            direction="superset", antecedent=tau("cat:Artefact"),
                            consequent="< down(ex:inGallery) >", **common),
    ])


@pytest.fixture(name="ex_slice")
def _ex_slice(tmp_path):
    """(graph_path, constraints_path) for the custom-vocabulary graph."""
    graph_path = str(tmp_path / "museum.nt")
    with open(graph_path, "w", encoding="utf-8") as fh:
        fh.write(EX_GRAPH)
    cs_path = str(tmp_path / "museum.constraints.json")
    kgrepair.save_constraint_file(_ex_constraints(), cs_path)
    return graph_path, cs_path


def _run(argv, capsys):
    """Run the CLI and return (exit_code, parsed_json_or_None)."""
    code = main(argv)
    out = capsys.readouterr().out
    return code, (json.loads(out) if out.strip() else None)


# ---------- check -----------------------------------------------------------

def test_check_on_violating_fixture_exits_2_and_lists_the_failures(capsys):
    code, payload = _run(["check", "--in", GEO_FIXTURE,
                          "--domain", "geography", "--kg", "wikidata"], capsys)
    assert code == EXIT_VIOLATIONS

    result = payload["result"]
    assert result["consistent"] is False
    assert result["by_tier"]["ptime_core"] > 0
    fired = {c["cid"]: c["witness_count"] for c in result["constraints"]
             if c["witness_count"]}
    assert fired["geo.wd.dom.country"] == 1
    assert fired["geo.wd.rng.country"] == 1
    assert payload["constraints_source"] == "geography/wikidata/v1"
    assert payload["input_basename"] == "synthetic_geography_wd.nt"


def test_check_on_a_consistent_graph_exits_0(capsys, tmp_path):
    """Repair the fixture first, then check the repaired graph."""
    out = str(tmp_path / "repaired.nt")
    assert main(["repair", "--in", GEO_FIXTURE, "--domain", "geography",
                 "--kg", "wikidata", "--mode", "superset", "--out", out,
                 "--report", str(tmp_path / "r.json")]) == EXIT_OK

    code, payload = _run(["check", "--in", out, "--domain", "geography",
                          "--kg", "wikidata"], capsys)
    assert code == EXIT_OK
    assert payload["result"]["by_tier"]["ptime_core"] == 0


def test_boundary_violations_alone_do_not_fail_the_check(capsys, tmp_path):
    """Boundary-tier constraints are report-only, so a graph failing only those
    still exits 0 while still reporting them."""
    out = str(tmp_path / "repaired.nt")
    main(["repair", "--in", GEO_FIXTURE, "--domain", "geography", "--kg", "wikidata",
          "--mode", "superset", "--out", out, "--report", str(tmp_path / "r.json")])

    code, payload = _run(["check", "--in", out, "--domain", "geography",
                          "--kg", "wikidata"], capsys)
    assert code == EXIT_OK
    assert payload["result"]["by_tier"]["boundary"] > 0
    assert payload["result"]["consistent"] is False


def test_witness_limit_bounds_the_preview_without_hiding_the_count(capsys):
    code, payload = _run(["check", "--in", GEO_FIXTURE, "--domain", "geography",
                          "--kg", "wikidata", "--witness-limit", "0"], capsys)
    assert code == EXIT_VIOLATIONS
    for c in payload["result"]["constraints"]:
        assert c["witnesses"] == []
        assert c["witnesses_truncated"] is (c["witness_count"] > 0)


# ---------- repair ----------------------------------------------------------

def test_repair_superset_writes_a_graph_that_revalidates_clean(capsys, tmp_path):
    out = str(tmp_path / "repaired.nt")
    code, payload = _run(["repair", "--in", GEO_FIXTURE, "--domain", "geography",
                          "--kg", "wikidata", "--mode", "superset", "--out", out],
                         capsys)
    assert code == EXIT_OK
    assert payload["mode"] == "superset"
    assert payload["output_basename"] == "repaired.nt"
    assert payload["cap"]["status"] == "OK"

    reloaded = kgrepair.load_graph(out)
    cs = kgrepair.constraints.get("geography", "wikidata")
    assert kgrepair.validate(reloaded, cs).by_tier()["ptime_core"] == 0


def test_repair_report_result_equals_the_engine_to_dict(capsys, tmp_path):
    """The body under `result` is the repair result's own to_dict(), so the command
    line and the viewer cannot report different things about the same run. Compared
    after a JSON round trip, since JSON has no tuples."""
    out = str(tmp_path / "repaired.nt")
    _code, payload = _run(["repair", "--in", GEO_FIXTURE, "--domain", "geography",
                           "--kg", "wikidata", "--mode", "superset", "--out", out],
                          capsys)

    graph = kgrepair.load_graph(GEO_FIXTURE)
    cs = kgrepair.constraints.get("geography", "wikidata")
    expected = json.loads(json.dumps(kgrepair.superset_repair(graph, cs).to_dict()))
    assert payload["result"] == expected


def test_repair_subset_deletes_and_reports_its_changelog(capsys, tmp_path):
    out = str(tmp_path / "repaired.nt")
    code, payload = _run(["repair", "--in", GEO_FIXTURE, "--domain", "geography",
                          "--kg", "wikidata", "--mode", "subset", "--out", out],
                         capsys)
    assert code == EXIT_OK
    assert payload["result"]["attestations"]["subset_only_deleted"] is True
    assert all(r["op"].startswith("remove") for r in payload["result"]["changelog"])


def test_repair_aborts_by_cap_and_writes_no_graph(capsys, tmp_path):
    """A graph where the subset repair would delete most of the nodes trips the cap.
    Exit 3, no engine run, no output file."""
    graph_path = str(tmp_path / "capped.nt")
    with open(graph_path, "w", encoding="utf-8") as fh:
        for i in range(6):
            fh.write(f"<ex:thing{i}> <ex:madeOf> <cat:marble> .\n")
    cs_path = str(tmp_path / "cs.json")
    kgrepair.save_constraint_file(_ex_constraints(), cs_path)
    out = str(tmp_path / "never_written.nt")

    code, payload = _run(["repair", "--in", graph_path, "--constraints", cs_path,
                          "--mode", "subset", "--out", out,
                          "--type-predicate", "ex:isa",
                          "--type-predicate", "ex:subclassOf"], capsys)
    assert code == EXIT_CAPPED
    assert payload["cap"]["status"] == "ABORTED-BY-CAP"
    assert payload["cap"]["aborted"] is True
    assert payload["cap"]["fraction"] > payload["cap"]["cap"]
    assert payload["result"] is None
    assert not os.path.exists(out)


def test_raising_the_cap_lets_the_same_repair_run(capsys, tmp_path):
    graph_path = str(tmp_path / "capped.nt")
    with open(graph_path, "w", encoding="utf-8") as fh:
        for i in range(6):
            fh.write(f"<ex:thing{i}> <ex:madeOf> <cat:marble> .\n")
    cs_path = str(tmp_path / "cs.json")
    kgrepair.save_constraint_file(_ex_constraints(), cs_path)
    out = str(tmp_path / "repaired.nt")

    code, payload = _run(["repair", "--in", graph_path, "--constraints", cs_path,
                          "--mode", "subset", "--out", out,
                          "--max-deletion-fraction", "1.0",
                          "--type-predicate", "ex:isa"], capsys)
    assert code == EXIT_OK
    assert payload["cap"]["status"] == "OK"
    assert os.path.exists(out)


# ---------- constraint sourcing --------------------------------------------

def test_no_constraint_source_exits_1_with_guidance(capsys):
    assert main(["check", "--in", GEO_FIXTURE]) == EXIT_USAGE
    err = capsys.readouterr().err
    assert "--constraints" in err and "--domain" in err
    assert "not wired" in err                    # derivation is a documented hook


def test_constraints_and_domain_are_mutually_exclusive(capsys, tmp_path):
    cs_path = str(tmp_path / "cs.json")
    kgrepair.save_constraint_file(_ex_constraints(), cs_path)
    assert main(["check", "--in", GEO_FIXTURE, "--constraints", cs_path,
                 "--domain", "geography"]) == EXIT_USAGE


def test_constraints_and_kg_are_rejected_together(capsys, tmp_path):
    cs_path = str(tmp_path / "cs.json")
    kgrepair.save_constraint_file(_ex_constraints(), cs_path)
    assert main(["check", "--in", GEO_FIXTURE, "--constraints", cs_path,
                 "--kg", "wikidata"]) == EXIT_USAGE
    assert "alternatives" in capsys.readouterr().err


def test_unknown_builtin_slice_exits_1_and_lists_what_exists(capsys):
    assert main(["check", "--in", GEO_FIXTURE,
                 "--domain", "geography", "--kg", "nosuchkg"]) == EXIT_USAGE
    err = capsys.readouterr().err
    assert "no built-in constraint set" in err and "wikidata" in err


def test_domain_without_kg_exits_1(capsys):
    assert main(["check", "--in", GEO_FIXTURE, "--domain", "geography"]) == EXIT_USAGE
    assert "must be given together" in capsys.readouterr().err


def test_missing_graph_file_exits_1(capsys):
    assert main(["check", "--in", "/nonexistent/nope.nt",
                 "--domain", "geography", "--kg", "wikidata"]) == EXIT_USAGE
    assert "could not read graph" in capsys.readouterr().err


def test_no_subcommand_exits_1(capsys):
    assert main([]) == EXIT_USAGE
    assert "subcommand is required" in capsys.readouterr().err


# ---------- allow-list (opt in) ---------------------------------------------

ALLOWLIST = {
    "allowlist_id": "museum-v1", "source": "example",
    "predicates": ["ex:isa", "ex:subclassOf", "ex:madeOf"],
    "deny_predicates": [], "prefixes": {"ex": "http://example.org/"},
}


def test_allowlist_is_off_unless_asked_for(capsys, ex_slice):
    graph_path, cs_path = ex_slice
    _code, payload = _run(["check", "--in", graph_path, "--constraints", cs_path,
                           "--type-predicate", "ex:isa",
                           "--type-predicate", "ex:subclassOf"], capsys)
    assert payload["allowlist_applied"] is False
    assert "allowlist_edges_dropped" not in payload
    fired = {c["cid"]: c["witness_count"] for c in payload["result"]["constraints"]}
    assert fired["mus.req.gallery"] == 1         # ex:inGallery was not filtered out


def test_allowlist_filters_the_named_predicates(capsys, ex_slice, tmp_path):
    graph_path, cs_path = ex_slice
    al_path = str(tmp_path / "al.json")
    with open(al_path, "w", encoding="utf-8") as fh:
        json.dump(ALLOWLIST, fh)

    _code, payload = _run(["check", "--in", graph_path, "--constraints", cs_path,
                           "--allowlist", al_path,
                           "--type-predicate", "ex:isa",
                           "--type-predicate", "ex:subclassOf"], capsys)
    assert payload["allowlist_applied"] is True
    assert payload["allowlist_edges_dropped"] == 1     # the one ex:inGallery edge
    fired = {c["cid"]: c["witness_count"] for c in payload["result"]["constraints"]}
    assert fired["mus.req.gallery"] == 2               # both artefacts now lack one


def test_allowlist_help_makes_no_ethics_claim():
    text = build_parser().format_help()
    for word in ("ethic", "personal data", "gdpr", "safe", "guarantee"):
        assert word not in text.lower()


# ---------- the agnostic command-line gate ----------------------------------

def test_cli_checks_and_repairs_a_non_wikidata_graph(capsys, ex_slice, tmp_path):
    """The gate: a graph with an ex:isa / ex:subclassOf spine and hand-written
    constraints goes through check and repair at the command line, with no Wikidata
    vocabulary anywhere. This is what proves --type-predicate really reaches
    load_graph rather than the default vocabulary being silently used."""
    graph_path, cs_path = ex_slice
    spine = ["--type-predicate", "ex:isa", "--type-predicate", "ex:subclassOf"]

    code, checked = _run(["check", "--in", graph_path, "--constraints", cs_path]
                         + spine, capsys)
    assert code == EXIT_VIOLATIONS
    fired = {c["cid"]: c["witness_count"] for c in checked["result"]["constraints"]
             if c["witness_count"]}
    assert fired == {"mus.dom.madeof": 1, "mus.req.gallery": 1}
    assert checked["type_predicates"] == ["ex:isa", "ex:subclassOf"]

    out = str(tmp_path / "repaired.nt")
    code, repaired = _run(["repair", "--in", graph_path, "--constraints", cs_path,
                           "--mode", "superset", "--out", out] + spine, capsys)
    assert code == EXIT_OK
    assert repaired["result"]["attestations"]["consistent_after"] is True

    reloaded = kgrepair.load_graph(out, type_predicates=set(EX_TYPE_PREDICATES))
    assert kgrepair.validate(reloaded, _ex_constraints()).by_tier()["ptime_core"] == 0

    for blob in (json.dumps(checked), json.dumps(repaired),
                 open(out, encoding="utf-8").read(),
                 open(cs_path, encoding="utf-8").read()):
        hit = WIKIDATA_MARKERS.search(blob)
        assert hit is None, f"Wikidata vocabulary leaked: {hit.group(0)!r}"


def test_without_the_type_predicate_flag_the_custom_spine_is_not_seen(capsys, ex_slice):
    """The complement of the gate: omitting --type-predicate falls back to the
    default vocabulary, which cannot see an ex:isa spine, so the class tests match
    nothing. The flag is doing real work."""
    graph_path, cs_path = ex_slice
    _code, payload = _run(["check", "--in", graph_path, "--constraints", cs_path],
                          capsys)
    fired = {c["cid"]: c["witness_count"] for c in payload["result"]["constraints"]}
    assert fired["mus.req.gallery"] == 0
    assert payload["type_predicates"] == sorted(kgrepair.DEFAULT_TYPE_PREDICATES)


# ---------- report shape ----------------------------------------------------

def test_two_identical_runs_produce_identical_bytes(tmp_path):
    first, second = str(tmp_path / "a.json"), str(tmp_path / "b.json")
    argv = ["repair", "--in", GEO_FIXTURE, "--domain", "geography", "--kg", "wikidata",
            "--mode", "superset", "--out", str(tmp_path / "g.nt")]
    assert main(argv + ["--report", first]) == EXIT_OK
    assert main(argv + ["--report", second]) == EXIT_OK
    assert open(first, "rb").read() == open(second, "rb").read()


def test_report_carries_no_absolute_paths(tmp_path, capsys):
    out = str(tmp_path / "repaired.nt")
    _code, payload = _run(["repair", "--in", GEO_FIXTURE, "--domain", "geography",
                           "--kg", "wikidata", "--mode", "superset", "--out", out],
                          capsys)
    text = json.dumps(payload)
    assert ROOT not in text and str(tmp_path) not in text
    assert payload["input_basename"] == os.path.basename(GEO_FIXTURE)


def test_report_goes_to_a_file_when_asked(tmp_path, capsys):
    path = str(tmp_path / "report.json")
    assert main(["check", "--in", GEO_FIXTURE, "--domain", "geography",
                 "--kg", "wikidata", "--report", path]) == EXIT_VIOLATIONS
    assert capsys.readouterr().out == ""
    with open(path, encoding="utf-8") as fh:
        assert json.load(fh)["result"]["consistent"] is False


# ---------- packaging -------------------------------------------------------

def test_python_dash_m_kgrepair_runs():
    out = subprocess.run([sys.executable, "-m", "kgrepair", "--help"],
                         capture_output=True, text=True, cwd=os.sep)
    assert out.returncode == 0
    assert "check" in out.stdout and "repair" in out.stdout


def test_console_script_is_declared():
    import tomllib
    with open(os.path.join(ROOT, "pyproject.toml"), "rb") as fh:
        cfg = tomllib.load(fh)
    assert cfg["project"]["scripts"] == {"kgrepair": "kgrepair.cli:main"}


def test_cli_imports_no_third_party_module():
    code = ("import sys, kgrepair.cli\n"
            "print(','.join(m for m in ('matplotlib', 'streamlit') if m in sys.modules))\n")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                         cwd=os.sep)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == ""


def test_cli_holds_no_repair_or_validation_logic():
    """The thin-skin rule, checked mechanically: cli.py may call the engines and the
    validator but must not walk a graph or build a result itself."""
    src = open(os.path.join(ROOT, "src", "kgrepair", "cli.py"), encoding="utf-8").read()
    for forbidden in (".edges()", ".nodes", "Evaluator", "eval_node", "check_one",
                      "remove_node", "add_edge", "ChangeRecord(", ".witnesses"):
        assert forbidden not in src, f"cli.py looks like it does its own work: {forbidden}"
