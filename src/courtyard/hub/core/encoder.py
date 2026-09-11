"""Text encoders for hub memory's similarity search (design hub-memory.md section 7).

One interface, three implementations, a `none` default:

* `NoEncoder`: nothing configured; recall is full-text only and says so.
* `HttpEncoder`: any OpenAI-compatible embeddings endpoint, meant for a LOCAL service
  (Ollama serves one at http://127.0.0.1:11434/v1/embeddings). A non-local URL needs the
  explicit `COURTYARD_EMBEDDINGS_ALLOW_REMOTE=1`, because it sends message bodies off the
  machine and the README promises nothing does by default.
* `FakeEncoder` (`fake://`): a deterministic bag-of-words vector with a small synonym
  table, for the tests and for runbook scripts that must not depend on a model server.
  It is honest about what it is: it proves the plumbing, not semantics.

The hub stays light: no torch, no model inside the process. The encoder's `model` name
is stored with every vector, so a model change is a re-embed of the rows that carry
another name, never a schema change.
"""

from __future__ import annotations

import hashlib
import math
import re
from typing import Protocol
from urllib.parse import urlsplit

import httpx

from courtyard.hub.config import LOCAL_HOSTS, Config


class EncoderError(Exception):
    """The encoder could not produce vectors (no encoder, service down, bad answer)."""


class Encoder(Protocol):
    name: str  # none | http | fake
    model: str  # what is stored with every vector

    def embed(self, texts: list[str], timeout: float | None = None) -> list[list[float]]:
        """`timeout` overrides the encoder's own for one call (a recall waits seconds, the
        sweep may wait a minute)."""
        ...


class NoEncoder:
    name = "none"
    model = ""

    def embed(self, texts: list[str], timeout: float | None = None) -> list[list[float]]:
        raise EncoderError("no encoder is configured (COURTYARD_EMBEDDINGS_URL)")


class HttpEncoder:
    """`POST {url}` with `{"model": ..., "input": [...]}`; reads `data[i].embedding`, the
    shape OpenAI defined and Ollama, LM Studio, vLLM and llama.cpp all serve."""

    name = "http"

    def __init__(self, url: str, model: str, api_key: str | None = None, timeout: float = 60.0):
        self.url = url
        self.model = model
        self._headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._timeout = timeout

    def embed(self, texts: list[str], timeout: float | None = None) -> list[list[float]]:
        if not texts:
            return []
        try:
            resp = httpx.post(
                self.url,
                json={"model": self.model, "input": texts},
                headers=self._headers,
                timeout=timeout or self._timeout,
            )
            resp.raise_for_status()
            data = resp.json()["data"]
        except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
            raise EncoderError(f"embeddings endpoint {self.url} ({self.model}): {exc}") from exc
        ordered = sorted(data, key=lambda d: d.get("index", 0))
        vectors = [list(map(float, d["embedding"])) for d in ordered]
        if len(vectors) != len(texts):
            raise EncoderError(f"{self.url} returned {len(vectors)} vectors for {len(texts)} texts")
        return vectors


_SYNONYMS = {
    "pg": "database",
    "postgres": "database",
    "postgresql": "database",
    "db": "database",
    "tf": "terraform",
    "k8s": "kubernetes",
    "kube": "kubernetes",
    "release": "version",
    "releases": "version",
    "versions": "version",
}
_FAKE_DIMS = 32


class FakeEncoder:
    """Deterministic: each word (synonyms folded) hashes into one of 32 buckets; the vector
    is the normalized bucket count. Two texts sharing words, or synonyms of words, are
    close; nothing else is. Enough to exercise every code path around real vectors."""

    name = "fake"
    model = "fake-bag-of-words-32"

    def embed(self, texts: list[str], timeout: float | None = None) -> list[list[float]]:
        return [self._one(t) for t in texts]

    @staticmethod
    def _one(text: str) -> list[float]:
        vec = [0.0] * _FAKE_DIMS
        for word in re.findall(r"[a-z0-9]+", text.lower()):
            word = _SYNONYMS.get(word, word)
            bucket = int(hashlib.md5(word.encode()).hexdigest(), 16) % _FAKE_DIMS
            vec[bucket] += 1.0
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]


def encoder_from_config(cfg: Config) -> Encoder:
    url = (cfg.embeddings_url or "").strip()
    if not url:
        return NoEncoder()
    if url == "fake://":
        return FakeEncoder()
    return HttpEncoder(url, cfg.embeddings_model, cfg.embeddings_api_key)


def is_local_url(url: str) -> bool:
    try:
        host = urlsplit(url).hostname or ""
    except ValueError:
        return False
    return host in LOCAL_HOSTS
