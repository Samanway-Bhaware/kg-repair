"""V1 -- Load screen: manifest + constraint-set selection, slice stats."""
from __future__ import annotations

import os
import sys
from typing import List

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

import streamlit as st

from app import logic
from app import manifests as mf
from app import state as st_state


def _format_manifest(entry: mf.ManifestEntry) -> str:
    return f"[{entry.namespace}] {entry.name}"


def _render_real_badges(entry: mf.ManifestEntry) -> None:
    cols = st.columns(4)
    cols[0].metric("source", entry.source or "?")
    cols[1].metric("domain", entry.domain or "?")
    cols[2].metric("rung (target edges)", entry.target_edges or 0)
    cols[3].metric("cache generation", (entry.cache_generation_hash or "?")[:10])
    ts = mf.retrieval_timestamp_range(entry)
    if ts:
        earliest, latest = ts
        if earliest == latest:
            st.caption(f"retrieved: {earliest}")
        else:
            st.caption(f"retrieved: {earliest} .. {latest}")
    else:
        st.caption("retrieval timestamp: not resolvable offline (raw cache not present locally)")


def _render_synthetic_badges(entry: mf.ManifestEntry) -> None:
    cols = st.columns(3)
    cols[0].metric("seed", entry.seed if entry.seed is not None else "?")
    cols[1].metric("profile hash", (entry.profile_hash or "?")[:10])
    cols[2].metric("target edges", entry.target_edges or 0)


def _render_stats_panel(entry: mf.ManifestEntry, graph) -> None:
    st.subheader("Slice stats", help=(
        "|V| (nodes), |E| (edges), labels, and data values as loaded from the .nt "
        "file -- compared live against the numbers recorded in the manifest. A "
        "mismatch means the fixture on disk has drifted from its manifest."))
    manifest_stats = entry.stats
    graph_stats = graph.stats()
    cols = st.columns(4)
    labels = [("|V|", "V", "nodes"), ("|E|", "E", "edges"),
              ("labels", "labels", "labels"), ("data values", "data_values", "valued_nodes")]
    mismatch = False
    for col, (title, mkey, gkey) in zip(cols, labels):
        mval, gval = manifest_stats.get(mkey, 0), graph_stats.get(gkey, 0)
        col.metric(title, gval)
        if mval != gval:
            mismatch = True
    if mismatch:
        st.warning(
            "Loaded graph stats do not match the manifest's recorded stats -- the "
            "fixture on disk may have drifted from its manifest.")
    else:
        st.caption("Loaded graph stats match the manifest exactly.")


def _render_constraint_list(cs) -> None:
    core = [c for c in cs if c.tier == "ptime_core"]
    boundary = [c for c in cs if c.tier == "boundary"]

    st.markdown(f"**ptime_core** ({len(core)}) -- auto-repairable")
    if core:
        st.dataframe(
            [{"cid": c.cid, "kind": c.kind, "direction": c.direction,
              "provenance": c.provenance, "version": c.version} for c in core],
            width="stretch", hide_index=True,
        )
    else:
        st.caption("(none)")

    st.markdown(f"**boundary** ({len(boundary)}) -- report-only, never auto-repaired")
    if boundary:
        st.dataframe(
            [{"cid": c.cid, "kind": c.kind, "provenance": c.provenance,
              "status": "report-only"} for c in boundary],
            width="stretch", hide_index=True,
        )
    else:
        st.caption("(none)")


def _type_predicate_box(key: str):
    """The custom typing-spine control, the viewer's `--type-predicate`.

    Empty means the loader's default vocabulary, which covers rdf:type,
    rdfs:subClassOf and the Wikidata spine. Naming your own labels here is what
    lets a graph with, say, an `ex:isa` spine be class-tested at all.
    """
    text = st.text_area(
        "Type predicates (one per line, or comma separated)", value="", key=key,
        help=(
            "The edge labels that type a node in YOUR graph, for example ex:isa and "
            "ex:subclassOf. Their objects are treated as class nodes so a class test "
            "can reach them. Leave empty to use the default vocabulary "
            "(rdf:type, rdfs:subClassOf, schema:subClassOf, wdt:P31, wdt:P279)."))
    chosen = logic.parse_type_predicates(text)
    effective = logic.effective_type_predicates(chosen)
    st.caption("in effect: " + ", ".join(f"`{p}`" for p in sorted(effective)))
    return chosen


def _allowlist_box(key: str):
    """Optional predicate filter. Off unless the user uploads a file."""
    return st.file_uploader(
        "Predicate allow-list (optional, JSON)", type=["json"], key=key,
        help=(
            "Opt in. Drops every edge whose predicate is not named in this file of "
            "yours, before checking or repairing. It filters on predicate names you "
            "chose and does nothing else. Leave empty and no filtering happens."))


def _render_upload_source() -> None:
    """Bring your own graph and your own rules."""
    st.caption(
        "Load any N-Triples graph and check or repair it against constraints you "
        "wrote. Nothing here is tied to the project's own fixtures or to Wikidata.")

    graph_file = st.file_uploader("Graph (N-Triples)", type=["nt", "txt"],
                                  key="upload_graph")

    kind = st.radio("Constraints", ["Upload a constraint file", "Use a built-in set"],
                    horizontal=True, key="upload_cs_kind",
                    help=("Your own constraint file names your own predicates. The "
                          "built-in sets target the project's Wikidata/DBpedia/YAGO "
                          "slices and will not match a different vocabulary."))
    cs_file = builtin_choice = None
    if kind == "Upload a constraint file":
        cs_file = st.file_uploader("Constraint file (JSON)", type=["json"],
                                   key="upload_cs")
    else:
        builtin_choice = st.selectbox("Built-in constraint set",
                                      options=list(logic.builtin_constraint_choices()),
                                      key="upload_builtin")

    chosen_types = _type_predicate_box("upload_types")
    allowlist_file = _allowlist_box("upload_allowlist")

    if graph_file is None:
        st.info("Upload an N-Triples graph to begin.")
        return
    if kind == "Upload a constraint file" and cs_file is None:
        st.info("Upload a constraint file, or switch to a built-in set.")
        return

    try:
        graph = logic.load_graph_from_text(
            graph_file.getvalue().decode("utf-8"), graph_file.name,
            type_predicates=chosen_types)
        if cs_file is not None:
            cs = logic.load_constraints_from_text(
                cs_file.getvalue().decode("utf-8"), cs_file.name)
            cs_source = cs_file.name
        else:
            domain, kg, version = logic.builtin_constraint_choices()[builtin_choice]
            cs = logic.load_builtin_constraints(domain, kg, version)
            cs_source = f"{domain}/{kg}/v{version}"

        applied, dropped = False, 0
        if allowlist_file is not None:
            graph, dropped = logic.apply_user_allowlist(
                graph, allowlist_file.getvalue().decode("utf-8"), allowlist_file.name)
            applied = True
    except logic.ViewerError as exc:
        st.error(str(exc))
        return
    except UnicodeDecodeError:
        st.error("Uploaded file is not UTF-8 text.")
        return

    session = logic.Session(
        graph=graph, constraints=cs, graph_name=graph_file.name,
        constraints_source=cs_source,
        type_predicates=logic.effective_type_predicates(chosen_types),
        allowlist_applied=applied, allowlist_edges_dropped=dropped)
    st_state.set_session(session)

    st.success(f"Loaded `{graph_file.name}` against `{cs_source}`.")
    if applied:
        st.caption(f"allow-list applied: {dropped} edge(s) dropped.")
    stats = session.stats()
    cols = st.columns(4)
    for col, (title, key) in zip(cols, [("|V|", "nodes"), ("|E|", "edges"),
                                        ("labels", "labels"),
                                        ("data values", "valued_nodes")]):
        col.metric(title, stats.get(key, 0))
    if not stats.get("edges"):
        st.warning("The loaded graph has no edges, so no constraint can be violated. "
                   "Check that the file really is N-Triples.")

    with st.expander("Constraints in this set", expanded=False):
        _render_constraint_list(cs)


def render() -> None:
    st.header("Load")
    # The scope statement goes above the upload control, not below it: someone
    # about to upload a file should meet it before they choose one. This line
    # states scope and deliberately makes no claim of its own about what an
    # uploaded file may contain.
    st.caption(
        "This viewer runs locally on this machine only. Anything you upload stays "
        "in this session, never enters the committed corpus or the slice manifest, "
        "and is not filtered by the project's Level-0 allow-lists: what an uploaded "
        "file contains, and the responsibility for it, is yours.")
    source = st.radio("Input source", ["Project fixture", "Upload your own"],
                      horizontal=True, key="input_source",
                      help=("Project fixture browses the committed slices under "
                            "fixtures/. Upload your own takes any N-Triples graph "
                            "and any constraint file you wrote."))
    if source == "Upload your own":
        _render_upload_source()
        return

    entries: List[mf.ManifestEntry] = mf.discover_manifests()
    if not entries:
        st.error("No manifests found under fixtures/real/ or fixtures/synthetic/.")
        return

    # Options are the formatted labels themselves (not a raw key + format_func):
    # keeps the widget's on-the-wire value and its display text identical, which
    # is both simpler and plays well with AppTest-driven selection.
    by_label = {_format_manifest(e): e for e in entries}
    manifest_labels = list(by_label.keys())
    prev_label = next((lbl for lbl, e in by_label.items()
                       if e.key == st.session_state["manifest_key"]), None)
    default_index = manifest_labels.index(prev_label) if prev_label in manifest_labels else 0

    chosen_label_m = st.selectbox("Slice (manifest)", options=manifest_labels, index=default_index,
        help=(
            "Which knowledge-graph slice to load. [real] entries are Wikidata/DBpedia/"
            "YAGO extracts under fixtures/real/; [synthetic] entries are generated "
            "slices with injected ground-truth violations under fixtures/synthetic/. "
            "Changing this resets every downstream screen."))
    entry = by_label[chosen_label_m]
    if entry.key != st.session_state["manifest_key"]:
        st.session_state["manifest_key"] = entry.key
        st.session_state["constraint_label"] = None
        st_state.reset_downstream_of_load()

    st.caption(f"namespace: **{entry.namespace}**  ·  name: `{entry.name}`  ·  "
              f"content hash: `{(entry.content_hash or '?')[:16]}`")
    if entry.namespace == "real":
        _render_real_badges(entry)
    else:
        _render_synthetic_badges(entry)

    choices = mf.matching_constraint_sets(entry)
    if not choices:
        st.error(f"No constraint set is available for domain={entry.domain!r}, "
                f"source={entry.source!r}. This slice cannot be checked or repaired.")
        return
    labels = list(choices.keys())
    default_c_index = labels.index(st.session_state["constraint_label"]) \
        if st.session_state["constraint_label"] in labels else 0
    chosen_label = st.selectbox("Constraint set", options=labels, index=default_c_index,
        help=(
            "The constraint set to validate/repair against, matched to this slice's "
            "domain and source KG. (v1)/(v2) marks the constraint-definition version "
            "-- v2 is the RC1/RC2 fix for anatomy/disease/medication; v1 stays "
            "available unchanged for comparison."))
    if chosen_label != st.session_state["constraint_label"]:
        st.session_state["constraint_label"] = chosen_label
        st_state.reset_downstream_of_check()
    cs = choices[chosen_label]

    graph = mf.load_graph_cached(entry.nt_path, entry.content_hash or "")
    _render_stats_panel(entry, graph)
    st_state.set_session(mf.session_for(entry, cs, chosen_label))

    with st.expander("Constraints in this set", expanded=False):
        _render_constraint_list(cs)
