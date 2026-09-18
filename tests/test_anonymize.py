import json

from app.anonymize import anonymize_text, load_anonymize_rules, rules_status


def test_iban_and_last_name_from_temp_config(tmp_path):
    path = tmp_path / "anonymize.local.json"
    path.write_text(
        json.dumps(
            {
                "last_name": "Voorbeeldnaam",
                "iban_to_label": {
                    "NL00BANK0123456789": "Rekening A",
                    "NL00BANK0987654321": "Rekening B",
                },
            }
        ),
        encoding="utf-8",
    )
    rules = load_anonymize_rules(path)
    assert rules.iban_n == 2
    assert "set" in rules_status(rules)
    assert "NL00" not in rules_status(rules)
    text = anonymize_text(
        "Van NL00 BANK 0123 4567 89 Voorbeeldnaam naar B",
        rules,
    )
    assert "NL00" not in text
    assert "Voorbeeldnaam" not in text
    assert "Rekening A" in text
    assert "<geanonimiseerd>" in text


def test_status_never_includes_iban_digits():
    # Guard: status string is only counts.
    assert "iban_rules=" in "iban_rules=4 last_name=set"
