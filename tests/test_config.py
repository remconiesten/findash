import os
from pathlib import Path

import pytest

from app import config


def test_load_settings_from_env_without_dotenv(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "ENV_PATH", tmp_path / "no-such.env")
    monkeypatch.setattr(config, "PKG_ROOT", tmp_path)
    for key in config.SETTING_KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("MARIADB_HOST", "core-mariadb")
    monkeypatch.setenv("MARIADB_PORT", "3306")
    monkeypatch.setenv("MARIADB_USER", "findash")
    monkeypatch.setenv("MARIADB_PASSWORD", "from-env")
    monkeypatch.setenv("MARIADB_DATABASE", "findash")
    settings = config.load_settings(path=tmp_path / "no-such.env")
    assert settings["MARIADB_HOST"] == "core-mariadb"
    assert settings["MARIADB_PASSWORD"] == "from-env"
    assert settings["FINDASH_DATABASE"] == "findash"


def test_env_overrides_dotenv(monkeypatch, tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "MARIADB_HOST=from-file\n"
        "MARIADB_PORT=3306\n"
        "MARIADB_USER=findash\n"
        "MARIADB_PASSWORD=file-secret\n"
        "MARIADB_DATABASE=findash\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("MARIADB_HOST", "from-env")
    monkeypatch.setenv("MARIADB_PORT", "3306")
    monkeypatch.setenv("MARIADB_USER", "findash")
    monkeypatch.setenv("MARIADB_PASSWORD", "env-secret")
    monkeypatch.setenv("MARIADB_DATABASE", "findash")
    settings = config.load_settings(path=env_file)
    assert settings["MARIADB_HOST"] == "from-env"
    assert settings["MARIADB_PASSWORD"] == "env-secret"


def test_load_settings_missing_raises(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "ENV_PATH", tmp_path / "no-such.env")
    for key in config.SETTING_KEYS:
        monkeypatch.delenv(key, raising=False)
    with pytest.raises(ValueError, match="Missing"):
        config.load_settings(path=tmp_path / "no-such.env")


def test_anonymize_path_from_env(monkeypatch, tmp_path):
    target = tmp_path / "anon.json"
    target.write_text(
        '{"last_name":"X","iban_to_label":{"NL00TEST0123456789":"Rekening A"}}',
        encoding="utf-8",
    )
    monkeypatch.setenv("FINDASH_ANONYMIZE", str(target))
    from app.anonymize import load_anonymize_rules

    rules = load_anonymize_rules()
    assert rules.iban_n == 1
    assert Path(os.environ["FINDASH_ANONYMIZE"]) == target


def test_chart_rekeningen_puts_cc_first():
    from app.config import chart_rekeningen

    ordered = chart_rekeningen()
    assert ordered[0] == "Rekening A"
    assert "Rekening B" in ordered
    assert chart_rekeningen("Rekening B") == ("Rekening B",)
