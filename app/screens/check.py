"""
V2 -- Check screen: consistency run, violations grouped by constraint, per-witness
neighbourhood, and the report-first prevalence header.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import streamlit as st

from app import manifests as mf
from app import state as st_state
from app import viz
from app.caps import SUBSET_CAP_DEFAULT
from kgrepair import (DEFAULT_K, DEFAULT_NODE_CAP, check_cap, extract_neighbourhood,
                      validate)


def _consistency_of(session) -> dict:
    """Uncached path for an uploaded graph: the fixture cache key (manifest hash +
    constraint label) does not identify an upload, so it is not reused here."""
    return _rows_from(session.graph, session.constraints)


def _rows_from(graph, cs) -> dict:
    """The screen's display payload, built from the public validate + cap calls."""
    report = validate(graph, cs, use_closure=True)
    # The same verdict the Repair screen, the command line and the bench scripts
    # get, rather than a second measurement that could disagree with them.
    decision = check_cap(graph, cs, "subset")
    rows = []
    for v in report.violations:
        c = v.constraint
        rows.append({
            "cid": c.cid, "kind": c.kind, "tier": c.tier, "direction": c.direction,
            "provenance": c.provenance,
            "containment": f"{c.antecedent}  ⊑  {c.consequent}",
            "count": v.count, "witnesses": sorted(v.witnesses),
        })
    return {
        "rows": rows,
        "consistent": report.consistent,
        "total_witnesses": report.total_witnesses(),
        "by_tier": report.by_tier(),
        "subset_witness_fraction": decision.fraction,
        "subset_witness_count": decision.witness_count,
        "subset_cap_aborted": decision.aborted,
    }


@st.cache_data(show_spinner="Running consistency check...")
def _run_consistency(nt_path: str, content_hash: str, cs_label: str) -> dict:
    """Cached on (manifest hash, constraint-set label) -- that pair fully
    determines the ConstraintSet (`matching_constraint_sets` is a pure function
    of the manifest entry), so screen switches never re-validate. Returns plain
    dicts (picklable), not the ValidationReport object itself, so this can
    safely be `cache_data` rather than `cache_resource`."""
    graph = mf.load_graph_cached(nt_path, content_hash)
    entries = mf.discover_manifests()
    entry = next(e for e in entries if e.nt_path == nt_path)
    cs = mf.matching_constraint_sets(entry)[cs_label]
    return _rows_from(graph, cs)


def _render_prevalence_header(result: dict, num_nodes: int) -> None:
    frac = result["subset_witness_fraction"]
    st.subheader("Prevalence (report-first)", help=(
        "Measured and shown before any repair is run. This is the deliberate "
        "report-first discipline used for every real-corpus run: prevalence is a "
        "finding on its own, not just a precheck."))
    cols = st.columns(3)
    cols[0].metric("ptime_core/subset witnesses", result["subset_witness_count"], help=(
        "Count of nodes in phi \\ psi across every ptime_core constraint with "
        "direction=\"subset\" -- the nodes SubsetRepair would delete. A node flagged "
        "by two rules counts once (one deletion clears it from both)."))
    cols[1].metric("witness % of |V|", f"{frac:.1%}", help=(
        "Witness count divided by total node count -- the fraction of the graph "
        "SubsetRepair would remove. Compared directly against the subset-repair "
        "cap."))
    cols[2].metric("subset-repair cap", f"{SUBSET_CAP_DEFAULT:.0%}", help=(
        "The deletion-fraction ceiling. If the witness fraction exceeds this, a "
        "subset repair is reported as ABORTED-BY-CAP rather than silently deleting "
        "a large slice of the graph."))
    if result["subset_cap_aborted"]:
        st.warning(
            f"Witness fraction ({frac:.1%}) exceeds the {SUBSET_CAP_DEFAULT:.0%} "
            "deletion-fraction cap -- a subset (deletion) repair on this slice would "
            "be reported as **ABORTED-BY-CAP**, not silently run. Superset (addition) "
            "repair uses its own 30% addition-fraction cap, checked on its own screen.")
    else:
        st.caption(f"Under the {SUBSET_CAP_DEFAULT:.0%} cap -- a subset repair would proceed.")


def render() -> None:
    st.header("Check")
    session = st_state.session()
    if session is None:
        st.info("Load a graph and a constraint set on the Load screen first.")
        return
    entry, cs = session.entry, session.constraints

    if session.is_upload:
        result = _consistency_of(session)
    else:
        result = _run_consistency(entry.nt_path, entry.content_hash or "",
                                  st.session_state["constraint_label"])
    st.session_state["consistency_report"] = result
    st.session_state["consistency_meta"] = {
        "manifest_key": entry.key if entry is not None else session.graph_name,
        "constraint_label": session.constraints_source}

    if result["consistent"]:
        st.success("Consistent: no violations under this constraint set.")
        return

    st.warning(f"INCONSISTENT: {len(result['rows'])} constraint(s) checked, "
              f"{result['total_witnesses']} total witness(es) "
              f"({result['by_tier']['ptime_core']} ptime_core, "
              f"{result['by_tier']['boundary']} boundary).")

    graph = session.graph
    _render_prevalence_header(result, graph.stats()["nodes"])

    st.subheader("Violations")
    for row in result["rows"]:
        if row["count"] == 0:
            continue
        badge = "report-only" if row["tier"] == "boundary" else row["direction"]
        with st.expander(f"[{row['tier']}/{badge}] {row['cid']} ({row['kind']}) "
                         f"-- {row['count']} witness(es)"):
            st.code(row["containment"], language=None)
            st.caption(f"provenance: {row['provenance']}", help=(
                "How this rule was obtained. given = stated directly by the source "
                "KG (e.g. Wikidata P2302); compiled = mechanically translated from a "
                "given statement (e.g. rdfs domain/range); derived = induced from "
                "data by measuring prevalence on a clean reference slice."))
            if row["tier"] == "boundary":
                st.caption("boundary constraint: validated and reported only, never auto-repaired.")
            k = st.slider("neighbourhood hops (k)", 0, 3, DEFAULT_K,
                         key=f"k_{row['cid']}", help=(
                             "How many edge-hops out from the witness node to walk, "
                             "in both directions. 0 = just the witness itself."))
            node_cap = st.slider("node cap", 10, DEFAULT_NODE_CAP, DEFAULT_NODE_CAP,
                                 key=f"cap_{row['cid']}", help=(
                                     "Hard ceiling on how many nodes the "
                                     "neighbourhood walk may visit, regardless of k. "
                                     "Protects against a dense hub node blowing up "
                                     "the rendered graph; hitting it truncates the "
                                     "view."))
            witness = st.selectbox("witness node", options=row["witnesses"],
                                   key=f"witness_{row['cid']}", help=(
                                       "Pick one witness from this constraint's "
                                       "violation set to inspect. Its neighbourhood "
                                       "is rendered below so you can see the local "
                                       "structure that makes it a violation."))
            if witness:
                view = extract_neighbourhood(graph, witness, k=k, node_cap=node_cap)
                if view.truncated:
                    st.caption(f"neighbourhood truncated at node_cap={node_cap}")
                viz.render_legend(st)
                st.pyplot(viz.render_neighbourhood(view), width="content")
