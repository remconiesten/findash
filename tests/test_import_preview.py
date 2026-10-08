from app.hybrid import memory_for_text
from pathlib import Path

from app.import_preview import (
    apply_overrides,
    certainty,
    choose_cats,
    default_pair,
    preview_bank,
    preview_cc_text,
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


def _cc_sample() -> str:
    return "\n".join(
        [
            "01-06-2025 SHOP AMSTERDAM Betaling - 12,50",
            "02-06-2025 SHOP AMSTERDAM Credit + 12,50",
            "03-06-2025 MAANDINCASSO Incasso + 40,00",
            "09-06-2025 DIT IS GEEN TRANSACTIE",
        ]
    )


def test_preview_cc_refund_follows_charge_and_unmatched_is_visible():
    preview = preview_cc_text(_cc_sample(), _rules(), set(), [])
    refunds = [r for r in preview["rows"] if r.get("typ") == "Credit"]
    charges = [r for r in preview["rows"] if r.get("typ") == "Betaling"]
    incasso = [r for r in preview["rows"] if r.get("typ") == "Incasso"]
    fout = [r for r in preview["rows"] if r["status"] == "fout"]
    assert preview["n_new"] == 3
    assert preview["n_err"] == 1
    assert len(refunds) == 1 and refunds[0]["status"] == "nieuw"
    assert refunds[0]["insert"]["Af Bij"] == "Bij"
    assert refunds[0]["hoofd"] == charges[0]["hoofd"] == "Overige uitgaven"
    assert refunds[0]["sub"] == charges[0]["sub"] == "overig"
    assert refunds[0]["hoofd"] != "Inkomsten"
    assert incasso[0]["richting"] == "Bij"
    assert incasso[0]["hoofd"] == "Aflossing"
    assert fout[0].get("insert") is None
    assert "TRANSACTIE" in fout[0]["omschrijving"]
    assert preview["rows"][0]["status"] == "fout"


def test_preview_cc_bad_date_does_not_hide_the_rest():
    text = "\n".join(
        [
            "01-06-2025 SHOP AMSTERDAM Betaling - 12,50",
            "31-02-2025 SHOP AMSTERDAM Credit + 1,00",
        ]
    )
    preview = preview_cc_text(text, _rules(), set(), [])
    assert preview["n_new"] == 1
    assert preview["n_err"] == 1
    assert preview["rows"][0]["status"] == "fout"
    kept = [r for r in preview["rows"] if r.get("typ") == "Betaling"]
    assert kept[0]["status"] == "nieuw"
    assert kept[0]["richting"] == "Af"


def test_preview_cc_refund_uses_af_memory_when_charge_is_absent():
    memory = [
        {
            "index_text": "shop amsterdam",
            "richting": "Af",
            "hoofd": "Huishouden",
            "sub": "boodschappen",
        }
        for _ in range(3)
    ]
    text = "02-06-2025 SHOP AMSTERDAM Credit + 12,50"
    preview = preview_cc_text(text, _rules(), set(), memory)
    row = preview["rows"][0]
    assert row["richting"] == "Bij"
    assert row["hoofd"] == "Huishouden"
    assert row["sub"] == "boodschappen"
    assert row["tone"] == "sure"
    assert preview["n_err"] == 0


def test_import_wait_markup_is_hidden_until_submit():
    root = Path(__file__).resolve().parents[1] / "findash" / "app" / "templates"
    form = (root / "partials" / "import_form.html").read_text()
    preview = (root / "import_preview.html").read_text()
    base = (root / "base.html").read_text()
    assert 'class="import-wait" hidden' in form
    assert "import.wait_preview" in form
    assert 'class="import-wait" hidden' in preview
    assert "import.wait_commit" in preview
    assert "import-form" in base and "import-commit" in base
    assert "aria-busy" in base


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
