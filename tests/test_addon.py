from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_addon_manifest_has_gui_secrets_not_values():
    text = (ROOT / "findash/config.yaml").read_text()
    assert "mariadb_password: password" in text
    assert "qdrant_api_key: password" in text
    assert "ingress: true" in text
    assert "share:rw" in text
    assert "github.com/remconiesten/findash" in (ROOT / "repository.yaml").read_text()


def test_run_maps_options_without_logging_keys():
    src = (ROOT / "findash/run.py").read_text()
    assert "MARIADB_PASSWORD" in src
    assert "print(" not in src
    assert "/data/options.json" in src
    assert "/share/findash/anonymize.local.json" in src
