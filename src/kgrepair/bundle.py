"""
The output bundle: everything a repair run produces, in one directory.

A repair answers a question about someone's data, and the answer is not just the
repaired graph. It is the repaired graph, what changed, what the rules were, and
what the run attested. Four files, so that a person who receives the directory can
check the work without having the toolkit to hand:

    repaired.nt           the repaired graph, sorted canonical N-Triples
    changes.nt.diff       one line per statement added or removed, with a marker
    report.json           the run record: engine, constraint provenance, caps,
                          attestations, and whether the graph came out consistent
    constraints.used.json the constraint file the run was given, copied verbatim

The diff is reversible on purpose. `repaired.nt` with the diff applied backwards
reproduces the input, byte for byte against its canonical serialisation, and
`reconstruct_input` does exactly that so a test can assert it rather than a reader
having to trust it.

A run stopped by a safety cap still gets a bundle. It has no `repaired.nt` and no
diff, because no engine ran, and its `report.json` says so and says why. Handing
back nothing would tell the user only that something did not happen.
"""
from __future__ import annotations

import json
import os
import zipfile
from typing import Dict, Iterable, List, Optional, Tuple

from .datagraph import DataGraph
from .ntriples import to_ntriples

#: The files a complete bundle carries.
REPAIRED = "repaired.nt"
DIFF = "changes.nt.diff"
REPORT = "report.json"
CONSTRAINTS = "constraints.used.json"

#: Line markers in the diff. One character, so a line stays a statement plus a mark.
ADDED, REMOVED = "+", "-"


def _statement(triple: Tuple[str, str, str]) -> str:
    src, label, dst = triple
    return f"<{src}> <{label}> <{dst}> ."


def diff_lines(before: DataGraph, after: DataGraph) -> List[str]:
    """The statement-level difference between two graphs, sorted.

    Removals first, then additions, each block sorted, so two runs over the same
    pair of graphs write the same file. Node-only changes do not appear: N-Triples
    has no way to write an isolated node, so a node that lost or gained no edge is
    not a statement. The change log in `report.json` carries those.
    """
    old, new = set(before.edges()), set(after.edges())
    lines = [f"{REMOVED} {_statement(t)}" for t in sorted(old - new)]
    lines += [f"{ADDED} {_statement(t)}" for t in sorted(new - old)]
    return lines


def parse_diff(text: str) -> Tuple[List[str], List[str]]:
    """(removed, added) statement lines, from a diff this module wrote."""
    removed, added = [], []
    for line in text.splitlines():
        if not line.strip():
            continue
        marker, statement = line[0], line[2:]
        if marker == REMOVED:
            removed.append(statement)
        elif marker == ADDED:
            added.append(statement)
        else:
            raise ValueError(f"unrecognised diff line: {line!r}")
    return removed, added


def reconstruct_input(repaired_text: str, diff_text: str) -> str:
    """Apply the diff backwards to the repaired graph, returning the input.

    Take out what the repair added, put back what it removed, sort. The result is
    the canonical serialisation of the graph that went in, which is what makes the
    diff an auditable record rather than a summary of one.
    """
    removed, added = parse_diff(diff_text)
    statements = {line for line in repaired_text.splitlines() if line.strip()}
    statements -= set(added)
    statements |= set(removed)
    return "".join(line + "\n" for line in sorted(statements))


def write_bundle(directory: str, *, report: Dict,
                 repaired: Optional[DataGraph] = None,
                 original: Optional[DataGraph] = None,
                 constraints_json: Optional[str] = None) -> List[str]:
    """Write a bundle into `directory`, returning the file names written, sorted.

    `repaired` and `original` are both needed for a diff; with neither, the bundle
    is the cap-aborted kind and carries the report alone. Nothing here decides
    whether a repair should have run: it writes down what did.
    """
    os.makedirs(directory, exist_ok=True)
    written: List[str] = []

    if repaired is not None:
        with open(os.path.join(directory, REPAIRED), "w", encoding="utf-8") as fh:
            fh.write(to_ntriples(repaired))
        written.append(REPAIRED)

        if original is not None:
            lines = diff_lines(original, repaired)
            with open(os.path.join(directory, DIFF), "w", encoding="utf-8") as fh:
                fh.write("".join(line + "\n" for line in lines))
            written.append(DIFF)

    if constraints_json is not None:
        with open(os.path.join(directory, CONSTRAINTS), "w", encoding="utf-8") as fh:
            fh.write(constraints_json)
        written.append(CONSTRAINTS)

    with open(os.path.join(directory, REPORT), "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, sort_keys=True)
        fh.write("\n")
    written.append(REPORT)

    return sorted(written)


def zip_bundle(directory: str, archive_path: Optional[str] = None) -> str:
    """Pack a bundle directory into one archive; return the path written.

    Deterministic: entries are added in sorted order with a fixed timestamp, so two
    archives of the same bundle are byte-identical and can be compared.
    """
    archive_path = archive_path or (directory.rstrip(os.sep) + ".zip")
    with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name in sorted(os.listdir(directory)):
            path = os.path.join(directory, name)
            if not os.path.isfile(path):
                continue
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            with open(path, "rb") as fh:
                zf.writestr(info, fh.read())
    return archive_path


def bundle_summary(*, mode: str, constraint_provenance: str,
                   consistent_after: Optional[bool], aborted: bool,
                   reason: Optional[str] = None) -> Dict:
    """The three things T4 asks the report to state, in one place.

    Which engine ran, where the rules came from, and whether the graph came out
    consistent. `consistent_after` is null when no engine ran, which is not the
    same as a repair that ran and did not converge.
    """
    out = {
        "engine": mode,
        "constraint_provenance": constraint_provenance,
        "consistent_after": consistent_after,
        "engine_ran": not aborted,
    }
    if aborted:
        out["reason"] = reason or ("the repair would have touched more of the graph "
                                   "than the safety cap allows, so no engine ran")
    return out
