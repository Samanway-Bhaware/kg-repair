"""
V1 -- session-state accessors for the viewer.

Streamlit reruns the whole script on every interaction; these typed helpers are
the one place that knows the session_state keys, so screens read/write through
them instead of scattering string keys everywhere.
"""
from __future__ import annotations

import streamlit as st

_DEFAULTS = {
    "manifest_key": None,             # ManifestEntry.key of the selected slice
    "constraint_label": None,         # label chosen in matching_constraint_sets()
    "session": None,                  # app.logic.Session, whichever way it was loaded
    "consistency_report": None,       # kgrepair.validator.ValidationReport (V2)
    "consistency_meta": None,         # dict: which (manifest, constraints) it was run on
    "repair_result": None,            # SubsetRepairResult | SupersetRepairResult (V3)
    "repair_meta": None,              # dict: mode, params, aborted info
    "review_queue": None,             # app.logic.ReviewQueue, mid-review (P7b)
    "review_cursor": 0,               # which entry the Review screen is showing
}


def init() -> None:
    for key, default in _DEFAULTS.items():
        st.session_state.setdefault(key, default)


def set_session(session) -> None:
    """Record the loaded session, resetting downstream screens when it changes."""
    current = st.session_state.get("session")
    if current is None or current.fingerprint != session.fingerprint:
        reset_downstream_of_load()
    st.session_state["session"] = session


def session():
    """The loaded `app.logic.Session`, or None if the Load screen has not run yet."""
    return st.session_state.get("session")


def reset_downstream_of_load() -> None:
    """Selecting a new manifest/constraint set invalidates Check and Repair results."""
    st.session_state["consistency_report"] = None
    st.session_state["consistency_meta"] = None
    st.session_state["repair_result"] = None
    st.session_state["repair_meta"] = None
    st.session_state["review_queue"] = None
    st.session_state["review_cursor"] = 0


def set_review_queue(queue) -> None:
    """Record a derived queue and start the review at its first entry."""
    st.session_state["review_queue"] = queue
    st.session_state["review_cursor"] = 0


def review_queue():
    """The `app.logic.ReviewQueue` under review, or None if none was derived."""
    return st.session_state.get("review_queue")


def reset_downstream_of_check() -> None:
    st.session_state["repair_result"] = None
    st.session_state["repair_meta"] = None
