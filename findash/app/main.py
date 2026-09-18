"""findash v1 HTTP app."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pymysql.err import OperationalError

from urllib.parse import urlencode, urlparse

from app.classify import (
    add_months,
    default_from_to,
    month_bounds,
    months_inclusive,
    parse_cycle,
    period_presets,
    ym_of,
)
from app.config import load_settings
from app.db import TimedCursor, connect, select1, ui_string_exists
from app.embed import get_embedder
from app.formatters import color_for, format_eur, format_eur_auto
from app.i18n import LOCALES, Translator, load_translator
from app.ingest import point_id
from app.qdrant_io import (
    patch_own_payload,
    ping,
    qdrant_enabled,
    redact_qdrant_error,
    search_own,
)
from app.doubt import annotate, load_entity_stats
from app.anonymize import load_anonymize_rules
from app.bank_csv import CsvFormatError
from app.hybrid import propose
from app.import_preview import (
    apply_overrides,
    attach_preview_neighbors,
    drop_stage,
    existing_txids,
    insert_new,
    load_stage,
    preview_bank,
    preview_cc,
    save_stage,
)
from app.studio import (
    MENU_QUEUES,
    PAGE_SIZE,
    QUEUES,
    apply_correction,
    fetch_row,
    list_rows,
    load_memory_corpus,
    load_split_text_keys,
    memory_by_id,
    oorsprong_ready,
    pair_allowlist,
    parse_drempel,
    parse_q,
    parse_src,
    parse_sub_sid,
    parse_txid,
    subs_for_hoofd,
    suggestion_from_neighbors,
    undo_correction,
)
from app import queries

ROOT = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(ROOT / "templates"))
templates.env.filters["eur"] = format_eur
templates.env.filters["eur_auto"] = format_eur_auto

app = FastAPI(title="FinDash", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=str(ROOT / "static")), name="static")


@app.middleware("http")
async def ingress_prefix(request: Request, call_next):
    request.state.base = (request.headers.get("x-ingress-path") or "").rstrip("/")
    return await call_next(request)


def _base(request: Request) -> str:
    return (getattr(request.state, "base", None) or "").rstrip("/")


_jinja_page = templates.TemplateResponse


def render(
    request: Request, name: str, context: dict[str, Any], status_code: int = 200
):
    payload = dict(context)
    payload["request"] = request
    payload["base"] = _base(request)
    return _jinja_page(request, name, payload, status_code=status_code)


def redirect(request: Request, path: str, status_code: int = 303) -> RedirectResponse:
    prefix = _base(request)
    if path.startswith("http://") or path.startswith("https://"):
        return RedirectResponse(path, status_code=status_code)
    if prefix and (path == prefix or path.startswith(prefix + "/")):
        return RedirectResponse(path, status_code=status_code)
    if not path.startswith("/"):
        path = "/" + path
    return RedirectResponse(prefix + path, status_code=status_code)


def _locale(request: Request) -> str:
    raw = request.cookies.get("findash_lang") or load_settings()["FINDASH_DEFAULT_LOCALE"]
    return raw if raw in LOCALES else "nl"


def _cycle(request: Request) -> str:
    return parse_cycle(request.cookies.get("findash_cycle"))


def _salary_starts(cur: TimedCursor, from_ym: int, to_ym: int, cycle: str):
    if cycle != "salary":
        return None
    today_ym = ym_of(date.today())
    lo = min(from_ym, add_months(today_ym, -1))
    hi = max(to_ym, add_months(today_ym, 1))
    return queries.load_payday_starts(cur, lo, hi)


def _int_param(value: str | None) -> int | None:
    if value in (None, "", "all"):
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _str_param(value: str | None) -> str | None:
    if not value or value == "all":
        return None
    return value


def _resolve_range(
    cur: TimedCursor, from_year, from_month, to_year, to_month, cycle: str = "calendar"
):
    to_ym_default = queries.default_to_ym(cur, cycle)
    if to_ym_default is None:
        return None
    fy, fm = _int_param(from_year), _int_param(from_month)
    ty, tm = _int_param(to_year), _int_param(to_month)
    to_ym = ty * 100 + tm if ty and tm else to_ym_default
    if fy and fm:
        from_ym = fy * 100 + fm
    else:
        from_ym, _ = default_from_to(to_ym)
    if from_ym > to_ym:
        from_ym, to_ym = to_ym, from_ym
    return from_ym, to_ym


@app.get("/health")
def health() -> JSONResponse:
    try:
        select1()
    except Exception as exc:
        return JSONResponse(
            {"ok": False, "error": type(exc).__name__},
            status_code=503,
        )
    schema = "ok" if ui_string_exists() else "missing"
    qdrant = "disabled"
    settings = load_settings()
    if qdrant_enabled(settings):
        try:
            ping(settings)
            qdrant = "ok"
        except Exception as qexc:
            qdrant = "down"
            _ = redact_qdrant_error(qexc)
    return JSONResponse(
        {"ok": True, "findash_schema": schema, "qdrant": qdrant}
    )


@app.get("/ready")
def ready() -> JSONResponse:
    try:
        select1()
    except Exception:
        return JSONResponse({"ok": False}, status_code=503)
    if not ui_string_exists():
        return JSONResponse({"ok": False, "findash_schema": "missing"}, status_code=503)
    return JSONResponse({"ok": True, "findash_schema": "ok"})


@app.post("/locale")
def set_locale(request: Request, lang: str = Form(...)) -> Response:
    if lang not in LOCALES:
        return JSONResponse({"error": "invalid lang"}, status_code=400)
    dest = _cycle_dest(request)
    resp = redirect(request, dest)
    resp.set_cookie(
        "findash_lang",
        lang,
        path="/",
        httponly=True,
        samesite="lax",
        secure=False,
        max_age=86400 * 400,
    )
    return resp


def _cycle_dest(request: Request) -> str:
    prefix = _base(request)
    ref = urlparse(request.headers.get("referer") or "")
    path = ref.path or ""
    if prefix and path.startswith(prefix):
        path = path[len(prefix) :] or "/"
    if path.startswith("/import-studio"):
        dest = path
        if ref.query:
            dest = f"{path}?{ref.query}"
        return dest
    if path in ("/", "") and ref.query:
        return f"/?{ref.query}"
    return "/"


@app.post("/cycle")
def set_cycle(request: Request, cycle: str = Form(...)) -> Response:
    chosen = parse_cycle(cycle)
    resp = redirect(request, _cycle_dest(request))
    resp.set_cookie(
        "findash_cycle",
        chosen,
        path="/",
        httponly=True,
        samesite="lax",
        secure=False,
        max_age=86400 * 400,
    )
    return resp


@app.get("/", response_class=HTMLResponse)
def overview(
    request: Request,
    from_year: Optional[str] = None,
    from_month: Optional[str] = None,
    to_year: Optional[str] = None,
    to_month: Optional[str] = None,
    rekening: Optional[str] = None,
    hoofd: Optional[str] = None,
    sub: Optional[str] = None,
    tx_kind: Optional[str] = None,
    tx_year: Optional[str] = None,
    tx_month: Optional[str] = None,
    tx_rekening: Optional[str] = None,
    tx_sub: Optional[str] = None,
) -> HTMLResponse:
    locale = _locale(request)
    cycle = _cycle(request)
    timings: list[tuple[str, float]] = []
    try:
        conn = connect()
    except (OperationalError, FileNotFoundError, ValueError):
        tr = Translator(locale, {}, {})
        return render(
            request,
            "overview.html",
            {
                "t": tr,
                "locale": locale,
                "cycle": cycle,
                "error": tr.ui("health.db_down"),
                "vocab": {"rekening": [], "hoofd": [], "sub": []},
                "kpis": None,
                "years": [2024, 2025, 2026],
                "months": list(range(1, 13)),
                "from_year": 2025,
                "from_month": 9,
                "to_year": 2026,
                "to_month": 8,
                "rekening": "all",
                "hoofd": "all",
                "sub": "all",
                "focus_hoofd": None,
                "focus_sub": None,
                "focus_color": "#E76F51",
                "presets": _preset_ctx(202509, 202608, cycle),
                "htmx": request.headers.get("hx-request") == "true",
            },
            status_code=503,
        )
    try:
        with conn.cursor() as raw:
            cur = TimedCursor(raw, timings)
            tr = load_translator(cur, locale)
            rng = _resolve_range(cur, from_year, from_month, to_year, to_month, cycle)
            if rng is None:
                ctx = _empty_ctx(request, tr, locale)
                ctx["timings"] = timings
                return _render(request, ctx)
            from_ym, to_ym = rng
            rek = _str_param(rekening)
            h = _str_param(hoofd)
            s = _str_param(sub)
            starts = _salary_starts(cur, from_ym, to_ym, cycle)
            vocab = queries.filter_vocab(cur, h)
            kpis = queries.kpis(
                cur, from_ym, to_ym, rek, h, s, cycle=cycle, starts=starts
            )
            n_months = len(months_inclusive(from_ym, to_ym)) or 1
            kpis["n_months"] = n_months
            kpis["avg_month"] = kpis["expenses_net"] / n_months
            kpis["avg_income"] = kpis["income"] / n_months
            by_h = queries.by_groep(
                cur, from_ym, to_ym, rek, h, s, "hoofd", cycle=cycle, starts=starts
            )
            by_s = (
                queries.by_groep(
                    cur, from_ym, to_ym, rek, h, s, "sub", cycle=cycle, starts=starts
                )
                if h
                else []
            )
            grain = "sub" if h and not s else "hoofd"
            stack = queries.monthly_stack(
                cur, from_ym, to_ym, rek, h, s, grain=grain, cycle=cycle, starts=starts
            )
            ivu = queries.in_vs_uit(
                cur, from_ym, to_ym, rek, h, s, cycle=cycle, starts=starts
            )
            intern = queries.intern_monthly(
                cur, from_ym, to_ym, rek, cycle=cycle, starts=starts
            )
            intern_sum = queries.intern_totals(intern)
            saving = queries.saving_monthly(
                cur, from_ym, to_ym, rek, cycle=cycle, starts=starts
            )
            saving_accounts = queries.saving_by_account(saving)
            refunds = queries.refund_monthly(
                cur, from_ym, to_ym, rek, h, s, cycle=cycle, starts=starts
            )
            by_income = queries.income_by_sub(
                cur, from_ym, to_ym, rek, cycle=cycle, starts=starts
            )
            unclass = queries.unclassified_count(
                cur, from_ym, to_ym, rek, cycle=cycle, starts=starts
            )
            y0, y1 = queries.year_bounds(cur)
            years = list(range(y0, y1 + 1))
            ctx = {
                "t": tr,
                "locale": locale,
                "cycle": cycle,
                "cycle_span": _cycle_span(tr, from_ym, to_ym, cycle, starts),
                "error": None,
                "from_ym": from_ym,
                "to_ym": to_ym,
                "from_year": from_ym // 100,
                "from_month": from_ym % 100,
                "to_year": to_ym // 100,
                "to_month": to_ym % 100,
                "years": sorted({y for y in years} | {from_ym // 100, to_ym // 100}),
                "months": list(range(1, 13)),
                "rekening": rek or "all",
                "hoofd": h or "all",
                "sub": s or "all",
                "vocab": vocab,
                "kpis": kpis,
                "by_hoofd": by_h,
                "by_sub": by_s,
                "chart_monthly_stack": _localize_stack(
                    stack, tr, ns="sub" if h and not s else "hoofd"
                ),
                "chart_donut": _donut(by_s if h else by_h, tr, "sub" if h else "hoofd"),
                "chart_in_vs_uit": _localize_ivu(ivu, tr),
                "chart_saving": _localize_saving(
                    queries.saving_series(saving, from_ym, to_ym), tr
                ),
                "chart_title": _chart_title(tr, h, s),
                "drill_level": "sub" if h and not s else ("none" if s else "hoofd"),
                "focus_hoofd": h,
                "focus_sub": s,
                "focus_color": color_for(h),
                "presets": _preset_ctx(from_ym, to_ym, cycle, starts),
                "intern": intern,
                "intern_sum": intern_sum,
                "saving": saving,
                "saving_accounts": saving_accounts,
                "refunds": refunds,
                "by_income": by_income,
                "unclassified": unclass,
                "timings": timings,
                "query_ms": sum(ms for _, ms in timings),
                "show_index_hint": sum(ms for _, ms in timings) >= 300,
                "htmx": request.headers.get("hx-request") == "true",
            }
            return _render(request, ctx)
    finally:
        conn.close()


@app.get("/tx", response_class=HTMLResponse)
def transactions(
    request: Request,
    from_year: Optional[str] = None,
    from_month: Optional[str] = None,
    to_year: Optional[str] = None,
    to_month: Optional[str] = None,
    rekening: Optional[str] = None,
    hoofd: Optional[str] = None,
    sub: Optional[str] = None,
    tx_kind: Optional[str] = None,
    tx_year: Optional[str] = None,
    tx_month: Optional[str] = None,
    tx_rekening: Optional[str] = None,
    tx_sub: Optional[str] = None,
    tx_hoofd: Optional[str] = None,
    tx_van: Optional[str] = None,
    tx_naar: Optional[str] = None,
) -> HTMLResponse:
    locale = _locale(request)
    cycle = _cycle(request)
    timings: list[tuple[str, float]] = []
    kind = _str_param(tx_kind)
    if kind not in queries.TX_KINDS:
        kind = "spend"
    try:
        conn = connect()
    except (OperationalError, FileNotFoundError, ValueError):
        tr = Translator(locale, {}, {})
        return render(
            request,
            "partials/tx_embed.html",
            {"t": tr, "locale": locale, "tx": {"rows": [], "truncated": False, "kind": kind}},
            status_code=503,
        )
    try:
        with conn.cursor() as raw:
            cur = TimedCursor(raw, timings)
            tr = load_translator(cur, locale)
            rng = _resolve_range(cur, from_year, from_month, to_year, to_month, cycle)
            if rng is None:
                tx = {"rows": [], "truncated": False, "kind": kind}
            else:
                from_ym, to_ym = rng
                starts = _salary_starts(cur, from_ym, to_ym, cycle)
                tx = queries.list_transactions(
                    cur,
                    from_ym,
                    to_ym,
                    _str_param(rekening),
                    _str_param(hoofd),
                    _str_param(sub),
                    kind,
                    tx_year=_int_param(tx_year),
                    tx_month=_int_param(tx_month),
                    tx_rekening=_str_param(tx_rekening),
                    tx_sub=_str_param(tx_sub),
                    tx_hoofd=_str_param(tx_hoofd),
                    cycle=cycle,
                    starts=starts,
                    tx_van=tx_van,
                    tx_naar=tx_naar,
                    filter_legs=tx_van is not None or tx_naar is not None,
                )
            return render(
                request,
                "partials/tx_embed.html",
                {
                    "t": tr,
                    "locale": locale,
                    "tx": tx,
                    "tx_kind": kind,
                    "tx_year": _int_param(tx_year),
                    "tx_month": _int_param(tx_month),
                    "tx_rekening": _str_param(tx_rekening) or "",
                    "tx_sub": _str_param(tx_sub) or "",
                    "tx_hoofd": _str_param(tx_hoofd) or "",
                },
            )
    finally:
        conn.close()


def _studio_pairs_map(pairs: set[tuple[str, str]]) -> tuple[list[str], dict[str, list[str]]]:
    hoofden = sorted({h for h, _ in pairs})
    by_h = {h: subs_for_hoofd(pairs, h) for h in hoofden}
    return hoofden, by_h


def _attach_suggestions(
    rows: list[dict[str, Any]],
    settings: dict[str, str],
    drempel,
    memory_map: dict[tuple[str, str], dict[str, Any] | None] | None = None,
) -> bool:
    _ = settings, drempel
    memory_map = memory_map or {}
    for row in rows:
        row["knn"] = None
        row["entity_options"] = []
        mem = memory_map.get((row["src"], row["transactie_id"]))
        sug = propose(mem)
        row["suggest"] = sug
        row["above"] = bool(sug)
        row.pop("embed_text", None)
    return False


def _studio_row_html(request: Request, ctx: dict[str, Any]) -> HTMLResponse:
    html = templates.get_template("partials/studio_row.html").render(ctx)
    return HTMLResponse(html)


@app.get("/import-studio", response_class=HTMLResponse)
def import_studio(
    request: Request,
    queue: Optional[str] = None,
    from_year: Optional[str] = None,
    from_month: Optional[str] = None,
    to_year: Optional[str] = None,
    to_month: Optional[str] = None,
    rekening: Optional[str] = None,
    drempel: Optional[str] = None,
    page: Optional[str] = None,
    q: Optional[str] = None,
) -> HTMLResponse:
    locale = _locale(request)
    timings: list[tuple[str, float]] = []
    qid = queue if queue in QUEUES else "twijfel"
    threshold = parse_drempel(drempel)
    page_n = _int_param(page) or 1
    needle = parse_q(q)
    settings = load_settings()
    try:
        conn = connect()
    except (OperationalError, FileNotFoundError, ValueError):
        tr = Translator(locale, {}, {})
        return render(
            request,
            "studio.html",
            {
                "t": tr,
                "locale": locale,
                "error": tr.ui("health.db_down"),
                "queues": MENU_QUEUES,
                "queue": qid,
                "vocab": {"rekening": []},
                "years": [2024, 2025, 2026],
                "months": list(range(1, 13)),
                "from_year": 2025,
                "from_month": 9,
                "to_year": 2026,
                "to_month": 8,
                "rekening": "all",
                "drempel": str(threshold),
                "rows": [],
            },
            status_code=503,
        )
    try:
        with conn.cursor() as raw:
            cur = TimedCursor(raw, timings)
            tr = load_translator(cur, locale)
            if not oorsprong_ready(cur):
                return render(
                    request,
                    "studio.html",
                    {
                        "t": tr,
                        "locale": locale,
                        "error": "Import-studio schema ontbreekt (migratie 004).",
                        "queues": MENU_QUEUES,
                        "queue": qid,
                        "vocab": {"rekening": []},
                        "years": [2024, 2025, 2026],
                        "months": list(range(1, 13)),
                        "from_year": 2025,
                        "from_month": 1,
                        "to_year": 2026,
                        "to_month": 8,
                        "rekening": "all",
                        "drempel": str(threshold),
                        "rows": [],
                    },
                    status_code=503,
                )
            rng = _resolve_range(cur, from_year, from_month, to_year, to_month)
            if rng is None:
                return render(
                    request,
                    "studio.html",
                    {
                        "t": tr,
                        "locale": locale,
                        "error": tr.ui("empty.no_data"),
                        "queues": MENU_QUEUES,
                        "queue": qid,
                        "vocab": {"rekening": []},
                        "years": [2024, 2025, 2026],
                        "months": list(range(1, 13)),
                        "from_year": 2025,
                        "from_month": 1,
                        "to_year": 2026,
                        "to_month": 8,
                        "rekening": "all",
                        "drempel": str(threshold),
                        "rows": [],
                    },
                )
            from_ym, to_ym = rng
            rek = _str_param(rekening)
            vocab = queries.filter_vocab(cur, None)
            pairs = pair_allowlist(cur)
            hoofden, subs_by_hoofd = _studio_pairs_map(pairs)
            rows, total = list_rows(
                cur,
                from_ym=from_ym,
                to_ym=to_ym,
                queue=qid,
                rekening=rek,
                page=page_n,
                q=needle,
            )
            mmap = memory_by_id(load_memory_corpus(cur))
            qdown = _attach_suggestions(rows, settings, threshold, mmap)
            majority, mixed_entities = load_entity_stats(cur)
            split_texts = load_split_text_keys(cur)
            for row in rows:
                annotate(
                    row,
                    majority,
                    threshold,
                    split_texts=split_texts,
                    mixed_entities=mixed_entities,
                )
            y0, y1 = queries.year_bounds(cur)
            ctx = {
                "t": tr,
                "locale": locale,
                "cycle": _cycle(request),
                "error": None,
                "queues": MENU_QUEUES,
                "queue": qid,
                "from_year": from_ym // 100,
                "from_month": from_ym % 100,
                "to_year": to_ym // 100,
                "to_month": to_ym % 100,
                "years": list(range(y0, y1 + 1)),
                "months": list(range(1, 13)),
                "rekening": rek or "all",
                "vocab": vocab,
                "drempel": f"{threshold:.2f}",
                "q": needle,
                "rows": rows,
                "total": total,
                "page": page_n,
                "has_next": page_n * PAGE_SIZE < total,
                "pages": max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE) if total else 1,
                "hoofden": hoofden,
                "subs_by_hoofd": subs_by_hoofd,
                "qdrant_down": qdown,
                "query_ms": sum(ms for _, ms in timings),
                "saved": _int_param(request.query_params.get("saved")),
                "skipped": _int_param(request.query_params.get("skipped")),
                "imported": _int_param(request.query_params.get("imported")),
                "import_dupes": _int_param(request.query_params.get("import_dupes")),
            }
            return render(request, "studio.html", ctx)
    finally:
        conn.close()


@app.post("/import-studio/preview", response_class=HTMLResponse)
async def import_studio_preview(
    request: Request,
    bank_csv: Optional[UploadFile] = File(default=None),
    cc_pdf: Optional[UploadFile] = File(default=None),
) -> HTMLResponse:
    locale = _locale(request)
    tr = Translator(locale, {}, {})
    bank_bytes = await bank_csv.read() if bank_csv and bank_csv.filename else b""
    pdf_bytes = await cc_pdf.read() if cc_pdf and cc_pdf.filename else b""
    if bool(bank_bytes) == bool(pdf_bytes):
        return render(
            request,
            "import_preview.html",
            {"t": tr, "locale": locale, "error": tr.ui("import.need_one"), "preview": None},
            status_code=400,
        )
    if max(len(bank_bytes), len(pdf_bytes)) > 8 * 1024 * 1024:
        return render(
            request,
            "import_preview.html",
            {"t": tr, "locale": locale, "error": tr.ui("import.too_big"), "preview": None},
            status_code=400,
        )
    try:
        rules = load_anonymize_rules()
    except FileNotFoundError:
        return render(
            request,
            "import_preview.html",
            {"t": tr, "locale": locale, "error": tr.ui("import.anon_missing"), "preview": None},
            status_code=503,
        )
    except ValueError:
        return render(
            request,
            "import_preview.html",
            {"t": tr, "locale": locale, "error": tr.ui("import.anon_missing"), "preview": None},
            status_code=503,
        )
    try:
        conn = connect()
    except (OperationalError, FileNotFoundError, ValueError):
        return render(
            request,
            "import_preview.html",
            {"t": tr, "locale": locale, "error": tr.ui("health.db_down"), "preview": None},
            status_code=503,
        )
    try:
        with conn.cursor() as raw:
            cur = TimedCursor(raw, [])
            tr = load_translator(cur, locale)
            memory_rows = load_memory_corpus(cur)
            if bank_bytes:
                existing = existing_txids(cur, "bank")
                try:
                    preview = preview_bank(bank_bytes, rules, existing, memory_rows)
                except CsvFormatError as exc:
                    msg = tr.ui("import.csv_cols") + " " + ", ".join(exc.headers[:24])
                    return render(
                        request,
                        "import_preview.html",
                        {"t": tr, "locale": locale, "error": msg, "preview": None},
                        status_code=400,
                    )
            else:
                existing = existing_txids(cur, "cc")
                try:
                    preview = preview_cc(pdf_bytes, rules, existing, memory_rows)
                except Exception:
                    return render(
                        request,
                        "import_preview.html",
                        {"t": tr, "locale": locale, "error": tr.ui("import.pdf_fail"), "preview": None},
                        status_code=400,
                    )
            token = save_stage(preview)
            settings = load_settings()
            attach_preview_neighbors(preview["rows"], settings)
            show = dict(preview)
            for row in show["rows"]:
                row.pop("insert", None)
            pairs = pair_allowlist(cur)
            hoofden, subs_by_hoofd = _studio_pairs_map(pairs)
            return render(
                request,
                "import_preview.html",
                {
                    "t": tr,
                    "locale": locale,
                    "cycle": _cycle(request),
                    "error": None,
                    "preview": show,
                    "token": token,
                    "hoofden": hoofden,
                    "subs_by_hoofd": subs_by_hoofd,
                },
            )
    finally:
        conn.close()


@app.post("/import-studio/commit")
async def import_studio_commit(request: Request) -> Response:
    form = await request.form()
    token = str(form.get("token") or "")
    staged = load_stage(token)
    if not staged:
        return redirect(request, "/import-studio")
    conn = None
    n = 0
    done = False
    try:
        conn = connect()
        with conn.cursor() as raw:
            cur = TimedCursor(raw, [])
            pairs = pair_allowlist(cur)
            inserts = staged.get("inserts") or []
            apply_overrides(inserts, form, pairs)
            n = insert_new(cur, staged["kind"], inserts)
            done = True
    except ValueError:
        return HTMLResponse("400", status_code=400)
    except (OperationalError, FileNotFoundError):
        return HTMLResponse("503", status_code=503)
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
        if done:
            drop_stage(token)
    dest = "/import-studio?" + urlencode(
        {"imported": str(n), "import_dupes": str(staged.get("n_dupe") or 0)}
    )
    return redirect(request, dest)


@app.get("/import-studio/subs", response_class=HTMLResponse)
def import_studio_subs(
    request: Request, hoofd: Optional[str] = None, sid: Optional[str] = None
) -> HTMLResponse:
    locale = _locale(request)
    try:
        conn = connect()
    except (OperationalError, FileNotFoundError, ValueError):
        return HTMLResponse("", status_code=503)
    try:
        with conn.cursor() as raw:
            cur = TimedCursor(raw, [])
            tr = load_translator(cur, locale)
            pairs = pair_allowlist(cur)
            subs = subs_for_hoofd(pairs, hoofd or "")
            return render(
                request,
                "partials/studio_subs.html",
                {"t": tr, "subs": subs, "sid": parse_sub_sid(sid)},
            )
    finally:
        conn.close()


@app.get("/import-studio/neighbors", response_class=HTMLResponse)
def import_studio_neighbors(
    request: Request,
    src: Optional[str] = None,
    transactie_id: Optional[str] = None,
) -> HTMLResponse:
    locale = _locale(request)
    src_n = parse_src(src)
    txid = parse_txid(transactie_id)
    settings = load_settings()
    tr = Translator(locale, {}, {})
    if not src_n or not txid:
        return render(
            request,
            "partials/studio_neighbors.html",
            {"t": tr, "neighbors": [], "error": "400", "mixed": False, "split": []},
            status_code=400,
        )
    if not qdrant_enabled(settings):
        return render(
            request,
            "partials/studio_neighbors.html",
            {"t": tr, "neighbors": [], "error": tr.ui("studio.qdrant_down"), "mixed": False, "split": []},
            status_code=503,
        )
    conn = None
    try:
        conn = connect()
        with conn.cursor() as raw:
            cur = TimedCursor(raw, [])
            tr = load_translator(cur, locale)
            row = fetch_row(cur, src_n, txid)
        if not row:
            return render(
                request,
                "partials/studio_neighbors.html",
                {"t": tr, "neighbors": [], "error": "400", "mixed": False, "split": []},
                status_code=400,
            )
        embedder = get_embedder(settings)
        vector = embedder.embed_queries([row.get("embed_text") or ""])[0]
        neighbors = search_own(
            settings,
            vector,
            limit=5,
            exclude_point_id=point_id(src_n, txid),
            richting=row.get("richting") or None,
        )
        sug = suggestion_from_neighbors(neighbors)
        return render(
            request,
            "partials/studio_neighbors.html",
            {
                "t": tr,
                "neighbors": neighbors,
                "error": None,
                "mixed": bool(sug and sug.get("mixed")),
                "split": (sug or {}).get("split") or [],
            },
        )
    except Exception as exc:
        _ = redact_qdrant_error(exc)
        return render(
            request,
            "partials/studio_neighbors.html",
            {"t": tr, "neighbors": [], "error": tr.ui("studio.qdrant_down"), "mixed": False, "split": []},
            status_code=503,
        )
    finally:
        if conn is not None:
            conn.close()


@app.post("/import-studio/correct", response_class=HTMLResponse)
def import_studio_correct(
    request: Request,
    src: str = Form(...),
    transactie_id: str = Form(...),
    hoofd: str = Form(...),
    sub: str = Form(""),
    sub_new: str = Form(""),
    entiteit: str = Form(""),
    drempel: str = Form(""),
    score: str = Form(""),
) -> HTMLResponse:
    locale = _locale(request)
    src_n = parse_src(src)
    txid = parse_txid(transactie_id)
    threshold = parse_drempel(drempel)
    settings = load_settings()
    if not src_n or not txid:
        return HTMLResponse("400", status_code=400)
    try:
        conn = connect()
        with conn.cursor() as raw:
            cur = TimedCursor(raw, [])
            tr = load_translator(cur, locale)
            pairs = pair_allowlist(cur)
            sim = None
            if score:
                try:
                    sim = parse_drempel(score)
                except Exception:
                    sim = None
            try:
                row = apply_correction(
                    cur,
                    src=src_n,
                    transactie_id=txid,
                    hoofd=hoofd,
                    sub=sub,
                    similarity=sim,
                    pairs=pairs,
                    entiteit=entiteit,
                    sub_new=sub_new,
                )
            except ValueError as exc:
                code = str(exc.args[0]) if exc.args else ""
                key = (
                    f"studio.err.{code}"
                    if code in ("structural", "pair", "source", "empty")
                    else "studio.save_fail"
                )
                return HTMLResponse(tr.ui(key), status_code=400)
            if not row:
                return HTMLResponse("400", status_code=400)
            if qdrant_enabled(settings):
                try:
                    patch_own_payload(
                        settings,
                        point_id(src_n, txid),
                        {
                            "hoofd": row["hoofd"],
                            "sub": row["sub"],
                            "entiteit": row.get("entiteit_key") or row.get("entiteit") or "",
                            "corrected": True,
                            "flow_kind": row["flow_kind"],
                        },
                    )
                except Exception as exc:
                    _ = redact_qdrant_error(exc)
            mmap = memory_by_id(load_memory_corpus(cur))
            _attach_suggestions([row], settings, threshold, mmap)
            majority, mixed_entities = load_entity_stats(cur)
            split_texts = load_split_text_keys(cur)
            annotate(
                row,
                majority,
                threshold,
                split_texts=split_texts,
                mixed_entities=mixed_entities,
            )
            pairs = pair_allowlist(cur)
            hoofden, subs_by_hoofd = _studio_pairs_map(pairs)
            return _studio_row_html(
                request,
                {
                    "t": tr,
                    "locale": locale,
                    "row": row,
                    "drempel": f"{threshold:.2f}",
                    "hoofden": hoofden,
                    "subs_by_hoofd": subs_by_hoofd,
                },
            )
    except (OperationalError, FileNotFoundError, ValueError):
        return HTMLResponse("503", status_code=503)
    finally:
        try:
            conn.close()
        except Exception:
            pass


@app.post("/import-studio/undo", response_class=HTMLResponse)
def import_studio_undo(
    request: Request,
    src: str = Form(...),
    transactie_id: str = Form(...),
    drempel: str = Form(""),
) -> HTMLResponse:
    locale = _locale(request)
    src_n = parse_src(src)
    txid = parse_txid(transactie_id)
    threshold = parse_drempel(drempel)
    settings = load_settings()
    if not src_n or not txid:
        return HTMLResponse("400", status_code=400)
    try:
        conn = connect()
        with conn.cursor() as raw:
            cur = TimedCursor(raw, [])
            tr = load_translator(cur, locale)
            row = undo_correction(cur, src=src_n, transactie_id=txid)
            if not row:
                return HTMLResponse("400", status_code=400)
            if qdrant_enabled(settings):
                try:
                    patch_own_payload(
                        settings,
                        point_id(src_n, txid),
                        {
                            "hoofd": row["hoofd"],
                            "sub": row["sub"],
                            "corrected": False,
                            "flow_kind": row["flow_kind"],
                        },
                    )
                except Exception as exc:
                    _ = redact_qdrant_error(exc)
            mmap = memory_by_id(load_memory_corpus(cur))
            _attach_suggestions([row], settings, threshold, mmap)
            majority, mixed_entities = load_entity_stats(cur)
            split_texts = load_split_text_keys(cur)
            annotate(
                row,
                majority,
                threshold,
                split_texts=split_texts,
                mixed_entities=mixed_entities,
            )
            pairs = pair_allowlist(cur)
            hoofden, subs_by_hoofd = _studio_pairs_map(pairs)
            return _studio_row_html(
                request,
                {
                    "t": tr,
                    "locale": locale,
                    "row": row,
                    "drempel": f"{threshold:.2f}",
                    "hoofden": hoofden,
                    "subs_by_hoofd": subs_by_hoofd,
                },
            )
    except (OperationalError, FileNotFoundError, ValueError):
        return HTMLResponse("503", status_code=503)
    finally:
        try:
            conn.close()
        except Exception:
            pass


@app.post("/import-studio/bulk")
async def import_studio_bulk(request: Request) -> Response:
    form = await request.form()
    drempel = str(form.get("drempel") or "")
    queue = str(form.get("queue") or "twijfel")
    from_year = str(form.get("from_year") or "")
    from_month = str(form.get("from_month") or "")
    to_year = str(form.get("to_year") or "")
    to_month = str(form.get("to_month") or "")
    rekening = str(form.get("rekening") or "all")
    q = str(form.get("q") or "")
    threshold = parse_drempel(drempel)
    settings = load_settings()
    saved = 0
    skipped = 0
    items: list[str] = []
    seen: set[str] = set()
    for raw in form.getlist("sel"):
        token = str(raw or "")
        if token and token not in seen:
            seen.add(token)
            items.append(token)
    conn = None
    try:
        conn = connect()
        with conn.cursor() as raw:
            cur = TimedCursor(raw, [])
            pairs = pair_allowlist(cur)
            majority, mixed_entities = load_entity_stats(cur)
            split_texts = load_split_text_keys(cur)
            mmap = memory_by_id(load_memory_corpus(cur))
            for token in items:
                if ":" not in token:
                    skipped += 1
                    continue
                src_n, _, txid_raw = token.partition(":")
                src_n = parse_src(src_n)
                txid = parse_txid(txid_raw)
                if not src_n or not txid:
                    skipped += 1
                    continue
                row = fetch_row(cur, src_n, txid)
                if not row:
                    skipped += 1
                    continue
                hoofd = str(form.get(f"hoofd-{token}") or "").strip()
                sub = str(form.get(f"sub-{token}") or "").strip()
                sub_new = str(form.get(f"sub_new-{token}") or "").strip()
                entiteit = str(form.get(f"entiteit-{token}") or "").strip()
                sim = None
                if not hoofd or (not sub and not sub_new):
                    _attach_suggestions([row], settings, threshold, mmap)
                    annotate(
                        row,
                        majority,
                        threshold,
                        split_texts=split_texts,
                        mixed_entities=mixed_entities,
                    )
                    sug = row.get("suggest")
                    if not sug:
                        skipped += 1
                        continue
                    hoofd = str(sug.get("hoofd") or "")
                    sub = str(sug.get("sub") or "")
                    sub_new = ""
                    if sug.get("score") is not None:
                        sim = parse_drempel(str(sug.get("score") or ""))
                try:
                    patched = apply_correction(
                        cur,
                        src=src_n,
                        transactie_id=txid,
                        hoofd=hoofd,
                        sub=sub,
                        similarity=sim,
                        pairs=pairs,
                        entiteit=entiteit,
                        sub_new=sub_new,
                    )
                except ValueError:
                    skipped += 1
                    continue
                if not patched:
                    skipped += 1
                    continue
                pairs.add((patched["hoofd"], patched["sub"]))
                if qdrant_enabled(settings):
                    try:
                        patch_own_payload(
                            settings,
                            point_id(src_n, txid),
                            {
                                "hoofd": patched["hoofd"],
                                "sub": patched["sub"],
                                "corrected": True,
                                "flow_kind": patched["flow_kind"],
                            },
                        )
                    except Exception as exc:
                        _ = redact_qdrant_error(exc)
                saved += 1
    except (OperationalError, FileNotFoundError, ValueError):
        return HTMLResponse("503", status_code=503)
    finally:
        if conn is not None:
            conn.close()
    qid = queue if queue in QUEUES else "twijfel"
    dest = "/import-studio?" + urlencode(
        {
            "queue": qid,
            "from_year": from_year,
            "from_month": from_month,
            "to_year": to_year,
            "to_month": to_month,
            "rekening": rekening or "all",
            "drempel": f"{threshold:.2f}",
            "q": parse_q(q),
            "saved": str(saved),
            "skipped": str(skipped),
        }
    )
    return redirect(request, dest)


def _empty_ctx(request: Request, tr: Translator, locale: str) -> dict[str, Any]:
    cycle = _cycle(request)
    return {
        "t": tr,
        "locale": locale,
        "cycle": cycle,
        "cycle_span": None,
        "error": None,
        "empty": True,
        "vocab": {"rekening": [], "hoofd": [], "sub": []},
        "kpis": None,
        "years": [2024, 2025, 2026],
        "months": list(range(1, 13)),
        "from_year": 2025,
        "from_month": 9,
        "to_year": 2026,
        "to_month": 8,
        "rekening": "all",
        "hoofd": "all",
        "sub": "all",
        "focus_hoofd": None,
        "focus_sub": None,
        "focus_color": "#E76F51",
        "presets": _preset_ctx(202509, 202608, cycle),
        "htmx": request.headers.get("hx-request") == "true",
    }


def _preset_ctx(
    from_ym: int,
    to_ym: int,
    cycle: str = "calendar",
    starts: dict | None = None,
) -> list[dict[str, Any]]:
    out = []
    for item in period_presets(date.today(), cycle, starts):
        fy, fm = divmod(int(item["from_ym"]), 100)
        # divmod(202609, 100) -> 2026, 9 yes
        ty, tm = divmod(int(item["to_ym"]), 100)
        out.append(
            {
                **item,
                "from_year": fy,
                "from_month": fm,
                "to_year": ty,
                "to_month": tm,
                "active": int(item["from_ym"]) == from_ym and int(item["to_ym"]) == to_ym,
            }
        )
    return out


def _labels_for_ym(ym_list: list[int], tr: Translator) -> list[str]:
    return [tr.ym(ym // 100, ym % 100, short=True) for ym in ym_list]


def _chart_title(tr: Translator, hoofd: str | None, sub: str | None) -> str:
    if sub:
        return f"{tr.ui('chart.monthly_stack_cat')}: {tr.term('sub', sub)}"
    if hoofd:
        return f"{tr.ui('chart.monthly_stack_cat')}: {tr.term('hoofd', hoofd)}"
    return tr.ui("chart.monthly_stack")


def _localize_stack(stack: dict[str, Any], tr: Translator, ns: str) -> dict[str, Any]:
    datasets = []
    for ds in stack.get("datasets", []):
        key = ds.get("key") or ds.get("label")
        datasets.append(
            {
                "key": key,
                "label": tr.term(ns, key),
                "data": ds.get("data", []),
            }
        )
    return {
        "labels": _labels_for_ym(stack.get("ym") or [], tr),
        "datasets": datasets,
        "drill": "sub" if ns == "sub" else "hoofd",
    }


def _localize_ivu(ivu: dict[str, Any], tr: Translator) -> dict[str, Any]:
    return {
        "labels": _labels_for_ym(ivu.get("ym") or [], tr),
        "income": ivu.get("income", []),
        "expenses": ivu.get("expenses", []),
        "income_label": tr.ui("chart.income_series"),
        "expense_label": tr.ui("chart.expense_series"),
    }


def _localize_saving(series: dict[str, Any], tr: Translator) -> dict[str, Any]:
    return {
        "labels": _labels_for_ym(series.get("ym") or [], tr),
        "netto": series.get("netto", []),
        "storting": series.get("storting", []),
        "opname": series.get("opname", []),
        "label": tr.ui("kpi.saving_net"),
        "in_label": tr.ui("kpi.saving_in"),
        "out_label": tr.ui("kpi.saving_out"),
    }


def _cycle_span(
    tr: Translator,
    from_ym: int,
    to_ym: int,
    cycle: str,
    starts: dict | None = None,
) -> str | None:
    if cycle != "salary":
        return None
    start, _ = month_bounds(from_ym, cycle, starts)
    _, end = month_bounds(to_ym, cycle, starts)

    def fmt(d: date) -> str:
        return f"{d.day} {tr.month(d.month)} {d.year}"

    return f"{fmt(start)} – {fmt(end)}"


def _donut(rows: list[dict[str, Any]], tr: Translator, ns: str) -> dict[str, Any]:
    labels = [tr.term(ns if ns != "hoofd" else "hoofd", r["label"]) for r in rows]
    if ns == "sub":
        labels = [tr.term("sub", r["label"]) for r in rows]
    return {
        "labels": labels,
        "data": [float(r["netto"]) for r in rows],
        "keys": [r["label"] for r in rows],
    }


def _render(request: Request, ctx: dict[str, Any]) -> HTMLResponse:
    ctx["request"] = request
    ctx.setdefault("cycle", _cycle(request))
    if ctx.get("htmx"):
        dash = templates.get_template("partials/dashboard.html").render(ctx)
        sub = templates.get_template("partials/sub_select.html").render(ctx)
        zoom = templates.get_template("partials/zoom_pill.html").render(ctx)
        presets = templates.get_template("partials/presets.html").render(ctx)
        html = (
            dash
            + f'<div id="sub-wrap" hx-swap-oob="innerHTML">{sub}</div>'
            + f'<div id="zoom-slot" hx-swap-oob="innerHTML">{zoom}</div>'
            + f'<div id="preset-wrap" hx-swap-oob="innerHTML">{presets}</div>'
        )
        return HTMLResponse(html)
    return render(request, "overview.html", ctx)


def run() -> None:
    import uvicorn

    settings = load_settings()
    uvicorn.run(
        "app.main:app",
        host=settings["FINDASH_HOST"],
        port=int(settings["FINDASH_PORT"]),
        reload=False,
    )


if __name__ == "__main__":
    run()
