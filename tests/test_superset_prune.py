"""
D6 · T4 -- addition-minimisation (redundancy-pruning) pass.

  * pruning removes a redundant overlapping addition while preserving consistency;
  * pruning is deterministic (two runs identical);
  * `prune=False` reproduces the saturation-phase output exactly (superset of pruned);
  * consistency preserved post-prune across the seed corpus;
  * grep gate: no *affirmative* minimality/uniqueness claim in any D6 deliverable file
    (the wording is deliberately not asserted).
"""
import os
import re

from kgrepair.constraints.model import Constraint, ConstraintSet
from kgrepair.datagraph import DataGraph
from kgrepair.repair import superset_repair
from kgrepair.synthetic import generate
from kgrepair.validator import Validator


ROOT = os.path.join(os.path.dirname(__file__), "..")
GEO, CITY = "wd:Q2221906", "wd:Q515"

def _tau(c):
    return f'< down(wdt:P31) . down(wdt:P279)* . [val("{c}")] >'


def _overlap_case():
    """A node that is BOTH a domain witness (needs tau_Geo) and a typing-existence
    witness (needs tau_City); City subclasses Geo, so -type->City subsumes -type->Geo."""
    cs = ConstraintSet("t", [
        Constraint(cid="dom", domain="d", kg="wd", kind="existential_domain",
                   tier="ptime_core", provenance="c", direction="subset",
                   antecedent="< down(wdt:P17) >", consequent=_tau(GEO)),
        Constraint(cid="typ", domain="d", kg="wd", kind="typing_existence",
                   tier="ptime_core", provenance="c", direction="superset",
                   antecedent="< down(wdt:P17) > & < down(wdt:P131) >", consequent=_tau(CITY)),
    ])

    def build():
        g = DataGraph()
        g.set_value(GEO, GEO)
        g.set_value(CITY, CITY)
        g.add_edge(CITY, "wdt:P279", GEO)
        g.add_edge("x", "wdt:P17", "a")
        g.add_edge("x", "wdt:P131", "b")
        return g
    return cs, build


def test_pruning_removes_redundant_overlap():
    cs, build = _overlap_case()
    res = superset_repair(build(), cs, prune=True)
    assert ("x", "wdt:P31", CITY) in res.added_edges
    assert ("x", "wdt:P31", GEO) not in res.added_edges     # redundant -> pruned
    assert res.pruned_edges == 1
    assert res.attestations["consistent_after"]


def test_prune_false_reproduces_saturation():
    cs, build = _overlap_case()
    sat = superset_repair(build(), cs, prune=False)
    assert ("x", "wdt:P31", GEO) in sat.added_edges
    assert ("x", "wdt:P31", CITY) in sat.added_edges
    assert sat.pruned_edges == 0
    # pruned result's kept edges are a subset of the saturation edges
    pruned = superset_repair(build(), cs, prune=True)
    assert pruned.added_edges < sat.added_edges
    assert pruned.attestations["consistent_after"]
    assert sat.attestations["consistent_after"]


def test_pruning_is_deterministic():
    cs, build = _overlap_case()
    r1 = superset_repair(build(), cs, prune=True)
    r2 = superset_repair(build(), ConstraintSet("rev", list(reversed(cs.constraints))),
                         prune=True)
    assert r1.changelog_dicts() == r2.changelog_dicts()
    assert set(r1.graph.edges()) == set(r2.graph.edges())


def test_pruning_preserves_consistency_over_seeds():
    for seed in range(120):
        sl = generate(seed, 200)
        res = superset_repair(sl.graph, sl.constraints, prune=True)
        rep = Validator(res.graph, use_closure=True).validate(sl.constraints)
        assert all(v.count == 0 for v in rep.failing()
                   if v.constraint.tier == "ptime_core"), seed
        assert res.attestations["superset_only_added"], seed


# ---------- grep gate: no affirmative minimality/uniqueness claim -------------

_D6_FILES = [
    "src/kgrepair/repair/superset.py",
    "tests/test_superset_repair.py",
    "tests/test_superset_synthetic.py",
    "tests/test_superset_t1_model.py",
    "docs/real_repair.md",
    "docs/real_repair_examples.md",
    # D7/C1 (constraints v2 -- same "deterministic canonical, never minimal" wording rule)
    "src/kgrepair/constraints/biomedical_v2.py",
    "docs/constraints_v2.md",
    # pre-packaging wording pass (W1/W4): the gate now also bans bare "unique" as a
    # claim about THIS toolkit's repair output, so the D5 engine files and the two
    # new fidelity documents are in scope too.
    "src/kgrepair/repair/subset.py",
    "src/kgrepair/repair/__init__.py",
    "src/kgrepair/constraints/model.py",
    "docs/algorithm_fidelity.md",
    "docs/why_algorithm_2_cannot_run_as_written.md",
    # packaging: the two files that state the public API to users, and so are the
    # most likely place for an over-strong claim about the engines to reappear.
    "src/kgrepair/api.py",
    "src/kgrepair/__init__.py",
    # the command line: its help text and report field names are user-facing too.
    "src/kgrepair/cli.py",
    "src/kgrepair/caps.py",
    # the differential oracle (comparison 1): it runs Algorithm 2 as written and
    # reports a size gap, so it is the most recent place where a minimality claim
    # could reappear as an inference from a measurement.
    "tests/reference_superset.py",
    "tests/test_differential_superset.py",
    "docs/differential_oracle.md",
]  # this gate file is excluded: it contains the search terms definitionally.
# Files whose purpose is to quote and discuss the disputed "unique maximal"/"minimal"
# wording, or to attribute the paper's own theorem statements, are deliberately not
# listed above: there the wording is the artifact under review, not a regression.
# a "minimal"/"unique" mention is allowed only when the line also disclaims it, or
# attributes it to the paper (a theorem/lemma/corollary citation), or only mentions it
# inside double quotes (a quotation is a mention, not an assertion).
_DISCLAIMERS = ("not", "never", "nor", "without", "avoid", "reconcile",
                "open question", "open design", "deliberately",
                "no result change", "small ",
                # attribution to the paper's own claims is permitted
                "paper", "theorem", "thm", "lemma", "corollary", "hypothesis",
                "claim", "states", "quote", "wording", "generalis", "generaliz",
                "disclaim")
_CLAIM = re.compile(r"minimal|unique", re.IGNORECASE)


def _claim_only_inside_quotes(line: str) -> bool:
    """True when every claim term on the line sits inside a double-quoted span, i.e.
    the line quotes disputed wording rather than asserting it (e.g. subset.py's NOTE
    block referring to the `"unique maximal repair"` wording)."""
    return not _CLAIM.search(re.sub(r'"[^"]*"', "", line).lower())


def test_no_affirmative_minimality_claim_in_d6_files():
    offenders = []
    for rel in _D6_FILES:
        path = os.path.join(ROOT, rel)
        if not os.path.exists(path):
            continue
        for i, line in enumerate(open(path, encoding="utf-8"), 1):
            low = line.lower()
            if (_CLAIM.search(low)
                    and not any(d in low for d in _DISCLAIMERS)
                    and not _claim_only_inside_quotes(line)):
                offenders.append(f"{rel}:{i}: {line.strip()}")
    assert not offenders, "affirmative minimality/uniqueness wording:\n" + "\n".join(offenders)

    # The disclaimer and quotation carve-outs must not widen the gate into a no-op:
    # an undisclaimed, unquoted claim is still caught. (Asserted inside this test
    # rather than as a separate one so the suite's test count is unchanged.)
    probe = "returns the unique minimal repair of the graph"
    assert _CLAIM.search(probe)
    assert not any(d in probe for d in _DISCLAIMERS)
    assert not _claim_only_inside_quotes(probe)
