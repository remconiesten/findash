from datetime import date
from decimal import Decimal

from app.classify import match_cc_settlements
from app.queries import _ymd


def _cc(i, d, amt):
    return {
        "id": i,
        "cc_date": d,
        "bedrag": Decimal(amt),
        "rekening": "Rekening A",
        "af_bij": "Bij",
        "hoofd": "Aflossing",
        "sub": "creditcard",
        "cc_type": "Incasso",
    }


def _bank(i, d, amt):
    return {
        "id": i,
        "bank_date": d,
        "bedrag": Decimal(amt),
        "rekening": "Rekening A",
        "af_bij": "Af",
        "hoofd": "Overige uitgaven",
        "sub": "creditcard",
    }


def test_two_incassos_same_amount_first_wins():
    cc = [
        _cc(2, date(2026, 3, 3), "100.00"),
        _cc(1, date(2026, 2, 3), "100.00"),
    ]
    bank = [_bank(9, date(2026, 2, 5), "100.00")]
    pairs = match_cc_settlements(
        cc, bank, visible_from=date(2026, 2, 1), visible_to=date(2026, 3, 31)
    )
    matched = [p for p in pairs if p["status"] == "matched"]
    unmatched_cc = [p for p in pairs if p["status"] == "unmatched_cc"]
    assert len(matched) == 1
    assert matched[0]["cc_id"] == 1
    assert len(unmatched_cc) == 1
    assert unmatched_cc[0]["cc_id"] == 2


def test_decimal_not_float():
    cc = [_cc(1, date(2026, 8, 3), "10.10")]
    bank = [_bank(2, date(2026, 8, 5), "10.10")]
    pairs = match_cc_settlements(
        cc, bank, visible_from=date(2026, 8, 1), visible_to=date(2026, 8, 31)
    )
    assert pairs[0]["status"] == "matched"
    assert pairs[0]["bedrag"] == Decimal("10.10")


def test_fetch_window_shows_incasso_on_last_day():
    cc = [_cc(1, date(2026, 8, 31), "50.00")]
    bank = [_bank(2, date(2026, 9, 3), "50.00")]
    pairs = match_cc_settlements(
        cc, bank, visible_from=date(2026, 8, 1), visible_to=date(2026, 8, 31)
    )
    assert len(pairs) == 1
    assert pairs[0]["status"] == "matched"


def test_cc_inspect_sql_has_no_strftime_percent():
    """PyMySQL uses % for binds; STR_TO_DATE('%Y') would 500 the homepage."""
    import inspect
    from app import queries as q

    src = inspect.getsource(q.cc_inspect)
    assert "%Y" not in src
    assert "%m" not in src
    assert _ymd(date(2026, 8, 31)) == 20260831


def test_extra_topup_unmatched():
    cc = [_cc(1, date(2026, 6, 3), "521.14")]
    bank = [
        _bank(2, date(2026, 6, 5), "521.14"),
        _bank(3, date(2026, 6, 30), "1000.00"),
    ]
    pairs = match_cc_settlements(
        cc, bank, visible_from=date(2026, 6, 1), visible_to=date(2026, 6, 30)
    )
    statuses = {p["status"] for p in pairs}
    assert "matched" in statuses
    assert "unmatched_topup" in statuses
