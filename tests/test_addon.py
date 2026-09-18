import importlib.util
import json
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]


def _load_run():
    spec = importlib.util.spec_from_file_location("addon_run", ROOT / "findash/run.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_addon_manifest_has_gui_secrets_not_values():
    text = (ROOT / "findash/config.yaml").read_text()
    assert "mariadb_password: password" in text
    assert "qdrant_api_key: password" in text
    assert "anonymize_json: str" in text
    assert "ingress: true" in text
    assert "share:rw" in text
    assert 'version: "0.2.2"' in text
    assert "github.com/remconiesten/findash" in (ROOT / "repository.yaml").read_text()


def test_dockerfile_runs_as_root():
    text = (ROOT / "findash/Dockerfile").read_text()
    assert "USER " not in text


def test_run_maps_options_without_logging_keys():
    src = (ROOT / "findash/run.py").read_text()
    assert "MARIADB_PASSWORD" in src
    assert "anonymize_json" in src
    assert "print(" not in src
    assert "/data/options.json" in src
    assert "/share/findash/anonymize.local.json" in src
    assert "/data/anonymize.local.json" in src


def test_persist_anonymize_json_writes_file(tmp_path):
    run = _load_run()
    dest = tmp_path / "anonymize.local.json"
    payload = {
        "last_name": "Voorbeeldnaam",
        "iban_to_label": {"NL00BANK0123456789": "Rekening A"},
    }
    written = run.persist_anonymize_json(json.dumps(payload), dest)
    assert written == dest
    saved = json.loads(dest.read_text(encoding="utf-8"))
    assert saved == payload
    assert run.persist_anonymize_json("  ", dest) is None
    assert run.persist_anonymize_json(payload, dest) == dest


def test_persist_anonymize_json_rejects_invalid():
    run = _load_run()
    try:
        run.persist_anonymize_json("{", Path("/tmp/unused.json"))
    except SystemExit as exc:
        assert "valid JSON" in str(exc)
    else:
        raise AssertionError("expected SystemExit")


def test_env_from_options_skips_anonymize_json():
    run = _load_run()
    env = run.env_from_options(
        {
            "mariadb_host": "core-mariadb",
            "anonymize_json": '{"last_name":"x"}',
        }
    )
    assert env["MARIADB_HOST"] == "core-mariadb"
    assert "anonymize_json" not in env
    assert "FINDASH_ANONYMIZE" not in env


def test_store_icon_and_logo_are_square_png():
    for name in ("icon.png", "logo.png"):
        path = ROOT / "findash" / name
        with Image.open(path) as img:
            assert img.format == "PNG"
            assert img.size[0] == img.size[1]
            assert img.size[0] >= 128
