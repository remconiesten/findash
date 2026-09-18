from decimal import Decimal

from app.formatters import HOOFD_COLORS, colors_for_keys, format_eur_auto, hue_distance, series_tone


def test_small_amounts_use_comma_decimals():
    assert format_eur_auto(Decimal("12.3"), "nl") == "€ 12,30"
    assert format_eur_auto(Decimal("99.99"), "nl") == "€ 99,99"


def test_large_amounts_are_whole_euros():
    assert format_eur_auto(Decimal("100"), "nl") == "€ 100"
    assert format_eur_auto(Decimal("1234.6"), "nl") == "€ 1.235"


def test_sub_colors_stable_regardless_of_order():
    keys_a = ["boodschappen", "hellofresh", "katten"]
    keys_b = list(reversed(keys_a))
    parent = "Huishouden"
    amounts = {"boodschappen": 80, "hellofresh": 40, "katten": 10}
    a = colors_for_keys(keys_a, parent, amounts)
    b = colors_for_keys(keys_b, parent, amounts)
    assert a == b
    assert a["boodschappen"] == HOOFD_COLORS["Huishouden"]
    assert a["hellofresh"] == HOOFD_COLORS["Wonen"]
    assert a["katten"] == HOOFD_COLORS["Vrije tijd"]
    assert hue_distance(a["boodschappen"], a["hellofresh"]) > 40


def test_largest_sub_uses_parent_pill_color():
    pal = colors_for_keys(["klein", "groot"], "Wonen", {"klein": 1, "groot": 50})
    assert pal["groot"] == HOOFD_COLORS["Wonen"]
    assert pal["klein"] != pal["groot"]
    assert pal["klein"] in HOOFD_COLORS.values()


def test_hoofd_colors_keep_named_palette():
    palette = colors_for_keys(["Wonen", "Vervoer"])
    assert palette["Wonen"] == "#2A9D8F"
    assert palette["Vervoer"] == "#4CC9F0"


def test_series_tone_income_darker_than_second():
    assert series_tone("income", 0) == "#2A9D8F"
    assert series_tone("income", 1) == "#8ED0C6"
    assert series_tone("expense", 0) == "#E76F51"
    assert series_tone("expense", 1) != series_tone("expense", 0)


def test_ivu_legend_income_accounts_then_expense_accounts():
    from app.i18n import Translator
    from app.main import _localize_ivu

    tr = Translator("nl", {}, {})
    out = _localize_ivu(
        {
            "ym": [202601],
            "datasets": [
                {"key": "Rekening A", "kind": "income", "data": [1]},
                {"key": "Rekening B", "kind": "income", "data": [2]},
                {"key": "Rekening A", "kind": "expense", "data": [3]},
                {"key": "Rekening B", "kind": "expense", "data": [4]},
            ],
        },
        tr,
    )
    labels = [row["label"] for row in out["datasets"]]
    assert labels[0].startswith("Inkomsten")
    assert labels[1].startswith("Inkomsten")
    assert labels[2].startswith("Uitgaven")
    assert labels[3].startswith("Uitgaven")
    assert "Rekening A" in labels[0]
    assert "Rekening B" in labels[1]
