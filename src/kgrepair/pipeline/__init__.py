"""
Real-KG extraction pipeline (feeds D7 evaluation / D8 repaired-KGs).

Two stages:
  * FETCH (Stage 1, `cache` + `fetch`) -- polite, cached, Level-0-filtered retrieval
    of raw responses; the cache is the determinism boundary.
  * SLICE (Stage 2, `slicing`) -- deterministic pure function of (cache, params) into
    a DataGraph + manifest under the `real/` namespace.

Level-0: allow-lists (`allowlist`) whitelist predicates at fetch time; person/org
predicates never reach disk, and a deny-check asserts they never reach a slice.
"""
from .allowlist import AllowList, filter_triples, load_allowlist
from .cache import RawCache
from .slicing import RealSlice, SliceParams, deny_check, slice_from_cache

__all__ = [
    "AllowList", "load_allowlist", "filter_triples",
    "RawCache",
    "SliceParams", "RealSlice", "slice_from_cache", "deny_check",
]
