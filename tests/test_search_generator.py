"""
P4d: the two-axis search as the default generator, with the shape sweep selectable.

What this file holds, and what it deliberately does not. It holds the switch: that
`derive_candidates` routes on `DeriveConfig.generator`, that both values run end to
end from the library, the command line and the viewer, that a candidate file says
which one produced it, and that the search reaches all four repairable shapes. It
does not re-check the search's scoring or its pruning laws; those are
`test_search_core.py` (against the unpruned oracle) and `test_search_shaping.py`.

The adapter in `derive._derive_by_search` applies no floor of its own, so there is
nothing here that could admit a rule the search did not.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

import kgrepair
from kgrepair.derive import (GENERATORS, SEARCH, SHAPES, DeriveConfig,
                             derive_candidates)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GEO = os.path.join(ROOT, "fixtures", "real", "real_wikidata_geography_1000.nt")
TAXA = os.path.join(ROOT, "fixtures", "real", "real_wikidata_taxa_1000.nt")

FOUR_SHAPES = ("existential_domain", "existential_range",
               "typing_existence", "requires_statement")


def _geo():
    return kgrepair.load_graph(GEO)


 
# the switch
 
def test_the_default_generator_is_the_search():
    assert DeriveConfig().generator == SEARCH
    assert set(GENERATORS) == {SEARCH, SHAPES}


def test_both_generators_run_and_produce_different_candidate_sets():
    """Interchangeable in shape, not in content. If the two returned the same set
    the switch would be a rename rather than a change, and this test would be
    passing for the wrong reason."""
    graph = _geo()
    search_result = derive_candidates(graph, "geography", "wikidata",
                                      DeriveConfig(generator=SEARCH))
    shape_result = derive_candidates(graph, "geography", "wikidata",
                                     DeriveConfig(generator=SHAPES))

    for result in (search_result, shape_result):
        assert result.stats["emitted"] == len(result.constraints) > 0
        assert result.vocab["type_predicate"] and result.vocab["subclass_predicate"]
        kept = [r for r in result.report if not r["pruned_redundant"]]
        assert len(kept) == len(result.constraints)
    # the shape sweep reports the rows its reduced cover dropped; the search drops
    # its own before scoring, so every row it reports is a candidate
    assert len(shape_result.report) > len(shape_result.constraints)
    assert len(search_result.report) == len(search_result.constraints)

    assert len(search_result.constraints) > len(shape_result.constraints)
    assert ({c.antecedent for c in search_result.constraints}
            != {c.antecedent for c in shape_result.constraints})


def test_an_unknown_generator_is_refused_by_name():
    with pytest.raises(ValueError) as caught:
        derive_candidates(_geo(), "geography", "wikidata",
                          DeriveConfig(generator="whatever"))
    assert "whatever" in str(caught.value)


def test_both_generators_are_deterministic():
    for generator in GENERATORS:
        cfg = DeriveConfig(generator=generator)
        first = derive_candidates(_geo(), "geography", "wikidata", cfg)
        second = derive_candidates(_geo(), "geography", "wikidata", cfg)
        assert [c.to_dict() for c in first.constraints] == \
               [c.to_dict() for c in second.constraints]
        assert first.report == second.report and first.stats == second.stats


 
# what the search reaches
 
def test_the_search_reaches_all_four_repairable_shapes():
    """The shape is read back off what the search produced rather than generated
    from a template, so this asserts the reading covers the four the engines act
    on. Taxa is the slice where all four appear at once."""
    result = derive_candidates(kgrepair.load_graph(TAXA), "taxa", "wikidata",
                               DeriveConfig(generator=SEARCH))
    kinds = {c.kind for c in result.constraints}
    assert set(FOUR_SHAPES) <= kinds


def test_every_search_candidate_is_in_fragment_and_validates():
    """The fragment guard runs on every emitted candidate, and each one parses and
    evaluates against the graph it came from without raising."""
    graph = _geo()
    result = derive_candidates(graph, "geography", "wikidata",
                               DeriveConfig(generator=SEARCH))
    report = kgrepair.validate(graph, result.constraints)
    assert len(report.violations) == len(result.constraints)
    for c in result.constraints:
        assert c.tier == "ptime_core" and c.provenance == "mined"
        assert c.params["miner"] == "search_v1"


def test_a_widening_reaches_the_candidate_set_as_a_weakening():
    """Residual profiling emits disjunctive consequents, which the shape sweep has
    no template for. They arrive as `weakening` candidates, which is a shape the
    other generator cannot produce at all."""
    result = derive_candidates(_geo(), "geography", "wikidata",
                               DeriveConfig(generator=SEARCH))
    weakenings = [c for c in result.constraints if c.kind == "weakening"]
    assert weakenings, "the geography slice is expected to yield widenings"
    assert all(" | " in c.consequent for c in weakenings)
    assert all(c.direction == "superset" for c in weakenings)


 
# a candidate file says how it was produced
 
def test_a_candidate_file_records_its_generator():
    graph = _geo()
    for generator in GENERATORS:
        cf = kgrepair.derive_candidate_file(graph, "geography", "wikidata",
                                            generator=generator)
        assert cf.parameters["generator"] == generator


def test_the_generator_argument_overrides_the_config():
    cf = kgrepair.derive_candidate_file(
        _geo(), "geography", "wikidata",
        config=DeriveConfig(generator=SEARCH), generator=SHAPES)
    assert cf.parameters["generator"] == SHAPES


def test_an_unknown_generator_argument_is_refused():
    with pytest.raises(ValueError):
        kgrepair.derive_candidate_file(_geo(), "geography", "wikidata",
                                       generator="whatever")


 
# end to end: the command line and the viewer agree
 
def _run_cli(tmp_path, generator):
    out = os.path.join(str(tmp_path), f"candidates.{generator}.json")
    code = subprocess.run(
        [sys.executable, "-m", "kgrepair", "derive", "--in", GEO, "--out", out,
         "--domain", "geography", "--kg", "wikidata", "--generator", generator],
        capture_output=True, text=True, check=False)
    assert code.returncode == 0, code.stderr
    with open(out, encoding="utf-8") as fh:
        return json.load(fh)


def test_both_generators_run_from_the_command_line(tmp_path):
    for generator in GENERATORS:
        written = _run_cli(tmp_path, generator)
        assert written["parameters"]["generator"] == generator
        assert written["candidates"]
        assert all(c["status"] == "pending" for c in written["candidates"])


def test_the_viewer_and_the_command_line_derive_the_same_file(tmp_path):
    """T3's gate. The viewer reaches the generator through a plain string, because
    `DeriveConfig` is internal and the viewer may only touch the public API; the
    file it builds is the same one the command line writes at the same settings."""
    from app import logic

    for generator in GENERATORS:
        from_cli = _run_cli(tmp_path, generator)
        queue = logic.start_review(_geo(), "geography", "wikidata",
                                   dataset=os.path.basename(GEO),
                                   generator=generator)
        from_viewer = queue.candidate_file.to_dict()
        assert from_viewer["parameters"] == from_cli["parameters"]
        assert ([c["cid"] for c in from_viewer["candidates"]]
                == [c["cid"] for c in from_cli["candidates"]])
        assert from_viewer["candidates"] == from_cli["candidates"]
