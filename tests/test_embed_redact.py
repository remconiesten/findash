from app.embed import (
    PASSAGE_PREFIX,
    QUERY_PREFIX,
    fake_embed_passages,
    index_text,
    normalize,
    rekening_token,
    strip_iban,
)


def test_strip_iban_and_long_digit_runs():
    out = strip_iban("AH NL00XXXX0123456789 extra 12345678 rest")
    assert "XXXX" not in out
    assert "12345678" not in out
    assert "…" in out
    assert "AH" in out
    assert "rest" in out


def test_index_text_is_omschrijving_only():
    text = index_text("AH TO GO AMSTERDAM")
    assert text == "AH TO GO AMSTERDAM"
    assert "Af" not in text
    assert index_text(None) == ""
    assert rekening_token("Rekening A") == "A"
    assert rekening_token("spaarrekening") == "Onbekend"
    assert len(index_text("x" * 500)) == 200


def test_index_text_never_keeps_synthetic_iban():
    text = index_text("Betaling NL00XXXX0123456789")
    assert "NL00" not in text
    assert "XXXX" not in text


def test_normalize_chain():
    assert normalize("AH-TO/GO, Extra") == "ahtogo extra"


def test_e5_prefixes_are_part_of_the_contract():
    assert PASSAGE_PREFIX == "passage: "
    assert QUERY_PREFIX == "query: "
    vecs = fake_embed_passages(["Af|A|AH"])
    assert len(vecs) == 1
    assert len(vecs[0]) == 384
    assert fake_embed_passages(["Af|A|AH"]) == vecs


def test_embed_module_does_not_import_fastembed():
    import app.embed as embed
    import sys

    assert "fastembed" not in sys.modules or hasattr(embed, "Embedder")
    source = embed.__file__
    text = open(source, encoding="utf-8").read()
    assert "from fastembed" not in text.split("class Embedder")[0]
