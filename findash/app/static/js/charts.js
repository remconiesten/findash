const HOOFD_COLORS = {
  "Huishouden": "#E76F51",
  "Wonen": "#2A9D8F",
  "Vrije tijd": "#E9C46A",
  "Vervoer": "#4CC9F0",
  "Telecom/tech": "#7B68EE",
  "Voorkomen": "#F4A261",
  "Medische kosten": "#E07A9A",
  "Verzekeringen": "#52B788",
  "Educatie": "#3D8BFF",
  "Overige uitgaven": "#C77DFF",
  "Interne overboeking": "#8D99AE",
  "Aflossing": "#8D99AE",
};
const FALLBACK = ["#E76F51", "#2A9D8F", "#E9C46A", "#4CC9F0", "#7B68EE", "#F4A261"];

let charts = [];
let chartRo = null;

function parseJson(id) {
  const el = document.getElementById(id);
  if (!el) return null;
  return JSON.parse(el.textContent);
}

function destroyCharts() {
  if (chartRo) {
    chartRo.disconnect();
    chartRo = null;
  }
  charts.forEach((c) => c.destroy());
  charts = [];
}

function colorFor(key, i) {
  return HOOFD_COLORS[key] || FALLBACK[i % FALLBACK.length];
}

function formatEuroTip(value) {
  const n = Number(value);
  const abs = Math.abs(n);
  const rounded = abs >= 100 ? Math.round(n) : n;
  const opts = abs >= 100
    ? { style: "currency", currency: "EUR", minimumFractionDigits: 0, maximumFractionDigits: 0 }
    : { style: "currency", currency: "EUR", minimumFractionDigits: 2, maximumFractionDigits: 2 };
  return new Intl.NumberFormat("nl-NL", opts).format(rounded);
}

function euroTooltip() {
  return {
    callbacks: {
      label: (ctx) => {
        const name = ctx.dataset.label || ctx.label || "";
        const raw = ctx.parsed.y ?? ctx.parsed;
        return `${name}: ${formatEuroTip(raw)}`;
      },
    },
  };
}

function appUrl(path) {
  const href = (document.querySelector("base") && document.querySelector("base").getAttribute("href")) || "/";
  const raw = String(path || "");
  if (!raw || raw === "." || raw.charAt(0) === "#") return raw;
  if (/^https?:/i.test(raw)) return raw;
  if (raw.indexOf("/api/hassio_ingress/") === 0) return raw;
  const rel = raw.replace(/^\//, "");
  const resolved = new URL(rel, new URL(href, window.location.origin));
  return resolved.pathname + resolved.search;
}

function currentNext() {
  let path = window.location.pathname || "/";
  const m = path.match(/^\/api\/hassio_ingress\/[^/]+(\/.*)?$/);
  if (m) path = m[1] || "/";
  if (!path) path = "/";
  return path + (window.location.search || "");
}

function prefixAppLinks(root) {
  const scope = root || document;
  scope.querySelectorAll("form[action]").forEach((form) => {
    const action = form.getAttribute("action");
    if (!action || action === ".") return;
    form.setAttribute("action", appUrl(action));
  });
  ["hx-get", "hx-post"].forEach((attr) => {
    scope.querySelectorAll("[" + attr + "]").forEach((el) => {
      const value = el.getAttribute(attr);
      if (!value || value === ".") return;
      el.setAttribute(attr, appUrl(value));
    });
  });
  scope.querySelectorAll("a[href]").forEach((el) => {
    const href = el.getAttribute("href");
    if (!href || href === "." || href.charAt(0) === "#") return;
    if (href.indexOf("/api/hassio_ingress/") === 0) return;
    if (
      href === "/" ||
      href.indexOf("/import-studio") === 0 ||
      href.indexOf("import-studio") === 0 ||
      href.indexOf("static/") === 0
    ) {
      el.setAttribute("href", appUrl(href));
    }
  });
}

function bindNextOnSubmit() {
  document.querySelectorAll("form.langs").forEach((form) => {
    form.addEventListener("submit", () => {
      const field = form.querySelector("input[name=next]");
      if (field) field.value = currentNext();
    });
  });
}

function applyDrill(level, key) {
  const form = document.getElementById("filters");
  const hoofd = document.getElementById("hoofd");
  const sub = document.getElementById("sub");
  if (!form || !hoofd) return;
  if (level === "clear") {
    hoofd.value = "all";
    if (sub) sub.value = "all";
  } else if (level === "hoofd") {
    hoofd.value = key;
    if (sub) sub.value = "all";
  } else if (level === "sub") {
    if (sub) sub.value = key;
  }
  const url = appUrl("/?" + new URLSearchParams(new FormData(form)).toString());
  if (window.htmx) {
    window.htmx.ajax("GET", url, { target: "#dashboard", swap: "innerHTML" });
    history.pushState({}, "", url);
  } else {
    window.location.assign(url);
  }
}

function baseChartOptions(extra) {
  return Object.assign({
    responsive: true,
    maintainAspectRatio: false,
    resizeDelay: 0,
    animation: false,
    plugins: { legend: { position: "bottom" }, tooltip: euroTooltip() },
  }, extra || {});
}

function resizeCharts() {
  charts.forEach((c) => {
    try { c.resize(); } catch (_err) { /* ignore */ }
  });
}

function bindChartResize() {
  if (chartRo) {
    chartRo.disconnect();
    chartRo = null;
  }
  if (typeof ResizeObserver !== "function") return;
  chartRo = new ResizeObserver(() => resizeCharts());
  document.querySelectorAll(".charts, .saving-mini").forEach((el) => chartRo.observe(el));
}

function drawCharts() {
  destroyCharts();
  const stack = parseJson("chart-monthly-stack");
  const donut = parseJson("chart-donut");
  const ivu = parseJson("chart-in-vs-uit");
  const monthly = document.getElementById("c-monthly");
  const donutEl = document.getElementById("c-donut");
  const ivuEl = document.getElementById("c-ivu");
  if (monthly && stack) {
    const many = (stack.datasets || []).length > 1;
    charts.push(new Chart(monthly, {
      type: "bar",
      data: {
        labels: stack.labels,
        datasets: (stack.datasets || []).map((ds, i) => ({
          label: ds.label,
          data: ds.data,
          key: ds.key,
          backgroundColor: ds.color || colorFor(ds.key || ds.label, i),
          stack: many ? "exp" : undefined,
        })),
      },
      options: baseChartOptions({
        onClick: (_e, els, chart) => {
          if (!els.length) return;
          const ds = chart.data.datasets[els[0].datasetIndex];
          const level = stack.drill || "hoofd";
          if (ds && ds.key && level !== "none") applyDrill(level, ds.key);
        },
      }),
    }));
  }
  if (donutEl && donut) {
    charts.push(new Chart(donutEl, {
      type: "doughnut",
      data: {
        labels: donut.labels,
        datasets: [{
          data: donut.data,
          backgroundColor: donut.colors || (donut.keys || donut.labels || []).map((k, i) => colorFor(k, i)),
        }],
      },
      options: baseChartOptions({
        onClick: (_e, els) => {
          if (!els.length) return;
          const key = (donut.keys || [])[els[0].index];
          const level = stack && stack.drill === "sub" ? "sub" : "hoofd";
          if (key) applyDrill(level, key);
        },
      }),
    }));
  }
  if (ivuEl && ivu) {
    const ivuSets = ivu.datasets || [];
    charts.push(new Chart(ivuEl, {
      type: "bar",
      data: {
        labels: ivu.labels,
        datasets: ivuSets.map((ds) => ({
          label: ds.label,
          data: ds.data,
          backgroundColor: ds.color,
        })),
      },
      options: baseChartOptions({
        plugins: {
          legend: { position: "bottom" },
          tooltip: euroTooltip(),
        },
      }),
    }));
  }
  const saving = parseJson("chart-saving");
  const savingEl = document.getElementById("c-saving");
  if (savingEl && saving) {
    const netto = saving.netto || [];
    const colors = netto.map((v) => (Number(v) < 0 ? "#E76F51" : "#2A9D8F"));
    charts.push(new Chart(savingEl, {
      type: "line",
      data: {
        labels: saving.labels,
        datasets: [{
          label: saving.label || "Netto sparen",
          data: netto,
          borderColor: "#1B3A4B",
          backgroundColor: "rgba(42, 157, 143, 0.14)",
          fill: "origin",
          tension: 0.25,
          pointBackgroundColor: colors,
          pointBorderColor: colors,
          pointRadius: 4,
          pointHoverRadius: 6,
        }],
      },
      options: baseChartOptions({
        plugins: {
          legend: { display: false },
          tooltip: {
            callbacks: {
              label: (ctx) => {
                const i = ctx.dataIndex;
                const net = formatEuroTip(ctx.parsed.y);
                const inn = formatEuroTip((saving.storting || [])[i] || 0);
                const out = formatEuroTip((saving.opname || [])[i] || 0);
                return [
                  `${saving.label || "Netto"}: ${net}`,
                  `${saving.in_label || "Sparen"}: ${inn}`,
                  `${saving.out_label || "Opname"}: ${out}`,
                ];
              },
            },
          },
        },
        onClick: () => {
          const det = document.getElementById("inspect-saving");
          if (!det) return;
          det.open = true;
          det.scrollIntoView({ behavior: "smooth", block: "nearest" });
        },
      }),
    }));
  }
  bindChartResize();
}

function hydrate() {
  const run = () => {
    drawCharts();
    resizeCharts();
  };
  if (typeof requestAnimationFrame === "function") {
    requestAnimationFrame(() => requestAnimationFrame(run));
  } else {
    run();
  }
}

window.addEventListener("load", resizeCharts);
if (document.fonts && document.fonts.ready) {
  document.fonts.ready.then(resizeCharts);
}

document.body.addEventListener("click", (e) => {
  const preset = e.target.closest("[data-preset]");
  if (preset) {
    e.preventDefault();
    const form = preset.closest("form") || document.getElementById("filters");
    if (!form) return;
    form.querySelector("[name=from_year]").value = preset.dataset.fromYear;
    form.querySelector("[name=from_month]").value = preset.dataset.fromMonth;
    form.querySelector("[name=to_year]").value = preset.dataset.toYear;
    form.querySelector("[name=to_month]").value = preset.dataset.toMonth;
    if (form.id === "studio-filters") {
      form.submit();
      return;
    }
    const url = appUrl("/?" + new URLSearchParams(new FormData(form)).toString());
    if (window.htmx) {
      window.htmx.ajax("GET", url, { target: "#dashboard", swap: "innerHTML" });
      history.pushState({}, "", url);
    } else {
      window.location.assign(url);
    }
    return;
  }
  const closer = e.target.closest("[data-tx-close]");
  if (closer) {
    e.preventDefault();
    const embed = closer.closest("tr.tx-embed");
    if (embed) embed.remove();
    return;
  }
  const tx = e.target.closest("[data-tx]");
  if (tx) {
    e.preventDefault();
    const tr = tx.closest("tr");
    const form = document.getElementById("filters");
    if (!tr || !form) return;
    const next = tr.nextElementSibling;
    if (next && next.classList.contains("tx-embed")) {
      next.remove();
      return;
    }
    document.querySelectorAll("tr.tx-embed").forEach((el) => el.remove());
    const embed = document.createElement("tr");
    embed.className = "tx-embed";
    embed.innerHTML = `<td colspan="${tr.children.length}"><div class="tx-embed-body"></div></td>`;
    tr.after(embed);
    const params = new URLSearchParams(new FormData(form));
    params.set("tx_kind", tx.dataset.kind || "spend");
    if (tx.dataset.year) params.set("tx_year", tx.dataset.year);
    if (tx.dataset.month) params.set("tx_month", tx.dataset.month);
    if (tx.dataset.rekening) params.set("tx_rekening", tx.dataset.rekening);
    if (tx.dataset.txSub) params.set("tx_sub", tx.dataset.txSub);
    if (tx.dataset.txHoofd) params.set("tx_hoofd", tx.dataset.txHoofd);
    if (tx.dataset.van !== undefined) params.set("tx_van", tx.dataset.van);
    if (tx.dataset.naar !== undefined) params.set("tx_naar", tx.dataset.naar);
    const url = appUrl("/tx?" + params.toString());
    const body = embed.querySelector(".tx-embed-body");
    if (window.htmx) {
      window.htmx.ajax("GET", url, { target: body, swap: "innerHTML" });
    } else {
      window.location.assign(url);
    }
    return;
  }
  const btn = e.target.closest("[data-drill]");
  if (!btn) return;
  e.preventDefault();
  applyDrill(btn.dataset.drill, btn.dataset.key || "");
});

document.addEventListener("DOMContentLoaded", () => {
  prefixAppLinks(document);
  bindNextOnSubmit();
  hydrate();
});
document.body.addEventListener("htmx:beforeSwap", (e) => {
  if (e.detail.target && e.detail.target.id === "dashboard") destroyCharts();
});
document.body.addEventListener("htmx:afterSwap", (e) => {
  const target = e.detail.target;
  if (target) prefixAppLinks(target);
  if (target && target.classList && target.classList.contains("tx-embed-body")) {
    const embed = target.closest("tr.tx-embed");
    if (embed) embed.scrollIntoView({ behavior: "smooth", block: "nearest" });
    return;
  }
  if (target && target.id === "dashboard") {
    hydrate();
    const time = document.getElementById("chart-time");
    if (time && document.querySelector(".zoom-pill")) {
      time.scrollIntoView({ behavior: "smooth", block: "nearest" });
    }
  }
});
