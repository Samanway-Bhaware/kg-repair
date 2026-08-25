"""
V1 -- viewer entry point: `streamlit run app/main.py`.

Sidebar navigation across six screens (Load / Check / Derive / Review /
Repair / Export), backed
by session state in `state.py`. This file only wires navigation + bootstraps
`sys.path`, so the viewer also runs from a bare checkout without `pip install -e .`;
every screen does its own work by calling straight into the `kgrepair` public API.
"""
from __future__ import annotations

import os
import sys

_APP_DIR = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.join(_APP_DIR, "..")
for p in (_ROOT, os.path.join(_ROOT, "src")):
    if p not in sys.path:
        sys.path.insert(0, p)

import streamlit as st

from app import state as st_state
from app.screens import check as screen_check
from app.screens import derive as screen_derive
from app.screens import export as screen_export
from app.screens import load as screen_load
from app.screens import repair as screen_repair
from app.screens import review as screen_review

st.set_page_config(page_title="kgrepair viewer", layout="wide")
st_state.init()

_SCREENS = {
    "Load": screen_load,
    "Check": screen_check,
    # Derive and Review are the path for someone with no constraints of their own:
    # propose, decide every entry, seal, and only then repair.
    "Derive": screen_derive,
    "Review": screen_review,
    "Repair": screen_repair,
    "Export": screen_export,
}


def main() -> None:
    st.sidebar.title("kgrepair viewer")
    screen_name = st.sidebar.radio("Screen", list(_SCREENS.keys()))
    screen = _SCREENS[screen_name]
    if screen is None:
        st.header(screen_name)
        st.info(f"{screen_name} screen not built yet.")
        return
    screen.render()


if __name__ == "__main__":
    main()
