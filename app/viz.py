"""
V2 -- shared NeighbourhoodView rendering: networkx (layout/graph model) +
matplotlib (drawing). Chosen over pyvis (not installed in this environment) and
consistent with the matplotlib precedent already established for D7/C2
reporting (`scripts/build_evaluation.py`); used by every graph view in the
viewer so the legend/colour scheme never drifts between screens.

Colour = status (unchanged/added/deleted); a blue ring marks the BFS center;
a dashed black outline marks a fresh-symbol node (D6 naming: `fresh:<cid>:<n>`).
`hide_added`/`grey_deleted` implement the V3 before/after split (before hides
additions; after greys/dashes deletions) without a second extraction -- both
render the SAME `NeighbourhoodView`.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import networkx as nx

from kgrepair import NeighbourhoodView

STATUS_COLOR = {
    "unchanged": "#8a8f98",
    "deleted": "#d1453d",
    "added": "#2f9e44",
}
CENTER_RING = "#1c7ed6"
FRESH_OUTLINE = "#111318"

LEGEND_MD = (
    "**Legend** &nbsp; "
    "\U0001F7E2 added &nbsp; \U0001F534 deleted &nbsp; ⚫ unchanged &nbsp; "
    "\U0001F535 ring = BFS center &nbsp; dashed outline = fresh symbol"
)


def render_legend(st) -> None:
    """`st` is passed in (not imported here) so this stays a plain rendering
    helper callable from any screen without hard-wiring the caller's `st`."""
    st.markdown(LEGEND_MD)


def _short(node_id: str, maxlen: int = 22) -> str:
    return node_id if len(node_id) <= maxlen else node_id[: maxlen - 1] + "…"


def render_neighbourhood(view: NeighbourhoodView, *, hide_added: bool = False,
                         grey_deleted: bool = False, figsize=(6.5, 5.5)):
    """Render one `NeighbourhoodView` to a matplotlib Figure."""
    g = nx.MultiDiGraph()
    keep_ids = {n.id for n in view.nodes if not (hide_added and n.status == "added")}
    for n in view.nodes:
        if n.id in keep_ids:
            g.add_node(n.id, value=n.value, status=n.status, fresh=n.fresh,
                      is_center=n.is_center)
    kept_edges = []
    for e in view.edges:
        if e.src in keep_ids and e.dst in keep_ids and not (hide_added and e.status == "added"):
            g.add_edge(e.src, e.dst, label=e.label, status=e.status)
            kept_edges.append((e.src, e.dst, e.status))

    fig, ax = plt.subplots(figsize=figsize)
    if g.number_of_nodes() == 0:
        ax.set_axis_off()
        return fig
    pos = nx.spring_layout(g, seed=0)

    for status, color in STATUS_COLOR.items():
        ids = [n for n, d in g.nodes(data=True) if d["status"] == status]
        if not ids:
            continue
        alpha = 0.35 if (grey_deleted and status == "deleted") else 0.95
        ring_colors = [CENTER_RING if g.nodes[n]["is_center"] else "white" for n in ids]
        ring_widths = [2.4 if g.nodes[n]["is_center"] else 0.6 for n in ids]
        nx.draw_networkx_nodes(g, pos, nodelist=ids, node_color=color, alpha=alpha,
                               edgecolors=ring_colors, linewidths=ring_widths, ax=ax)

    fresh_ids = [n for n, d in g.nodes(data=True) if d["fresh"]]
    if fresh_ids:
        nx.draw_networkx_nodes(g, pos, nodelist=fresh_ids, node_color="none",
                               edgecolors=FRESH_OUTLINE, linewidths=1.6,
                               node_size=420, ax=ax)

    for status, color in STATUS_COLOR.items():
        elist = [(u, v) for u, v, s in kept_edges if s == status]
        if not elist:
            continue
        alpha = 0.3 if (grey_deleted and status == "deleted") else 0.85
        style = "dashed" if (grey_deleted and status == "deleted") else "solid"
        nx.draw_networkx_edges(g, pos, edgelist=elist, edge_color=color, alpha=alpha,
                               style=style, ax=ax, arrows=True, arrowsize=10,
                               connectionstyle="arc3,rad=0.08")

    nx.draw_networkx_labels(g, pos, labels={n: _short(n) for n in g.nodes}, font_size=7, ax=ax)
    ax.set_axis_off()
    fig.tight_layout()
    return fig
