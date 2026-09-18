from app.bank_csv import CsvFormatError, parse_bank_csv
from app.txid import bank_txid


def test_parse_ing_semicolon_and_hash():
    csv = (
        "Datum;Naam / Omschrijving;Rekening;Tegenrekening;Code;Af Bij;"
        "Bedrag (EUR);Mutatiesoort;Mededelingen;Saldo na mutatie\n"
        "20240115;AH TO GO;NL00BANK0123456789;;GT;Af;12,50;Betaalautomaat;statiegeld;100,00\n"
    )
    rows, headers = parse_bank_csv(csv)
    assert "Datum" in headers
    assert len(rows) == 1
    row = rows[0]
    assert row["error"] is None
    assert row["richting"] == "Af"
    assert row["txid"] == bank_txid("20240115", "AH TO GO", "statiegeld", "100,00")
    assert row["jaar"] == 2024


def test_missing_columns_lists_headers():
    try:
        parse_bank_csv("Foo;Bar\n1;2\n")
        assert False
    except CsvFormatError as exc:
        assert "Foo" in exc.headers
        assert "Datum" in str(exc)


def test_duplicate_hash_same_raw_cells():
    csv = (
        "Datum;Naam / Omschrijving;Rekening;Af Bij;Bedrag (EUR);"
        "Mededelingen;Saldo na mutatie\n"
        "20240115;AH;NL00X;Af;1,00;x;10,00\n"
        "20240115;AH;NL00X;Af;1,00;x;10,00\n"
    )
    rows, _headers = parse_bank_csv(csv)
    assert rows[0]["txid"] == rows[1]["txid"]
