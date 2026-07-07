/* G10 Valutadashboard – leser data/*.json og rendrer oversikt + landskort. */

const nb = new Intl.NumberFormat("nb-NO", { maximumFractionDigits: 4 });
const nb1 = new Intl.NumberFormat("nb-NO", { minimumFractionDigits: 1, maximumFractionDigits: 1 });
const nb2 = new Intl.NumberFormat("nb-NO", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const pct = (v) => (v == null ? "–" : `${v > 0 ? "+" : ""}${nb2.format(v)} %`);
const pct1 = (v) => (v == null ? "–" : `${v > 0 ? "+" : ""}${nb1.format(v)} %`);
const rate = (v) => (v == null ? "–" : `${nb2.format(v)} %`);
const signed = (v, fmt = nb1) => (v == null ? "–" : `${v > 0 ? "+" : ""}${fmt.format(v)}`);
const thousands = (v) => (v == null ? "–" : `${v > 0 ? "+" : ""}${nb1.format(v / 1000)}k`);

const dateFmt = new Intl.DateTimeFormat("nb-NO", { day: "numeric", month: "short" });

const PALETTE = ["#2563eb", "#f59e0b", "#10b981", "#ef4444", "#8b5cf6",
                 "#06b6d4", "#ec4899", "#84cc16", "#f97316"];

let cssVar;

function changeChip(label, value, invert) {
  const shown = value == null ? null : invert ? -value : value;
  const cls = shown == null ? "" : shown > 0 ? "pos" : shown < 0 ? "neg" : "";
  return `<span class="chip">${label} <b class="${cls}">${pct(shown)}</b></span>`;
}

/**
 * Datadrevet retningssignal for valutaen (heuristikk, ikke prognose):
 *  - rentesignal: 3 mnd-rente minus styringsrente → hva markedet priser av endringer
 *  - momentum:    kursutvikling mot NOK siste 3 mnd
 *  - realrente:   styringsrente minus KPI å/å
 */
function directionSignal(c) {
  const invert = c.fx?.index; // I-44: lavere indeks = sterkere krone
  const parts = [];
  let score = 0;

  const m3 = c.rates?.m3, policy = c.rates?.policy;
  if (m3 != null && policy != null) {
    const spread = m3 - policy;
    score += Math.max(-1, Math.min(1, spread / 0.4)) * 0.45;
    if (spread > 0.15) parts.push("markedet priser <b>renteheving</b>");
    else if (spread < -0.15) parts.push("markedet priser <b>rentekutt</b>");
    else parts.push("markedet priser <b>uendret rente</b>");
  }

  let mom = c.fx?.changes?.m3;
  if (mom != null) {
    if (invert) mom = -mom;
    score += Math.max(-1, Math.min(1, mom / 4)) * 0.35;
    if (mom > 0.5) parts.push("valutaen har <b>styrket seg</b> siste 3 mnd");
    else if (mom < -0.5) parts.push("valutaen har <b>svekket seg</b> siste 3 mnd");
  }

  const cpi = c.cpi?.value;
  if (policy != null && cpi != null) {
    const real = policy - cpi;
    score += Math.max(-1, Math.min(1, real / 2)) * 0.2;
    if (real > 0.5) parts.push("positiv realrente");
    else if (real < -0.5) parts.push("negativ realrente");
  }

  const dir = score > 0.12 ? "up" : score < -0.12 ? "down" : "flat";
  const arrow = { up: "▲", down: "▼", flat: "▶" }[dir];
  const word = { up: "Styrkende drivere", down: "Svekkende drivere", flat: "Nøytralt bilde" }[dir];
  return { dir, arrow, word, text: parts.join(" · ") || "For lite data" };
}

function fxLine(c) {
  if (!c.fx) return `<div class="fx-value">–</div>`;
  if (c.fx.index) {
    return `<div class="fx-value">I-44: ${nb.format(c.fx.value)} <small>importveid kroneindeks (lavere = sterkere NOK)</small></div>`;
  }
  return `<div class="fx-value">${c.fx.per} ${c.currency} = ${nb.format(c.fx.value)} NOK</div>`;
}

function pppLine(c) {
  if (!c.ppp) return "";
  if (c.ppp.valuation == null) return `PPP: <b>referansevaluta</b>`;
  const v = c.ppp.valuation;
  const word = v > 0 ? "overvurdert" : "undervurdert";
  const proxy = c.ppp.proxy ? ` <small>(proxy: ${c.ppp.proxy})</small>` : "";
  return `PPP mot USD: <b>${nb1.format(Math.abs(v))} % ${word}</b>${proxy}`;
}

function cotLine(c) {
  if (!c.cot) {
    return c.currency === "NOK" || c.currency === "SEK"
      ? `<span>Spekulativ posisjonering: <small>ingen likvide futures for ${c.currency}</small></span>`
      : "";
  }
  const cls = c.cot.net > 0 ? "pos" : c.cot.net < 0 ? "neg" : "";
  const oi = c.cot.pct_oi != null ? ` · ${signed(c.cot.pct_oi)} % av OI` : "";
  const wk = c.cot.change_w != null ? ` · uke: ${thousands(c.cot.change_w)}` : "";
  return `<span>Spek. netto (CFTC): <b class="${cls}">${thousands(c.cot.net)}</b>${oi}${wk}</span>`;
}

function card(c, market) {
  const sig = directionSignal(c);
  const inv = c.fx?.index;
  const ch = c.fx?.changes || {};
  const meeting = c.meeting ? dateFmt.format(new Date(c.meeting)) : "–";
  const curve = c.rates.y10 != null && c.rates.m3 != null ? c.rates.y10 - c.rates.m3 : null;
  const volChip = c.vol30 != null
    ? `<span class="chip">vol <b>${nb1.format(c.vol30)} %</b></span>` : "";
  const brentRow = c.id === "no" && market?.brent
    ? `<div class="meta-row"><span>Brent: <b>${nb2.format(market.brent.value)} USD</b> <small>(1m ${pct1(market.brent.changes?.m1)})</small></span>
       <span>90d-korr. olje↔NOK: <b>${market.brent_nok_corr != null ? nb2.format(market.brent_nok_corr) : "–"}</b></span></div>`
    : "";
  return `
  <article class="card" id="card-${c.id}">
    <div class="card-head">
      <span class="flag">${c.flag}</span>
      <h2>${c.name}</h2>
      <span class="ccy">${c.currency}</span>
    </div>
    ${fxLine(c)}
    <div class="changes">
      ${changeChip("1d", ch.d1, inv)}${changeChip("1u", ch.w1, inv)}${changeChip("1m", ch.m1, inv)}${changeChip("3m", ch.m3, inv)}${changeChip("1å", ch.y1, inv)}${volChip}
    </div>
    <div class="chart-wrap"><canvas id="chart-${c.id}"></canvas></div>
    <div class="rates">
      <div class="rate-box"><div class="label">Styring</div><div class="val">${rate(c.rates.policy)}</div></div>
      <div class="rate-box"><div class="label">3 mnd</div><div class="val">${rate(c.rates.m3)}</div></div>
      <div class="rate-box"><div class="label">10 år</div><div class="val">${rate(c.rates.y10)}</div></div>
      <div class="rate-box"><div class="label">Kurve 10å−3m</div><div class="val">${curve != null ? signed(curve, nb2) : "–"}</div></div>
    </div>
    <div class="chart-label">Styringsrente 2 år</div>
    <div class="chart-wrap-sm"><canvas id="policy-${c.id}"></canvas></div>
    <div class="meta-row">
      <span>KPI å/å: <b>${c.cpi ? rate(Math.round(c.cpi.value * 10) / 10) : "–"}</b> <small>(${c.cpi?.period ?? ""})</small></span>
      <span>Ledighet: <b>${c.unemployment ? rate(c.unemployment.value) : "–"}</b> <small>(${c.unemployment?.period ?? ""})</small></span>
    </div>
    <div class="meta-row">
      <span>${pppLine(c)}</span>
      <span>${c.bank}: <b>${meeting}</b></span>
    </div>
    ${c.cot || c.currency === "NOK" || c.currency === "SEK" ? `<div class="meta-row">${cotLine(c)}</div>` : ""}
    ${brentRow}
    <div class="signal ${sig.dir}">
      <span class="arrow">${sig.arrow}</span>
      <span class="expl"><b>${sig.word}.</b> ${sig.text}</span>
    </div>
  </article>`;
}

function baseLineOptions(tooltipLabel) {
  return {
    responsive: true,
    maintainAspectRatio: false,
    animation: false,
    interaction: { mode: "index", intersect: false },
    plugins: {
      legend: { display: false },
      tooltip: { callbacks: { label: tooltipLabel } },
    },
    scales: {
      x: {
        ticks: {
          color: cssVar("--muted"), maxTicksLimit: 5, maxRotation: 0,
          callback(value) { return dateFmt.format(new Date(this.getLabelForValue(value))); },
        },
        grid: { display: false },
      },
      y: {
        ticks: { color: cssVar("--muted"), maxTicksLimit: 4 },
        grid: { color: cssVar("--border") },
      },
    },
  };
}

function drawFxChart(c, history) {
  const key = c.fx?.index ? "I44" : c.currency;
  const series = history.fx?.[key];
  if (!series) return;
  const entries = Object.entries(series).sort(([a], [b]) => a.localeCompare(b));
  const per = c.fx?.per ?? 1;
  new Chart(document.getElementById(`chart-${c.id}`), {
    type: "line",
    data: {
      labels: entries.map(([d]) => d),
      datasets: [{
        data: entries.map(([, v]) => v * per),
        borderColor: cssVar("--accent"), borderWidth: 1.6, pointRadius: 0, tension: 0.2,
      }],
    },
    options: baseLineOptions((item) => c.fx?.index
      ? `I-44: ${nb.format(item.parsed.y)}`
      : `${per} ${c.currency} = ${nb.format(item.parsed.y)} NOK`),
  });
}

function drawPolicyChart(c, history) {
  const series = history.policy?.[c.bis] ?? history.policy?.[{
    us: "US", ea: "XM", jp: "JP", gb: "GB", ch: "CH", ca: "CA", au: "AU", nz: "NZ", se: "SE", no: "NO",
  }[c.id]];
  if (!series) return;
  const entries = Object.entries(series).sort(([a], [b]) => a.localeCompare(b));
  new Chart(document.getElementById(`policy-${c.id}`), {
    type: "line",
    data: {
      labels: entries.map(([d]) => d),
      datasets: [{
        data: entries.map(([, v]) => v),
        borderColor: cssVar("--flat"), borderWidth: 1.4, pointRadius: 0, stepped: true,
      }],
    },
    options: baseLineOptions((item) => `Styringsrente: ${rate(item.parsed.y)}`),
  });
}

function renderMovers(countries) {
  const rows = countries
    .filter((c) => c.fx && !c.fx.index && c.fx.changes?.w1 != null)
    .map((c) => ({ ...c, w1: c.fx.changes.w1 }))
    .sort((a, b) => b.w1 - a.w1);
  if (rows.length < 2) return;
  const best = rows[0], worst = rows[rows.length - 1];
  const fmt = (c) => `<b>${c.flag} ${c.currency}</b> <span class="${c.w1 > 0 ? "pos" : "neg"}">${pct(c.w1)}</span>`;
  document.getElementById("movers").innerHTML = `
    <span class="mover">Sterkest mot NOK siste uke: ${fmt(best)}</span>
    <span class="mover">Svakest mot NOK siste uke: ${fmt(worst)}</span>`;
}

function renderComparison(countries, history) {
  const datasets = [];
  let labels = null;
  let i = 0;
  for (const c of countries) {
    if (!c.fx || c.fx.index) continue;
    const series = history.fx?.[c.currency];
    if (!series) continue;
    const entries = Object.entries(series).sort(([a], [b]) => a.localeCompare(b));
    if (!labels || entries.length > labels.length) labels = entries.map(([d]) => d);
    const base = entries[0][1];
    datasets.push({
      label: `${c.flag} ${c.currency}`,
      data: Object.fromEntries(entries.map(([d, v]) => [d, +(v / base * 100).toFixed(2)])),
      borderColor: PALETTE[i++ % PALETTE.length],
      borderWidth: 1.6, pointRadius: 0, tension: 0.2,
    });
  }
  // Chart.js håndterer objekt-data via parsing-nøkler; map til labels-akse
  const mapped = datasets.map((ds) => ({ ...ds, data: labels.map((d) => ds.data[d] ?? null) }));
  new Chart(document.getElementById("comparisonChart"), {
    type: "line",
    data: { labels, datasets: mapped },
    options: {
      ...baseLineOptions((item) => `${item.dataset.label}: ${nb2.format(item.parsed.y)}`),
      plugins: {
        legend: { display: true, position: "bottom", labels: { color: cssVar("--text"), boxWidth: 18, boxHeight: 3 } },
        tooltip: { callbacks: { label: (item) => `${item.dataset.label}: ${nb2.format(item.parsed.y)}` } },
      },
      spanGaps: true,
    },
  });
}

function renderRisk(market) {
  const tiles = [];
  const tile = (label, val, sub) =>
    `<div class="risk-tile"><div class="label">${label}</div><div class="val">${val}</div><div class="sub">${sub}</div></div>`;
  const chg = (v) => `1m <span class="${v > 0 ? "pos" : v < 0 ? "neg" : ""}">${pct1(v)}</span>`;
  if (market.audjpy) tiles.push(tile("AUD/JPY (risk on/off)", nb2.format(market.audjpy.value), chg(market.audjpy.changes?.m1)));
  if (market.vix) tiles.push(tile("VIX", nb2.format(market.vix.value), chg(market.vix.changes?.m1)));
  if (market.brent) tiles.push(tile("Brent (USD)", nb2.format(market.brent.value), chg(market.brent.changes?.m1)));
  document.getElementById("riskTiles").innerHTML = tiles.join("");
  const corr = market.brent_nok_corr;
  if (corr != null) {
    document.getElementById("riskPanel").insertAdjacentHTML("beforeend",
      `<p class="risk-note">Stigende AUD/JPY og fallende VIX = risikoappetitt, som normalt støtter NOK.
       90-dagers korrelasjon Brent↔kronestyrke: <b>${nb2.format(corr)}</b>.</p>`);
  }
}

function renderDiffs(countries) {
  const norway = countries.find((c) => c.id === "no");
  if (!norway) return;
  const cell = (a, b) => {
    if (a == null || b == null) return `<td>–</td>`;
    const d = a - b;
    const cls = d > 0.05 ? "pos" : d < -0.05 ? "neg" : "";
    return `<td class="${cls}">${signed(d, nb2)}</td>`;
  };
  const rows = countries.filter((c) => c.id !== "no").map((c) => `
    <tr>
      <td>${c.flag} ${c.currency}</td>
      ${cell(c.rates.policy, norway.rates.policy)}
      ${cell(c.rates.m3, norway.rates.m3)}
      ${cell(c.rates.y10, norway.rates.y10)}
    </tr>`).join("");
  document.getElementById("diffTable").innerHTML = `
    <table class="diff-table">
      <thead><tr><th>Valuta</th><th>Styringsrente</th><th>3 mnd</th><th>10 år</th></tr></thead>
      <tbody>${rows}</tbody>
    </table>
    <p class="risk-note">Positiv differanse = høyere rente enn Norge → isolert sett støtte for valutaen mot NOK.</p>`;
}

async function init() {
  const bust = `?v=${Date.now()}`;
  const [dashboard, history] = await Promise.all([
    fetch(`data/dashboard.json${bust}`).then((r) => r.json()),
    fetch(`data/history.json${bust}`).then((r) => r.json()),
  ]);

  const css = getComputedStyle(document.documentElement);
  cssVar = (name) => css.getPropertyValue(name).trim();

  const updated = new Date(dashboard.updated);
  document.getElementById("updated").textContent =
    `Sist oppdatert: ${updated.toLocaleString("nb-NO", { dateStyle: "long", timeStyle: "short" })}`;

  const market = dashboard.market || {};
  renderMovers(dashboard.countries);
  renderRisk(market);
  renderDiffs(dashboard.countries);

  const grid = document.getElementById("grid");
  grid.innerHTML = dashboard.countries.map((c) => card(c, market)).join("");
  renderComparison(dashboard.countries, history);
  dashboard.countries.forEach((c) => { drawFxChart(c, history); drawPolicyChart(c, history); });
}

init().catch((err) => {
  document.getElementById("grid").innerHTML =
    `<p class="loading">Kunne ikke laste data: ${err.message}</p>`;
});
