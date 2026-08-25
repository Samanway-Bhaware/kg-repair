"""
P4c/T2: fetch Wikidata property constraints (P2302) for the predicates in the
committed slices, and cache them as a standalone artifact.

Third-party ground truth. These constraints were written by the Wikidata community,
not by this project's author, which is what makes them a stronger yardstick than
agreement with the authored sets. The cache is the artifact the evaluation reads;
the evaluation never touches the network, so it stays repeatable offline once this
has run.

Read through `Special:EntityData`, one entity document per property, rather than
through the query service. The query service was rate-limiting to one request per
minute during an outage when this was written, and the constraint statements are
plain claims on the property entity, so the entity endpoint answers the same
question without depending on a degraded service. A failure loses one property
rather than the run. Results are written sorted, with no wall-clock field, so
re-fetching unchanged data rewrites the same bytes.

Scripts-only dependency: `certifi`, for a trust store the stdlib does not ship with
on this platform. Like matplotlib in `build_evaluation.py`, this is reporting
tooling and not the toolkit; `src/kgrepair/` remains stdlib-only.

Usage:  python scripts/fetch_p2302.py [--out data/raw/constraints/wikidata_p2302.json]
"""
from __future__ import annotations

import argparse
import json
import os
import ssl
import sys
import time
import urllib.parse
import urllib.request

ROOT = os.path.join(os.path.dirname(__file__), "..")
DEFAULT_OUT = os.path.join(ROOT, "data", "raw", "constraints", "wikidata_p2302.json")
ENDPOINT = "https://www.wikidata.org/wiki/Special:EntityData/{}.json"
USER_AGENT = "kgrepair-eval/0.5 (open-source toolkit; offline evaluation cache)"

#: The constraint qualifiers this evaluation reads: the class a constraint names,
#: the relation it uses (instance-of or subclass-of), and the property it points at.
QUALIFIER_CLASS, QUALIFIER_RELATION, QUALIFIER_PROPERTY = "P2308", "P2309", "P2306"

#: Every non-typing predicate that occurs in the committed Wikidata slices, which is
#: what the derivation can propose rules about.
PREDICATES = [
    "P17", "P30", "P36", "P47", "P105", "P131", "P171", "P206", "P361", "P527",
    "P780", "P828", "P1376", "P2175",
]

def _context():
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def _qid(url):
    return url.rsplit("/", 1)[-1] if isinstance(url, str) and url.startswith("http") else url


def _qualifier_values(qualifiers, pid):
    """Every item id a qualifier carries, sorted. A constraint may name several
    classes, and the evaluation treats them as alternatives."""
    out = []
    for snak in qualifiers.get(pid, []):
        value = snak.get("datavalue", {}).get("value", {})
        if isinstance(value, dict) and value.get("id"):
            out.append(value["id"])
    return sorted(set(out))


def fetch_one(prop: str, context, timeout: int = 60):
    """The P2302 constraint statements on one property, as plain records."""
    req = urllib.request.Request(ENDPOINT.format(prop),
                                 headers={"User-Agent": USER_AGENT,
                                          "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout, context=context) as resp:
        payload = json.loads(resp.read().decode("utf-8"))

    entity = payload["entities"][prop]
    rows = []
    for statement in entity.get("claims", {}).get("P2302", []):
        mainsnak = statement.get("mainsnak", {})
        value = mainsnak.get("datavalue", {}).get("value", {})
        if not isinstance(value, dict) or not value.get("id"):
            continue
        qualifiers = statement.get("qualifiers", {})
        rows.append({
            "constraint_type": value["id"],
            "classes": _qualifier_values(qualifiers, QUALIFIER_CLASS),
            "relation": (_qualifier_values(qualifiers, QUALIFIER_RELATION) or [None])[0],
            "properties": _qualifier_values(qualifiers, QUALIFIER_PROPERTY),
            "rank": statement.get("rank", "normal"),
        })
    # sorted and de-duplicated, so the cache is byte-stable across fetches
    deduplicated = {json.dumps(r, sort_keys=True) for r in rows}
    return [json.loads(r) for r in sorted(deduplicated)]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--sleep", type=float, default=0.5,
                    help="seconds between queries, to stay a polite client")
    args = ap.parse_args(argv)

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    context = _context()
    cache, failed = {}, []
    for prop in PREDICATES:
        try:
            cache[prop] = fetch_one(prop, context)
            sys.stdout.write(f"{prop}: {len(cache[prop])} constraint statement(s)\n")
        except Exception as exc:                     # one property, not the run
            failed.append(prop)
            sys.stderr.write(f"{prop}: {type(exc).__name__}: {exc}\n")
        time.sleep(args.sleep)

    payload = {"endpoint": ENDPOINT, "properties": sorted(cache),
               "failed": sorted(failed), "constraints": cache}
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, sort_keys=True)
        fh.write("\n")
    sys.stdout.write(f"wrote {args.out} ({len(cache)} properties, {len(failed)} failed)\n")
    return 1 if failed and not cache else 0


if __name__ == "__main__":
    raise SystemExit(main())
