from app.classify import intern_leg, known_counterpart, TX_KINDS
from app.formatters import redact_text
from app.queries import intern_pair_match


def test_intern_leg_uses_known_labels():
    assert intern_leg("Rekening B", "Af", "Rekening A", None) == (
        "Rekening B",
        "Rekening A",
    )
    assert intern_leg("Rekening A", "Bij", "Rekening B", None) == (
        "Rekening B",
        "Rekening A",
    )


def test_intern_leg_drops_iban_like_counterparts():
    assert known_counterpart("NL00XXXX0123456789") is None
    van, naar = intern_leg("Rekening B", "Af", "NL00XXXX0123456789", None)
    assert van == "Rekening B"
    assert naar is None


def test_intern_leg_falls_back_to_safe_entiteit():
    assert intern_leg("Rekening A", "Af", None, "spaarrekening") == (
        "Rekening A",
        "spaarrekening",
    )


def test_redact_replaces_iban_tokens():
    out = redact_text("Betaling NL12ABNA0123456789 extra")
    assert "ABNA" not in out
    assert "…" in out


def test_redact_empty():
    assert redact_text(None) == ""
    assert redact_text("") == ""


def test_refund_kind_is_only_refunds():
    assert TX_KINDS["refund"] == ("refund",)
    assert "expense" in TX_KINDS["spend"]
    assert "expense" not in TX_KINDS["refund"]


def test_intern_pair_match_keeps_one_direction():
    assert intern_pair_match(
        "Rekening B",
        "Af",
        "Rekening A",
        None,
        "Rekening B",
        "Rekening A",
    )
    assert not intern_pair_match(
        "Rekening A",
        "Af",
        "Rekening B",
        None,
        "Rekening B",
        "Rekening A",
    )
    assert intern_pair_match(
        "Rekening B", "Af", "NL00XXXX0123456789", None, "Rekening B", None
    )
