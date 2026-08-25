"""
V0 -- NeighbourhoodView extraction tests (viewer support, no Streamlit involved).

Covers: hard node_cap enforcement + determinism on repeat; diff-tag correctness
against a fixture ChangeRecord for BOTH engines (a deletion case and an
addition-with-fresh-symbol case); and the repair-engine/viewer import-direction
boundary (repair/subset.py, repair/superset.py must never import this module).
"""
import ast as pyast
import os

from kgrepair.constraints.model import Constraint, ConstraintSet
from kgrepair.datagraph import DataGraph
from kgrepair.neighbourhood import extract_neighbourhood, change_record_center
from kgrepair.repair import subset_repair, superset_repair


SRC = os.path.join(os.path.dirname(__file__), "..", "src", "kgrepair")

 
# cap enforcement + determinism
 

def _star_graph(n: int) -> DataGraph:
    """A hub node connected to n spokes by one label -- a 1-hop neighbourhood
    bigger than any reasonable node_cap."""
    g = DataGraph()
    for i in range(n):
        g.add_edge("hub", "rel", f"spoke{i:03d}")
    return g


def test_node_cap_hard_enforced():
    g = _star_graph(300)
    view = extract_neighbourhood(g, "hub", k=2, node_cap=10)
    assert len(view.nodes) <= 10
    assert view.truncated is True


def test_extraction_is_deterministic_on_repeat():
    g = _star_graph(300)
    v1 = extract_neighbourhood(g, "hub", k=2, node_cap=25)
    v2 = extract_neighbourhood(g, "hub", k=2, node_cap=25)
    assert [n.id for n in v1.nodes] == [n.id for n in v2.nodes]
    assert [(e.src, e.label, e.dst) for e in v1.edges] == \
           [(e.src, e.label, e.dst) for e in v2.edges]


def test_whole_small_graph_returned_when_under_cap():
    g = DataGraph()
    g.add_edge("a", "rel", "b")
    g.add_edge("b", "rel", "c")
    view = extract_neighbourhood(g, "a", k=2, node_cap=150)
    assert view.node_ids() == {"a", "b", "c"}
    assert view.truncated is False


def test_unknown_center_raises_keyerror():
    g = DataGraph()
    g.add_edge("a", "rel", "b")
    try:
        extract_neighbourhood(g, "nope")
        assert False, "expected KeyError"
    except KeyError:
        pass


 
# diff tagging -- subset (deletion) case
 

def _dom_range_cs(cid, kind, antecedent, consequent, direction="subset"):
    return ConstraintSet("t", [Constraint(
        cid=cid, domain="d", kg="wd", kind=kind, tier="ptime_core",
        provenance="c", direction=direction,
        antecedent=antecedent, consequent=consequent)])


def test_deletion_diff_tags_against_pre_repair_graph():
    # x has a country edge to y but no type -> dom.country witness under subset repair
    cs = _dom_range_cs(
        "dom", "existential_domain",
        "< down(wdt:P17) >",
        '< down(wdt:P31) . down(wdt:P279)* . [val("wd:Q6256")] >',
    )
    g = DataGraph()
    g.set_value("wd:Q6256", "wd:Q6256")
    g.add_edge("x", "wdt:P17", "y")
    g.add_edge("neighbour", "rel", "x")   # an unrelated incident edge, stays unchanged

    res = subset_repair(g, cs)
    assert "x" in res.deleted_nodes

    # Extract from the PRE-repair graph `g` (subset repair only deletes, so the
    # deleted node/edges are still present there to tag).
    view = extract_neighbourhood(g, "x", k=1, changelog=res.changelog)
    by_id = {n.id: n for n in view.nodes}
    assert by_id["x"].status == "deleted"
    edge_status = {(e.src, e.label, e.dst): e.status for e in view.edges}
    assert edge_status[("x", "wdt:P17", "y")] == "deleted"
    assert edge_status[("neighbour", "rel", "x")] == "deleted"  # cascaded removal


 
# diff tagging -- superset (addition, with a fresh symbol) case
 

def test_addition_diff_tags_include_fresh_symbol_node():
    # requires-statement: x must have SOME wdt:P169 edge; none exists -> fresh target.
    cs = _dom_range_cs(
        "req", "requires_statement",
        '< down(wdt:P17) >',
        "< down(wdt:P169) >",
        direction="superset",
    )
    g = DataGraph()
    g.add_edge("x", "wdt:P17", "y")

    res = superset_repair(g, cs)
    fresh_targets = [e for e in res.added_edges if e[1] == "wdt:P169"]
    assert fresh_targets, "expected a fresh existential target to be added"
    _, _, fresh_node = fresh_targets[0]
    assert fresh_node.startswith("fresh:req:")
    assert fresh_node in res.added_nodes, (
        "fresh-symbol targets must now get an explicit add_node record, "
        "so the change log actually names every node it creates")

    # Extract from the POST-repair graph (superset only adds, so additions are
    # present there); center on the ChangeRecord's own witness helper.
    fresh_rec = next(r for r in res.changelog if r.op == "add_edge" and r.dst == fresh_node)
    center = change_record_center(fresh_rec)
    assert center == "x"

    view = extract_neighbourhood(res.graph, center, k=1, changelog=res.changelog)
    by_id = {n.id: n for n in view.nodes}
    assert by_id[fresh_node].status == "added"
    assert by_id[fresh_node].fresh is True
    assert by_id["x"].status == "unchanged"
    edge_status = {(e.src, e.label, e.dst): e.status for e in view.edges}
    assert edge_status[("x", "wdt:P169", fresh_node)] == "added"


 
# import-direction boundary
 

def test_repair_engines_never_import_neighbourhood():
    for fname in ("subset.py", "superset.py"):
        path = os.path.join(SRC, "repair", fname)
        with open(path, "r", encoding="utf-8") as fh:
            tree = pyast.parse(fh.read(), filename=path)
        for node in pyast.walk(tree):
            if isinstance(node, pyast.ImportFrom):
                mod = node.module or ""
                assert "neighbourhood" not in mod, f"{fname} imports {mod!r}"
            elif isinstance(node, pyast.Import):
                for alias in node.names:
                    assert "neighbourhood" not in alias.name, f"{fname} imports {alias.name!r}"
