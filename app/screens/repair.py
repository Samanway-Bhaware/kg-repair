"""
V3 -- Repair screen: run SubsetRepair or SupersetRepair through the public API,
respecting the same report-first caps as the CLI/bench scripts, with a full
outcome panel (OK / ABORTED-BY-CAP), an ordered ChangeRecord table, per-record
before/after neighbourhood diffs, and a separate boundary (report-only) panel.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import streamlit as st

from app import logic
from app import state as st_state
from app import viz
from app.caps import SUBSET_CAP_DEFAULT, SUPERSET_CAP_DEFAULT
from kgrepair import (ABORTED_BY_CAP, DEFAULT_K, DEFAULT_NODE_CAP, RunContext,
                      change_record_center, constraints_meta, extract_neighbourhood,
                      slice_meta_from_graph, validate)

_ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
# Default: the real results/ directory, so interactive viewer runs genuinely
# join the shared D7 dataset (that's the point of tagging origin="viewer").
# `KGREPAIR_VIEWER_RESULTS_DIR` lets a demo/screenshot session (or anything
# else that must not pollute results/runs.jsonl -- see the D7 evaluation
# pipeline, which reads it) point elsewhere without editing this file; tests
# in tests/test_viewer_repair.py monkeypatch this module attribute directly.
RESULTS_DIR = os.environ.get("KGREPAIR_VIEWER_RESULTS_DIR", os.path.join(_ROOT, "results"))


def _slice_meta(session, graph, cap: float, decision, extra_key: str):
    """Run-record metadata for either input source.

    A committed fixture contributes its manifest identity; an uploaded graph has
    none, so it is recorded as origin "viewer-upload" with the file name only.
    """
    entry = session.entry
    params = {"origin": "viewer" if entry is not None else "viewer-upload",
              extra_key: cap, "witness_fraction": round(decision.fraction, 4)}
    if entry is not None:
        params["manifest"] = entry.name
        return slice_meta_from_graph(
            graph, source=entry.namespace, manifest_hash=entry.content_hash or "",
            seed=entry.seed, params=params)
    params["upload"] = session.graph_name
    return slice_meta_from_graph(graph, source="upload", manifest_hash="",
                                 seed=None, params=params)


def _run_subset(session, *, strategy: str, cap: float, use_closure: bool) -> dict:
    cs, graph = session.constraints, session.graph
    decision = logic.cap_decision(session, "subset", cap)
    slice_meta = _slice_meta(session, graph, cap, decision, "deletion_cap")
    mode = f"subset_{strategy}"
    res = before = after = None
    run = None
    with RunContext(RESULTS_DIR, slice=slice_meta, constraints=constraints_meta(cs),
                    mode=mode, config={"cap": cap, "use_closure": use_closure}) as ctx:
        if decision.aborted:
            ctx.status = ABORTED_BY_CAP
            run = logic.run_repair(session, "subset", cap=cap, strategy=strategy)
        else:
            before = validate(graph, cs, use_closure=True)
            run = logic.run_repair(session, "subset", cap=cap, strategy=strategy,
                                   phase=ctx.phase)
            res = run.result
            with ctx.phase("consistency_final"):
                after = validate(res.graph, cs, use_closure=True)
            ctx.set_repair_result(res, before, after)
    # ctx.record is only populated once __exit__ runs, i.e. after this `with`
    # block closes -- read it here, not from inside the block.
    out = {"status": ctx.status, "engine": "subset", "strategy": strategy, "cap": cap,
          "witness_fraction": decision.fraction, "witness_count": decision.witness_count,
          "num_nodes": decision.denominator, "payload": run.payload,
          "run_id": ctx.run_id, "record": ctx.record}
    if res is not None:
        out.update(result=res, pre_graph=graph, before=before, after=after)
    return out


def _run_superset(session, *, prune: bool, cap: float, use_closure: bool) -> dict:
    cs, graph = session.constraints, session.graph
    decision = logic.cap_decision(session, "superset", cap)
    slice_meta = _slice_meta(session, graph, cap, decision, "addition_cap")
    res = before = after = None
    run = None
    with RunContext(RESULTS_DIR, slice=slice_meta, constraints=constraints_meta(cs),
                    mode="superset", config={"cap": cap, "prune": prune,
                                             "use_closure": use_closure}) as ctx:
        if decision.aborted:
            ctx.status = ABORTED_BY_CAP
            run = logic.run_repair(session, "superset", cap=cap, prune=prune)
        else:
            before = validate(graph, cs, use_closure=True)
            run = logic.run_repair(session, "superset", cap=cap, prune=prune,
                                   phase=ctx.phase)
            res = run.result
            with ctx.phase("consistency_final"):
                after = validate(res.graph, cs, use_closure=True)
            ctx.set_superset_result(res, before, after)
    out = {"status": ctx.status, "engine": "superset", "prune": prune, "cap": cap,
          "witness_fraction": decision.fraction, "witness_count": decision.witness_count,
          "num_edges": decision.denominator, "payload": run.payload,
          "run_id": ctx.run_id, "record": ctx.record}
    if res is not None:
        out.update(result=res, pre_graph=graph, before=before, after=after)
    return out


def _session_key(session) -> str:
    """Identity of the loaded input, for invalidating a stale repair result."""
    return session.entry.key if session.entry is not None else f"upload:{session.graph_name}"


def _render_aborted(result: dict) -> None:
    engine = result["engine"]
    st.error(f"{ABORTED_BY_CAP} -- {engine} repair was NOT run.")
    cols = st.columns(3)
    if engine == "subset":
        cols[0].metric("witnesses", result["witness_count"])
        cols[1].metric("witness % of |V|", f"{result['witness_fraction']:.1%}")
        cols[2].metric("deletion-fraction cap", f"{result['cap']:.0%}")
    else:
        cols[0].metric("planned additions", result["witness_count"])
        cols[1].metric("additions % of |E|", f"{result['witness_fraction']:.1%}")
        cols[2].metric("addition-fraction cap", f"{result['cap']:.0%}")
    st.info(
        "This mirrors the report-first discipline used for the real P4/D6-T5 corpus "
        "runs: prevalence is measured and reported BEFORE the engine is ever invoked, "
        "so an over-cap slice is a first-class finding, not a silent failure.")


def _render_attestations(attestations: dict) -> None:
    cols = st.columns(len(attestations))
    for col, (name, ok) in zip(cols, attestations.items()):
        col.metric(name, "PASS" if ok else "FAIL", delta=None)
    if not all(attestations.values()):
        st.error("One or more invariants FAILED -- see attestations above.")


def _render_ok_subset(result: dict) -> None:
    res = result["result"]
    st.success(f"Repaired in {res.rounds} round(s) ({res.mode} strategy).")
    cols = st.columns(4)
    cols[0].metric("nodes deleted", len(res.deleted_nodes))
    cols[1].metric("rounds", res.rounds)
    cols[2].metric("recheck_count", res.recheck_count)
    cols[3].metric("violations before -> after",
                   f"{result['before'].total_witnesses()} -> {result['after'].total_witnesses()}")
    _render_attestations(res.attestations)


def _render_ok_superset(result: dict) -> None:
    res = result["result"]
    st.success(f"Repaired in {res.rounds} round(s) (prune={result['prune']}).")
    cols = st.columns(4)
    cols[0].metric("nodes added", len(res.added_nodes))
    cols[1].metric("edges added", len(res.added_edges))
    cols[2].metric("rounds", res.rounds)
    cols[3].metric("violations before -> after",
                   f"{result['before'].total_witnesses()} -> {result['after'].total_witnesses()}")
    _render_attestations(res.attestations)

    st.markdown("**Additions by kind / by constraint**")
    kcols = st.columns(2)
    kcols[0].dataframe([{"kind": k, "count": v} for k, v in res.additions_by_kind.items()],
                       width="stretch", hide_index=True)
    kcols[1].dataframe([{"constraint": k, "count": v}
                       for k, v in res.additions_by_constraint.items() if v],
                       width="stretch", hide_index=True)
    if res.fresh_used:
        st.caption(f"fresh symbols used ({len(res.fresh_used)}): "
                  + ", ".join(f"`{f}`" for f in res.fresh_used))
    if result["prune"]:
        st.caption(f"redundancy pruning removed {res.pruned_edges} edge(s), "
                  f"{res.pruned_nodes} node(s).")


def _render_changelog_and_diffs(result: dict, entry, cs) -> None:
    res = result["result"]
    engine = result["engine"]
    st.subheader("Change log")
    if not res.changelog:
        st.caption("(empty -- the slice was already consistent)")
        return
    rows = res.changelog_dicts()
    st.dataframe(rows, width="stretch", hide_index=True)

    if engine == "subset":
        st.caption("rows are ordered by round -- the set-at-a-time deletion cascade "
                  "(a round's deletions can create the NEXT round's witnesses).")
    else:
        st.caption("`provenance` is the value-pool origin of each addition: "
                  "graph (existing value) | named (constraint-named class/constant) | "
                  "fresh (a bounded fresh symbol).")

    st.subheader("Per-record before/after neighbourhood")
    # Options are the formatted labels themselves (see the Load screen's manifest
    # picker for why: AppTest's selectbox driver does not round-trip format_func).
    record_labels = [f"{i:04d} · round {r.round} · {r.op} · {r.constraint}"
                     for i, r in enumerate(res.changelog)]
    chosen = st.selectbox("change record", options=record_labels)
    rec = res.changelog[int(chosen.split(" ", 1)[0])]
    center = change_record_center(rec)
    k = st.slider("neighbourhood hops (k)", 0, 3, DEFAULT_K, key="repair_k")
    node_cap = st.slider("node cap", 10, DEFAULT_NODE_CAP, DEFAULT_NODE_CAP, key="repair_cap")

    # Subset only deletes -> the pre-repair graph still has the deleted stuff.
    # Superset only adds -> the post-repair graph has the added stuff. Either way
    # this is the ONE extraction the neighbourhood.py module docstring calls for.
    ref_graph = result["pre_graph"] if engine == "subset" else res.graph
    if center not in ref_graph.nodes:
        st.warning(f"center node {center!r} not present in the reference graph "
                  "for this record (unexpected) -- cannot render a neighbourhood.")
        return
    view = extract_neighbourhood(ref_graph, center, k=k, node_cap=node_cap,
                                 changelog=res.changelog)
    if view.truncated:
        st.caption(f"neighbourhood truncated at node_cap={node_cap}")
    viz.render_legend(st)
    before_col, after_col = st.columns(2)
    with before_col:
        st.markdown("**before** (additions hidden)")
        st.pyplot(viz.render_neighbourhood(view, hide_added=True), width="content")
    with after_col:
        st.markdown("**after** (deletions greyed/dashed)")
        st.pyplot(viz.render_neighbourhood(view, grey_deleted=True), width="content")


def _render_boundary_panel(result: dict, cs) -> None:
    res = result["result"]
    boundary = [c for c in cs if c.tier == "boundary"]
    if not boundary:
        return
    report = validate(res.graph, boundary, use_closure=True)
    failing = report.failing()
    st.subheader("Boundary findings (report-only, never repaired)")
    if not failing:
        st.caption("No boundary violations on the repaired graph.")
        return
    st.dataframe(
        [{"cid": v.constraint.cid, "kind": v.constraint.kind, "count": v.count,
          "status": "report-only"} for v in failing],
        width="stretch", hide_index=True,
    )


def render() -> None:
    st.header("Repair")
    session = st_state.session()
    if session is None:
        st.info("Load a graph and a constraint set on the Load screen first.")
        return
    entry, cs = session.entry, session.constraints

    engine = st.radio("Engine", ["SubsetRepair (deletion)", "SupersetRepair (addition)"],
                      horizontal=True, help=(
                          "SubsetRepair (Algorithm 1) fixes violations by deleting "
                          "the witness node -- never touches data values, only "
                          "removes nodes/edges. SupersetRepair (Algorithm 2) fixes "
                          "violations by adding the missing structure (a type edge, "
                          "a required statement) from a bounded value pool -- never "
                          "deletes anything."))
    # use_closure and strategy controls are hidden for now; fixed at their defaults.
    use_closure = True
    strategy = "full"

    if engine.startswith("Subset"):
        cap = st.number_input("deletion-fraction cap", min_value=0.0, max_value=1.0,
                              value=SUBSET_CAP_DEFAULT, step=0.01, format="%.2f", help=(
                                  "The witness-fraction ceiling checked before this "
                                  "run (see the Check screen's prevalence header). "
                                  "If the measured witness fraction exceeds this "
                                  "value, the engine is not invoked and the run is "
                                  "reported as ABORTED-BY-CAP."))
    else:
        # prune control is hidden for now; fixed at its default.
        prune = True
        cap = st.number_input("addition-fraction cap", min_value=0.0, max_value=1.0,
                              value=SUPERSET_CAP_DEFAULT, step=0.01, format="%.2f")

    if st.button("Run repair"):
        if engine.startswith("Subset"):
            result = _run_subset(session, strategy=strategy, cap=cap,
                                 use_closure=use_closure)
        else:
            result = _run_superset(session, prune=prune, cap=cap,
                                   use_closure=use_closure)
        st.session_state["repair_result"] = result
        st.session_state["repair_meta"] = {"manifest_key": _session_key(session),
                                           "constraint_label": session.constraints_source}

    result = st.session_state.get("repair_result")
    meta = st.session_state.get("repair_meta")
    if result is None or meta is None or meta["manifest_key"] != _session_key(session):
        return

    st.divider()
    st.caption(f"run_id: `{result['run_id']}`")
    if result["status"] == ABORTED_BY_CAP:
        _render_aborted(result)
        return

    if result["engine"] == "subset":
        _render_ok_subset(result)
    else:
        _render_ok_superset(result)

    _render_changelog_and_diffs(result, entry, cs)
    _render_boundary_panel(result, cs)
