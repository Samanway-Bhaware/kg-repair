"""
P8b/T4: accuracy of superset-repair additions against the source knowledge graph.

Superset repair adds edges. This asks the source whether it agrees, for a sample of
them, and reports the proportion corroborated with a confidence interval.

Why this lives in `scripts/` and not in `kgrepair.metrics`: it is the one metric in
`docs/quality_metrics.md` that needs a source query, and the library is network-free.
It takes a repair report or a change log as input, so it runs after a repair rather
than inside one.

Level 0. Each check is a SPARQL ASK, which returns a single boolean. No triple, no
label and no object value comes back, so nothing person-pointing enters this process
at any point. That is the same discipline the P8a coverage probe used.

What a contradicted addition means. It means the source does not assert that triple.
It does not mean the triple is false: the slice and the source can both be incomplete
in the same place, and the D6 work found most contradictions there traced to
constraint scoping rather than to a repair defect. The number below is agreement with
the source, and the report says so.

Usage:
  export SSL_CERT_FILE=$(python3 -c "import certifi;print(certifi.where())")
  python scripts/addition_accuracy.py --report run.json --source wikidata
  python scripts/addition_accuracy.py --report run.json --source wikidata --sample 100
"""
from __future__ import annotations

import argparse
import json
import math
import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from kgrepair.pipeline import load_allowlist                               # noqa: E402
from kgrepair.pipeline.extract import DBPEDIA_ENDPOINT, WIKIDATA_ENDPOINT  # noqa: E402
from kgrepair.pipeline.fetch import FetchPolicy, PoliteFetcher             # noqa: E402

ROOT = os.path.join(os.path.dirname(__file__), "..")
OUT_DIR = os.path.join(ROOT, "eval")

#: Sampling is a fixed-seed simple random sample without replacement. Simple random
#: rather than systematic-over-sorted, because the change log is ordered by repair
#: round and constraint, and every systematic rule over that order risks sampling one
#: constraint's additions in a block. Fixed seed so a run is reproducible.
DEFAULT_SEED = 20260806
DEFAULT_SAMPLE = 60
CONFIDENCE_Z = 1.959963984540054          # two-sided 95 percent

#: Below this many additions, a proportion is not worth quoting. Three corroborated
#: out of four is 0.75 with an interval running from roughly 0.3 to 0.95, which is
#: not a measurement of anything. Such a cell reports its raw counts and says so.
MIN_FOR_PROPORTION = 10


def wilson_interval(successes: int, trials: int, z: float = CONFIDENCE_Z):
    """The Wilson score interval for a binomial proportion.

    Used rather than the normal approximation because the proportion is expected near
    an extreme and the sample is small, which is where the normal interval is known to
    run outside [0, 1] and to under-cover.
    """
    if trials == 0:
        return (None, None)
    phat = successes / trials
    denom = 1 + z * z / trials
    centre = (phat + z * z / (2 * trials)) / denom
    margin = (z * math.sqrt(phat * (1 - phat) / trials
                            + z * z / (4 * trials * trials))) / denom
    return (round(max(0.0, centre - margin), 4), round(min(1.0, centre + margin), 4))


def added_edges(payload) -> list:
    """Every `add_edge` record in a repair report or a bare change log."""
    if isinstance(payload, dict):
        changelog = (payload.get("result") or {}).get("changelog")
        if changelog is None:
            changelog = payload.get("changelog")
    else:
        changelog = payload
    if not changelog:
        return []
    return [(r["src"], r["label"], r["dst"]) for r in changelog
            if r.get("op") == "add_edge"]


def expand(curie: str, prefixes) -> str:
    if ":" not in curie:
        return curie
    prefix, rest = curie.split(":", 1)
    namespace = prefixes.get(prefix)
    return f"{namespace}{rest}" if namespace else curie


#: (type predicate, subclass predicate) per source, for the entailed check below.
_SPINE = {"wikidata": ("wdt:P31", "wdt:P279"),
          "dbpedia": ("rdf:type", "rdfs:subClassOf")}


def ask_exact(fetcher, endpoint, triple, prefixes) -> bool:
    """Does the source assert this exact triple?"""
    s, p, o = (expand(t, prefixes) for t in triple)
    return fetcher.sparql_ask(endpoint, f"ASK {{ <{s}> <{p}> <{o}> }}")


def ask_entailed(fetcher, endpoint, triple, prefixes, source) -> bool:
    """Does the source agree that the subject is an instance of that class, allowing
    for a more specific type?

    The exact check is too strict for a typing addition. Superset repair adds
    `x isa C` to satisfy a class test that is itself `isa . subclass-of*`, so the
    source can perfectly well agree while asserting only `x isa D` with `D` a subclass
    of `C`. Asking the exact triple then scores a correct addition as contradicted,
    which is a defect in the question rather than in the repair.

    Both numbers are reported. Exact agreement says whether the source states the same
    triple; entailed agreement says whether the source states something that implies
    it. For a non-typing addition the two are the same question and only the exact one
    is asked.
    """
    type_pred, subclass_pred = _SPINE[source]
    if triple[1] != type_pred:
        return None
    s, _p, o = (expand(t, prefixes) for t in triple)
    tp, sp = expand(type_pred, prefixes), expand(subclass_pred, prefixes)
    return fetcher.sparql_ask(
        endpoint, f"ASK {{ <{s}> <{tp}>/<{sp}>* <{o}> }}")


def _write(payload, path):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, sort_keys=True)
        fh.write("\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", required=True,
                    help="a repair report JSON, or a bare change-log JSON")
    ap.add_argument("--source", required=True, choices=["wikidata", "dbpedia"])
    ap.add_argument("--sample", type=int, default=DEFAULT_SAMPLE)
    ap.add_argument("--seed", type=int, default=DEFAULT_SEED)
    ap.add_argument("--min-interval", type=float, default=1.0)
    ap.add_argument("--out", default=os.path.join(OUT_DIR, "addition_accuracy.json"))
    args = ap.parse_args()

    with open(args.report, encoding="utf-8") as fh:
        payload = json.load(fh)
    additions = sorted(set(added_edges(payload)))
    if not additions:
        print("no add_edge records in that report, so there is nothing to check")
        _write({"source": args.source, "additions_total": 0,
                "status": "NO-ADDITIONS",
                "note": "the engine added no edge, so accuracy is not defined here"},
               args.out)
        return 0
    if len(additions) < MIN_FOR_PROPORTION:
        print(f"only {len(additions)} addition(s): too few to quote a proportion")
        _write({"source": args.source, "additions_total": len(additions),
                "status": "TOO-FEW-TO-SAMPLE",
                "minimum_for_a_proportion": MIN_FOR_PROPORTION,
                "additions": [list(t) for t in additions],
                "note": ("a proportion over this many edges carries an interval so "
                         "wide it states nothing; the additions are listed instead")},
               args.out)
        return 0

    rng = random.Random(args.seed)
    size = min(args.sample, len(additions))
    sample = sorted(rng.sample(additions, size))

    al = load_allowlist(args.source)
    endpoint = WIKIDATA_ENDPOINT if args.source == "wikidata" else DBPEDIA_ENDPOINT
    fetcher = PoliteFetcher(FetchPolicy(min_interval_s=args.min_interval, timeout_s=60))

    exact_yes = entailed_yes = 0
    rows = []
    for triple in sample:
        try:
            exact = ask_exact(fetcher, endpoint, triple, al.prefixes)
            entailed = ask_entailed(fetcher, endpoint, triple, al.prefixes, args.source)
            error = None
        except Exception as exc:                  # a failed check is reported, not fatal
            exact, entailed, error = None, None, f"{type(exc).__name__}: {exc}"
        # A non-typing addition has no entailed form, so the exact answer is the only
        # answer and stands in for both.
        effective = exact if entailed is None else entailed
        exact_yes += 1 if exact else 0
        entailed_yes += 1 if effective else 0
        rows.append({"triple": list(triple), "corroborated_exact": exact,
                     "corroborated_entailed": entailed, "error": error})
        mark = "ERR" if error else ("yes" if exact else ("via*" if effective else "no "))
        print(f"  {mark}  {triple}", flush=True)

    checked = sum(1 for r in rows if r["error"] is None)
    low, high = wilson_interval(entailed_yes, checked)
    exact_low, exact_high = wilson_interval(exact_yes, checked)
    result = {
        "source": args.source,
        "additions_total": len(additions),
        "sampling_rule": (f"simple random sample without replacement, seed "
                          f"{args.seed}, over the deduplicated sorted add_edge set"),
        "sample_size": size,
        "checked": checked,
        "corroborated_exact": exact_yes,
        "corroborated_entailed": entailed_yes,
        "proportion_exact": round(exact_yes / checked, 4) if checked else None,
        "proportion_entailed": round(entailed_yes / checked, 4) if checked else None,
        "confidence": "95 percent Wilson score interval",
        "interval_exact": [exact_low, exact_high],
        "interval_entailed": [low, high],
        "note": ("Agreement with the source, not truth. A triple the source does not "
                 "assert may still be correct: the slice and the source can be "
                 "incomplete in the same place. Read the entailed proportion as the "
                 "headline for typing additions: the exact one asks whether the "
                 "source states the same triple, which is too strict for a class "
                 "test the source satisfies with a more specific type."),
        "checks": rows,
    }
    _write(result, args.out)
    print(f"\nexact:    {exact_yes}/{checked} ({result['proportion_exact']}), "
          f"95 percent interval [{exact_low}, {exact_high}]")
    print(f"entailed: {entailed_yes}/{checked} ({result['proportion_entailed']}), "
          f"95 percent interval [{low}, {high}]")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
