"""Named overview queries. Filters are bound params; table names from allowlist."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from app.classify import (
    bank_flow_sql,
    CC_FLOW_SQL,
    PAYDAY,
    PAYDAY_LOOKBACK,
    TX_KINDS,
    add_months,
    as_decimal,
    bucket_sql,
    build_payday_starts,
    intern_leg,
    match_cc_settlements,
    month_bounds,
    months_inclusive,
    period_ymd,
    salary_ym_of,
    ym_of,
)
from app.config import cc_rekening, chart_rekeningen, own_rekeningen, sql_rekening_literal
from app.db import TimedCursor, tx_ident
from app.formatters import redact_text


def _ymd(d: date) -> int:
    return d.year * 10000 + d.month * 100 + d.day


def _period_sql(
    from_ym: int,
    to_ym: int,
    rekening: str | None,
    cycle: str = "calendar",
    starts: dict[int, date] | None = None,
) -> tuple[str, list[Any]]:
    lo, hi = period_ymd(from_ym, to_ym, cycle, starts)
    sql = " AND (Jaar * 10000 + Maand * 100 + Dag) BETWEEN %s AND %s"
    params: list[Any] = [lo, hi]
    if rekening:
        sql += " AND Rekening = %s"
        params.append(rekening)
    return sql, params


def load_payday_starts(
    cur: TimedCursor, from_ym: int, to_ym: int
) -> dict[int, date]:
    cal_from = add_months(from_ym, -2)
    cal_to = add_months(to_ym, 1)
    cur.execute(
        "payday_starts",
        f"""
        SELECT Jaar, Maand, MIN(Dag) AS dag
        FROM {tx_ident("FinBotTransactions")}
        WHERE Hoofdcategorie = 'Inkomsten'
          AND Subcategorie = 'salaris'
          AND `Af Bij` = 'Bij'
          AND Dag BETWEEN %s AND %s
          AND (Jaar * 100 + Maand) BETWEEN %s AND %s
        GROUP BY Jaar, Maand
        """,
        [PAYDAY_LOOKBACK, PAYDAY, cal_from, cal_to],
    )
    early: dict[int, int] = {}
    for r in cur.fetchall():
        early[int(r["Jaar"]) * 100 + int(r["Maand"])] = int(r["dag"])
    return build_payday_starts(early, from_ym, to_ym)


def _cat_filters(hoofd: str | None, sub: str | None) -> str:
    bits = []
    if hoofd:
        bits.append(" AND Hoofdcategorie = %s")
    if sub:
        bits.append(" AND Subcategorie = %s")
    return "".join(bits)


def _union_sql(
    *,
    extra_bank: str = "",
    extra_cc: str = "",
    select_extra_bank: str = "",
    select_extra_cc: str = "",
) -> str:
    return f"""
    SELECT Jaar, Maand, Dag, Rekening, Hoofdcategorie, Subcategorie,
           `Af Bij` AS af_bij, bedrag, flow_kind, src {select_extra_bank and "" or ""}
    FROM (
      SELECT Jaar, Maand, Dag, Rekening, Hoofdcategorie, Subcategorie, `Af Bij`,
             `Bedrag (EUR)` AS bedrag, {bank_flow_sql()} AS flow_kind, 'bank' AS src
             {select_extra_bank}
      FROM {tx_ident("FinBotTransactions")}
      WHERE 1=1 {extra_bank}
      UNION ALL
      SELECT Jaar, Maand, Dag, Rekening, Hoofdcategorie, Subcategorie, `Af Bij`,
             Bedrag AS bedrag, {CC_FLOW_SQL} AS flow_kind, 'cc' AS src
             {select_extra_cc}
      FROM {tx_ident("FinBotTransactionsCC")}
      WHERE 1=1 {extra_cc}
    ) t
    """


def default_to_ym(cur: TimedCursor, cycle: str = "calendar") -> int | None:
    cur.execute(
        "default_range",
        f"SELECT MAX(Jaar * 10000 + Maand * 100 + Dag) AS ymd "
        f"FROM {tx_ident('FinBotTransactions')}",
    )
    row = cur.fetchone()
    if not row or row["ymd"] is None:
        return None
    ymd = int(row["ymd"])
    d = date(ymd // 10000, (ymd // 100) % 100, ymd % 100)
    if cycle != "salary":
        return ym_of(d)
    cal = ym_of(d)
    starts = load_payday_starts(cur, add_months(cal, -1), add_months(cal, 1))
    return salary_ym_of(d, starts)


def default_range(cur: TimedCursor) -> int | None:
    return default_to_ym(cur, "calendar")


def year_bounds(cur: TimedCursor) -> tuple[int, int]:
    cur.execute(
        "year_bounds",
        f"""
        SELECT MIN(Jaar) AS y0, MAX(Jaar) AS y1 FROM (
          SELECT Jaar FROM {tx_ident("FinBotTransactions")}
          UNION ALL
          SELECT Jaar FROM {tx_ident("FinBotTransactionsCC")}
        ) t
        """,
    )
    row = cur.fetchone() or {}
    y0, y1 = row.get("y0"), row.get("y1")
    if y0 is None or y1 is None:
        return 2024, 2026
    return int(y0), int(y1)


def filter_vocab(
    cur: TimedCursor, hoofd: str | None
) -> dict[str, list[str]]:
    cur.execute(
        "filter_vocab_pairs",
        f"""
        SELECT DISTINCT Hoofdcategorie AS hoofd, Subcategorie AS sub
        FROM {tx_ident("FinBotTransactions")}
        UNION
        SELECT DISTINCT Hoofdcategorie, Subcategorie
        FROM {tx_ident("FinBotTransactionsCC")}
        """,
    )
    pairs = [(r["hoofd"], r["sub"]) for r in cur.fetchall() if r["hoofd"] and r["sub"]]
    hoofden = sorted({h for h, _ in pairs})
    if hoofd:
        subs = sorted({s for h, s in pairs if h == hoofd})
    else:
        subs = sorted({s for _, s in pairs})
    cur.execute(
        "filter_rekening",
        f"""
        SELECT DISTINCT Rekening AS v FROM {tx_ident("FinBotTransactions")}
        UNION
        SELECT DISTINCT Rekening FROM {tx_ident("FinBotTransactionsCC")}
        """,
    )
    rekeningen = sorted(
        {row["v"] for row in cur.fetchall() if row["v"] in own_rekeningen()}
    )
    return {"rekening": rekeningen, "hoofd": hoofden, "sub": subs}


def _cat_sql(hoofd: str | None, sub: str | None) -> tuple[str, list[Any]]:
    sql = ""
    params: list[Any] = []
    if hoofd:
        sql += " AND Hoofdcategorie = %s"
        params.append(hoofd)
    if sub:
        sql += " AND Subcategorie = %s"
        params.append(sub)
    return sql, params


def kpis(
    cur: TimedCursor,
    from_ym: int,
    to_ym: int,
    rekening: str | None,
    hoofd: str | None,
    sub: str | None,
    cycle: str = "calendar",
    starts: dict[int, date] | None = None,
) -> dict[str, Decimal]:
    period, p = _period_sql(from_ym, to_ym, rekening, cycle, starts)
    cat = ""
    pc = list(p)
    if hoofd:
        cat += " AND Hoofdcategorie = %s"
        pc.append(hoofd)
    if sub:
        cat += " AND Subcategorie = %s"
        pc.append(sub)

    union_cat = _union_sql(extra_bank=period + cat, extra_cc=period + cat)
    union_nocat = _union_sql(extra_bank=period, extra_cc=period)
    cur.execute(
        "kpis_real",
        f"""
        SELECT
          COALESCE(SUM(CASE WHEN flow_kind='expense' THEN bedrag ELSE 0 END), 0) AS expense,
          COALESCE(SUM(CASE WHEN flow_kind='refund' THEN bedrag ELSE 0 END), 0) AS refund,
          COALESCE(SUM(CASE WHEN flow_kind='income' THEN bedrag ELSE 0 END), 0) AS income
        FROM ({union_cat}) u
        """,
        pc + pc,
    )
    real = cur.fetchone()
    cur.execute(
        "kpis_excluded",
        f"""
        SELECT
          COALESCE(SUM(CASE WHEN flow_kind='internal' AND af_bij='Af' THEN bedrag ELSE 0 END), 0) AS internal,
          COALESCE(SUM(CASE WHEN flow_kind='saving' AND af_bij='Af' THEN bedrag ELSE 0 END), 0) AS saving_af,
          COALESCE(SUM(CASE WHEN flow_kind='saving' AND af_bij='Bij' THEN bedrag ELSE 0 END), 0) AS saving_bij,
          COALESCE(SUM(CASE WHEN flow_kind='cc_settlement' AND src='bank' THEN bedrag ELSE 0 END), 0) AS cc
        FROM ({union_nocat}) u
        """,
        p + p,
    )
    ex = cur.fetchone()
    expense = as_decimal(real["expense"])
    refund = as_decimal(real["refund"])
    income = as_decimal(real["income"])
    saving_af = as_decimal(ex["saving_af"])
    saving_bij = as_decimal(ex["saving_bij"])
    expenses_net = expense - refund
    return {
        "expense": expense,
        "refund": refund,
        "expenses_net": expenses_net,
        "income": income,
        "delta": income - expenses_net,
        "internal": as_decimal(ex["internal"]),
        "saving_in": saving_af,
        "saving_out": saving_bij,
        "saving": saving_af - saving_bij,
        "cc": as_decimal(ex["cc"]),
    }


def by_groep(
    cur: TimedCursor,
    from_ym: int,
    to_ym: int,
    rekening: str | None,
    hoofd: str | None,
    sub: str | None,
    grain: str,
    cycle: str = "calendar",
    starts: dict[int, date] | None = None,
) -> list[dict[str, Any]]:
    period, p = _period_sql(from_ym, to_ym, rekening, cycle, starts)
    cat, cp = _cat_sql(hoofd, sub)
    period += cat
    p = p + cp
    group_col = "Hoofdcategorie" if grain == "hoofd" else "Subcategorie"
    union = _union_sql(extra_bank=period, extra_cc=period)
    cur.execute(
        f"by_{grain}",
        f"""
        SELECT {group_col} AS label,
               COALESCE(SUM(CASE WHEN flow_kind='expense' THEN bedrag ELSE 0 END), 0) AS expense,
               COALESCE(SUM(CASE WHEN flow_kind='refund' THEN bedrag ELSE 0 END), 0) AS refund,
               COALESCE(SUM(CASE WHEN flow_kind='expense' THEN bedrag
                                 WHEN flow_kind='refund' THEN -bedrag ELSE 0 END), 0) AS netto
        FROM ({union}) u
        GROUP BY {group_col}
        HAVING netto <> 0
        ORDER BY netto DESC
        """,
        p + p,
    )
    rows = []
    for r in cur.fetchall():
        rows.append(
            {
                "label": r["label"],
                "expense": as_decimal(r["expense"]),
                "refund": as_decimal(r["refund"]),
                "netto": as_decimal(r["netto"]),
            }
        )
    return rows


def income_by_sub(
    cur: TimedCursor,
    from_ym: int,
    to_ym: int,
    rekening: str | None,
    cycle: str = "calendar",
    starts: dict[int, date] | None = None,
) -> list[dict[str, Any]]:
    period, p = _period_sql(from_ym, to_ym, rekening, cycle, starts)
    union = _union_sql(extra_bank=period, extra_cc=period)
    cur.execute(
        "income_by_sub",
        f"""
        SELECT Subcategorie AS label,
               COALESCE(SUM(bedrag), 0) AS som,
               COUNT(*) AS n
        FROM ({union}) u
        WHERE flow_kind = 'income'
        GROUP BY Subcategorie
        HAVING som <> 0
        ORDER BY som DESC
        """,
        p + p,
    )
    rows = []
    for r in cur.fetchall():
        rows.append(
            {
                "label": r["label"],
                "som": as_decimal(r["som"]),
                "n": int(r["n"]),
            }
        )
    return rows


def monthly_stack(
    cur: TimedCursor,
    from_ym: int,
    to_ym: int,
    rekening: str | None,
    hoofd: str | None,
    sub: str | None,
    grain: str = "hoofd",
    cycle: str = "calendar",
    starts: dict[int, date] | None = None,
) -> dict[str, Any]:
    period, p = _period_sql(from_ym, to_ym, rekening, cycle, starts)
    cat, cp = _cat_sql(hoofd, sub)
    period += cat
    p = p + cp
    group_col = "Subcategorie" if grain == "sub" else "Hoofdcategorie"
    ym_expr = bucket_sql(cycle, starts=starts)
    union = _union_sql(extra_bank=period, extra_cc=period)
    cur.execute(
        "monthly_stack",
        f"""
        SELECT {ym_expr} AS ym, {group_col} AS label,
               COALESCE(SUM(CASE WHEN flow_kind='expense' THEN bedrag
                                 WHEN flow_kind='refund' THEN -bedrag ELSE 0 END), 0) AS netto
        FROM ({union}) u
        GROUP BY ym, {group_col}
        """,
        p + p,
    )
    months = months_inclusive(from_ym, to_ym)
    series: dict[str, dict[int, Decimal]] = {}
    for r in cur.fetchall():
        ym = int(r["ym"])
        h = r["label"] or ""
        series.setdefault(h, {})[ym] = as_decimal(r["netto"])
    datasets = []
    for h, by_m in sorted(series.items()):
        datasets.append(
            {
                "key": h,
                "label": h,
                "data": [float(by_m.get(ym, Decimal("0"))) for ym in months],
            }
        )
    return {"ym": months, "datasets": datasets}


def in_vs_uit(
    cur: TimedCursor,
    from_ym: int,
    to_ym: int,
    rekening: str | None,
    hoofd: str | None,
    sub: str | None,
    cycle: str = "calendar",
    starts: dict[int, date] | None = None,
) -> dict[str, Any]:
    period, p = _period_sql(from_ym, to_ym, rekening, cycle, starts)
    cat, cp = _cat_sql(hoofd, sub)
    period += cat
    p = p + cp
    ym_expr = bucket_sql(cycle, starts=starts)
    union = _union_sql(extra_bank=period, extra_cc=period)
    cur.execute(
        "in_vs_uit",
        f"""
        SELECT {ym_expr} AS ym, Rekening,
               COALESCE(SUM(CASE WHEN flow_kind='income' THEN bedrag ELSE 0 END), 0) AS income,
               COALESCE(SUM(CASE WHEN flow_kind='expense' THEN bedrag
                                 WHEN flow_kind='refund' THEN -bedrag ELSE 0 END), 0) AS expenses
        FROM ({union}) u
        GROUP BY ym, Rekening
        """,
        p + p,
    )
    by_m: dict[int, dict[str, tuple[Decimal, Decimal]]] = {}
    for r in cur.fetchall():
        ym = int(r["ym"])
        rek = r["Rekening"] or ""
        by_m.setdefault(ym, {})[rek] = (
            as_decimal(r["income"]),
            as_decimal(r["expenses"]),
        )
    accounts = list(chart_rekeningen(rekening))
    months = months_inclusive(from_ym, to_ym)
    datasets: list[dict[str, Any]] = []
    for kind in ("income", "expense"):
        for acc in accounts:
            data = []
            for ym in months:
                pair = by_m.get(ym, {}).get(acc, (Decimal("0"), Decimal("0")))
                data.append(float(pair[0] if kind == "income" else pair[1]))
            datasets.append({"key": acc, "kind": kind, "data": data})
    return {"ym": months, "datasets": datasets}


def intern_monthly(
    cur: TimedCursor,
    from_ym: int,
    to_ym: int,
    rekening: str | None,
    cycle: str = "calendar",
    starts: dict[int, date] | None = None,
) -> list[dict[str, Any]]:
    period, p = _period_sql(from_ym, to_ym, rekening, cycle, starts)
    ym_expr = bucket_sql(cycle, starts=starts)
    cur.execute(
        "intern_bank",
        f"""
        SELECT {ym_expr} AS ym, Rekening, `Af Bij` AS af_bij,
               Tegenrekening AS tegen_raw, Entiteit AS entiteit,
               SUM(`Bedrag (EUR)`) AS som, COUNT(*) AS n
        FROM {tx_ident("FinBotTransactions")}
        WHERE Hoofdcategorie = 'Interne overboeking' {period}
        GROUP BY ym, Rekening, `Af Bij`, Tegenrekening, Entiteit
        """,
        p,
    )
    grouped: dict[tuple[Any, ...], dict[str, Any]] = {}
    for r in cur.fetchall():
        van, naar = intern_leg(r["Rekening"], r["af_bij"], r["tegen_raw"], r["entiteit"])
        jaar, maand = divmod(int(r["ym"]), 100)
        key = (jaar, maand, van, naar)
        slot = grouped.setdefault(
            key,
            {"Jaar": key[0], "Maand": key[1], "van": van, "naar": naar, "som": Decimal("0"), "n": 0},
        )
        slot["som"] += as_decimal(r["som"])
        slot["n"] += int(r["n"])
    extra_cc = period + " AND Hoofdcategorie = 'Interne overboeking'"
    cur.execute(
        "intern_cc",
        f"""
        SELECT {ym_expr} AS ym, Rekening, `Af Bij` AS af_bij,
               SUM(Bedrag) AS som, COUNT(*) AS n
        FROM {tx_ident("FinBotTransactionsCC")}
        WHERE {CC_FLOW_SQL} = 'internal' {extra_cc}
        GROUP BY ym, Rekening, `Af Bij`
        """,
        p,
    )
    for r in cur.fetchall():
        van, naar = intern_leg(r["Rekening"], r["af_bij"], None, None)
        jaar, maand = divmod(int(r["ym"]), 100)
        key = (jaar, maand, van, naar)
        slot = grouped.setdefault(
            key,
            {"Jaar": key[0], "Maand": key[1], "van": van, "naar": naar, "som": Decimal("0"), "n": 0},
        )
        slot["som"] += as_decimal(r["som"])
        slot["n"] += int(r["n"])
    return sorted(grouped.values(), key=lambda r: (r["Jaar"], r["Maand"], r["van"] or "", r["naar"] or ""))


def intern_totals(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    bucket: dict[tuple[Any, ...], dict[str, Any]] = {}
    for r in rows:
        key = (r["van"], r["naar"])
        slot = bucket.setdefault(key, {"van": r["van"], "naar": r["naar"], "som": Decimal("0"), "n": 0})
        slot["som"] += as_decimal(r["som"])
        slot["n"] += int(r["n"])
    return sorted(bucket.values(), key=lambda r: (-r["som"], r["van"] or "", r["naar"] or ""))


def saving_monthly(
    cur: TimedCursor,
    from_ym: int,
    to_ym: int,
    rekening: str | None,
    cycle: str = "calendar",
    starts: dict[int, date] | None = None,
) -> list[dict[str, Any]]:
    period, p = _period_sql(from_ym, to_ym, rekening, cycle, starts)
    ym_expr = bucket_sql(cycle, starts=starts)
    union = _union_sql(extra_bank=period, extra_cc=period)
    cur.execute(
        "saving_monthly",
        f"""
        SELECT {ym_expr} AS ym, Rekening,
               COALESCE(SUM(CASE WHEN Subcategorie = 'sparen' AND af_bij = 'Af'
                                 THEN bedrag ELSE 0 END), 0) AS storting,
               COALESCE(SUM(CASE WHEN Subcategorie = 'van spaarrekening' AND af_bij = 'Bij'
                                 THEN bedrag ELSE 0 END), 0) AS opname,
               COUNT(*) AS n
        FROM ({union}) u
        WHERE flow_kind = 'saving'
        GROUP BY ym, Rekening
        ORDER BY ym, Rekening
        """,
        p + p,
    )
    rows = []
    for r in cur.fetchall():
        storting = as_decimal(r["storting"])
        opname = as_decimal(r["opname"])
        jaar, maand = divmod(int(r["ym"]), 100)
        rows.append(
            {
                "Jaar": jaar,
                "Maand": maand,
                "Rekening": r["Rekening"],
                "storting": storting,
                "opname": opname,
                "netto": storting - opname,
                "n": int(r["n"]),
            }
        )
    return rows


def saving_series(rows: list[dict[str, Any]], from_ym: int, to_ym: int) -> dict[str, Any]:
    months = months_inclusive(from_ym, to_ym)
    by_m: dict[int, dict[str, Decimal]] = {
        ym: {"storting": Decimal("0"), "opname": Decimal("0"), "netto": Decimal("0")}
        for ym in months
    }
    for r in rows:
        ym = int(r["Jaar"]) * 100 + int(r["Maand"])
        if ym not in by_m:
            continue
        by_m[ym]["storting"] += as_decimal(r["storting"])
        by_m[ym]["opname"] += as_decimal(r["opname"])
        by_m[ym]["netto"] += as_decimal(r["netto"])
    return {
        "ym": months,
        "netto": [float(by_m[ym]["netto"]) for ym in months],
        "storting": [float(by_m[ym]["storting"]) for ym in months],
        "opname": [float(by_m[ym]["opname"]) for ym in months],
    }


def saving_by_account(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    bucket: dict[str, dict[str, Any]] = {}
    for r in rows:
        rek = r["Rekening"] or ""
        slot = bucket.setdefault(
            rek,
            {
                "Rekening": r["Rekening"],
                "storting": Decimal("0"),
                "opname": Decimal("0"),
                "netto": Decimal("0"),
                "n": 0,
            },
        )
        slot["storting"] += as_decimal(r["storting"])
        slot["opname"] += as_decimal(r["opname"])
        slot["netto"] += as_decimal(r["netto"])
        slot["n"] += int(r["n"])
    return sorted(bucket.values(), key=lambda r: r["Rekening"] or "")


def refund_monthly(
    cur: TimedCursor,
    from_ym: int,
    to_ym: int,
    rekening: str | None,
    hoofd: str | None,
    sub: str | None,
    cycle: str = "calendar",
    starts: dict[int, date] | None = None,
) -> list[dict[str, Any]]:
    period, p = _period_sql(from_ym, to_ym, rekening, cycle, starts)
    cat, cp = _cat_sql(hoofd, sub)
    period += cat
    p = p + cp
    ym_expr = bucket_sql(cycle, starts=starts)
    union = _union_sql(extra_bank=period, extra_cc=period)
    cur.execute(
        "refund_monthly",
        f"""
        SELECT {ym_expr} AS ym, Hoofdcategorie, Subcategorie, Rekening,
               SUM(bedrag) AS som, COUNT(*) AS n
        FROM ({union}) u
        WHERE flow_kind = 'refund'
        GROUP BY ym, Hoofdcategorie, Subcategorie, Rekening
        ORDER BY ym, Hoofdcategorie, Subcategorie
        """,
        p + p,
    )
    rows = []
    for r in cur.fetchall():
        jaar, maand = divmod(int(r["ym"]), 100)
        rows.append({**r, "Jaar": jaar, "Maand": maand})
    return rows


def unclassified_count(
    cur: TimedCursor,
    from_ym: int,
    to_ym: int,
    rekening: str | None,
    cycle: str = "calendar",
    starts: dict[int, date] | None = None,
) -> int:
    period, p = _period_sql(from_ym, to_ym, rekening, cycle, starts)
    union = _union_sql(extra_bank=period, extra_cc=period)
    cur.execute(
        "unclassified_count",
        f"SELECT COUNT(*) AS n FROM ({union}) u WHERE flow_kind = 'unclassified'",
        p + p,
    )
    row = cur.fetchone()
    return int(row["n"] if row else 0)


def cc_inspect(
    cur: TimedCursor,
    from_ym: int,
    to_ym: int,
    rekening: str | None,
    cycle: str = "calendar",
    starts: dict[int, date] | None = None,
) -> list[dict[str, Any]]:
    vis_from, vis_to = month_bounds(from_ym, cycle, starts)[0], month_bounds(to_ym, cycle, starts)[1]
    cc_from = vis_from - timedelta(days=4)
    cc_to = vis_to
    bank_from = vis_from
    bank_to = vis_to + timedelta(days=4)

    extra_cc = " AND `Af Bij` = 'Bij' AND `Type` = 'Incasso'"
    extra_cc += (
        " AND (Jaar * 10000 + Maand * 100 + Dag) BETWEEN %s AND %s"
    )
    p_cc: list[Any] = [_ymd(cc_from), _ymd(cc_to)]
    extra_bank = (
        " AND Hoofdcategorie = 'Overige uitgaven' AND Subcategorie = 'creditcard'"
        " AND `Af Bij` = 'Af' AND Rekening = "
        + sql_rekening_literal(cc_rekening())
        + " AND Datum BETWEEN %s AND %s"
    )
    p_bank: list[Any] = [_ymd(bank_from), _ymd(bank_to)]
    if rekening:
        extra_cc += " AND Rekening = %s"
        extra_bank += " AND Rekening = %s"
        p_cc.append(rekening)
        p_bank.append(rekening)

    cur.execute(
        "cc_incasso_rows",
        f"""
        SELECT id, Jaar, Maand, Dag, Rekening, Hoofdcategorie AS hoofd,
               Subcategorie AS sub, `Af Bij` AS af_bij, Bedrag AS bedrag, `Type` AS cc_type
        FROM {tx_ident("FinBotTransactionsCC")}
        WHERE 1=1 {extra_cc}
        """,
        p_cc,
    )
    cc_rows = []
    for r in cur.fetchall():
        cc_rows.append(
            {
                **r,
                "cc_date": date(int(r["Jaar"]), int(r["Maand"]), int(r["Dag"])),
            }
        )

    cur.execute(
        "bank_cc_rows",
        f"""
        SELECT id, Jaar, Maand, Dag, Datum, Rekening, Hoofdcategorie AS hoofd,
               Subcategorie AS sub, `Af Bij` AS af_bij, `Bedrag (EUR)` AS bedrag
        FROM {tx_ident("FinBotTransactions")}
        WHERE 1=1 {extra_bank}
        """,
        p_bank,
    )
    bank_rows = []
    for r in cur.fetchall():
        ds = str(r["Datum"])
        bank_rows.append(
            {
                **r,
                "bank_date": date(int(ds[0:4]), int(ds[4:6]), int(ds[6:8])),
            }
        )
    return match_cc_settlements(
        cc_rows, bank_rows, visible_from=vis_from, visible_to=vis_to
    )


TX_LIMIT = 200


def intern_pair_match(
    rekening: str | None,
    af_bij: str | None,
    tegen_raw: str | None,
    entiteit: str | None,
    want_van: str | None,
    want_naar: str | None,
) -> bool:
    van, naar = intern_leg(rekening, af_bij, tegen_raw, entiteit)
    return van == want_van and naar == want_naar


def list_transactions(
    cur: TimedCursor,
    from_ym: int,
    to_ym: int,
    rekening: str | None,
    hoofd: str | None,
    sub: str | None,
    kind: str,
    tx_year: int | None = None,
    tx_month: int | None = None,
    tx_rekening: str | None = None,
    tx_sub: str | None = None,
    tx_hoofd: str | None = None,
    cycle: str = "calendar",
    starts: dict[int, date] | None = None,
    tx_van: str | None = None,
    tx_naar: str | None = None,
    filter_legs: bool = False,
) -> dict[str, Any]:
    kinds = TX_KINDS.get(kind)
    if not kinds:
        return {"rows": [], "truncated": False, "kind": kind}
    if tx_year and tx_month:
        from_ym = to_ym = tx_year * 100 + tx_month
    rek = tx_rekening or rekening
    period, p = _period_sql(from_ym, to_ym, rek, cycle, starts)
    cat = ""
    if kind in ("spend", "refund"):
        cat_h = tx_hoofd or hoofd
        cat_s = tx_sub if (tx_hoofd or tx_sub) else sub
        extra, cp = _cat_sql(cat_h, cat_s)
        cat += extra
        p.extend(cp)
    elif kind == "income" and tx_sub:
        cat += " AND Subcategorie = %s"
        p.append(tx_sub)
    in_sql = " IN (" + ", ".join(["%s"] * len(kinds)) + ")"
    extra_bank = period + cat + " AND " + bank_flow_sql() + in_sql
    extra_cc = period + cat + " AND " + CC_FLOW_SQL + in_sql
    params = p + list(kinds)
    limit_sql = "" if kind == "internal" and filter_legs else f"LIMIT {TX_LIMIT + 1}"
    if kind == "internal":
        bank_extra = ", Tegenrekening AS tegen_raw, Entiteit AS entiteit"
        cc_extra = ", NULL AS tegen_raw, Entiteit AS entiteit"
    else:
        bank_extra = ", NULL AS tegen_raw, NULL AS entiteit"
        cc_extra = ", NULL AS tegen_raw, NULL AS entiteit"
    cur.execute(
        "tx_list",
        f"""
        SELECT id, Jaar, Maand, Dag, Datum AS datum_int, Rekening, `Af Bij` AS af_bij,
               `Bedrag (EUR)` AS bedrag, Hoofdcategorie, Subcategorie,
               `Naam / Omschrijving` AS omschrijving, 'bank' AS src
               {bank_extra}
        FROM {tx_ident("FinBotTransactions")}
        WHERE 1=1 {extra_bank}
        UNION ALL
        SELECT id, Jaar, Maand, Dag, NULL AS datum_int, Rekening, `Af Bij` AS af_bij,
               Bedrag AS bedrag, Hoofdcategorie, Subcategorie,
               Omschrijving AS omschrijving, 'cc' AS src
               {cc_extra}
        FROM {tx_ident("FinBotTransactionsCC")}
        WHERE 1=1 {extra_cc}
        ORDER BY Jaar DESC, Maand DESC, Dag DESC, id DESC
        {limit_sql}
        """,
        params + params,
    )
    raw = list(cur.fetchall())
    if kind == "internal" and filter_legs:
        want_van = tx_van or None
        want_naar = tx_naar or None
        raw = [
            r
            for r in raw
            if intern_pair_match(
                r["Rekening"],
                r["af_bij"],
                r.get("tegen_raw"),
                r.get("entiteit"),
                want_van,
                want_naar,
            )
        ]
    truncated = len(raw) > TX_LIMIT
    rows = []
    for r in raw[:TX_LIMIT]:
        rows.append(
            {
                "id": r["id"],
                "datum": _tx_date(r),
                "Rekening": r["Rekening"],
                "af_bij": r["af_bij"],
                "bedrag": as_decimal(r["bedrag"]),
                "Hoofdcategorie": r["Hoofdcategorie"],
                "Subcategorie": r["Subcategorie"],
                "omschrijving": redact_text(r["omschrijving"]),
                "src": r["src"],
            }
        )
    return {"rows": rows, "truncated": truncated, "kind": kind}


def _tx_date(row: dict[str, Any]) -> str:
    raw = row.get("datum_int")
    if raw:
        ds = str(int(raw)).zfill(8)
        return f"{ds[6:8]}-{ds[4:6]}-{ds[0:4]}"
    day = int(row.get("Dag") or 1)
    return f"{day:02d}-{int(row['Maand']):02d}-{int(row['Jaar'])}"

