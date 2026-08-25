"""
V1 -- manifest discovery for the Load screen.

Pure data-assembly glue over the already-committed fixture manifests in
`fixtures/real/` and `fixtures/synthetic/`. No repair or validation logic lives
here -- loading a graph and picking a matching constraint set are the only two
things this module does; `screens/check.py`/`screens/repair.py` call straight
into the library (`kgrepair.validator`, `kgrepair.repair`) for everything else.
"""
from __future__ import annotations

import glob
import json
import os
import sys
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import streamlit as st

from kgrepair import ConstraintSet, DataGraph, load_graph
from kgrepair import constraints as constraints_pkg

from app import logic

ROOT = os.path.join(os.path.dirname(__file__), "..")
FIXTURES_REAL = os.path.join(ROOT, "fixtures", "real")
FIXTURES_SYNTHETIC = os.path.join(ROOT, "fixtures", "synthetic")


@dataclass(frozen=True)
class ManifestEntry:
    namespace: str          # "real" | "synthetic"
    name: str
    nt_path: str
    manifest_path: str
    manifest: Dict

    @property
    def key(self) -> str:
        return f"{self.namespace}:{self.name}"

    # -- real-only fields -----------------------------------------------------
    @property
    def source(self) -> Optional[str]:
        """slice_source: wikidata | dbpedia | yago (real only)."""
        return self.manifest.get("slice_source")

    @property
    def domain(self) -> Optional[str]:
        return self.manifest.get("domain")

    @property
    def cache_generation_hash(self) -> Optional[str]:
        return self.manifest.get("cache_generation_hash")

    # -- synthetic-only fields -------------------------------------------------
    @property
    def seed(self) -> Optional[int]:
        return self.manifest.get("seed")

    @property
    def profile_hash(self) -> Optional[str]:
        return self.manifest.get("profile_hash")

    # -- shared -----------------------------------------------------------------
    @property
    def target_edges(self) -> Optional[int]:
        return self.manifest.get("target_edges")

    @property
    def content_hash(self) -> Optional[str]:
        return self.manifest.get("content_hash")

    @property
    def stats(self) -> Dict[str, int]:
        m = self.manifest
        return {"V": m.get("V", 0), "E": m.get("E", 0),
                "labels": m.get("labels", 0), "data_values": m.get("data_values", 0)}


def _load_entry(namespace: str, manifest_path: str) -> ManifestEntry:
    with open(manifest_path, "r", encoding="utf-8") as fh:
        manifest = json.load(fh)
    nt_path = manifest_path[: -len(".manifest.json")] + ".nt"
    return ManifestEntry(namespace=namespace, name=manifest["name"],
                         nt_path=nt_path, manifest_path=manifest_path, manifest=manifest)


def discover_manifests() -> List[ManifestEntry]:
    """Every real/ and synthetic/ manifest, namespace-badged, sorted for a stable
    picker order (real first, then synthetic; alphabetical within each)."""
    entries: List[ManifestEntry] = []
    for path in sorted(glob.glob(os.path.join(FIXTURES_REAL, "*.manifest.json"))):
        entries.append(_load_entry("real", path))
    for path in sorted(glob.glob(os.path.join(FIXTURES_SYNTHETIC, "*.manifest.json"))):
        entries.append(_load_entry("synthetic", path))
    return entries


def retrieval_timestamp_range(entry: ManifestEntry) -> Optional[Tuple[str, str]]:
    """(earliest, latest) retrieval_timestamp across the manifest's cited
    query_hashes, resolved from the Stage-1 raw cache's .meta.json sidecars.
    Returns None if the manifest names no query hashes or the cache isn't present
    locally (offline-safe: never raises, never fetches anything)."""
    query_hashes = set(entry.manifest.get("query_hashes", []))
    if not query_hashes or not entry.domain or not entry.source:
        return None
    cache_dir = os.path.join(ROOT, "data", "raw", entry.domain, entry.source)
    if not os.path.isdir(cache_dir):
        return None
    stamps: List[str] = []
    for meta_path in glob.glob(os.path.join(cache_dir, "*.meta.json")):
        try:
            with open(meta_path, "r", encoding="utf-8") as fh:
                meta = json.load(fh)
        except (OSError, json.JSONDecodeError):
            continue
        if meta.get("query_hash") in query_hashes and meta.get("retrieval_timestamp"):
            stamps.append(meta["retrieval_timestamp"])
    if not stamps:
        return None
    return (min(stamps), max(stamps))


 
# cached loaders -- keyed on (manifest hash, constraint set id+version) so
# switching screens never recomputes (global_constraints, viewer prompt).
 

@st.cache_resource(show_spinner=False)
def load_graph_cached(nt_path: str, content_hash: str) -> DataGraph:
    """`content_hash` is part of the cache key (not read from disk here) so a
    fixture that changes on disk without a matching manifest update still busts
    the cache instead of silently serving stale data.

    `cache_resource`, not `cache_data`: `DataGraph`'s adjacency uses
    `defaultdict(lambda: ...)`, which isn't picklable, and `cache_data` pickles
    every cached value. This means callers get back the SAME object on every
    call -- safe here because every viewer code path that runs a repair does so
    with `in_place=False` (the library default), which clones before mutating;
    the viewer never edits a loaded graph in place (no_goals: no graph editing
    through the UI)."""
    return load_graph(nt_path)


@st.cache_resource(show_spinner=False)
def _registry_constraint_set(domain: str, kg: str, version: int) -> Optional[ConstraintSet]:
    try:
        return constraints_pkg.get(domain, kg, version=version)
    except KeyError:
        return None


#: The synthetic generator's four rules, committed as an ordinary constraint file
#: so the viewer reads them the same way it reads a user's own upload, rather than
#: reaching into the generator module. `tests/test_viewer_logic.py` guards it
#: against drifting from `kgrepair.synthetic`.
SYNTHETIC_CONSTRAINTS = os.path.join(
    FIXTURES_SYNTHETIC, "synthetic_geoLike.constraints.json")


@st.cache_resource(show_spinner=False)
def _synthetic_constraint_set() -> ConstraintSet:
    return logic.load_constraints_from_path(SYNTHETIC_CONSTRAINTS)


def session_for(entry: ManifestEntry, cs: ConstraintSet, label: str) -> logic.Session:
    """A `logic.Session` for a committed fixture slice.

    Fixtures use the loader's default type predicates: they are Wikidata, DBpedia
    and YAGO extracts whose typing spine the default vocabulary already covers.
    A user's own graph declares its spine on the upload form instead.
    """
    return logic.Session(
        graph=load_graph_cached(entry.nt_path, entry.content_hash or ""),
        constraints=cs, graph_name=os.path.basename(entry.nt_path),
        constraints_source=label,
        type_predicates=logic.effective_type_predicates(None),
        entry=entry)


def selected_entry_and_cs():
    """(entry, ConstraintSet) for the Load screen's current session-state
    selection, or (None, None) if nothing (valid) is selected yet. Shared by
    every downstream screen (Check, Repair, Export) so "select a manifest on
    Load first" is defined once."""
    entries = discover_manifests()
    by_key = {e.key: e for e in entries}
    entry = by_key.get(st.session_state.get("manifest_key"))
    if entry is None:
        return None, None
    choices = matching_constraint_sets(entry)
    cs = choices.get(st.session_state.get("constraint_label"))
    return entry, cs


def matching_constraint_sets(entry: ManifestEntry) -> Dict[str, ConstraintSet]:
    """label -> ConstraintSet, restricted to sets that actually apply to this
    manifest's (namespace, domain, source) -- never offer a mismatched pair."""
    if entry.namespace == "synthetic":
        cs = _synthetic_constraint_set()
        return {f"{cs.name} (v1)": cs}
    out: Dict[str, ConstraintSet] = {}
    if not entry.domain or not entry.source:
        return out
    seen_names: set = set()
    for version in (1, 2):
        cs = _registry_constraint_set(entry.domain, entry.source, version)
        if cs is None or cs.name in seen_names:
            continue                     # domain has no v2 override -> v2 == v1, skip the dup
        seen_names.add(cs.name)
        out[f"{cs.name} (v{version})"] = cs
    return out
