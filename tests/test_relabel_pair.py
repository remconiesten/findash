import importlib.util
from pathlib import Path

import pytest


def _mod():
    path = Path(__file__).resolve().parent.parent / "scripts" / "relabel_pair.py"
    spec = importlib.util.spec_from_file_location("relabel_pair", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_validate_move_ok():
    _mod().validate_move("Wonen", "Huishouden", "glazenwassers")


def test_validate_move_rejects_same_and_structural():
    mod = _mod()
    with pytest.raises(ValueError):
        mod.validate_move("Wonen", "Wonen", "glazenwassers")
    with pytest.raises(ValueError):
        mod.validate_move("Interne overboeking", "Huishouden", "intern")
    with pytest.raises(ValueError):
        mod.validate_move("", "Huishouden", "glazenwassers")
