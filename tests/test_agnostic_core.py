"""
Dataset-agnosticism gate.

The whole toolkit is exercised through the public API on a knowledge graph that
has nothing to do with Wikidata: a small museum-catalogue graph whose typing
spine is `ex:isa` / `ex:kindOf` and whose domain predicates are `ex:madeOf` and
`ex:inGallery`, with a constraint set hand-written here to name those predicates.
Seeded violations are found by the validator and then fixed by each repair
engine, and every artifact of the run is scanned for Wikidata vocabulary.

This is the definition-of-done gate for "the core is knowledge-graph-agnostic":
if a Wikidata predicate, prefix, or assumption ever leaks into the graph model,
the validator, or the repair engines, this test fails. The command-line interface
and the Streamlit viewer are skins over the same API, so they inherit the
property rather than having to re-establish it.
"""
import json
import os
import re

import pytest

import kgrepair
from kgrepair import Constraint, ConstraintSet

# The typing spine of THIS graph. Passing it to the loader is what makes class
# nodes self-valued so `val("...")` can match them; nothing about the default
# vocabulary is assumed.
TYPE_PREDICATES = {"ex:isa", "ex:kindOf"}

# Wikidata vocabulary that must not appear anywhere in this test's data or output.
WIKIDATA_MARKERS = re.compile(r"\bP31\b|\bP279\b|\bwd:|\bwdt:|wikidata", re.IGNORECASE)

GRAPH = """\
# a clean vase: typed, made of a typed material, in a gallery
<ex:vase1> <ex:isa> <cat:Vase> .
<cat:Vase> <ex:kindOf> <cat:Artefact> .
<ex:vase1> <ex:madeOf> <cat:clay> .
<ex:vase1> <ex:inGallery> <ex:gallery1> .

# a clean artefact named by a full IRI rather than a CURIE
<http://example.org/collection/amphora1> <ex:isa> <cat:Vase> .
<http://example.org/collection/amphora1> <ex:madeOf> <cat:marble> .
<http://example.org/collection/amphora1> <ex:inGallery> <ex:gallery1> .

<cat:marble> <ex:isa> <cat:Material> .

# SEEDED: made of something, but is not an artefact          -> domain violation
<ex:sculpture1> <ex:madeOf> <cat:marble> .

# SEEDED: cat:clay is the target of madeOf but is not typed  -> range violation
# (no triple: the absence is the violation)

# SEEDED: an artefact with no gallery                        -> requires violation
<ex:vase2> <ex:isa> <cat:Vase> .
<ex:vase2> <ex:madeOf> <cat:marble> .
"""


def _tau(cls):
    """The class test for this graph's own spine: isa, then kindOf transitively."""
    return f'< down(ex:isa) . down(ex:kindOf)* . [val("{cls}")] >'


def _constraints(requires_direction="superset"):
    """A hand-written constraint set over the museum vocabulary.

    Three ptime_core shapes, exactly as the toolkit classifies them: existential
    domain, existential range, and requires-statement.
    """
    common = dict(domain="museum", kg="example", tier="ptime_core",
                  provenance="derived", version=1)
    return ConstraintSet("museum@example", [
        Constraint(cid="mus.dom.madeof", kind="existential_domain",
                   direction="subset",
                   antecedent="< down(ex:madeOf) >",
                   consequent=_tau("cat:Artefact"),
                   note="anything made of something is an artefact", **common),
        Constraint(cid="mus.rng.madeof", kind="existential_range",
                   direction="subset",
                   antecedent="< up(ex:madeOf) >",
                   consequent=_tau("cat:Material"),
                   note="anything something is made of is a material", **common),
        Constraint(cid="mus.req.gallery", kind="requires_statement",
                   direction=requires_direction,
                   antecedent=_tau("cat:Artefact"),
                   consequent="< down(ex:inGallery) >",
                   note="every artefact is displayed in a gallery", **common),
    ])


@pytest.fixture(name="graph")
def _graph():
    return kgrepair.load_graph_string(GRAPH, type_predicates=TYPE_PREDICATES)


def _assert_no_wikidata(*blobs):
    for blob in blobs:
        hit = WIKIDATA_MARKERS.search(blob)
        assert hit is None, f"Wikidata vocabulary leaked into the run: {hit.group(0)!r}"


def _run_text(graph, cs, *results):
    """Everything the run produced, as one string, for the vocabulary scan."""
    parts = [kgrepair.to_ntriples(graph), json.dumps(cs.to_dict(), sort_keys=True)]
    parts += [r.to_json() for r in results]
    return parts


# ---------- the gate --------------------------------------------------------

def test_non_wikidata_graph_validates_and_repairs_through_the_public_api(graph):
    """The full loop on a graph with no Wikidata vocabulary anywhere."""
    cs = _constraints()
    cs.compile_all()                      # nothing here leaves the positive fragment

    report = kgrepair.validate(graph, cs)
    assert not report.consistent
    fired = {v.constraint.cid: v.witnesses for v in report.failing()}
    assert fired == {
        "mus.dom.madeof": {"ex:sculpture1"},
        "mus.rng.madeof": {"cat:clay"},
        "mus.req.gallery": {"ex:vase2"},
    }

    added = kgrepair.superset_repair(graph, cs)
    assert kgrepair.validate(added.graph, cs).by_tier()["ptime_core"] == 0

    deleted = kgrepair.subset_repair(graph, _constraints(requires_direction="subset"))
    assert kgrepair.validate(deleted.graph, cs).by_tier()["ptime_core"] == 0

    _assert_no_wikidata(*_run_text(graph, cs, added, deleted))
    _assert_no_wikidata(kgrepair.to_ntriples(added.graph),
                        kgrepair.to_ntriples(deleted.graph))


def test_superset_repair_adds_the_expected_structure(graph):
    """The additions are the missing type edges and the missing gallery edge, drawn
    from this graph's own vocabulary rather than from any built-in one."""
    result = kgrepair.superset_repair(graph, _constraints())

    assert result.attestations["superset_only_added"]
    assert result.attestations["data_values_unmodified"]
    assert result.attestations["consistent_after"]

    labels = {label for _s, label, _d in result.added_edges}
    assert labels <= {"ex:isa", "ex:kindOf", "ex:inGallery"}
    assert ("ex:sculpture1", "ex:isa", "cat:Artefact") in result.added_edges
    assert ("cat:clay", "ex:isa", "cat:Material") in result.added_edges
    assert any(s == "ex:vase2" and label == "ex:inGallery"
               for s, label, _d in result.added_edges)
    assert set(graph.edges()) < set(result.graph.edges())


def test_subset_repair_deletes_the_witnesses(graph):
    """Deletion repair removes exactly the offending nodes and nothing else."""
    result = kgrepair.subset_repair(graph, _constraints(requires_direction="subset"))

    assert result.attestations["subset_only_deleted"]
    assert result.attestations["data_values_unmodified"]
    assert result.deleted_nodes == {"ex:sculpture1", "cat:clay", "ex:vase2"}
    assert result.graph.nodes < graph.nodes
    assert "ex:vase1" in result.graph.nodes
    assert "http://example.org/collection/amphora1" in result.graph.nodes


def test_loader_preserves_iris_and_curies_verbatim(graph):
    """No prefix is expanded, abbreviated, or rewritten on the file-load path.
    Abbreviation belongs to the extraction pipeline, not to loading a graph."""
    assert "http://example.org/collection/amphora1" in graph.nodes
    assert "ex:vase1" in graph.nodes
    for node in graph.nodes:
        assert not node.startswith("wd:") and not node.startswith("wdt:")
    assert graph.labels == {"ex:isa", "ex:kindOf", "ex:madeOf", "ex:inGallery"}


def test_loader_does_not_self_value_outside_the_declared_spine():
    """Without naming the spine, `ex:isa` objects are ordinary nodes, so the class
    test finds nothing. This is the coupling the `type_predicates` argument removes:
    the default vocabulary is a default, not a rule baked into the loader."""
    default_load = kgrepair.load_graph_string(GRAPH)
    assert default_load.value("cat:Artefact") is None

    spine_load = kgrepair.load_graph_string(GRAPH, type_predicates=TYPE_PREDICATES)
    assert spine_load.value("cat:Artefact") == "cat:Artefact"
    assert set(default_load.edges()) == set(spine_load.edges())


def test_repair_needs_no_manifest_allowlist_or_pipeline(graph):
    """Validation and repair take a graph and a constraint set, and nothing else:
    no slice manifest, no allowlist_id, no allow-list hash, no deny-check."""
    import inspect
    for fn in (kgrepair.validate, kgrepair.subset_repair, kgrepair.superset_repair):
        params = set(inspect.signature(fn).parameters)
        assert not params & {"manifest", "allowlist", "allowlist_id", "allowlist_hash",
                             "source", "slice_id"}

    result = kgrepair.superset_repair(graph, _constraints())
    payload = result.to_json()
    for forbidden in ("allowlist_id", "allowlist_hash", "manifest", "slice_id"):
        assert forbidden not in payload


def test_repaired_graph_round_trips_through_ntriples(graph, tmp_path):
    """The repaired graph writes out and reads back with the same validation
    outcome, so the export path is agnostic too."""
    cs = _constraints()
    result = kgrepair.superset_repair(graph, cs)
    path = str(tmp_path / "repaired.nt")
    assert kgrepair.write_ntriples(result.graph, path) == path

    reloaded = kgrepair.load_graph(path, type_predicates=TYPE_PREDICATES)
    assert kgrepair.validate(reloaded, cs).by_tier()["ptime_core"] == 0
    _assert_no_wikidata(open(path, encoding="utf-8").read())


def test_constraint_file_carries_the_custom_vocabulary(tmp_path):
    """A user-authored constraint set survives a file round trip and still names
    only the user's own predicates."""
    cs = _constraints()
    path = str(tmp_path / "museum.json")
    kgrepair.save_constraint_file(cs, path)
    back = kgrepair.load_constraint_file(path, compile_now=True)

    assert back.to_dict() == cs.to_dict()
    text = open(path, encoding="utf-8").read()
    _assert_no_wikidata(text)
    assert "ex:madeOf" in text and "cat:Artefact" in text

    graph = kgrepair.load_graph_string(GRAPH, type_predicates=TYPE_PREDICATES)
    assert len(kgrepair.validate(graph, back).failing()) == 3


# ---------- optional user-supplied predicate filter -------------------------

ALLOWLIST = {
    "allowlist_id": "museum-v1",
    "source": "example",
    "predicates": ["ex:isa", "ex:kindOf", "ex:madeOf"],
    "deny_predicates": [],
    "prefixes": {"ex": "http://example.org/", "cat": "http://example.org/cat/"},
}


def _allowlist_file(tmp_path):
    path = str(tmp_path / "museum.allowlist.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(ALLOWLIST, fh)
    return path


def test_apply_allowlist_filters_only_the_named_predicates(graph, tmp_path):
    filtered, dropped = kgrepair.apply_allowlist(graph, _allowlist_file(tmp_path))

    assert filtered.labels == {"ex:isa", "ex:kindOf", "ex:madeOf"}
    assert dropped == 2                       # the two ex:inGallery edges
    assert graph.labels == {"ex:isa", "ex:kindOf", "ex:madeOf", "ex:inGallery"}
    assert filtered.nodes == graph.nodes      # nodes survive, only edges are dropped


def test_apply_allowlist_accepts_a_plain_predicate_iterable(graph):
    filtered, dropped = kgrepair.apply_allowlist(graph, {"ex:madeOf"})
    assert filtered.labels == {"ex:madeOf"}
    assert dropped == graph.num_edges() - filtered.num_edges()


def test_default_paths_do_no_filtering(graph, tmp_path):
    """Loading, validating and repairing filter nothing unless apply_allowlist is
    called: the excluded predicate is still there and still drives a constraint."""
    cs = _constraints()
    assert "ex:inGallery" in graph.labels
    report = kgrepair.validate(graph, cs)
    assert "mus.req.gallery" in {v.constraint.cid for v in report.failing()}

    result = kgrepair.superset_repair(graph, cs)
    assert "ex:inGallery" in result.graph.labels

    reloaded = kgrepair.load_graph_string(GRAPH, type_predicates=TYPE_PREDICATES)
    assert reloaded.num_edges() == graph.num_edges()


def test_filtering_changes_what_validation_sees(graph, tmp_path):
    """Once the user opts in, the dropped predicate is genuinely gone, and the
    constraint that depended on it now flags every artefact."""
    filtered, _dropped = kgrepair.apply_allowlist(graph, _allowlist_file(tmp_path))
    fired = {v.constraint.cid: v.witnesses
             for v in kgrepair.validate(filtered, _constraints()).failing()}
    assert fired["mus.req.gallery"] == {"ex:vase1", "ex:vase2",
                                        "http://example.org/collection/amphora1"}


def test_no_core_module_hardcodes_wikidata_predicates():
    """Static gate: the graph model, the validator, and both repair engines must
    not name a Wikidata predicate or prefix. Those belong in authored constraint
    files, which are data."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    targets = [
        os.path.join(root, "src", "kgrepair", "datagraph.py"),
        os.path.join(root, "src", "kgrepair", "validator.py"),
        os.path.join(root, "src", "kgrepair", "repair", "subset.py"),
        os.path.join(root, "src", "kgrepair", "repair", "superset.py"),
    ]
    marker = re.compile(r"P31|P279|wd:|wdt:")
    offenders = []
    for path in targets:
        for lineno, line in enumerate(open(path, encoding="utf-8"), 1):
            if marker.search(line):
                offenders.append(f"{os.path.relpath(path, root)}:{lineno}: {line.strip()}")
    assert offenders == [], offenders
