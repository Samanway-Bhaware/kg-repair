"""
P7b -- Review screen: decide every derived candidate, then seal.

One entry at a time, with the evidence for it and the graph around a node that
breaks it. Three decisions and nothing else: accept, reject, weaken. The seal
control stays disabled until every entry has one, because a seal covering an
entry nobody saw would defeat what it is for.

Presentation only. Every decision, refusal and measurement is an `app.logic`
call on the `ReviewQueue`.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

import streamlit as st

import kgrepair

from app import logic
from app import state as st_state
from app import viz

_DECISIONS = (("Accept", "accepted"), ("Reject", "rejected"), ("Weaken", "weakened"))


def _render_entry(queue, entry) -> None:
    """One candidate: what it says, what backs it, and what accepting it would do."""
    st.subheader(entry.cid)
    st.markdown(f"**{entry.gloss or 'no plain reading was recorded for this rule'}**")

    st.code(f"{entry.antecedent}\n  is contained in\n{entry.consequent}",
            language=None)

    # Impact is measured for this entry, on demand. Opening one entry does not
    # measure any other, which is the whole reason it is deferred.
    shown = queue.show(entry.cid)
    evidence, impact = shown["evidence"], shown["impact"]

    cols = st.columns(4)
    cols[0].metric("support", evidence.get("support", "?"))
    cols[1].metric("confidence", evidence.get("confidence", "?"))
    cols[2].metric("nodes that break it", impact.get("witnesses", "?"))
    cols[3].metric("kind", shown["kind"])

    stability = evidence.get("stability") or evidence.get("reference_confidence")
    if stability is not None:
        st.caption(f"stability: {stability}")
    if evidence.get("low_trust"):
        st.warning(f"low trust: {evidence.get('low_trust_reason', 'flagged')}")

    if impact.get("measured"):
        st.caption(
            f"accepting it means {impact.get('subset_deletions')} deletion(s) or "
            f"{impact.get('superset_additions')} addition(s), measured for this "
            f"entry only")

    if shown["witness_sample"]:
        st.caption("for example: " + ", ".join(shown["witness_sample"]))
        view = queue.witness_view(entry.cid)
        if view is not None:
            with st.expander("the graph around the first node that breaks it"):
                viz.render_neighbourhood(view)


def render() -> None:
    st.header("Review")
    queue = st_state.review_queue()
    if queue is None:
        st.info("Derive candidates on the Derive screen first.")
        return

    entries = queue.entries()
    pending = queue.pending()
    decided = len(entries) - len(pending)
    st.progress(decided / len(entries) if entries else 0.0,
                text=f"{decided} of {len(entries)} decided")

    labels = [f"{i + 1}. {e.cid} [{e.status}]" for i, e in enumerate(entries)]
    cursor = st.selectbox("Entry", options=range(len(entries)),
                          format_func=lambda i: labels[i],
                          index=min(st.session_state.get("review_cursor", 0),
                                    len(entries) - 1),
                          key="review_pick")
    st.session_state["review_cursor"] = cursor
    entry = entries[cursor]

    _render_entry(queue, entry)

    note = st.text_input("Note (recorded with the decision)", key="review_note")
    buttons = st.columns(3)
    for column, (label, status) in zip(buttons, _DECISIONS):
        if column.button(label, key=f"review_{status}"):
            try:
                queue.decide(entry.cid, status, note=note)
            except logic.ViewerError as exc:
                st.error(str(exc))
            else:
                st.session_state["review_cursor"] = min(cursor + 1, len(entries) - 1)
                st.rerun()

    st.divider()
    if pending:
        st.info(f"{len(pending)} entry(ies) still undecided. The file can be sealed "
                f"once every one has a decision.")
        return

    reviewer = st.text_input("Reviewer name", key="review_reviewer",
                             help="Recorded in the seal, because the seal records "
                                  "who made these decisions.")
    if st.button("Seal and use these constraints", key="review_seal",
                 disabled=not reviewer.strip()):
        try:
            queue.seal(reviewer)
            cs = queue.constraint_set()
        except logic.ViewerError as exc:
            st.error(str(exc))
            return

        session = st_state.session()
        st_state.set_session(logic.Session(
            graph=queue.graph, constraints=cs,
            graph_name=session.graph_name if session else "derived",
            constraints_source=f"reviewed candidates, sealed by {reviewer.strip()}",
            type_predicates=(session.type_predicates if session
                             else set(kgrepair.DEFAULT_TYPE_PREDICATES))))
        st.success(
            f"Sealed by {reviewer.strip()}. {len(cs)} constraint(s) accepted and now "
            f"loaded. Go to the Repair screen to run an engine over them; the graph "
            f"does not need loading again.")
