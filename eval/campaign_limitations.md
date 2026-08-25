# What this campaign does not show

Each limitation carries the measured size of the gap and what it would take to close it, so the future-work section has something to start from rather than an adjective.

## The slices are size-capped samples, not knowledge graphs

Every cell is a 1000-edge or 10000-edge slice grown by a seed-anchored walk. The P8a frontier probe fetched the same cells to their target cap and reached roughly 75000 allow-listed edges each, with thousands of nodes still unvisited, so a 1000-edge slice is on the order of **1.3 percent** of what those seeds alone reach, and the seeds are themselves a hand-picked set of 43 entities or fewer. Nothing here generalises to a whole knowledge graph.

*To close it:* run the campaign on the generation B ladder up to the 50000 rung, which P8a built and verified nests. That is compute, not new method.

## The constraints were authored by the person who built the toolkit

27 constraints across 7 sets (19 ptime_core, 8 boundary), all written by the author. No domain expert reviewed them, and the sign-off is still an open item. A repair is only as good as the theory it repairs against, and that theory is unvalidated.

*To close it:* domain-expert review of the constraint sets, which is a scheduled item rather than an open problem.

## The source is the only gold standard for additions

Accuracy of additions asks whether the source agrees, so a correct addition the source also lacks counts against the score, and an addition both share counts for it even if both are wrong. The measure is agreement, not truth, and it cannot be otherwise without an independent reference.

*To close it:* a hand-adjudicated sample, which is human time rather than method. A few hundred triples would give the agreement measure a calibration point.

## Boundary constraints are validated and never repaired

8 of the 27 constraints are boundary tier, and **537 boundary violations remain across 11 of the 23 completed cells** after repair. Symmetry as a path constraint pushes subset repair to NP-completeness (Theorem 11), and the upper-cardinality and inverse shapes need negation, so both sit outside the tractable fragment by construction. A graph this campaign calls repaired is repaired with respect to the ptime_core tier only.

*To close it:* nothing incremental. It needs an intractable algorithm or an approximation carrying its own guarantees, which is a different project.

## One cell is bounded by its allow-list, not by its source

P8a measured DBpedia geography exhausting at 751 allow-listed edges, with 98.2 percent of the sampled structure dropped by the allow-list and 3 of 151 predicates admitted. The 1000-edge slice used here is at the ceiling of what that cell can offer. Its 2 additions are too few to quote a proportion, and its numbers are not a source-level comparison against Wikidata.

*To close it:* widen the DBpedia allow-list, which is an allow-list scope decision and not one this campaign may take.

## The cap bounds nodes deleted, not edges destroyed

The subset cap compares the union of witness nodes against the node count. On `wikidata:geography:1000:subset` it passed, and the repair then removed **95.9 percent of the edges** by cascade, because deleting a node takes every edge incident to it with it. A cap expressed over nodes does not bound the damage expressed over edges.

*To close it:* a second cap on the edge fraction, a small change to `caps.py`, deliberately not made here: this campaign runs the caps as they shipped.
