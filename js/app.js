/* G10 Valutadashboard – leser data/*.json og rendrer landskort. */

const nb = new Intl.NumberFormat("nb-NO", { maximumFractionDigits: 4 });
const nb2 = new Intl.NumberFormat("nb-NO", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const pct = (v) => (v == null ? "–" : `${v > 0 ? "+" : ""}${nb2.format(v)} %`);
const rate = (v) => (v == null ? "–" : `${nb2.format(v)} %`);

const dateFmt = new Intl.DateTimeFormat("nb-NO", { day: "numeric", month: "short" });

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

function card(c) {
  const sig = directionSignal(c);
  const inv = c.fx?.index;
  const ch = c.fx?.changes || {};
  const meeting = c.meeting
    ? dateFmt.format(new Date(c.meeting))
    : "–";
  return `
  <article class="card" id="card-${c.id}">
    <div class="card-head">
      <span class="flag">${c.flag}</span>
      <h2>${c.name}</h2>
      <span class="ccy">${c.currency}</span>
    </div>
    ${fxLine(c)}
    <div class="changes">
      ${changeChip("1d", ch.d1, inv)}${changeChip("1u", ch.w1, inv)}${changeChip("1m", ch.m1, inv)}${changeChip("3m", ch.m3, inv)}${changeChip("1å", ch.y1, inv)}
    </div>
    <div class="chart-wrap"><canvas id="chart-${c.id}"></canvas></div>
    <div class="rates">
      <div class="rate-box"><div class="label">Styringsrente</div><div class="val">${rate(c.rates.policy)}</div></div>
      <div class="rate-box"><div class="label">3 mnd</div><div class="val">${rate(c.rates.m3)}</div></div>
      <div class="rate-box"><div class="label">10 år</div><div class="val">${rate(c.rates.y10)}</div></div>
    </div>
    <div class="meta-row">
      <span>KPI å/å: <b>${c.cpi ? rate(Math.round(c.cpi.value * 10) / 10) : "–"}</b> <small>(${c.cpi?.period ?? ""})</small></span>
      <span>${c.bank}: <b>${meeting}</b></span>
    </div>
    <div class="signal ${sig.dir}">
      <span class="arrow">${sig.arrow}</span>
      <span class="expl"><b>${sig.word}.</b> ${sig.text}</span>
    </div>
  </article>`;
}

function drawChart(c, history) {
  const key = c.fx?.index ? "I44" : c.currency;
  const series = history.fx?.[key];
  if (!series) return;
  const entries = Object.entries(series).sort(([a], [b]) => a.localeCompare(b));
  const per = c.fx?.per ?? 1;
  const css = getComputedStyle(document.documentElement);
  const accent = css.getPropertyValue("--accent").trim();
  const muted = css.getPropertyValue("--muted").trim();
  const border = css.getPropertyValue("--border").trim();

  new Chart(document.getElementById(`chart-${c.id}`), {
    type: "line",
    data: {
      labels: entries.map(([d]) => d),
      datasets: [{
        data: entries.map(([, v]) => v * per),
        borderColor: accent,
        borderWidth: 1.6,
        pointRadius: 0,
        tension: 0.2,
        fill: false,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: false,
      interaction: { mode: "index", intersect: false },
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            title: (items) => items[0].label,
            label: (item) => c.fx?.index
              ? `I-44: ${nb.format(item.parsed.y)}`
              : `${per} ${c.currency} = ${nb.format(item.parsed.y)} NOK`,
          },
        },
      },
      scales: {
        x: {
          ticks: {
            color: muted, maxTicksLimit: 5, maxRotation: 0,
            callback(value) {
              const d = this.getLabelForValue(value);
              return dateFmt.format(new Date(d));
            },
          },
          grid: { display: false },
        },
        y: {
          ticks: { color: muted, maxTicksLimit: 4 },
          grid: { color: border },
        },
      },
    },
  });
}

async function init() {
  const bust = `?v=${Date.now()}`;
  const [dashboard, history] = await Promise.all([
    fetch(`data/dashboard.json${bust}`).then((r) => r.json()),
    fetch(`data/history.json${bust}`).then((r) => r.json()),
  ]);

  const updated = new Date(dashboard.updated);
  document.getElementById("updated").textContent =
    `Sist oppdatert: ${updated.toLocaleString("nb-NO", { dateStyle: "long", timeStyle: "short" })}`;

  const grid = document.getElementById("grid");
  grid.innerHTML = dashboard.countries.map(card).join("");
  dashboard.countries.forEach((c) => drawChart(c, history));
}

init().catch((err) => {
  document.getElementById("grid").innerHTML =
    `<p class="loading">Kunne ikke laste data: ${err.message}</p>`;
});
