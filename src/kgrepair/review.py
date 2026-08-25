"""
The load gate: what a candidate file has to satisfy before an engine sees it.

Every refusal here is a named exception carrying a stable `code`. The command
line reports the whole class as exit 4, a pre-flight refusal, and prints the code
so a caller can tell the causes apart without a second exit code for each.

    E-SCHEMA     not a candidate file this toolkit understands
    E-UNSEALED   nobody sealed it
    E-PENDING    a reviewer has not decided every entry
    E-SEAL       the recorded seal does not recompute, so the file changed
    E-DRIFT      the graph is not the one the candidates were derived from
    E-FRAGMENT   an accepted constraint leaves the positive fragment
    E-BOUNDARY   an accepted constraint is boundary tier and cannot be repaired
    E-EMPTY      nothing was accepted, so there is nothing to load

Each message names the offending cid where the refusal is about one entry.
"""
from __future__ import annotations

from typing import Optional

from .candidates import CandidateFile, verify_seal
from .constraints.model import Constraint, ConstraintSet
from .datagraph import DataGraph


class CandidateGateError(Exception):
    """A candidate file was refused before any engine ran.

    `code` is the stable identifier for the cause and `cid` names the offending
    entry when the refusal is about one.
    """
    code = "E-GATE"

    def __init__(self, message: str, cid: Optional[str] = None):
        super().__init__(f"[{self.code}] {message}")
        self.cid = cid


class NotSealed(CandidateGateError):
    """The file was never sealed, so no one vouched for its contents."""
    code = "E-UNSEALED"


class ReviewIncomplete(CandidateGateError):
    """At least one entry is still pending a decision."""
    code = "E-PENDING"


class SealMismatch(CandidateGateError):
    """The seal does not recompute: the file changed after it was sealed."""
    code = "E-SEAL"


class SourceDrift(CandidateGateError):
    """The graph being repaired is not the graph the candidates came from."""
    code = "E-DRIFT"


class OutOfFragment(CandidateGateError):
    """An accepted constraint leaves Reg-GXPath_pos."""
    code = "E-FRAGMENT"


class BoundaryNotRepairable(CandidateGateError):
    """An accepted constraint is boundary tier and no engine may act on it."""
    code = "E-BOUNDARY"


class NothingAccepted(CandidateGateError):
    """Every entry was rejected, so the file carries no constraint to load."""
    code = "E-EMPTY"


class SchemaRejected(CandidateGateError):
    """The file is not a candidate file of a schema this toolkit reads."""
    code = "E-SCHEMA"


def graph_content_hash(graph: DataGraph) -> str:
    """A content hash over a graph's edges, for pinning a file to a slice.

    Matches the hash the slice pipeline records, so a candidate file derived from
    a committed slice can be checked against that slice's manifest.
    """
    import hashlib
    import json
    payload = sorted(graph.edges())
    return hashlib.sha256(json.dumps(payload).encode("utf-8")).hexdigest()[:16]


def reviewed_constraint_set(cf: CandidateFile, graph: Optional[DataGraph] = None, *,
                            allow_graph_drift: bool = False,
                            for_repair: bool = True) -> ConstraintSet:
    """Turn a sealed, fully reviewed candidate file into a loadable ConstraintSet.

    This is the only route from a candidate file to an engine. Every refusal below
    happens before a constraint is handed anywhere, so an unsealed, drifted, or
    out-of-fragment file cannot reach a repair at all.

    `graph` pins the file to the data it was derived from. Passing it is what
    catches a file being pointed at a different slice; `allow_graph_drift` lets a
    caller proceed anyway, and the caller is then responsible for recording that
    they did. `for_repair=False` loads for validation only, which is the one case
    where a boundary-tier entry is allowed through.
    """
    if cf.schema is None:
        raise SchemaRejected("file carries no schema tag")

    if cf.authored:
        # An authored file says "a person wrote these rules down". A seal says "a
        # person reviewed rules a search proposed". They are different claims about
        # different things, so a file carrying both hides which one was actually
        # made, and that is a malformed file rather than something to accept.
        if (cf.review or {}).get("seal") or cf.sealed:
            raise SchemaRejected(
                "this file declares provenance 'authored' and also carries a review "
                "seal. Authored constraints are asserted by whoever wrote them and "
                "need no seal; a seal records a review of derived candidates. Drop "
                "one or the other, so the file states which claim is being made.")
    else:
        if not cf.sealed:
            raise NotSealed("candidate file is not sealed: a reviewer has to decide "
                            "every entry and seal the file before it can drive a "
                            "repair")

    still_pending = cf.pending()
    if still_pending:
        first = still_pending[0]
        raise ReviewIncomplete(
            f"{len(still_pending)} candidate(s) still pending, first is {first.cid}"
            + (". An authored file states its assertions with status 'accepted'."
               if cf.authored else ""),
            cid=first.cid)

    # The seal and the source-graph hash are the two things an authored file is
    # excused, and only those two. A seal cannot be verified when there is none to
    # verify, and there is no derivation run whose evidence a different graph would
    # invalidate: an authored rule is a claim about the domain, not a measurement of
    # one slice. Every other refusal below applies to both kinds of file.
    if not cf.authored:
        if not verify_seal(cf):
            raise SealMismatch("the recorded seal does not recompute over this "
                               "file's accepted set: the file changed after it was "
                               "sealed, so the decisions it records can no longer be "
                               "trusted")

        if graph is not None:
            actual = graph_content_hash(graph)
            recorded = (cf.source or {}).get("content_hash")
            if recorded and actual != recorded and not allow_graph_drift:
                raise SourceDrift(
                    f"these candidates were derived from a graph with content hash "
                    f"{recorded}, but the graph being repaired hashes to {actual}. "
                    f"The evidence behind every decision in this file was measured "
                    f"on the other graph. Pass allow_graph_drift to proceed anyway.")

    accepted = cf.accepted()
    if not accepted:
        raise NothingAccepted("no candidate in this file was accepted, so there is "
                              "nothing to load")

    cs = ConstraintSet(f"reviewed@{(cf.source or {}).get('dataset', 'unknown')}")
    for cand in accepted:
        if for_repair and cand.tier == "boundary":
            raise BoundaryNotRepairable(
                f"{cand.cid} is boundary tier, which is validated and reported "
                f"only. No engine may act on it.", cid=cand.cid)
        c = Constraint(
            cid=cand.cid, domain=(cf.source or {}).get("domain", "derived"),
            kg=(cf.source or {}).get("kg", "derived"), kind=cand.kind,
            tier=cand.tier, provenance=cf.provenance, direction=cand.direction,
            antecedent=cand.antecedent, consequent=cand.consequent,
            note=cand.note or cand.gloss)
        # Parse every accepted constraint, including one a person hand-edited into
        # the file. A reviewer can type anything into a JSON file, so the fragment
        # check has to happen here rather than trusting what derivation wrote.
        try:
            c.compile()
        except Exception as exc:
            raise OutOfFragment(
                f"{cand.cid} does not parse inside the positive fragment: {exc}. "
                f"Negation, path complement and disequality are rejected.",
                cid=cand.cid) from exc
        cs.add(c)
    return cs


def review_attestations(cf: CandidateFile, *, allow_graph_drift: bool = False) -> dict:
    """What a repair driven by a reviewed candidate file should record about it.

    The repair engines are untouched by the review machinery and neither of them
    knows a candidate file exists, so this is merged into the report rather than
    produced by an engine. It answers the question a reader of a repaired graph
    will ask: who authorised these rules, and against what.
    """
    review = cf.review or {}
    out = {
        "constraint_provenance": cf.provenance,
        "constraint_seal": review.get("seal"),
        "constraint_source": (cf.source or {}).get("dataset")
                             or (cf.source or {}).get("content_hash"),
        "reviewer": review.get("reviewer"),
    }
    if cf.authored:
        # Null seal and null reviewer on an authored file are the expected state,
        # not a missing step, and a reader of the report should be told which.
        out["constraint_seal"] = None
        out["reviewer"] = None
        out["authorship"] = ("asserted by whoever wrote the constraint file; no "
                             "review seal applies to authored constraints")
    if allow_graph_drift:
        out["allow_graph_drift"] = True
    return out


def attach_review_attestations(result_payload: dict, cf: CandidateFile, *,
                               allow_graph_drift: bool = False) -> dict:
    """Merge the review attestations into a serialised repair result.

    Takes the payload an engine result already produced and returns it with the
    provenance of the rules added. The engine's own attestations are left exactly
    as they were.
    """
    payload = dict(result_payload)
    attestations = dict(payload.get("attestations") or {})
    attestations.update(review_attestations(cf, allow_graph_drift=allow_graph_drift))
    payload["attestations"] = attestations
    return payload
