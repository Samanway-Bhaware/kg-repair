"""
Three hand-built graphs small enough to score by hand.

Each one isolates a property the search has to get right, and each is small
enough that the expected admitted set can be written out and checked by reading
the graph rather than by running the code. That is what makes them usable as the
oracle's own correctness test: if the enumerator and the hand count disagree, the
hand count is the appeal.

  A  clean typing        one class with a superclass, one predicate, no silence
  B  silence             a body where a quarter of the nodes carry no type at all
  C  path heads          no typing at all, one rare predicate, two-step heads
"""
from __future__ import annotations

from kgrepair import DataGraph
from kgrepair.search import SearchConfig

TYPE = "wdt:P31"
SUBCLASS = "wdt:P279"


def _typed(g: DataGraph, node: str, cls: str) -> None:
    g.add_edge(node, TYPE, cls)
    g.set_value(cls, cls)


 
# A: clean typing
 
def graph_a() -> DataGraph:
    """Six nodes, each with one `wd:cap` edge and each typed City, where City is a
    subclass of Geo. Everything that can hold, holds."""
    g = DataGraph()
    g.add_edge("wd:City", SUBCLASS, "wd:Geo")
    g.set_value("wd:City", "wd:City")
    g.set_value("wd:Geo", "wd:Geo")
    for i in range(6):
        g.add_edge(f"wd:x{i}", "wd:cap", f"wd:c{i}")
        _typed(g, f"wd:x{i}", "wd:City")
    return g


CONFIG_A = SearchConfig(min_support=5, min_confidence=0.9,
                        max_antecedent=1, max_path=1)


 
# B: silence
 
def graph_b() -> DataGraph:
    """Twelve nodes with a `wd:cap` edge. Nine are typed City; three carry no type
    edge at all. The three are the ones a repair would fix and a score must not
    count against the rule."""
    g = DataGraph()
    for i in range(9):
        g.add_edge(f"wd:x{i}", "wd:cap", f"wd:c{i}")
        _typed(g, f"wd:x{i}", "wd:City")
    for i in range(9, 12):
        g.add_edge(f"wd:x{i}", "wd:cap", f"wd:c{i}")
    return g


CONFIG_B = SearchConfig(min_support=5, min_confidence=0.9,
                        max_antecedent=1, max_path=1)

#: The pair graph B exists to hold: the rule every silent node breaks.
B_BODY = "< down(wd:cap) >"
B_HEAD = '< down(wdt:P31) . down(wdt:P279)* . [val("wd:City")] >'
B_SILENT = {"wd:x9", "wd:x10", "wd:x11"}


 
# C: path heads
 
def graph_c() -> DataGraph:
    """Six `p` edges into six `q` edges, plus a rare `r` with two edges standing
    apart from everything else.

    No typing spine at all, so the config names one that does not occur: the
    vocabulary then has no classes and every predicate is minable, which is what
    puts the whole weight of the test on the path heads.
    """
    g = DataGraph()
    for i in range(6):
        g.add_edge(f"n:a{i}", "n:p", f"n:b{i}")
        g.add_edge(f"n:b{i}", "n:q", f"n:c{i}")
    g.add_edge("n:z0", "n:r", "n:z1")
    g.add_edge("n:z2", "n:r", "n:z3")
    return g


CONFIG_C = SearchConfig(min_support=5, min_confidence=0.9,
                        max_antecedent=1, max_path=2,
                        type_predicate=TYPE, subclass_predicate=SUBCLASS)


#: (name, graph factory, config) for the tests that sweep all three.
ALL_THREE = (("A", graph_a, CONFIG_A),
             ("B", graph_b, CONFIG_B),
             ("C", graph_c, CONFIG_C))


 
# D: the meta-class idiom, in the shape residual profiling is for
 
#: The two classes, named the way `tests/test_constraints_v2.py` names them.
DISEASE = "wd:Q12136"                  # 'disease'
TYPE_OF_DISEASE = "wd:Q112193867"      # 'type of disease', the meta-class


def graph_meta_class() -> DataGraph:
    """Eighteen things with a symptom. Twelve are typed disease directly; six are
    typed through the meta-class idiom instead, which no amount of subclass
    walking reaches from disease.

    This is the C1 finding from `docs/constraints_v2.md` reduced to a fixture: the
    rule "anything with a symptom is a disease" is right about the domain and
    scores badly on the data, and the reason is a naming idiom rather than a
    counterexample. It is the case residual profiling exists to surface.
    """
    g = DataGraph()
    g.set_value(DISEASE, DISEASE)
    g.set_value(TYPE_OF_DISEASE, TYPE_OF_DISEASE)
    for i in range(12):
        g.add_edge(f"wd:illness{i}", "wdt:P780", f"wd:symptom{i}")
        g.add_edge(f"wd:illness{i}", "wdt:P31", DISEASE)
    for i in range(6):
        g.add_edge(f"wd:condition{i}", "wdt:P780", f"wd:sign{i}")
        g.add_edge(f"wd:condition{i}", "wdt:P31", TYPE_OF_DISEASE)
    return g


CONFIG_META = SearchConfig(min_support=5, min_confidence=0.9,
                           max_antecedent=1, max_path=1, purity_floor=0.9)

#: The rule the fixture is about, and the widening it should draw out.
META_BODY = "< down(wdt:P780) >"
META_HEAD = f'< down(wdt:P31) . down(wdt:P279)* . [val("{DISEASE}")] >'
META_ATOM = f"c_{TYPE_OF_DISEASE}"
