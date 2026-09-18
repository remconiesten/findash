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
  const url = "/?" + new URLSearchParams(new FormData(form)).toString();
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
          backgroundColor: colorFor(ds.key || ds.label, i),
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
          backgroundColor: (donut.keys || donut.labels || []).map((k, i) => colorFor(k, i)),
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
    charts.push(new Chart(ivuEl, {
      type: "bar",
      data: {
        labels: ivu.labels,
        datasets: [
          { label: ivu.income_label || "Inkomsten", data: ivu.income, backgroundColor: "#2A9D8F" },
          { label: ivu.expense_label || "Uitgaven", data: ivu.expenses, backgroundColor: "#E76F51" },
        ],
      },
      options: baseChartOptions(),
    }));
  }
  const saving = parseJson("chart-saving");
  const savingEl = document.getElementById("c-saving");
  if (savingEl && saving) {
    const netto = saving.netto || [];
    const colors = netto.map((v) => (Number(v) < 0 ? "#E76F51" : "#2A9D8F"));
    charts.push(new Chart(savingEl, {
      type: "bar",
      data: {
        labels: saving.labels,
        datasets: [{
          label: saving.label || "Netto sparen",
          data: netto,
          backgroundColor: colors,
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
    const form = document.getElementById("filters");
    if (!form) return;
    form.querySelector("[name=from_year]").value = preset.dataset.fromYear;
    form.querySelector("[name=from_month]").value = preset.dataset.fromMonth;
    form.querySelector("[name=to_year]").value = preset.dataset.toYear;
    form.querySelector("[name=to_month]").value = preset.dataset.toMonth;
    const url = "/?" + new URLSearchParams(new FormData(form)).toString();
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
    const url = "/tx?" + params.toString();
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

document.addEventListener("DOMContentLoaded", hydrate);
document.body.addEventListener("htmx:beforeSwap", (e) => {
  if (e.detail.target && e.detail.target.id === "dashboard") destroyCharts();
});
document.body.addEventListener("htmx:afterSwap", (e) => {
  const target = e.detail.target;
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
