from app.hybrid import (
    entity_denied,
    first_non_null,
    memory_suggestions,
    propose,
    suggestion_from_others,
    tally,
)


def test_entity_denied_centroid_and_ing():
    assert entity_denied("persoon") is True
    assert entity_denied("spaarrekening") is True
    assert entity_denied("ING") is True
    assert entity_denied("ING Bank N.V.") is True
    assert entity_denied("Oranje Spaarrekening") is False
    assert entity_denied("Albert Heijn") is False


def test_others_need_min_n_and_share():
    same = [("Huishouden", "boodschappen")] * 5
    hit = suggestion_from_others(same, min_n=3, min_share=0.80)
    assert hit is not None
    assert hit["layer"] == "exact"
    assert hit["unanimous"] is True
    assert suggestion_from_others(same[:2], min_n=3, min_share=0.80) is None
    mixed = [("Huishouden", "boodschappen")] * 4 + [("Vrije tijd", "uit eten")] * 4
    assert suggestion_from_others(mixed, min_n=3, min_share=0.80) is None


def test_memory_loo_ah_silent_on_stable_group_and_amazon_mixed():
    ah = [
        {
            "index_text": "Albert Heijn",
            "richting": "Af",
            "entiteit": "Albert Heijn",
            "hoofd": "Huishouden",
            "sub": "boodschappen",
        }
        for _ in range(12)
    ]
    mem = memory_suggestions(ah)
    assert all(m and m["hoofd"] == "Huishouden" for m in mem)
    gold = [("Huishouden", "boodschappen")] * 12
    t = tally(gold, mem)
    assert t["shown"] == 12
    assert t["pair_ok"] == 12

    amaz = []
    cats = [
        ("Vrije tijd", "abonnementen"),
        ("Huishouden", "boodschappen"),
        ("Telecom/tech", "apparatuur"),
        ("Vrije tijd", "uit eten"),
    ]
    for i in range(12):
        h, s = cats[i % 4]
        amaz.append(
            {
                "index_text": "Amazon Payments Europe SCA",
                "richting": "Af",
                "entiteit": "Amazon Payments Europe SCA",
                "hoofd": h,
                "sub": s,
            }
        )
    mem_a = memory_suggestions(amaz)
    assert all(m is None for m in mem_a)

    same_ent = [
        {
            "index_text": f"AH filiaal {i}",
            "richting": "Af",
            "entiteit": "Albert Heijn",
            "hoofd": "Huishouden",
            "sub": "boodschappen",
        }
        for i in range(12)
    ]
    assert all(m is None for m in memory_suggestions(same_ent))


def test_propose_memory_only_knn_never_a_suggestion():
    mem = {"hoofd": "Huishouden", "sub": "boodschappen", "share": 1.0, "n": 12}
    knn = {
        "hoofd": "Vrije tijd",
        "sub": "uit eten",
        "score": 1.0,
        "unanimous": True,
        "mixed": False,
    }
    hit = propose(mem, knn)
    assert hit is not None
    assert hit["source"] == "text"
    assert hit["hoofd"] == "Huishouden"
    assert propose(None, knn) is None
    assert propose(None, None) is None


def test_first_non_null_and_tally_silent():
    assert first_non_null(None, {"hoofd": "X", "sub": "y"})["hoofd"] == "X"
    t = tally([("A", "a"), ("B", "b")], [None, None])
    assert t["shown"] == 0
    assert t["silent"] == 2
    assert t["hoofd_acc"] is None
