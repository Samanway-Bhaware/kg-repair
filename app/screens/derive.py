"""
P7b -- Derive screen: propose candidate constraints from the loaded graph.

Presentation only. Every decision is `app.logic.start_review`, which wraps the
public derivation entry point and hands back a review queue. This screen chooses
nothing about which candidates are good; it cannot, and that is the point of the
airlock.

Nothing derived here can repair anything until a person has decided every entry on
the Review screen and sealed the file.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

import streamlit as st

from app import logic
from app import state as st_state


def render() -> None:
    st.header("Derive")
    session = st_state.session()
    if session is None:
        st.info("Load a graph on the Load screen first.")
        return

    st.caption(
        "Propose constraints by profiling the loaded graph. Nothing proposed here "
        "can repair anything: every entry goes to the Review screen, where you "
        "decide each one and seal the file. There is no confidence at which a "
        "candidate skips that.")

    cols = st.columns(2)
    domain = cols[0].text_input(
        "Domain label", value="uploaded", key="derive_domain",
        help="Names the slice in the candidate file. Descriptive only.")
    kg = cols[1].text_input(
        "Knowledge-graph label", value="uploaded", key="derive_kg",
        help="Names the source in the candidate file. Descriptive only.")

    # The same two values `kgrepair derive --generator` takes, written out rather
    # than imported: the generator names live in `kgrepair.derive`, which is
    # internal, and this screen reaches the public API only.
    generator = st.radio(
        "Generator", options=("search", "shapes"), horizontal=True,
        key="derive_generator",
        help=("search walks a conjunction lattice and a head axis, and proposes "
              "broader readings of rules that nearly held. shapes is the earlier "
              "sweep of one template per repairable shape, which proposes far "
              "fewer rules and is the only one that flags cross-domain "
              "contamination. Whichever runs is recorded in the candidate file."))

    use_reference = st.checkbox(
        "Compare against the loaded graph as a reference", value=False,
        key="derive_stability",
        help=("Scores each candidate on a second graph and records whether the two "
              "agree. With no second graph loaded this compares the graph with "
              "itself, which is why it is off by default."))
    delta = None
    if use_reference:
        delta = st.slider(
            "Confidence gap allowed before a rule counts as unstable", 0.0, 1.0,
            0.1, 0.05, key="derive_delta",
            help=("A rule whose confidence differs by more than this between the "
                  "two graphs describes one graph rather than the domain."))

    st.caption(
        "The support and confidence floors are the derivation defaults and are not "
        "adjustable from this screen yet.")

    if st.button("Derive candidates", key="derive_run"):
        try:
            with st.spinner("Profiling the graph"):
                kwargs = {"dataset": session.graph_name, "generator": generator}
                if delta is not None:
                    kwargs["reference_graph"] = session.graph
                    kwargs["stability_delta"] = delta
                queue = logic.start_review(session.graph, domain, kg, **kwargs)
        except logic.ViewerError as exc:
            st.error(str(exc))
            return
        st_state.set_review_queue(queue)
        st.success(
            f"{len(queue.entries())} candidate(s) proposed, all pending. Open the "
            f"Review screen to decide each one.")

    queue = st_state.review_queue()
    if queue is None:
        return

    st.divider()
    entries = queue.entries()
    decided = len(entries) - len(queue.pending())
    st.metric("decided", f"{decided} / {len(entries)}")
    st.dataframe(
        [{"cid": e.cid, "kind": e.kind, "status": e.status, "reads as": e.gloss}
         for e in entries],
        width="stretch", hide_index=True)
    st.caption(
        "Impact is not computed here. It is one subset repair and one superset "
        "repair per candidate, which the cost measurement in docs/performance.md "
        "found to be most of what a derivation costs, so it is worked out one entry "
        "at a time on the Review screen.")
