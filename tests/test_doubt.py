from decimal import Decimal

from app.doubt import LARGE_SHOP_SAVING, annotate


def _row(**kwargs):
    base = {
        "hoofd": "Inkomsten",
        "sub": "van spaarrekening",
        "entiteit_key": "Albert Heijn",
        "richting": "Bij",
        "bedrag": Decimal("520.00"),
        "flow_kind": "saving",
        "suggest": {
            "hoofd": "Huishouden",
            "sub": "boodschappen",
            "score": 0.91,
            "unanimous": True,
            "neighbor_n": 5,
        },
        "above": True,
        "corrected": False,
    }
    base.update(kwargs)
    return base


def test_large_ah_saving_suppresses_grocery_knn():
    majority = {"albert heijn": ("Huishouden", "boodschappen", 400)}
    row = _row()
    annotate(row, majority, Decimal("0.70"))
    assert "shop_saving_large" in row["flags"]
    assert row["suggest"] is None
    assert row["bulk_ok"] is False
    assert row["doubt"] is True
    assert row["bedrag"] >= LARGE_SHOP_SAVING


def test_small_shop_saving_uses_rule_not_knn():
    majority = {"albert heijn": ("Huishouden", "boodschappen", 400)}
    row = _row(bedrag=Decimal("12.50"))
    annotate(row, majority, Decimal("0.70"))
    assert "shop_saving_small" in row["flags"]
    assert row["suggest"]["hoofd"] == "Huishouden"
    assert row["suggest"]["source"] == "regel"
    assert row["suggest"]["score"] is None
    assert row["bulk_ok"] is True


def test_knn_split_blocks_bulk_even_at_1():
    row = _row(
        hoofd="Huishouden",
        sub="overig",
        flow_kind="expense",
        entiteit_key="Amazon Payments Europe SCA",
        text_key="amazon payments europe sca",
        suggest={
            "hoofd": "Vrije tijd",
            "sub": "abonnementen",
            "score": 1.0,
            "unanimous": False,
            "mixed": True,
            "neighbor_n": 5,
            "split": [
                {"hoofd": "Vrije tijd", "sub": "abonnementen", "n": 3},
                {"hoofd": "Huishouden", "sub": "boodschappen", "n": 2},
            ],
        },
        knn={
            "hoofd": "Vrije tijd",
            "sub": "abonnementen",
            "score": 1.0,
            "unanimous": False,
            "mixed": True,
            "neighbor_n": 5,
        },
    )
    annotate(row, {}, Decimal("0.70"))
    assert "knn_split" in row["flags"]
    assert row["bulk_ok"] is False
    assert row["above"] is False


def test_split_text_blocks_unanimous_knn_bulk():
    row = _row(
        hoofd="Huishouden",
        sub="overig",
        flow_kind="expense",
        entiteit_key="Amazon Payments Europe SCA",
        text_key="amazon payments europe sca",
        suggest={
            "hoofd": "Vrije tijd",
            "sub": "abonnementen",
            "score": 1.0,
            "unanimous": True,
            "mixed": False,
            "neighbor_n": 5,
        },
        knn={
            "hoofd": "Vrije tijd",
            "sub": "abonnementen",
            "score": 1.0,
            "unanimous": True,
            "mixed": False,
            "neighbor_n": 5,
        },
    )
    annotate(
        row,
        {},
        Decimal("0.70"),
        split_texts={"amazon payments europe sca"},
        mixed_entities={"amazon payments europe sca"},
    )
    assert "split_text" in row["flags"]
    assert "mixed_entity" in row["flags"]
    assert row["bulk_ok"] is False


def test_overig_text_memory_is_bulk_ok():
    majority = {}
    row = _row(
        hoofd="Huishouden",
        sub="overig",
        flow_kind="expense",
        entiteit_key="",
        suggest={
            "hoofd": "Huishouden",
            "sub": "boodschappen",
            "source": "text",
            "share": 1.0,
            "n": 12,
            "unanimous": True,
        },
    )
    annotate(row, majority, Decimal("0.70"))
    assert row["bulk_ok"] is True
    assert "overig" in row["flags"]


def test_shop_as_income_overig():
    majority = {"lidl": ("Huishouden", "boodschappen", 300)}
    row = _row(
        sub="overig",
        flow_kind="income",
        entiteit_key="Lidl",
        bedrag=Decimal("9.97"),
        suggest=None,
    )
    annotate(row, majority, Decimal("0.70"))
    assert "shop_as_income" in row["flags"]
    assert row["suggest"]["sub"] == "boodschappen"
    assert row["bulk_ok"] is True
