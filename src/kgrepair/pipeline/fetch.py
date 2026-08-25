"""
Polite HTTP fetching (stdlib only -- no third-party deps).

`PoliteFetcher` wraps urllib with: a project User-Agent, a configurable minimum
inter-request interval (rate limit), retry-with-exponential-backoff on 429/5xx/
timeout, and a per-request timeout. It is the transport under the SPARQL extractors.

Resumability and Level-0 live in the extractor (`extract.py`), not here: the
extractor skips queries already in the cache and filters responses through the
allow-list before `RawCache.store`, so person/org triples never reach disk.
"""
from __future__ import annotations

import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

USER_AGENT = ("kgrepair/0.1 (open-source knowledge-graph repair toolkit; "
              "public data only, no personal data collected)")


@dataclass
class FetchPolicy:
    min_interval_s: float = 1.0       # rate limit: min gap between requests
    timeout_s: float = 60.0
    max_retries: int = 4
    backoff_base_s: float = 2.0
    accept: str = "application/n-triples"


class RateLimitError(RuntimeError):
    pass


class PoliteFetcher:
    def __init__(self, policy: FetchPolicy = FetchPolicy()):
        self.policy = policy
        self._last_request = 0.0
        self.request_count = 0

    def _throttle(self) -> None:
        gap = time.perf_counter() - self._last_request
        if gap < self.policy.min_interval_s:
            time.sleep(self.policy.min_interval_s - gap)

    def sparql_construct(self, endpoint: str, query: str) -> str:
        """POST a CONSTRUCT to a SPARQL endpoint; return the response body (N-Triples).
        Retries with exponential backoff; honours Retry-After when present."""
        data = urllib.parse.urlencode({"query": query}).encode("utf-8")
        headers = {"User-Agent": USER_AGENT, "Accept": self.policy.accept,
                   "Content-Type": "application/x-www-form-urlencoded"}
        last_err = None
        for attempt in range(self.policy.max_retries + 1):
            self._throttle()
            req = urllib.request.Request(endpoint, data=data, headers=headers, method="POST")
            try:
                t0 = time.perf_counter()
                with urllib.request.urlopen(req, timeout=self.policy.timeout_s) as resp:
                    body = resp.read().decode("utf-8", errors="replace")
                self._last_request = time.perf_counter()
                self.request_count += 1
                return body
            except urllib.error.HTTPError as e:
                last_err = e
                self._last_request = time.perf_counter()
                if e.code in (429, 500, 502, 503, 504) and attempt < self.policy.max_retries:
                    retry_after = e.headers.get("Retry-After") if e.headers else None
                    wait = float(retry_after) if (retry_after and retry_after.isdigit()) \
                        else self.policy.backoff_base_s * (2 ** attempt)
                    time.sleep(wait)
                    continue
                raise
            except (urllib.error.URLError, TimeoutError) as e:
                last_err = e
                self._last_request = time.perf_counter()
                if attempt < self.policy.max_retries:
                    time.sleep(self.policy.backoff_base_s * (2 ** attempt))
                    continue
                raise
        raise RateLimitError(f"exhausted retries: {last_err}")

    def sparql_ask(self, endpoint: str, query: str) -> bool:
        """POST an ASK query; return its boolean. Retries like `sparql_construct`;
        parses the sparql-results+json `{"boolean": ...}` envelope."""
        import json as _json
        data = urllib.parse.urlencode({"query": query}).encode("utf-8")
        headers = {"User-Agent": USER_AGENT, "Accept": "application/sparql-results+json",
                   "Content-Type": "application/x-www-form-urlencoded"}
        last_err = None
        for attempt in range(self.policy.max_retries + 1):
            self._throttle()
            req = urllib.request.Request(endpoint, data=data, headers=headers, method="POST")
            try:
                with urllib.request.urlopen(req, timeout=self.policy.timeout_s) as resp:
                    body = resp.read().decode("utf-8", errors="replace")
                self._last_request = time.perf_counter()
                self.request_count += 1
                return bool(_json.loads(body).get("boolean", False))
            except urllib.error.HTTPError as e:
                last_err = e
                self._last_request = time.perf_counter()
                if e.code in (429, 500, 502, 503, 504) and attempt < self.policy.max_retries:
                    retry_after = e.headers.get("Retry-After") if e.headers else None
                    wait = float(retry_after) if (retry_after and retry_after.isdigit()) \
                        else self.policy.backoff_base_s * (2 ** attempt)
                    time.sleep(wait)
                    continue
                raise
            except (urllib.error.URLError, TimeoutError) as e:
                last_err = e
                self._last_request = time.perf_counter()
                if attempt < self.policy.max_retries:
                    time.sleep(self.policy.backoff_base_s * (2 ** attempt))
                    continue
                raise
        raise RateLimitError(f"exhausted retries: {last_err}")

    def download(self, url: str, dest_path: str, *, chunk: int = 1 << 20) -> int:
        """Stream a (large) file to disk with the project UA; returns bytes written."""
        self._throttle()
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        total = 0
        with urllib.request.urlopen(req, timeout=self.policy.timeout_s) as resp, \
                open(dest_path, "wb") as fh:
            while True:
                buf = resp.read(chunk)
                if not buf:
                    break
                fh.write(buf)
                total += len(buf)
        self._last_request = time.perf_counter()
        self.request_count += 1
        return total
