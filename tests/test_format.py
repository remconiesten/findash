from decimal import Decimal

from app.formatters import format_eur_auto


def test_small_amounts_use_comma_decimals():
    assert format_eur_auto(Decimal("12.3"), "nl") == "€ 12,30"
    assert format_eur_auto(Decimal("99.99"), "nl") == "€ 99,99"


def test_large_amounts_are_whole_euros():
    assert format_eur_auto(Decimal("100"), "nl") == "€ 100"
    assert format_eur_auto(Decimal("1234.6"), "nl") == "€ 1.235"
