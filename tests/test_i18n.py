from pathlib import Path

from app.i18n import (
    CC_TYPE_EN,
    CC_TYPE_RU,
    EN_UI,
    HOOFD_EN,
    HOOFD_RU,
    NL_UI,
    REKENING_EN,
    REKENING_RU,
    RU_UI,
    SUB_EN,
    SUB_RU,
    Translator,
)

ROOT = Path(__file__).resolve().parents[1]
KNOWN_SUBS = {
    "AI",
    "WA",
    "abonnementen",
    "autoverzekering",
    "bankkosten",
    "belastingen overig",
    "belastingteruggaaf",
    "bibliotheek",
    "bijdrage kado",
    "bijdrage opa",
    "boeken",
    "boodschappen",
    "creditcard",
    "crypto verkoop",
    "cursus",
    "dansles",
    "debitrente",
    "eigen bijdrage",
    "eigen risico",
    "elektriciteit",
    "entertainment",
    "fiets",
    "geldopnames",
    "gemeentebelasting",
    "glazenwassers",
    "goede doelen",
    "hellofresh",
    "home automation",
    "hypotheek",
    "iCloud",
    "inrichting",
    "intern",
    "internet",
    "kado's",
    "kapper",
    "katten",
    "kinderbijslag",
    "kinderopvang",
    "kleding",
    "laadpaal",
    "laadvergoeding",
    "lekkernijen",
    "lekker\u00adnijen",
    "manicure/pedicure",
    "mobiel",
    "onderhoud",
    "opstal",
    "overig",
    "overlijdensrisico",
    "parkeren",
    "salaris",
    "school",
    "schoonmaakster",
    "schuldaflossing",
    "software",
    "sparen",
    "sport",
    "studiefonds kinderen",
    "supplementen",
    "taalcursus",
    "toeslagen",
    "tol",
    "tuin",
    "uit bouwdepot",
    "uit eten",
    "uitstapjes",
    "uitvaart",
    "vakantie",
    "van spaarrekening",
    "verbouwing",
    "verzorging",
    "warmte",
    "water",
    "waterschapsbelasting",
    "zakgeld",
    "zorgverzekering",
    "zwemles",
}


def test_ui_packs_cover_nl_keys():
    assert set(NL_UI) == set(EN_UI)
    assert set(NL_UI) == set(RU_UI)


def test_vocab_packs_are_paired():
    assert set(HOOFD_EN) == set(HOOFD_RU)
    assert set(SUB_EN) == set(SUB_RU)
    assert set(REKENING_EN) == set(REKENING_RU)
    assert set(CC_TYPE_EN) == set(CC_TYPE_RU)


def test_known_subs_are_translated():
    assert KNOWN_SUBS <= set(SUB_EN)


def test_term_fallbacks():
    en = Translator("en", {}, {})
    ru = Translator("ru", {}, {})
    assert en.term("sub", "boodschappen") == "groceries"
    assert ru.term("rekening", "spaarrekening") == "сбережения"
    assert en.term("cc_type", "Incasso") == "Direct debit"
    assert en.ui("preset.this_year") == "This year"


def test_nunito_is_primary_and_vendored():
    css = (ROOT / "findash/app/static/css/app.css").read_text()
    stack = 'font-family: "Nunito"'
    assert stack in css
    assert css.find(stack) < css.find("ui-rounded")
    fonts = ROOT / "findash/app/static/fonts"
    for subset in ("latin", "latin-ext", "cyrillic"):
        for weight in (400, 600, 700):
            path = fonts / f"nunito-{subset}-{weight}.woff2"
            assert path.is_file(), path
            assert path.read_bytes()[:4] == b"wOF2"
    assert "SIL OPEN FONT LICENSE" in (fonts / "OFL.txt").read_text()
    assert "nunito-latin-700.woff2" in css
