"""Qdrant access for findash_tx only. Optional import; never touch other collections."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

OWN_COLLECTION = "findash_tx"
VECTOR_SIZE = 384
_FINBOT_NAME = re.compile(r"finbot", re.IGNORECASE)
_SECRET_IN_TEXT = re.compile(
    r"(?i)(api[_-]?key|authorization|api-key)[\"'\s:=]+[^\s,;]+"
)


def redact_qdrant_error(exc: BaseException) -> str:
    return _SECRET_IN_TEXT.sub(r"\1=<redacted>", f"{type(exc).__name__}")


def public_url(url: str) -> str:
    parsed = urlparse(url)
    host = parsed.hostname or "?"
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    return f"{parsed.scheme or 'http'}://{host}:{port}"


def assert_own_collection(name: str) -> str:
    if not name or _FINBOT_NAME.search(name):
        raise ValueError("refusing FinBot or empty Qdrant collection name")
    if name != OWN_COLLECTION:
        raise ValueError(f"findash uses {OWN_COLLECTION} only")
    return name


def qdrant_enabled(settings: dict[str, str]) -> bool:
    return bool(settings.get("QDRANT_URL") and settings.get("QDRANT_API_KEY"))


PAYLOAD_KEYS = frozenset(
    {
        "src",
        "transactie_id",
        "hoofd",
        "sub",
        "entiteit",
        "richting",
        "rekening",
        "jaar",
        "maand",
        "flow_kind",
        "corrected",
    }
)
KEYWORD_INDEXES = ("src", "richting", "hoofd", "rekening", "flow_kind")


def _client(settings: dict[str, str], timeout: int = 5):
    from qdrant_client import QdrantClient

    return QdrantClient(
        url=settings["QDRANT_URL"],
        api_key=settings["QDRANT_API_KEY"],
        timeout=timeout,
        check_compatibility=False,
    )


def ping(settings: dict[str, str]) -> None:
    client = _client(settings)
    try:
        client.get_collections()
    finally:
        client.close()


def ping_collections(settings: dict[str, str]) -> dict[str, Any]:
    """Names + point counts. No scroll, no payloads."""
    client = _client(settings)
    try:
        listed = client.get_collections().collections or []
        names = [item.name for item in listed]
        rows = []
        for name in names:
            info = client.get_collection(name)
            rows.append(
                {
                    "name": name,
                    "points": int(info.points_count or 0),
                    "own": name == OWN_COLLECTION,
                    "foreign": bool(_FINBOT_NAME.search(name) or name != OWN_COLLECTION),
                }
            )
        return {"ok": True, "collections": rows}
    finally:
        client.close()


def ensure_own_collection(settings: dict[str, str]) -> str:
    """Create findash_tx if missing. Never drop or recreate. Never touch others."""
    from qdrant_client.models import Distance, VectorParams

    name = assert_own_collection(
        settings.get("FINDASH_QDRANT_COLLECTION") or OWN_COLLECTION
    )
    client = _client(settings)
    try:
        existing = {item.name for item in (client.get_collections().collections or [])}
        if name in existing:
            info = client.get_collection(name)
            size = None
            vectors = info.config.params.vectors
            if hasattr(vectors, "size"):
                size = vectors.size
            elif isinstance(vectors, dict) and "" in vectors:
                size = vectors[""].size
            if size not in (None, VECTOR_SIZE):
                raise RuntimeError(
                    f"{name} exists with vector size {size}, expected {VECTOR_SIZE}; not dropping"
                )
            return "exists"
        client.create_collection(
            collection_name=name,
            vectors_config=VectorParams(size=VECTOR_SIZE, distance=Distance.COSINE),
        )
        _ensure_payload_indexes(client, name)
        return "created"
    finally:
        client.close()


def _ensure_payload_indexes(client, name: str) -> None:
    from qdrant_client.models import PayloadSchemaType

    assert_own_collection(name)
    for field in KEYWORD_INDEXES:
        try:
            client.create_payload_index(
                collection_name=name,
                field_name=field,
                field_schema=PayloadSchemaType.KEYWORD,
            )
        except Exception:
            continue


def own_points_count(settings: dict[str, str]) -> int:
    name = assert_own_collection(
        settings.get("FINDASH_QDRANT_COLLECTION") or OWN_COLLECTION
    )
    client = _client(settings)
    try:
        info = client.get_collection(name)
        return int(info.points_count or 0)
    finally:
        client.close()


def upsert_own_points(settings: dict[str, str], points: list[dict]) -> int:
    """Upsert into findash_tx only. Payload allowlist; no omschrijving."""
    from qdrant_client.models import PointStruct

    name = assert_own_collection(
        settings.get("FINDASH_QDRANT_COLLECTION") or OWN_COLLECTION
    )
    structs = []
    for point in points:
        payload = point["payload"]
        extra = set(payload) - PAYLOAD_KEYS
        if extra:
            raise ValueError("payload has keys that are not allowed")
        if "omschrijving" in payload or "mededelingen" in payload:
            raise ValueError("refusing text payload")
        vector = point["vector"]
        if len(vector) != VECTOR_SIZE:
            raise ValueError("vector size mismatch")
        structs.append(
            PointStruct(id=point["id"], vector=vector, payload=payload)
        )
    if not structs:
        return 0
    client = _client(settings, timeout=60)
    try:
        _ensure_payload_indexes(client, name)
        client.upsert(collection_name=name, points=structs)
        return len(structs)
    finally:
        client.close()


def _hits_to_neighbors(
    hits: list[Any],
    *,
    limit: int,
    exclude_point_id: str | None,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for hit in hits:
        if exclude_point_id and str(hit.id) == exclude_point_id:
            continue
        payload = hit.payload or {}
        out.append(
            {
                "hoofd": payload.get("hoofd") or "",
                "sub": payload.get("sub") or "",
                "entiteit": payload.get("entiteit") or "",
                "richting": payload.get("richting") or "",
                "flow_kind": payload.get("flow_kind") or "",
                "score": float(hit.score),
            }
        )
        if len(out) >= limit:
            break
    return out


def _richting_filter(richting: str | None):
    if not richting:
        return None
    from qdrant_client.models import FieldCondition, Filter, MatchValue

    return Filter(
        must=[FieldCondition(key="richting", match=MatchValue(value=richting))]
    )


def search_own(
    settings: dict[str, str],
    vector: list[float],
    *,
    limit: int = 5,
    exclude_point_id: str | None = None,
    richting: str | None = None,
    client: Any | None = None,
) -> list[dict[str, Any]]:
    """k-NN in findash_tx. Optional richting payload filter. Payload-safe fields only."""
    if len(vector) != VECTOR_SIZE:
        raise ValueError("vector size mismatch")
    name = assert_own_collection(
        settings.get("FINDASH_QDRANT_COLLECTION") or OWN_COLLECTION
    )
    fetch = limit + (1 if exclude_point_id else 0)
    query_filter = _richting_filter(richting)
    own = client is None
    session = client or _client(settings, timeout=8)
    try:
        result = session.query_points(
            collection_name=name,
            query=vector,
            limit=fetch,
            with_payload=True,
            with_vectors=False,
            query_filter=query_filter,
        )
        hits = result.points
    finally:
        if own:
            session.close()
    return _hits_to_neighbors(hits, limit=limit, exclude_point_id=exclude_point_id)


def patch_own_payload(settings: dict[str, str], point_id: str, patch: dict[str, Any]) -> None:
    extra = set(patch) - PAYLOAD_KEYS
    if extra:
        raise ValueError("payload has keys that are not allowed")
    name = assert_own_collection(
        settings.get("FINDASH_QDRANT_COLLECTION") or OWN_COLLECTION
    )
    client = _client(settings, timeout=15)
    try:
        client.set_payload(
            collection_name=name,
            payload=patch,
            points=[point_id],
        )
    finally:
        client.close()
