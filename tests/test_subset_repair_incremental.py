"""
OPT-1 differential suite: the incremental dirty-set re-check MUST return the
identical repair as the full-recompute baseline.

This is the gate the acceptance criteria require to pass before any large-slice
output is trusted. We check equality on every committed fixture and on a large
batch of seeded, randomly-generated small graphs (property-based, deterministic).
"""
import os
import random

from kgrepair import constraints
from kgrepair.constraints.model import Constraint, ConstraintSet
from kgrepair.datagraph import DataGraph
from kgrepair.ntriples import load_ntriples_file
from kgrepair.repair import subset_repair


FIXTURES = os.path.join(os.path.dirname(__file__), "..", "fixtures")

_TAU = '< down(wdt:P31) . down(wdt:P279)* . [val("{c}")] >'


def _mixed_constraints():
    """Three subset-direction rules; P361 is disjoint from the country labels."""
    def c(cid, kind, ante, cons):
        return Constraint(cid=cid, domain="d", kg="wd", kind=kind,
                          tier="ptime_core", provenance="given", direction="subset",
                          antecedent=ante, consequent=cons)
    return ConstraintSet("mixed", [
        c("rng_country", "existential_range", "< up(wdt:P17) >", _TAU.format(c="Q6256")),
        c("dom_country", "existential_domain", "< down(wdt:P17) >", _TAU.format(c="Q2221906")),
        c("dom_partof", "existential_domain", "< down(wdt:P361) >", _TAU.format(c="Q4936952")),
    ])


def _assert_same_repair(g, cs):
    full = subset_repair(g, cs, strategy="full")
    inc = subset_repair(g, cs, strategy="incremental")
    assert full.deleted_nodes == inc.deleted_nodes
    assert set(full.graph.nodes) == set(inc.graph.nodes)
    assert set(full.graph.edges()) == set(inc.graph.edges())
    assert full.changelog_dicts() == inc.changelog_dicts()
    assert full.attestations["consistent_after"] and inc.attestations["consistent_after"]
    assert inc.recheck_count <= full.recheck_count
    assert full.mode == "full" and inc.mode == "incremental"
    return full, inc


# ---------- differential on the committed fixtures ---------------------------

def test_incremental_matches_full_on_fixtures():
    for domain, fixture in [("geography", "synthetic_geography_wd.nt"),
                            ("anatomy", "synthetic_anatomy_wd.nt"),
                            ("disease", "synthetic_disease_wd.nt")]:
        g = load_ntriples_file(os.path.join(FIXTURES, fixture))
        _assert_same_repair(g, constraints.get(domain, "wikidata"))


# ---------- property-based differential on seeded random graphs ---------------

def _random_graph(seed):
    rng = random.Random(seed)
    g = DataGraph()
    classes = ["Q6256", "Q2221906", "Q4936952"]
    for cls in classes:
        g.set_value(cls, cls)
    insts = [f"n{i}" for i in range(rng.randint(3, 8))]
    labels = ["wdt:P31", "wdt:P279", "wdt:P17", "wdt:P361"]
    targets = insts + classes
    for _ in range(rng.randint(3, 16)):
        s, l, d = rng.choice(insts), rng.choice(labels), rng.choice(targets)
        if s != d:
            g.add_edge(s, l, d)
    return g


def test_incremental_matches_full_on_random_graphs():
    cs = _mixed_constraints()
    saw_deletion = False
    for seed in range(400):
        g = _random_graph(seed)
        full, _ = _assert_same_repair(g, cs)
        saw_deletion = saw_deletion or bool(full.deleted_nodes)
    assert saw_deletion, "random corpus should exercise at least one real repair"


# ---------- the incremental path actually does less work ---------------------

def test_incremental_skips_untouched_constraints():
    """
    Round 1 deletes a lone part-of witness whose only edge is P361, so only the
    P361 rule is dirty for the verification round; the two country rules (labels
    P17/P31/P279) are skipped. full re-checks all 3 twice (6); incremental does 3+1.
    """
    cs = _mixed_constraints()
    g = DataGraph()
    for cls in ("Q6256", "Q2221906", "Q4936952"):
        g.set_value(cls, cls)
    g.add_edge("x", "wdt:P361", "w")   # x has part-of but no type, and no P17 anywhere

    full, inc = _assert_same_repair(g, cs)
    assert full.deleted_nodes == {"x"} == inc.deleted_nodes
    assert full.recheck_count == 6      # 3 constraints x (deletion round + verify round)
    assert inc.recheck_count == 4       # 3 (round 1) + 1 (only dom_partof dirty in verify)
    assert inc.recheck_count < full.recheck_count
