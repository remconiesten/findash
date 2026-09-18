import pytest

from app.db import assert_table, tx_ident


def test_raw_is_forbidden_on_findash():
    with pytest.raises(ValueError, match="forbidden"):
        assert_table("findash", "FinBotTransactionsRaw")
    with pytest.raises(ValueError, match="forbidden"):
        tx_ident("FinBotTransactionsRaw")


def test_tx_ident_points_at_env_schema():
    ident = tx_ident("FinBotTransactions")
    assert ident.endswith("`.`FinBotTransactions`")
    assert "FinBotTransactionsRaw" not in ident
