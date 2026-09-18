import pytest

from app.qdrant_io import OWN_COLLECTION, assert_own_collection, redact_qdrant_error


def test_own_collection_name():
    assert assert_own_collection(OWN_COLLECTION) == "findash_tx"


def test_refuses_finbot_collection_name():
    with pytest.raises(ValueError, match="FinBot"):
        assert_own_collection("FinBot")
    with pytest.raises(ValueError, match="FinBot"):
        assert_own_collection("finbot_tx")


def test_refuses_other_names():
    with pytest.raises(ValueError, match="findash_tx"):
        assert_own_collection("something_else")


def test_redact_error_is_type_only():
    class Fake(Exception):
        pass

    msg = redact_qdrant_error(Fake("api-key=supersecret"))
    assert "supersecret" not in msg
    assert "api-key" not in msg.lower() or "redacted" in msg.lower()
    assert "Fake" in msg
