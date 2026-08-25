"""
Deterministic synthetic slice generator with ground-truth violation injection (D7).

Purpose: sized, retraceable inputs for the memory profile and size ladder now, and
the seeded ground-truth harness the D7 precision/recall evaluation needs later --
the SAME tool, not throwaway. Everything lives under a `synth:` namespace and is
tagged `source="synthetic"` so it can never be mistaken for real-KG output.

Pipeline (per `generate`):
  1. Build a class hierarchy (rdfs:subClassOf spine) and a CLEAN instance graph that
     is consistent w.r.t. `synthetic_constraints()` -- verified with the real
     Validator during generation (clean-first invariant, not construction-by-hope).
  2. Inject violations on FRESH, disjoint nodes, one intended witness per injection.
     Ground truth is derived from the Validator's witness delta after each edit and
     cross-checked, so recorded ground truth == Validator witnesses exactly (the
     certification the precision/recall harness depends on).
  3. Emit the slice (N-Triples in ntriples.py's dialect), a manifest (seed, profile
     hash, injection rates, content + ground-truth hashes), and ground truth (JSONL).

Determinism: identical (seed, target_edges, profile) -> byte-identical N-Triples ->
identical content hash. The only randomness (which clean country/place an instance
links to) is drawn from a seeded RNG.

The generated graph is built to reload identically through `ntriples.load_ntriples`:
class nodes are valued exactly as the loader would value them (objects of rdf:type /
rdfs:subClassOf carry their own IRI as D(.)).
"""
from __future__ import annotations

import hashlib
import json
import os
import random
from dataclasses import asdict, dataclass, field
from typing import Dict, List, Optional

from .constraints.model import Constraint, ConstraintSet
from .datagraph import DataGraph
from .validator import Validator

# --- namespace / vocabulary (all synthetic) ---------------------------------
NS = "synth:"
TYPE = "rdf:type"                 # recognised by the loader's class-valuing rule
SUBCLASS = "rdfs:subClassOf"      # recognised by the loader's class-valuing rule
COUNTRY = "synth:country"         # instance label (P17 analogue)
LOCATED = "synth:locatedIn"       # instance label (P131 analogue)

GEO = "synth:Geo"
CITY = "synth:City"
COUNTRY_C = "synth:Country"
GEO_ONLY = "synth:GeoOnly"        # subclass of Geo but NOT City (for clean C_type)

_VALUING_PREDICATES = (TYPE, SUBCLASS)


def _tau(c: str) -> str:
    return f'< down({TYPE}) . down({SUBCLASS})* . [val("{c}")] >'


def synthetic_constraints() -> ConstraintSet:
    """The four ptime_core rules the generator builds/injects against."""
    def c(cid, kind, direction, ante, cons):
        return Constraint(cid=cid, domain="synthetic", kg="synthetic", kind=kind,
                          tier="ptime_core", provenance="derived", direction=direction,
                          antecedent=ante, consequent=cons)
    return ConstraintSet("synthetic@geography-like", [
        c("syn.dom.country", "existential_domain", "subset",
          f"< down({COUNTRY}) >", _tau(GEO)),
        c("syn.rng.country", "existential_range", "subset",
          f"< up({COUNTRY}) >", _tau(COUNTRY_C)),
        c("syn.type.city", "typing_existence", "superset",
          f"< down({COUNTRY}) > & < down({LOCATED}) >", _tau(CITY)),
        c("syn.req.city_country", "requires_statement", "superset",
          _tau(CITY), f"< down({COUNTRY}) >"),
    ])


@dataclass
class Profile:
    """Structure knobs; defaults mimic the hand-written geography fixture's shape."""
    hierarchy_depth: int = 4          # length of the City subclass chain (>=1)
    num_countries: Optional[int] = None   # default derived from size
    num_places: Optional[int] = None      # default derived from size
    data_value_density: float = 0.0   # fraction of places carrying a literal value
    zipf_skew: float = 0.0            # >0 concentrates country/place reuse on hubs
    injection_rates: Dict[str, float] = field(default_factory=lambda: {
        "existential_domain": 0.02,
        "existential_range": 0.02,
        "typing_existence": 0.02,
        "requires_statement": 0.02,
    })

    def hashable(self) -> Dict:
        return asdict(self)


@dataclass
class SyntheticSlice:
    name: str
    graph: DataGraph
    constraints: ConstraintSet
    ground_truth: List[Dict]
    manifest: Dict

    def to_ntriples(self) -> str:
        lines = [f"# synthetic slice {self.name} (source=synthetic; DO NOT mix with real-KG results)",
                 f"# manifest content_hash={self.manifest['content_hash']}"]
        for s, p, o in sorted(self.graph.edges()):
            lines.append(f"<{s}> <{p}> <{o}> .")
        return "\n".join(lines) + "\n"

    def ground_truth_jsonl(self) -> str:
        return "".join(json.dumps(r, sort_keys=True) + "\n" for r in self.ground_truth)


 
# helpers
 

def _add_edge(g: DataGraph, s: str, p: str, o: str) -> None:
    """Add an edge, mirroring the loader's class-valuing rule so the in-memory graph
    matches a reload from the emitted N-Triples exactly."""
    g.add_edge(s, p, o)
    if p in _VALUING_PREDICATES and g.value(o) is None:
        g.set_value(o, o)


def _content_hash(g: DataGraph) -> str:
    payload = {
        "edges": sorted(g.edges()),
        "values": sorted((v, g.value(v)) for v in g.nodes if g.value(v) is not None),
    }
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def _validate_witness_pairs(g: DataGraph, cs: ConstraintSet):
    """Set of (constraint_id, witness_node) currently reported by the Validator."""
    report = Validator(g).validate(cs)
    return {(v.constraint.cid, w) for v in report.failing() for w in v.witnesses}


 
# generation
 

def generate(seed: int, target_edges: int, profile: Optional[Profile] = None,
             *, name: Optional[str] = None) -> SyntheticSlice:
    profile = profile or Profile()
    rng = random.Random(seed)
    cs = synthetic_constraints()
    g = DataGraph()

    # --- 1. class hierarchy (subClassOf spine) ---
    depth = max(1, profile.hierarchy_depth)
    city_chain = [CITY] + [f"{CITY}/{i}" for i in range(1, depth)]
    for i in range(1, len(city_chain)):
        _add_edge(g, city_chain[i], SUBCLASS, city_chain[i - 1])   # deeper -> shallower
    leaf_city = city_chain[-1]                                     # instances typed here
    _add_edge(g, CITY, SUBCLASS, GEO)
    _add_edge(g, COUNTRY_C, SUBCLASS, GEO)
    _add_edge(g, GEO_ONLY, SUBCLASS, GEO)

    hierarchy_edges = g.num_edges()

    # --- size planning ---
    remaining = max(0, target_edges - hierarchy_edges)
    n_cities = max(1, remaining // 3)                             # each city ~3 edges
    n_countries = profile.num_countries or max(2, n_cities // 10)
    n_places = profile.num_places or max(2, n_cities // 5)

    countries = [f"{NS}c/{i}" for i in range(n_countries)]
    for cnode in countries:
        _add_edge(g, cnode, TYPE, COUNTRY_C)
    places = [f"{NS}p/{i}" for i in range(n_places)]
    for i, pnode in enumerate(places):
        g.add_node(pnode)
        if profile.data_value_density and rng.random() < profile.data_value_density:
            g.set_value(pnode, f"lit:{i}")

    def _pick(pool: List[str]) -> str:
        if profile.zipf_skew > 0:
            # concentrate on a small hub prefix
            hub = max(1, int(len(pool) * (1.0 - min(0.9, profile.zipf_skew))))
            return pool[rng.randint(0, hub - 1)]
        return pool[rng.randrange(len(pool))]

    # --- clean city instances (satisfy all four rules) ---
    for i in range(n_cities):
        x = f"{NS}x/{i}"
        _add_edge(g, x, TYPE, leaf_city)              # typed City (via deep chain)
        _add_edge(g, x, COUNTRY, _pick(countries))    # has a country (Country target)
        _add_edge(g, x, LOCATED, _pick(places))       # located in a place

    # --- clean-first invariant: verified, not assumed ---
    clean_pairs = _validate_witness_pairs(g, cs)
    if clean_pairs:
        raise AssertionError(f"clean graph is not consistent: {sorted(clean_pairs)[:5]}")

    # --- 2. inject violations on fresh, disjoint nodes ---
    # Each injector edits a fresh node neighbourhood and RETURNS the (constraint,
    # witness) pair(s) it is designed to create; ground truth is recorded from those
    # returns. We then validate ONCE (below) and assert the Validator's witness set
    # equals the recorded ground truth exactly -- so accounting stays O(E), not
    # O(injections x E), while the single final check still catches any interaction.
    ground_truth: List[Dict] = []

    def _count(kind: str) -> int:
        rate = profile.injection_rates.get(kind, 0.0)
        return max(1, int(rate * n_cities)) if rate > 0 else 0

    def inj_dom(k):
        """add synth:country from an untyped subject (existential_domain)"""
        r = f"{NS}viol/dom/{k}"
        _add_edge(g, r, COUNTRY, _pick(countries))         # r untyped -> not tau_Geo
        return [("syn.dom.country", r)]

    def inj_rng(k):
        """point synth:country at an untyped orphan target (existential_range)"""
        p, q = f"{NS}viol/rngS/{k}", f"{NS}viol/rngO/{k}"
        _add_edge(g, p, TYPE, GEO_ONLY)                    # p is Geo (dom ok), not City
        _add_edge(g, p, COUNTRY, q)                        # q untyped -> not Country
        return [("syn.rng.country", q)]

    def inj_type(k):
        """country+locatedIn on a non-City geo node (typing_existence)"""
        s = f"{NS}viol/type/{k}"
        _add_edge(g, s, TYPE, GEO_ONLY)                    # Geo but not City
        _add_edge(g, s, COUNTRY, _pick(countries))
        _add_edge(g, s, LOCATED, _pick(places))
        return [("syn.type.city", s)]

    def inj_req(k):
        """a City with its required synth:country dropped (requires_statement)"""
        t = f"{NS}viol/req/{k}"
        _add_edge(g, t, TYPE, leaf_city)                   # City, but no country edge
        _add_edge(g, t, LOCATED, _pick(places))
        return [("syn.req.city_country", t)]

    for kind, fn in (("existential_domain", inj_dom), ("existential_range", inj_rng),
                     ("typing_existence", inj_type), ("requires_statement", inj_req)):
        for k in range(_count(kind)):
            for (cid, node) in fn(k):
                ground_truth.append({"constraint_id": cid, "witness_node": node,
                                     "injection": kind, "edit": fn.__doc__ or kind})

    # --- 3. certification: one validation, exact accounting ---
    final_pairs = _validate_witness_pairs(g, cs)
    gt_pairs = {(r["constraint_id"], r["witness_node"]) for r in ground_truth}
    if final_pairs != gt_pairs:
        missing = gt_pairs - final_pairs
        extra = final_pairs - gt_pairs
        raise AssertionError(
            f"injection accounting mismatch: missing={sorted(missing)[:3]} "
            f"extra={sorted(extra)[:3]}")

    slice_name = name or f"synthetic_geoLike_{target_edges}_s{seed}"
    stats = g.stats()
    gt_hash = hashlib.sha256(
        "".join(json.dumps(r, sort_keys=True) + "\n" for r in ground_truth).encode()
    ).hexdigest()[:16]
    manifest = {
        "name": slice_name,
        "namespace": "synthetic",
        "source": "synthetic",
        "seed": seed,
        "target_edges": target_edges,
        "profile": profile.hashable(),
        "profile_hash": hashlib.sha256(
            json.dumps(profile.hashable(), sort_keys=True).encode()).hexdigest()[:16],
        "V": stats["nodes"], "E": stats["edges"],
        "labels": stats["labels"], "data_values": stats["valued_nodes"],
        "hierarchy_depth": depth,
        "injection_rates": profile.injection_rates,
        "injection_count": len(ground_truth),
        "constraints_set_id": cs.name,
        "content_hash": _content_hash(g),
        "ground_truth_hash": gt_hash,
    }
    return SyntheticSlice(slice_name, g, cs, ground_truth, manifest)


def write_slice(sl: SyntheticSlice, out_dir: str) -> Dict[str, str]:
    """Write <name>.nt / <name>.manifest.json / <name>.ground_truth.jsonl."""
    os.makedirs(out_dir, exist_ok=True)
    paths = {
        "nt": os.path.join(out_dir, f"{sl.name}.nt"),
        "manifest": os.path.join(out_dir, f"{sl.name}.manifest.json"),
        "ground_truth": os.path.join(out_dir, f"{sl.name}.ground_truth.jsonl"),
    }
    with open(paths["nt"], "w", encoding="utf-8") as fh:
        fh.write(sl.to_ntriples())
    with open(paths["manifest"], "w", encoding="utf-8") as fh:
        json.dump(sl.manifest, fh, indent=2)
    with open(paths["ground_truth"], "w", encoding="utf-8") as fh:
        fh.write(sl.ground_truth_jsonl())
    return paths
