import uuid

from app.ingest import (
    FORBIDDEN_SQL,
    SKIP_KINDS,
    assert_sql_safe,
    build_points,
    index_sql,
    point_id,
    row_to_payload,
)
from app.qdrant_io import PAYLOAD_KEYS, assert_own_collection


def test_ingest_sql_omits_raw_and_pii_columns():
    for src in ("bank", "cc"):
        sql = index_sql(src)
        assert_sql_safe(sql)
        upper = sql.upper()
        for needle in FORBIDDEN_SQL:
            assert needle.upper() not in upper
        assert "NOT IN" in upper
        for kind in SKIP_KINDS:
            assert kind in sql
    assert "saving" not in SKIP_KINDS


def test_point_id_is_stable_uuid5():
    a = point_id("bank", "abc")
    b = point_id("bank", "abc")
    c = point_id("cc", "abc")
    uuid.UUID(a)
    assert a == b
    assert a != c


def test_payload_allowlist_and_iban_stripped_entity():
    payload = row_to_payload(
        "bank",
        {
            "transactie_id": "deadbeef",
            "hoofd": "Huishouden",
            "sub": "boodschappen",
            "entiteit": "AH NL00XXXX0123456789",
            "richting": "Af",
            "rekening": "Rekening B",
            "jaar": 2026,
            "maand": 3,
            "flow_kind": "expense",
            "corrected": 0,
        },
    )
    assert set(payload) <= PAYLOAD_KEYS
    assert "omschrijving" not in payload
    assert "XXXX" not in payload["entiteit"]
    assert payload["corrected"] is False


def test_build_points_length():
    rows = [
        {
            "src": "bank",
            "transactie_id": "aa",
            "payload": row_to_payload(
                "bank",
                {
                    "transactie_id": "aa",
                    "hoofd": "H",
                    "sub": "s",
                    "entiteit": "",
                    "richting": "Af",
                    "rekening": "Rekening B",
                    "jaar": 2024,
                    "maand": 1,
                    "flow_kind": "expense",
                    "corrected": 0,
                },
            ),
        }
    ]
    points = build_points(rows, [[0.0] * 384])
    assert len(points) == 1
    assert_own_collection("findash_tx")


def test_upsert_rejects_foreign_collection():
    import pytest

    with pytest.raises(ValueError):
        assert_own_collection("FinBot")
