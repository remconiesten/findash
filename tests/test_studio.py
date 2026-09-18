from app.studio import (
    EXTRA_PAIRS,
    SKIP_KINDS,
    is_structural_target,
    parse_q,
    parse_src,
    parse_sub_sid,
    parse_txid,
    suggestion_from_neighbors,
)


def test_structural_targets():
    assert is_structural_target("Interne overboeking", "intern")
    assert is_structural_target("Overige uitgaven", "creditcard")
    assert not is_structural_target("Huishouden", "boodschappen")
    assert not is_structural_target("Inkomsten", "van spaarrekening")


def test_vervoer_bekeuringen_in_taxonomy():
    assert ("Vervoer", "bekeuringen") in EXTRA_PAIRS
    assert ("Educatie", "schoolbijdrage") in EXTRA_PAIRS
    assert ("Aflossing", "creditcard") in EXTRA_PAIRS
    assert ("Inkomsten", "ERE") in EXTRA_PAIRS
    assert ("Huishouden", "glazenwassers") in EXTRA_PAIRS


def test_skip_kinds_keep_saving():
    assert "saving" not in SKIP_KINDS
    assert "internal" in SKIP_KINDS


def test_parse_ids():
    assert parse_src("bank") == "bank"
    assert parse_src("raw") is None
    assert parse_txid("a" * 32) == "a" * 32
    assert parse_txid("not-an-id") is None
    assert parse_sub_sid("sub-bank-" + "a" * 32) == "sub-bank-" + "a" * 32
    assert parse_sub_sid("sub-imp-" + "a" * 32) is None
    assert parse_sub_sid("<script>") is None


def test_suggestion_unanimous():
    n = [
        {"hoofd": "Huishouden", "sub": "boodschappen", "score": 0.9},
        {"hoofd": "Huishouden", "sub": "boodschappen", "score": 0.8},
        {"hoofd": "Huishouden", "sub": "boodschappen", "score": 0.7},
    ]
    s = suggestion_from_neighbors(n)
    assert s["unanimous"] is True
    assert s["hoofd"] == "Huishouden"
    assert s["mixed"] is False
    mixed = suggestion_from_neighbors(
        n[:1] + [{"hoofd": "Vrije tijd", "sub": "uit eten", "score": 0.6}]
    )
    assert mixed["unanimous"] is False
    assert mixed["mixed"] is True
    assert len(mixed["split"]) == 2


def test_parse_q_strips_like_wildcards():
    assert parse_q("  Amazon%_  ") == "Amazon"
    assert parse_q(None) == ""


def test_bulk_form_copies_row_fields_on_submit():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    rows = (root / "findash/app/templates/partials/studio_rows.html").read_text()
    assert 'id="bulk-form"' in rows
    assert "studio-bulk-form" in rows
    assert "data-bulk-extra" in rows
    assert "['hoofd', 'sub', 'sub_new', 'entiteit']" in rows
    assert 'form="bulk-form"' in (root / "findash/app/templates/partials/studio_row.html").read_text()


def test_studio_row_subs_do_not_inherit_outer_swap():
    from pathlib import Path

    html = (Path(__file__).resolve().parents[1] / "findash/app/templates/partials/studio_row.html").read_text()
    assert 'hx-swap="outerHTML"' in html
    assert "import-studio/subs?sid=sub-" in html
    assert "js:{hoofd: event.target" not in html
    assert "novalidate" in html
    assert 'class="studio-correct"' in html
    assert 'class="studio-form"' in html
    assert "studio-save" in html
    assert "studio-edit" in html


def test_studio_page_renders():
    from fastapi.testclient import TestClient
    from app.main import app

    client = TestClient(app)
    resp = client.get("/import-studio")
    assert resp.status_code in (200, 503)
    if resp.status_code == 200:
        assert "Import-studio" in resp.text or "studio" in resp.text.lower()
        assert "FinBotTransactionsRaw" not in resp.text
        assert "Tegenrekening" not in resp.text
        assert 'name="q"' in resp.text


def test_subs_endpoint_returns_options_not_a_select():
    from fastapi.testclient import TestClient
    from app.main import app

    client = TestClient(app)
    resp = client.get("/import-studio/subs", params={"hoofd": "Huishouden"})
    assert resp.status_code in (200, 503)
    if resp.status_code == 200:
        assert "<select" not in resp.text.lower()
        assert "<option" in resp.text
    sid = "sub-bank-" + "a" * 32
    wrapped = client.get("/import-studio/subs", params={"hoofd": "Huishouden", "sid": sid})
    if wrapped.status_code == 200:
        assert f'id="{sid}"' in wrapped.text
        assert "<select" in wrapped.text.lower()
        assert "schoonmaakster" in wrapped.text
        assert "selected" in wrapped.text
    evil = client.get(
        "/import-studio/subs",
        params={"hoofd": "Huishouden", "sid": "<script>x</script>"},
    )
    if evil.status_code == 200:
        assert "<script>" not in evil.text
        assert "<select" not in evil.text.lower()


def test_correct_rejects_bad_pair_and_bad_id():
    from fastapi.testclient import TestClient
    from app.main import app

    client = TestClient(app)
    resp = client.post(
        "/import-studio/correct",
        data={
            "src": "bank",
            "transactie_id": "ab" * 16,
            "hoofd": "NietBestaandHoofd",
            "sub": "nietbestaand",
        },
    )
    assert resp.status_code == 400
    assert "paar" in resp.text.lower() or "pair" in resp.text.lower() or resp.text.strip() == "400"
    resp2 = client.post(
        "/import-studio/correct",
        data={"src": "bank", "transactie_id": "nope", "hoofd": "Huishouden", "sub": "boodschappen"},
    )
    assert resp2.status_code == 400
