"""
Candidate constraint files: the airlock between derivation and repair.

Derivation proposes. A person decides. Only a sealed file drives an engine.

Nothing in this project lets a confidence score authorise a repair. A derived
constraint reaches an engine only after a reviewer has looked at every entry and
sealed the file, and the load gate in `api.reviewed_constraint_set` refuses any
file where that did not happen. There is deliberately no threshold above which a
candidate skips review and no flag that accepts everything.

File shape (`kgrepair.candidates/v1`)
------------------------------------
    schema           the version tag above
    toolkit_version  the kgrepair version that wrote the file
    source           dataset and content_hash of the graph derived from, plus an
                     optional reference block with the same two fields
    parameters       the derivation settings, so a run can be reproduced
    review           state, reviewer, timestamps, the seal, and review_order
    candidates       every proposal, each carrying its own status
    refused          cids a reviewer rejected, kept so a later derive run cannot
                     quietly propose them again

A rejection is retained rather than deleted. Deleting it would mean the next
derive run re-proposes the same rule and the reviewer has to make the same
decision again, with nothing recording that they already made it once.

Status values
-------------
    pending    nobody has looked at it yet. Blocks sealing.
    accepted   a reviewer approved it. Only these reach an engine.
    rejected   a reviewer turned it down. Kept, and its cid enters `refused`.
    weakened   a reviewer accepted a broader form instead. Treated as accepted
               for loading, and the note records what changed.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

SCHEMA = "kgrepair.candidates/v1"

#: Where a file's constraints came from, which decides which gates apply.
#:
#: `derived` means a search proposed them from statistics, so a person has to have
#: reviewed and sealed the file before an engine sees it. `authored` means a person
#: wrote them down, which is the assertion the seal exists to record, so the seal
#: and the source-graph hash are waived and every other refusal still applies.
#:
#: A file with no provenance field is `derived`, so every file written before this
#: existed keeps exactly the behaviour it had.
AUTHORED, DERIVED = "authored", "derived"
PROVENANCES = (AUTHORED, DERIVED)

#: Statuses a reviewer can leave on an entry.
PENDING, ACCEPTED, REJECTED, WEAKENED = "pending", "accepted", "rejected", "weakened"
STATUSES = (PENDING, ACCEPTED, REJECTED, WEAKENED)

#: The statuses that let a candidate reach an engine.
LOADABLE = (ACCEPTED, WEAKENED)

_WS = re.compile(r"\s+")


def canonical_expression(text: str) -> str:
    """Whitespace-normalised expression text, for hashing and comparison.

    The parser accepts any spacing, so two spellings of one expression have to
    agree on a cid. Normalising runs of whitespace is enough for that and is
    stable across runs, which is what the cid needs.
    """
    return _WS.sub(" ", (text or "").strip())


def candidate_cid(domain: str, kg: str, antecedent: str, consequent: str) -> str:
    """A content-derived id: the same rule always gets the same cid.

    Deliberately not a counter. A counter would renumber every entry when an
    earlier candidate disappears, which would break the link between a reviewer's
    decision and the rule they decided on.
    """
    payload = "\n".join([domain, kg,
                             canonical_expression(antecedent),
                             canonical_expression(consequent)])
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:8]
    return f"{domain}.{kg}.derived.{digest}"


@dataclass
class Candidate:
    """One proposed constraint, with the evidence for it and a reviewer's verdict."""
    cid: str
    kind: str
    tier: str
    direction: str
    antecedent: str
    consequent: str
    gloss: str = ""
    evidence: Dict = field(default_factory=dict)
    impact: Dict = field(default_factory=dict)
    witness_sample: List[str] = field(default_factory=list)
    status: str = PENDING
    note: str = ""

    def to_dict(self) -> Dict:
        return {
            "cid": self.cid, "kind": self.kind, "tier": self.tier,
            "direction": self.direction,
            "antecedent": self.antecedent, "consequent": self.consequent,
            "gloss": self.gloss, "evidence": self.evidence, "impact": self.impact,
            "witness_sample": list(self.witness_sample),
            "status": self.status, "note": self.note,
        }

    @staticmethod
    def from_dict(d: Dict) -> "Candidate":
        status = d.get("status", PENDING)
        if status not in STATUSES:
            raise ValueError(f"{d.get('cid', '?')}: unknown status {status!r}; "
                             f"expected one of {', '.join(STATUSES)}")
        return Candidate(
            cid=d["cid"], kind=d["kind"], tier=d["tier"], direction=d["direction"],
            antecedent=d["antecedent"], consequent=d["consequent"],
            gloss=d.get("gloss", ""), evidence=d.get("evidence", {}),
            impact=d.get("impact", {}), witness_sample=list(d.get("witness_sample", [])),
            status=status, note=d.get("note", ""))

    @property
    def loadable(self) -> bool:
        return self.status in LOADABLE


@dataclass
class CandidateFile:
    """A whole candidate file: proposals, provenance, and the review record."""
    source: Dict = field(default_factory=dict)
    parameters: Dict = field(default_factory=dict)
    review: Dict = field(default_factory=lambda: {"state": "open", "reviewer": None,
                                                  "sealed_at": None, "seal": None,
                                                  "review_order": []})
    candidates: List[Candidate] = field(default_factory=list)
    refused: List[str] = field(default_factory=list)
    schema: str = SCHEMA
    toolkit_version: str = ""
    provenance: str = DERIVED

    @property
    def authored(self) -> bool:
        """Whether a person wrote these constraints rather than a search proposing them."""
        return self.provenance == AUTHORED

    # -- queries ------------------------------------------------------------
    def by_cid(self, cid: str) -> Optional[Candidate]:
        return next((c for c in self.candidates if c.cid == cid), None)

    def pending(self) -> List[Candidate]:
        return [c for c in self.candidates if c.status == PENDING]

    def accepted(self) -> List[Candidate]:
        """Entries a reviewer approved, in cid order. These are what can load."""
        return sorted((c for c in self.candidates if c.loadable), key=lambda c: c.cid)

    @property
    def sealed(self) -> bool:
        return self.review.get("state") == "sealed"

    def ordered_for_review(self) -> List[Candidate]:
        """Entries in review_order where one is recorded, then anything left over.

        review_order ranks by how much a decision matters rather than by cid, so a
        reviewer meets the consequential entries first.
        """
        order = {cid: i for i, cid in enumerate(self.review.get("review_order", []))}
        return sorted(self.candidates,
                      key=lambda c: (order.get(c.cid, len(order)), c.cid))

    # -- serialisation ------------------------------------------------------
    def to_dict(self) -> Dict:
        """The file payload, with candidates and refused in a settled order."""
        return {
            "schema": self.schema,
            "toolkit_version": self.toolkit_version,
            "provenance": self.provenance,
            "source": self.source,
            "parameters": self.parameters,
            "review": self.review,
            "candidates": [c.to_dict() for c in sorted(self.candidates,
                                                       key=lambda c: c.cid)],
            "refused": sorted(set(self.refused)),
        }

    @staticmethod
    def from_dict(payload: Dict) -> "CandidateFile":
        schema = payload.get("schema")
        if schema != SCHEMA:
            raise ValueError(f"unknown candidate-file schema {schema!r}; "
                             f"this toolkit writes {SCHEMA}")
        provenance = payload.get("provenance", DERIVED)
        if provenance not in PROVENANCES:
            raise ValueError(f"unknown provenance {provenance!r}; expected one of "
                             f"{', '.join(PROVENANCES)}")
        return CandidateFile(
            schema=schema,
            provenance=provenance,
            toolkit_version=payload.get("toolkit_version", ""),
            source=payload.get("source", {}),
            parameters=payload.get("parameters", {}),
            review=payload.get("review", {"state": "open", "reviewer": None,
                                          "sealed_at": None, "seal": None,
                                          "review_order": []}),
            candidates=[Candidate.from_dict(d) for d in payload.get("candidates", [])],
            refused=list(payload.get("refused", [])))


 
# file IO
 
def dumps_canonical(cf: CandidateFile) -> str:
    """The file as text, in a form two runs over the same content both produce.

    Sorted keys, sorted candidates, fixed separators, one trailing newline. Byte
    stability is what lets a reviewer diff two derive runs and see only what
    actually changed.
    """
    return json.dumps(cf.to_dict(), indent=2, sort_keys=True,
                      separators=(",", ": "), ensure_ascii=False) + "\n"


def write_canonical(cf: CandidateFile, path: str) -> str:
    """Write a candidate file in the byte-stable form; return the path written."""
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(dumps_canonical(cf))
    return path


def read_candidate_file(path: str) -> CandidateFile:
    """Read a candidate file, refusing a schema this toolkit does not write."""
    with open(path, encoding="utf-8") as fh:
        return CandidateFile.from_dict(json.load(fh))


 
# merge
 
def merge_candidates(existing: CandidateFile, fresh: CandidateFile) -> CandidateFile:
    """Fold a fresh derive run into a file that already carries decisions.

    Three rules, in order:

      1. a decision already recorded is kept, and the fresh version of that entry
         is discarded. Re-deriving must never overwrite a person's verdict;
      2. a fresh candidate whose cid is in `refused` is dropped, so a rejection
         stays rejected across runs;
      3. anything genuinely new is appended as pending.

    Merging never seals. If the merge brings in new pending entries the file drops
    back to open, because a seal covering entries nobody has seen would be a lie.
    """
    merged = CandidateFile(
        schema=existing.schema or SCHEMA,
        toolkit_version=fresh.toolkit_version or existing.toolkit_version,
        source=dict(fresh.source or existing.source),
        parameters=dict(fresh.parameters or existing.parameters),
        review=dict(existing.review),
        candidates=list(existing.candidates),
        refused=list(existing.refused))

    known = {c.cid for c in existing.candidates}
    refused = set(existing.refused)
    added = []
    for cand in fresh.candidates:
        if cand.cid in known or cand.cid in refused:
            continue
        added.append(cand)
    merged.candidates.extend(added)

    # review_order: keep the fresh ranking for entries it covers, then anything
    # the fresh run did not rank, so a merged file still leads with what matters.
    fresh_order = [cid for cid in fresh.review.get("review_order", [])
                   if any(c.cid == cid for c in merged.candidates)]
    leftover = sorted(c.cid for c in merged.candidates if c.cid not in set(fresh_order))
    merged.review["review_order"] = fresh_order + leftover

    if added or merged.pending():
        merged.review["state"] = "open"
        merged.review["seal"] = None
        merged.review["sealed_at"] = None
    return merged


 
# decisions and sealing
 
def set_status(cf: CandidateFile, cid: str, status: str, note: str = "") -> Candidate:
    """Record a verdict on one entry. A rejection also enters `refused`.

    Any change reopens a sealed file: the seal covers a specific set of decisions,
    so changing one has to invalidate it rather than silently outlive it.
    """
    if status not in STATUSES:
        raise ValueError(f"unknown status {status!r}; expected one of "
                         f"{', '.join(STATUSES)}")
    cand = cf.by_cid(cid)
    if cand is None:
        raise KeyError(f"no candidate with cid {cid!r}")
    cand.status = status
    if note:
        cand.note = note
    if status == REJECTED and cid not in cf.refused:
        cf.refused.append(cid)
    if status != REJECTED and cid in cf.refused:
        cf.refused.remove(cid)
    if cf.sealed:
        cf.review["state"] = "open"
        cf.review["seal"] = None
        cf.review["sealed_at"] = None
    return cand


def seal_payload(cf: CandidateFile, reviewer: str, sealed_at: str) -> str:
    """The exact text the seal is taken over. Shared by sealing and verification."""
    accepted = [{"cid": c.cid, "status": c.status,
                 "antecedent": canonical_expression(c.antecedent),
                 "consequent": canonical_expression(c.consequent)}
                for c in cf.accepted()]
    return json.dumps({"accepted": accepted, "reviewer": reviewer,
                       "sealed_at": sealed_at},
                      sort_keys=True, separators=(",", ": "), ensure_ascii=False)


def compute_seal(cf: CandidateFile, reviewer: str, sealed_at: str) -> str:
    """sha256 over the accepted set, the reviewer, and the timestamp.

    Tamper-evidence, not security. Anyone holding the file can recompute this, so
    it does not stop a determined edit; it makes an edit visible, which is the
    property the load gate needs. There is no secret and no signature here.
    """
    return hashlib.sha256(seal_payload(cf, reviewer, sealed_at).encode("utf-8")).hexdigest()


def seal_candidates(cf: CandidateFile, reviewer: str,
                    sealed_at: Optional[str] = None) -> CandidateFile:
    """Seal a fully reviewed file so it can drive an engine.

    Refuses while anything is still pending: the point of the seal is that a
    person saw every entry, so sealing over an unseen one would defeat it.
    """
    if not reviewer or not reviewer.strip():
        raise ValueError("sealing needs a reviewer name: the seal records who "
                         "made these decisions")
    still_pending = cf.pending()
    if still_pending:
        names = ", ".join(c.cid for c in still_pending[:5])
        raise ValueError(f"{len(still_pending)} candidate(s) still pending: {names}"
                         + (" ..." if len(still_pending) > 5 else ""))
    stamp = sealed_at or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    cf.review["state"] = "sealed"
    cf.review["reviewer"] = reviewer.strip()
    cf.review["sealed_at"] = stamp
    cf.review["seal"] = compute_seal(cf, reviewer.strip(), stamp)
    return cf


def verify_seal(cf: CandidateFile) -> bool:
    """True when the recorded seal still matches the file's accepted set."""
    if not cf.sealed:
        return False
    reviewer = cf.review.get("reviewer") or ""
    stamp = cf.review.get("sealed_at") or ""
    return cf.review.get("seal") == compute_seal(cf, reviewer, stamp)
