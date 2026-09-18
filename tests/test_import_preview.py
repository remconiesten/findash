from app.hybrid import memory_for_text
from app.import_preview import (
    apply_overrides,
    certainty,
    choose_cats,
    default_pair,
    preview_bank,
    sort_preview_rows,
)
from app.anonymize import AnonymizeRules


def _rules():
    return AnonymizeRules(
        last_name="Voorbeeldnaam",
        iban_to_label=(("NL00BANK0123456789", "Rekening A"),),
        iban_n=1,
        last_name_set=True,
    )


def test_default_pair_direction():
    assert default_pair("Af") == ("Overige uitgaven", "overig")
    assert default_pair("Bij") == ("Inkomsten", "overig")
    assert default_pair("Bij", "Incasso") == ("Aflossing", "creditcard")


def test_preview_marks_dupe_and_strips_iban():
    csv = (
        "Datum;Naam / Omschrijving;Rekening;Tegenrekening;Code;Af Bij;"
        "Bedrag (EUR);Mutatiesoort;Mededelingen;Saldo na mutatie\n"
        "20240115;AH TO GO;NL00BANK0123456789;;GT;Af;12,50;Betaalautomaat;;100,00\n"
    )
    existing = set()
    preview = preview_bank(csv.encode("utf-8"), _rules(), existing, [])
    assert preview["n_new"] == 1
    row = preview["rows"][0]
    assert row["status"] == "nieuw"
    assert "NL00" not in row["omschrijving"]
    assert "NL00" not in str(row.get("insert"))
    assert row["insert"]["Rekening"] == "Rekening A"
    assert row["rekening"] == "Rekening A"
    assert row["tone"] == "doubt"
    assert row["mem_share"] is None
    txid = row["txid"]
    preview2 = preview_bank(csv.encode("utf-8"), _rules(), {txid}, [])
    assert preview2["n_dupe"] == 1
    assert preview2["rows"][0]["status"] == "dubbel"
    assert preview2["rows"][0]["insert"] is None


def test_memory_for_text_uses_existing_labels():
    existing = [
        {
            "index_text": "Albert Heijn",
            "richting": "Af",
            "hoofd": "Huishouden",
            "sub": "boodschappen",
        }
        for _ in range(5)
    ]
    hit = memory_for_text(existing, "Albert Heijn", "Af")
    assert hit["hoofd"] == "Huishouden"
    assert memory_for_text(existing, "Iets anders", "Af") is None


def test_certainty_sure_vs_doubt():
    sure = certainty({"share": 1.0, "n": 12, "unanimous": True})
    assert sure["tone"] == "sure"
    weak = certainty({"share": 0.82, "n": 10, "unanimous": False})
    assert weak["tone"] == "doubt"
    assert certainty(None)["tone"] == "doubt"


def test_apply_overrides_writes_entity_and_pair():
    inserts = [
        {
            "TransactieID": "ab" * 16,
            "Hoofdcategorie": "Overige uitgaven",
            "Subcategorie": "overig",
            "Entiteit": "",
        }
    ]
    form = {
        "hoofd-" + "ab" * 16: "Huishouden",
        "sub-" + "ab" * 16: "boodschappen",
        "entiteit-" + "ab" * 16: "Albert Heijn",
    }
    apply_overrides(inserts, form, {("Huishouden", "boodschappen")})
    assert inserts[0]["Hoofdcategorie"] == "Huishouden"
    assert inserts[0]["Subcategorie"] == "boodschappen"
    assert inserts[0]["Entiteit"] == "Albert Heijn"


def test_preview_memory_is_green():
    csv = (
        "Datum;Naam / Omschrijving;Rekening;Tegenrekening;Code;Af Bij;"
        "Bedrag (EUR);Mutatiesoort;Mededelingen;Saldo na mutatie\n"
        "20240115;Albert Heijn;NL00BANK0123456789;;GT;Af;12,50;Betaalautomaat;;100,00\n"
    )
    existing_mem = [
        {
            "index_text": "Albert Heijn",
            "richting": "Af",
            "hoofd": "Huishouden",
            "sub": "boodschappen",
        }
        for _ in range(5)
    ]
    preview = preview_bank(csv.encode("utf-8"), _rules(), set(), existing_mem)
    row = preview["rows"][0]
    assert row["hoofd"] == "Huishouden"
    assert row["tone"] == "sure"
    assert row["mem_n"] == 5
    assert abs(row["mem_share"] - 1.0) < 1e-9


def test_incasso_ignores_memory_and_is_sure():
    poisoned = [
        {
            "index_text": "MAANDINCASSO",
            "richting": "Bij",
            "hoofd": "Interne overboeking",
            "sub": "intern",
        }
        for _ in range(12)
    ]
    hoofd, sub, cert = choose_cats("Bij", "MAANDINCASSO", poisoned, "Incasso")
    assert (hoofd, sub) == ("Aflossing", "creditcard")
    assert cert["tone"] == "sure"
    assert cert["source"] == "regel"


def test_sort_doubt_before_sure_then_date_desc():
    rows = [
        {"status": "nieuw", "tone": "sure", "datum": "2026-01-02", "txid": "a"},
        {"status": "dubbel", "tone": "", "datum": "2026-06-01", "txid": "b"},
        {"status": "nieuw", "tone": "doubt", "datum": "2026-01-01", "txid": "c"},
        {"status": "nieuw", "tone": "doubt", "datum": "2026-03-01", "txid": "d"},
        {"status": "nieuw", "tone": "sure", "datum": "2026-05-01", "txid": "e"},
    ]
    got = [r["txid"] for r in sort_preview_rows(rows)]
    assert got == ["d", "c", "e", "a", "b"]
