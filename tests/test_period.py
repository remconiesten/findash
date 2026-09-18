from datetime import date

from app.classify import (
    add_months,
    bucket_sql,
    build_payday_starts,
    default_from_to,
    month_bounds,
    period_presets,
    period_ymd,
    salary_ym_of,
)
from app.i18n import Translator


def test_default_window_202608():
    frm, to = default_from_to(202608)
    assert to == 202608
    assert frm == 202509


def test_add_months_rollover():
    assert add_months(202601, -1) == 202512
    assert add_months(202512, 1) == 202601


def test_preset_all_comes_first():
    from app.main import _preset_ctx

    items = _preset_ctx(202601, 202609, all_from=202401, all_to=202609)
    assert items[0]["id"] == "all"
    assert items[0]["from_year"] == 2024
    assert items[0]["from_month"] == 1
    assert items[0]["active"] is False
    assert any(p["id"] == "this_year" for p in items)


def test_presets_september_2026():
    by_id = {p["id"]: p for p in period_presets(date(2026, 9, 9))}
    assert by_id["this_year"]["from_ym"] == 202601
    assert by_id["this_year"]["to_ym"] == 202609
    assert by_id["this_quarter"]["from_ym"] == 202607
    assert by_id["this_quarter"]["to_ym"] == 202609
    assert by_id["last_quarter"]["from_ym"] == 202604
    assert by_id["last_quarter"]["to_ym"] == 202606
    assert by_id["this_month"]["from_ym"] == 202609
    assert by_id["last_month"]["from_ym"] == 202608


def test_month_names_nl_en_ru():
    nl = Translator("nl", {}, {})
    en = Translator("en", {}, {})
    ru = Translator("ru", {}, {})
    assert nl.month(9) == "september"
    assert en.month(9) == "September"
    assert ru.month(9) == "сентябрь"
    assert nl.ym(2026, 8, short=False) == "augustus 2026"
    assert "sep" in nl.ym(2025, 9, short=True)
    assert en.ui("app.title") == "FinDash"
    assert ru.term("hoofd", "Huishouden") == "Быт"
    assert en.term("sub", "boodschappen") == "groceries"


def test_salary_ym_named_after_ending_month():
    assert salary_ym_of(date(2026, 8, 25)) == 202609
    assert salary_ym_of(date(2026, 9, 24)) == 202609
    assert salary_ym_of(date(2026, 9, 25)) == 202610
    assert salary_ym_of(date(2025, 12, 25)) == 202601
    assert salary_ym_of(date(2026, 1, 24)) == 202601
    assert salary_ym_of(date(2026, 1, 1)) == 202601


def test_salary_month_bounds():
    start, end = month_bounds(202609, "salary")
    assert start == date(2026, 8, 25)
    assert end == date(2026, 9, 24)
    c0, c1 = month_bounds(202609, "calendar")
    assert c0 == date(2026, 9, 1)
    assert c1 == date(2026, 9, 30)
    jan_s, jan_e = month_bounds(202601, "salary")
    assert jan_s == date(2025, 12, 25)
    assert jan_e == date(2026, 1, 24)


def test_period_ymd_salary_window():
    assert period_ymd(202609, 202609, "salary") == (20260825, 20260924)
    assert period_ymd(202609, 202609, "calendar") == (20260901, 20260930)


def test_presets_salary_on_16_sep():
    by_id = {p["id"]: p for p in period_presets(date(2026, 9, 16), "salary")}
    assert by_id["this_month"]["from_ym"] == 202609
    assert by_id["last_month"]["from_ym"] == 202608
    assert by_id["this_year"]["from_ym"] == 202601
    assert by_id["this_year"]["to_ym"] == 202609


def test_presets_salary_on_25_sep_is_october():
    by_id = {p["id"]: p for p in period_presets(date(2026, 9, 25), "salary")}
    assert by_id["this_month"]["from_ym"] == 202610
    assert by_id["last_month"]["from_ym"] == 202609


def test_build_payday_starts_early_salary():
    starts = build_payday_starts({202608: 22}, 202608, 202609)
    assert starts[202609] == date(2026, 8, 22)
    assert starts[202608] == date(2026, 7, 25)


def test_early_salary_goes_to_next_named_month():
    starts = build_payday_starts({202608: 22}, 202608, 202610)
    assert salary_ym_of(date(2026, 8, 22), starts) == 202609
    assert salary_ym_of(date(2026, 8, 21), starts) == 202608
    start, end = month_bounds(202609, "salary", starts)
    assert start == date(2026, 8, 22)
    assert end == date(2026, 9, 24)


def test_two_salaries_use_earliest_day():
    starts = build_payday_starts({202608: 22}, 202609, 202609)
    assert starts[202609] == date(2026, 8, 22)


def test_no_salary_in_window_falls_back_to_25():
    starts = build_payday_starts({}, 202609, 202609)
    assert starts[202609] == date(2026, 8, 25)
    assert month_bounds(202609, "salary", starts)[0] == date(2026, 8, 25)


def test_bucket_sql_salary_uses_cut_dates():
    starts = {202609: date(2026, 8, 22), 202610: date(2026, 9, 25)}
    sql = bucket_sql("salary", starts=starts)
    assert "20260822" in sql
    assert "20260925" in sql
    assert "THEN 202609" in sql


def test_preset_today_after_early_payday_is_new_month():
    starts = build_payday_starts({202608: 22}, 202608, 202609)
    by_id = {p["id"]: p for p in period_presets(date(2026, 8, 23), "salary", starts)}
    assert by_id["this_month"]["from_ym"] == 202609
