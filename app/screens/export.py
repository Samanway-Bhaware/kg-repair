"""
V4 -- Export screen: downloads (repaired N-Triples, result JSON, run JSONL
record) plus a retraceability block tying every download back to exactly which
manifest/constraint-set/mode/code produced it.
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import streamlit as st

from app import logic
from app import state as st_state
from kgrepair import code_revision, to_ntriples


def _constraint_set_version(cs) -> int:
    versions = {c.version for c in cs}
    return max(versions) if versions else 1


def _render_retraceability(session, cs, result) -> None:
    st.subheader("Retraceability")
    entry = session.entry
    if entry is None:
        rows = [
            {"field": "input", "value": session.graph_name},
            {"field": "source", "value": "uploaded by you"},
            {"field": "type predicates",
             "value": ", ".join(sorted(session.type_predicates))},
            {"field": "allow-list applied", "value": str(session.allowlist_applied)},
        ]
    else:
        rows = [
            {"field": "manifest name", "value": entry.name},
            {"field": "namespace", "value": entry.namespace},
            {"field": "content hash", "value": entry.content_hash or "?"},
        ]
        if entry.namespace == "real":
            rows.append({"field": "cache generation",
                         "value": entry.cache_generation_hash or "?"})
        else:
            rows.append({"field": "seed", "value": entry.seed})
            rows.append({"field": "profile hash", "value": entry.profile_hash or "?"})
    rows.append({"field": "constraint set", "value": f"{cs.name} (v{_constraint_set_version(cs)})"})
    rows.append({"field": "code_revision", "value": code_revision()})
    if result is not None:
        rows.append({"field": "run_id", "value": result["run_id"]})
        rows.append({"field": "mode", "value": result.get("engine", "?")})
        params = result.get("record", {}).get("slice", {}).get("params", {})
        rows.append({"field": "mode params", "value": json.dumps(params)})
        rows.append({"field": "run timestamp", "value": result.get("record", {}).get("timestamp", "?")})
        rows.append({"field": "run status", "value": result["status"]})
    st.dataframe(rows, width="stretch", hide_index=True)


def render() -> None:
    st.header("Export")
    session = st_state.session()
    if session is None:
        st.info("Load a graph and a constraint set on the Load screen first.")
        return
    cs = session.constraints
    name = os.path.splitext(session.graph_name)[0]

    result = st.session_state.get("repair_result")
    meta = st.session_state.get("repair_meta")
    from app.screens.repair import _session_key
    for_this_input = (result is not None and meta is not None
                      and meta["manifest_key"] == _session_key(session))
    has_repair = for_this_input and "result" in result

    _render_retraceability(session, cs, result if for_this_input else None)

    st.subheader("Downloads")
    if not has_repair:
        st.info(
            "No repair result for this manifest yet -- run a repair on the Repair "
            "screen first to unlock the repaired-graph and result-JSON downloads. "
            "The original (unrepaired) graph can still be exported below.")
        st.download_button(
            "Download original graph (N-Triples)", data=to_ntriples(session.graph),
            file_name=f"{name}.nt", mime="text/plain")
        return

    res = result["result"]
    nt_text = to_ntriples(res.graph)
    json_text = res.to_json()
    record_text = json.dumps(result["record"], indent=2) if result.get("record") else "{}"

    cols = st.columns(3)
    cols[0].download_button(
        "Repaired graph (N-Triples)", data=nt_text,
        file_name=f"{name}.{result['engine']}_repaired.nt", mime="text/plain")
    cols[1].download_button(
        "Result JSON", data=json_text,
        file_name=f"{name}.{result['engine']}_result.json", mime="application/json")
    cols[2].download_button(
        "Run JSONL record", data=record_text,
        file_name=f"{name}.{result['engine']}_run.json", mime="application/json")

    n_isolated = logic.isolated_node_count(res.graph)
    if n_isolated:
        st.caption(
            f"{n_isolated} of {len(res.graph.nodes)} node(s) carry no incident edge "
            "and are not representable in N-Triples, so they are omitted from the "
            "downloaded graph. This never affects validation (every constraint in "
            "this project's fragment requires at least one edge), but the reloaded "
            "node count will be lower than `graph.stats()['nodes']`.")

    st.caption(
        "`Result JSON` is exactly `SubsetRepairResult.to_json()` / "
        "`SupersetRepairResult.to_json()` -- the same schema any future CLI would "
        "emit for this run, not a viewer-specific format.")
