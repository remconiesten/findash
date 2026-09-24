from pathlib import Path

import pytest

from app.db import assert_table, tx_ident

ROOT = Path(__file__).resolve().parents[1]


def test_raw_is_forbidden_on_findash():
    with pytest.raises(ValueError, match="forbidden"):
        assert_table("findash", "FinBotTransactionsRaw")
    with pytest.raises(ValueError, match="forbidden"):
        tx_ident("FinBotTransactionsRaw")


def test_tx_ident_points_at_env_schema():
    ident = tx_ident("FinBotTransactions")
    assert ident.endswith("`.`FinBotTransactions`")
    assert "FinBotTransactionsRaw" not in ident


def test_apply_schema_globs_only_seed_local_sql():
    src = (ROOT / "scripts/apply_findash_schema.py").read_text()
    assert 'glob("seed-*.local.sql")' in src
    assert 'glob("*.local.sql")' not in src
    assert "create-findash-user" not in src
