"""
Stage-1 raw cache.

Fetched responses (SPARQL results / dump segments) are written verbatim under
`data/raw/<source>/<content-hash>.nt`, each with a `.meta.json` sidecar recording
the exact query text, query hash, retrieval timestamp, source, and URL. The cache is
the **determinism boundary**: Stage-2 slicing reads only from here, so the same cache
+ params yields byte-identical slices. Live-data drift shows up as a new cache
generation (new content hashes), never as a silent slice change.

The cache is intentionally dumb: it does not filter. Level-0 filtering happens in the
fetcher (queries are allow-listed and responses defensively filtered) *before* store,
so only allow-listed triples ever reach disk. `iter_raw_triples` re-parses via the
project's own N-Triples reader so the cache speaks exactly the loader's dialect.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from typing import Iterator, List, Optional, Tuple

from ..ntriples import iter_triples


class RawCache:
    def __init__(self, root: str):
        self.root = root

    def source_dir(self, source: str) -> str:
        return os.path.join(self.root, source)

    def store(self, source: str, query_text: str, raw_ntriples: str,
              url: str = "", timestamp: Optional[str] = None) -> str:
        content_hash = hashlib.sha256(raw_ntriples.encode("utf-8")).hexdigest()[:16]
        d = self.source_dir(source)
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, f"{content_hash}.nt"), "w", encoding="utf-8") as fh:
            fh.write(raw_ntriples)
        meta = {
            "source": source,
            "url": url,
            "query_text": query_text,
            "query_hash": hashlib.sha256(query_text.encode("utf-8")).hexdigest()[:16],
            "content_hash": content_hash,
            "retrieval_timestamp": timestamp or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        with open(os.path.join(d, f"{content_hash}.meta.json"), "w", encoding="utf-8") as fh:
            json.dump(meta, fh, indent=2)
        return content_hash

    # -- read side ----------------------------------------------------------
    def _files(self, source: str) -> List[str]:
        d = self.source_dir(source)
        if not os.path.isdir(d):
            return []
        return sorted(f for f in os.listdir(d) if f.endswith(".nt"))

    def iter_raw_triples(self, source: str) -> Iterator[Tuple[str, str, str, bool]]:
        """Yield (s, p, o, o_is_literal) across every cached segment for `source`."""
        for name in self._files(source):
            with open(os.path.join(self.source_dir(source), name), "r", encoding="utf-8") as fh:
                for s, p, o_node, o_lit in iter_triples(fh):
                    yield (s, p, o_node, o_lit is not None)

    def generation_hash(self, source: str) -> str:
        """Hash over the sorted content hashes of every cached segment -- the cache
        generation id that pins slice determinism."""
        parts = sorted(name[:-3] for name in self._files(source))
        return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:16]

    def query_hashes(self, source: str) -> List[str]:
        out = []
        for name in self._files(source):
            meta_path = os.path.join(self.source_dir(source), name[:-3] + ".meta.json")
            if os.path.exists(meta_path):
                with open(meta_path, "r", encoding="utf-8") as fh:
                    out.append(json.load(fh).get("query_hash", ""))
        return sorted(out)
