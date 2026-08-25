"""
D2 constraint package: registry, availability matrix, and JSON export.

The availability matrix reflects the finalised 5-domain decision:

    Geography : Wikidata full, DBpedia full, YAGO full
    Taxa      : Wikidata full, DBpedia full, YAGO partial (class-level)
    Anatomy   : Wikidata only
    Disease   : Wikidata only
    Medication: Wikidata only
"""
from __future__ import annotations

import json
import os
from typing import Dict, List

from .model import Constraint, ConstraintSet
from . import biomedical, biomedical_v2, geography, taxa

AVAILABILITY: Dict[str, Dict[str, str]] = {
    "geography":  {"wikidata": "full",    "dbpedia": "full",    "yago": "full"},
    "taxa":       {"wikidata": "full",    "dbpedia": "full",    "yago": "partial"},
    "anatomy":    {"wikidata": "full",    "dbpedia": "none",    "yago": "none"},
    "disease":    {"wikidata": "full",    "dbpedia": "none",    "yago": "none"},
    "medication": {"wikidata": "full",    "dbpedia": "none",    "yago": "none"},
}

# D7/C1: domains with a v2 constraint fix (RC1/RC2). Domains absent here have no v2
# variant -- `registry(version=2)` falls back to their v1 ConstraintSet unchanged
# (geography/taxa were not implicated by the D6/T5 trace; see biomedical_v2.py).
_V2_OVERRIDES = biomedical_v2.all_biomedical_v2


def registry(version: int = 1) -> Dict[str, Dict[str, ConstraintSet]]:
    """domain -> kg -> ConstraintSet for every available slice.

    `version=1` (default) is the original, permanently-reproducible constraint set.
    `version=2` swaps in the RC1/RC2-fixed anatomy/disease/medication sets and leaves
    every other domain (geography, taxa) at v1 -- there is no "v2 of geography".
    """
    if version not in (1, 2):
        raise ValueError(f"unknown constraint version {version!r}")
    reg: Dict[str, Dict[str, ConstraintSet]] = {}
    for kg, cs in geography.all_geography().items():
        reg.setdefault("geography", {})[kg] = cs
    for kg, cs in taxa.all_taxa().items():
        reg.setdefault("taxa", {})[kg] = cs
    for domain, kgmap in biomedical.all_biomedical().items():
        for kg, cs in kgmap.items():
            reg.setdefault(domain, {})[kg] = cs
    if version == 2:
        for domain, kgmap in _V2_OVERRIDES().items():
            for kg, cs in kgmap.items():
                reg.setdefault(domain, {})[kg] = cs
    return reg


def get(domain: str, kg: str, version: int = 1) -> ConstraintSet:
    return registry(version=version)[domain][kg]


def compile_all() -> Dict[str, Dict[str, ConstraintSet]]:
    """Parse every constraint; surfaces any expression that leaves the fragment."""
    reg = registry()
    for kgmap in reg.values():
        for cs in kgmap.values():
            cs.compile_all()
    return reg


def export_json(out_dir: str) -> List[str]:
    """Write one JSON constraint file per (domain, kg); return the paths."""
    os.makedirs(out_dir, exist_ok=True)
    written: List[str] = []
    for domain, kgmap in registry().items():
        for kg, cs in kgmap.items():
            payload = {
                "slice": f"{domain}@{kg}",
                "availability": AVAILABILITY[domain][kg],
                "coverage": cs.coverage(),
                "constraints": [c.to_dict() for c in cs],
            }
            path = os.path.join(out_dir, f"{domain}.{kg}.json")
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, indent=2, ensure_ascii=False)
            written.append(path)
    return written


def load_json(path: str) -> ConstraintSet:
    """Read a JSON constraint file (built-in export or user-authored) into a set.

    Thin alias for `ConstraintSet.from_file`, which is the documented public
    entry point for user-supplied constraint files.
    """
    return ConstraintSet.from_file(path)
