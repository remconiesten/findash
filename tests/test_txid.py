import hashlib
from decimal import Decimal

from app.amounts import cc_mutatie_hash_token, js_number_to_string, parse_nl_amount
from app.cc_parse import bank_ymd, cc_ymd, extract_cc_lines, parse_cc_lines
from app.txid import bank_txid, cc_txid


def test_bank_txid_concatenates_four_raw_fields():
    raw = "20240115" + "AH TO GO" + "statiegeld" + "12.34"
    assert bank_txid("20240115", "AH TO GO", "statiegeld", "12.34") == hashlib.md5(
        raw.encode("utf-8")
    ).hexdigest()
    assert len(bank_txid("20240115", "AH TO GO", "statiegeld", "12.34")) == 32


def test_bank_txid_treats_missing_mededelingen_as_empty():
    assert bank_txid("20240115", "X", None, "1") == bank_txid("20240115", "X", "", "1")


def test_cc_txid_uses_parser_fields():
    token = cc_mutatie_hash_token("- 12,50")
    assert cc_txid("01-06-2025", "AH TO GO", "Betaling", token) == hashlib.md5(
        f"01-06-2025AH TO GOBetaling{token}".encode("utf-8")
    ).hexdigest()


def test_parse_nl_amount_european():
    assert parse_nl_amount("1.234,56") == Decimal("1234.56")
    assert parse_nl_amount("+ 12,50") == Decimal("12.50")
    assert parse_nl_amount("-1,00") == Decimal("-1.00")


def test_js_number_to_string_matches_integer_money():
    assert js_number_to_string(12.0) == "12"
    assert js_number_to_string(-12.5) == "-12.5"
    assert cc_mutatie_hash_token("+1.101,57") == "1101.57"
    assert cc_mutatie_hash_token("- 12,50") == "-12.5"


def test_bank_and_cc_dates():
    assert bank_ymd(20240115) == (2024, 1, 15)
    assert bank_ymd("20260831") == (2026, 8, 31)
    assert cc_ymd("03-06-2025") == (2025, 6, 3)


def test_extract_and_parse_cc_pdf_lines():
    pdf = "\n".join(
        [
            "noise",
            "01-06-2025 AH TO GO AMSTERDAM Betaling - 12,50",
            "03-06-2025 MAANDINCASSO Incasso +1.101,57",
            "not a tx",
            "15-01-2025 JAARLIJKSE Kosten - 1,50",
        ]
    )
    text = extract_cc_lines(pdf)
    rows = parse_cc_lines(text)
    assert len(rows) == 3
    assert rows[0]["Type"] == "Betaling"
    assert rows[0]["Omschrijving"] == "AH TO GO AMSTERDAM"
    assert rows[0]["Mutatie"] == Decimal("-12.50")
    assert rows[0]["Rekening"] == "Rekening A"
    assert rows[1]["Type"] == "Incasso"
    assert rows[1]["Mutatie"] == Decimal("1101.57")
    # n8n stripped only Incasso|Betaling; Kosten remains in Omschrijving (hash-stable).
    assert rows[2]["Type"] == "Kosten"
    assert "Kosten" in str(rows[2]["Omschrijving"])
