"""
T5 gate: deterministic synthetic slice generator + ground-truth injection.

Critical gate = injection accounting: the Validator's witness set on the injected
graph equals the recorded ground-truth witness set EXACTLY. This certifies the
harness for later precision/recall use.
"""
import hashlib
import os

from kgrepair.datagraph import DataGraph
from kgrepair.ntriples import load_ntriples
from kgrepair.synthetic import Profile, generate, synthetic_constraints, write_slice
from kgrepair.validator import Validator


def _witness_pairs(g, cs):
    rep = Validator(g).validate(cs)
    return {(v.constraint.cid, w) for v in rep.failing() for w in v.witnesses}


# ---------- determinism ------------------------------------------------------

def test_generation_is_deterministic():
    a = generate(seed=7, target_edges=1000)
    b = generate(seed=7, target_edges=1000)
    assert a.manifest["content_hash"] == b.manifest["content_hash"]
    assert a.manifest["ground_truth_hash"] == b.manifest["ground_truth_hash"]
    assert a.to_ntriples() == b.to_ntriples()
    # a different seed yields a different slice
    c = generate(seed=8, target_edges=1000)
    assert c.manifest["content_hash"] != a.manifest["content_hash"]


def test_ntriples_roundtrip_matches_in_memory_graph():
    sl = generate(seed=3, target_edges=1000)
    reloaded = load_ntriples(sl.to_ntriples().splitlines())
    assert set(reloaded.edges()) == set(sl.graph.edges())
    # class values reproduced identically on reload (loader valuing rule mirrored)
    valued = lambda g: {v: g.value(v) for v in g.nodes if g.value(v) is not None}
    assert valued(reloaded) == valued(sl.graph)
    # ground truth still exact against the reloaded graph
    assert _witness_pairs(reloaded, sl.constraints) == \
        {(r["constraint_id"], r["witness_node"]) for r in sl.ground_truth}


# ---------- clean-first ------------------------------------------------------

def test_clean_graph_before_injection_has_zero_violations():
    # rates=0 -> no injections -> the pure clean graph; must validate clean
    prof = Profile(injection_rates={})
    sl = generate(seed=1, target_edges=2000, profile=prof)
    assert sl.ground_truth == []
    assert _witness_pairs(sl.graph, sl.constraints) == set()


# ---------- injection accounting (THE critical gate) -------------------------

def test_injection_accounting_exact():
    sl = generate(seed=5, target_edges=3000)
    assert sl.ground_truth, "expected some injected violations"
    validator_pairs = _witness_pairs(sl.graph, sl.constraints)
    ground_truth_pairs = {(r["constraint_id"], r["witness_node"]) for r in sl.ground_truth}
    assert validator_pairs == ground_truth_pairs
    # each injection kind is represented and maps to the expected constraint
    kinds = {r["injection"] for r in sl.ground_truth}
    assert {"existential_domain", "existential_range",
            "typing_existence", "requires_statement"} <= kinds
    expected_cid = {
        "existential_domain": "syn.dom.country",
        "existential_range": "syn.rng.country",
        "typing_existence": "syn.type.city",
        "requires_statement": "syn.req.city_country",
    }
    for r in sl.ground_truth:
        assert r["constraint_id"] == expected_cid[r["injection"]]


def test_manifest_is_retraceable_and_synthetic_tagged():
    sl = generate(seed=2, target_edges=1500)
    m = sl.manifest
    assert m["namespace"] == "synthetic" and m["source"] == "synthetic"
    for key in ("seed", "profile_hash", "content_hash", "ground_truth_hash",
                "injection_rates", "V", "E", "hierarchy_depth"):
        assert key in m
    # recomputing the ground-truth hash from the records matches the manifest
    recomputed = hashlib.sha256(sl.ground_truth_jsonl().encode()).hexdigest()[:16]
    assert recomputed == m["ground_truth_hash"]


def test_write_slice_emits_three_artifacts(tmp_path):
    sl = generate(seed=9, target_edges=1000)
    paths = write_slice(sl, str(tmp_path))
    for p in paths.values():
        assert os.path.exists(p)
    assert paths["nt"].endswith(".nt")


# ---------- scale smoke ------------------------------------------------------

def test_scale_smoke_10k():
    sl = generate(seed=0, target_edges=10_000)
    assert sl.manifest["E"] >= 9_000    # roughly hits target
    # accounting still exact at 10k
    assert _witness_pairs(sl.graph, sl.constraints) == \
        {(r["constraint_id"], r["witness_node"]) for r in sl.ground_truth}
