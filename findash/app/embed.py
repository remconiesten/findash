"""IBAN-free index text. Embedder imports FastEmbed only when constructed."""

from __future__ import annotations

import os
import re
import threading
from pathlib import Path
from typing import Iterable, Sequence

from app.formatters import _IBAN_RE

_DIGIT_RUN = re.compile(r"\d{8,}")
_PUNCT = re.compile(r"[.,;:/\-]")
VECTOR_SIZE = 384
# FastEmbed 0.5–0.6 on Python 3.9 has no multilingual-e5-small (384-d).
# Design reserve: MiniLM-L12, same vector size as findash_tx.
DEFAULT_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
PASSAGE_PREFIX = "passage: "
QUERY_PREFIX = "query: "


def strip_iban(value: str | None) -> str:
    if not value:
        return ""
    text = _IBAN_RE.sub("…", str(value))
    text = _DIGIT_RUN.sub("…", text)
    return " ".join(text.split())


def rekening_token(rekening: str | None) -> str:
    text = (rekening or "").strip()
    if text.startswith("Rekening ") and len(text) > 9:
        rest = text[9:].strip()
        return rest or "Onbekend"
    return "Onbekend"


def index_text(omschrijving: str | None, *, limit: int = 200) -> str:
    """Vector text: IBAN-free omschrijving only. No Af/Bij, no rekening."""
    text = strip_iban(omschrijving)
    if len(text) > limit:
        return text[:limit]
    return text


def normalize(omschrijving: str | None, limit: int = 200) -> str:
    text = strip_iban(omschrijving).casefold()
    text = _PUNCT.sub("", text)
    text = " ".join(text.split())
    if len(text) > limit:
        return text[:limit]
    return text


class Embedder:
    """Lazy FastEmbed wrapper. Do not construct in pytest."""

    def __init__(
        self,
        model_name: str = DEFAULT_MODEL,
        cache_dir: str | Path = ".cache/fastembed",
    ) -> None:
        from fastembed import TextEmbedding

        cache = Path(cache_dir)
        cache.mkdir(parents=True, exist_ok=True)
        hf_home = cache.parent / "huggingface"
        hf_home.mkdir(parents=True, exist_ok=True)
        os.environ["HF_HOME"] = str(hf_home)
        os.environ["HUGGINGFACE_HUB_CACHE"] = str(hf_home)
        os.environ["HF_HUB_CACHE"] = str(hf_home)
        os.environ["HF_HUB_DISABLE_XET"] = "1"
        self.model_name = model_name
        self._use_e5_prefix = "e5" in model_name.lower()
        self._model = TextEmbedding(model_name=model_name, cache_dir=str(cache))

    def _prefixed(self, texts: Sequence[str], prefix: str) -> list[str]:
        if self._use_e5_prefix:
            return [prefix + text for text in texts]
        return list(texts)

    def embed_passages(self, texts: Sequence[str]) -> list[list[float]]:
        return [list(vec) for vec in self._model.embed(self._prefixed(texts, PASSAGE_PREFIX))]

    def embed_queries(self, texts: Sequence[str]) -> list[list[float]]:
        return [list(vec) for vec in self._model.embed(self._prefixed(texts, QUERY_PREFIX))]


def fake_vector(text: str, size: int = VECTOR_SIZE) -> list[float]:
    """Deterministic 384-d stand-in for tests. Not a real embedding."""
    seed = 0
    for char in text:
        seed = (seed * 31 + ord(char)) & 0xFFFFFFFF
    vec = []
    value = seed or 1
    for _ in range(size):
        value = (value * 1103515245 + 12345) & 0x7FFFFFFF
        vec.append((value / 0x7FFFFFFF) * 2.0 - 1.0)
    return vec


def fake_embed_passages(texts: Iterable[str]) -> list[list[float]]:
    return [fake_vector(PASSAGE_PREFIX + text) for text in texts]


_embedder_lock = threading.Lock()
_embedder: Embedder | None = None


def get_embedder(settings: dict[str, str]) -> Embedder:
    """Process-wide lazy Embedder. Not used by pytest."""
    global _embedder
    with _embedder_lock:
        if _embedder is None:
            root = Path(__file__).resolve().parent.parent
            cache = Path(settings.get("FINDASH_EMBED_CACHE") or ".cache/fastembed")
            if not cache.is_absolute():
                cache = root / cache
            _embedder = Embedder(
                model_name=settings.get("FINDASH_EMBED_MODEL") or DEFAULT_MODEL,
                cache_dir=cache,
            )
        return _embedder
