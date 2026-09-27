/* Redaksjonell oversikt: hero, renteforventninger (hantelgraf), kronen (søyleliste), tre ting, kildestatus. */
import { nb0, nb1, nb2, pct1, rate, signed, pp, moves, cls, shortDate, daysUntil, color, name } from "./format.js";
import { extremeText, targetInflation } from "./calc.js";
import { dumbbellChart, barList } from "./charts.js";

const longDate = new Intl.DateTimeFormat("nb-NO", { weekday: "long", day: "numeric", month: "long" });
const cap = (s) => s.charAt(0).toUpperCase() + s.slice(1);
const i12 = (c) => c.curve.implied["12m"];
/** Hva banen er lest ut av: futures på styringsrenten, OIS eller statskurve (inkl. terminpremie). */
export const curveKind = (c) => ({ futures: "futures", ois: "OIS", swap: "swapkurve", govt: "statskurve", zero: "statskurve" })[c.curve?.kind] ?? "";
/**
 * Hvor mye banen kan bære: «høy» (futures/OIS/swap følger styringsrenten), «middels» (statskurve med
 * terminpremie), «lav» (syntetisk nåpunkt: ingen korte punkter, eller et månedssnitt som front – JPY/CHF
 * uten veksler, NZD med OECD-front). Backend setter feltet; eldre data utledes av kind og anker.
 */
export const confidence = (c) => c.curve?.confidence ?? (c.curve?.synthetic_anchor ? "lav" : ["futures", "ois", "swap"].includes(c.curve?.kind) ? "høy" : "middels");
/** Kurver som får bære hero-tall og «størst sprik»: alt unntatt lav sikkerhet. */
const reliable = (c) => confidence(c) !== "lav";

/** Overskriften: hva markedet venter, i én setning. */
function headline(rows) {
  if (!rows.length) return "Rentekurvene er ikke tilgjengelige ennå.";
  const up = rows.filter((c) => i12(c) >= 13), down = rows.filter((c) => i12(c) <= -13);
  const who = (list) => list.map((c) => c.name).join(", ").replace(/, ([^,]*)$/, " og $1");
  if (up.length === rows.length) return "Markedet venter høyere renter fra alle sentralbankene det neste året.";
  if (down.length === rows.length) return "Markedet venter lavere renter fra alle sentralbankene det neste året.";
  if (up.length && down.length) return `Markedet venter hevinger i ${who(up)}, og kutt i ${who(down)}.`;
  if (up.length) return `Markedet venter hevinger i ${who(up)} – og uendret rente ellers.`;
  if (down.length) return `Markedet venter kutt i ${who(down)} – og uendret rente ellers.`;
  return "Markedet venter om lag uendrede renter det neste året.";
}

export function renderHero(countries, market, updated) {
  const rows = countries.filter((c) => c.curve);
  document.getElementById("kicker").textContent = `G10 valutabrief · ${cap(longDate.format(new Date(updated)))}`;
  document.getElementById("headline").textContent = headline(rows);

  const stats = [];
  // 1) Nærmest et vedtak: banken med neste møte der markedet priser en bevegelse
  const soon = countries.filter((c) => c.next_meeting && (c.next_meeting.bp != null ? Math.abs(c.next_meeting.bp) >= 10 : Math.abs(c.next_meeting.bp_3m ?? 0) >= 13))
    .sort((a, b) => a.next_meeting.date.localeCompare(b.next_meeting.date))[0];
  if (soon) {
    const nm = soon.next_meeting, d = daysUntil(nm.date);
    const what = nm.prob != null ? `<span title="${nm.source}">~${Math.round(nm.prob * 100)} % for ${nm.move ?? "bevegelse"}</span>`
      : nm.bp != null ? `<span title="${nm.source}">${pp(nm.bp)} priset</span>` : `kurven priser ${moves(nm.bp_3m)} innen 3 mnd`;
    stats.push([`<span class="text">${soon.flag} ${soon.bank.replace("Reserve Bank of ", "RB ")}</span>`, `nærmest et vedtak: ${shortDate(nm.date)}, ${d === 0 ? "i dag" : `om ${d} dager`} · ${what}`]);
  }
  // 2) Mest priset på 12 mnd, som nivå fra → til – bare kurver med markedsanker (ikke lav sikkerhet)
  const solid = rows.filter(reliable);
  if (solid.length) {
    const most = [...solid].sort((a, b) => Math.abs(i12(b)) - Math.abs(i12(a)))[0];
    stats.push([`<span class="text nowrap">${rate(most.rates.policy)} → ${rate(most.curve.path[12])}</span>`, `mest priset på 12 mnd: ${most.bank}, ${moves(i12(most))} <span title="Antall hevinger belønner lavt utgangspunkt; sier ikke at vedtaket er nært">– fra lavt nivå</span>`]);
  }
  // 3) Størst uenighet med bankens eget anslag
  const gaps = solid.filter((c) => c.cb_path?.level != null).map((c) => ({ c, gap: c.curve.path[12] - c.cb_path.level })).sort((a, b) => Math.abs(b.gap) - Math.abs(a.gap));
  if (gaps.length) {
    const { c, gap } = gaps[0];
    stats.push([`<span class="${cls(gap)}">${signed(gap, nb2)} pp</span>`, `størst uenighet med banken selv: ${c.currency} ligger ${gap > 0 ? "over" : "under"} ${c.bank}s eget anslag`]);
  }
  // 4) Ukens sterkeste mot kronen
  const movers = countries.filter((c) => c.fx && !c.fx.index && c.fx.changes?.w1 != null).sort((a, b) => b.fx.changes.w1 - a.fx.changes.w1);
  if (movers.length) {
    const b = movers[0];
    stats.push([`<span class="${cls(b.fx.changes.w1)}">${pct1(b.fx.changes.w1)}</span>`, `${b.currency} er sterkest mot kronen denne uken`]);
  }
  document.getElementById("heroStats").innerHTML = stats.slice(0, 4).map(([big, lbl]) =>
    `<div class="stat"><div class="big">${big}</div><div class="lbl">${lbl}</div></div>`).join("");
}

/**
 * «+73 bp siste måned, hvorav 25 levert»: endringen i renten markedet priser om 12 mnd er et
 * rent forventningsskift (markedsanker); det banken har levert i vinduet vises ved siden av,
 * så leseren ser hvor mye av veien som er gått og hvor mye som gjenstår å prise.
 */
export function repricingNote(c, window = "m1") {
  const d = c.curve?.repricing_detail?.[window];
  if (!d || d.delivered === 0 || Math.abs(d.level) < 5) return "";
  const span = window === "m1" ? "siste måned" : "siste uke";
  return ` <span class="muted">(${pp(d.level)} ${span}, hvorav ${pp(d.delivered)} levert – ${d.remaining > 0 ? `${pp(d.remaining)} mer` : d.remaining < 0 ? `${pp(-d.remaining)} mindre` : "like mye"} gjenstår å prise)</span>`;
}

/** Seksjon 1: rente nå og ventet om 12 mnd, som hantelgraf, pluss tekstliste. */
export function renderRates(countries) {
  const rows = countries.filter((c) => c.curve && c.rates.policy != null).sort((a, b) => i12(a) - i12(b));
  const missing = countries.filter((c) => !c.curve).map((c) => c.currency);
  const el = document.getElementById("rates");
  if (!rows.length) { el.innerHTML = `<p class="note">Ingen rentekurver tilgjengelig ennå.</p>`; return; }
  const chartRows = rows.map((c) => ({
    id: c.id, flag: c.flag, label: c.bank.replace("Reserve Bank of ", "RB ").replace("Swiss National Bank", "SNB"), short: c.currency,
    now: c.rates.policy, expected: c.curve.path[12], six: c.curve.path[6], color: color(c),
    text: `${rate(c.curve.path[12])} (${moves(i12(c))})`, textShort: rate(c.curve.path[12]),
    title: `${c.bank}: ${rate(c.rates.policy)} nå, ${rate(c.curve.path[12])} ventet om 12 mnd (${pp(i12(c))}) · ${c.curve.source}`,
    bank: c.cb_path?.level ?? null,
    bankTitle: c.cb_path ? `${c.bank}s eget anslag: ${rate(c.cb_path.level)} ${c.cb_path.horizon} (${c.cb_path.source}${c.cb_path.stale ? ", utdatert" : ""})` : "",
  }));
  // Hvor ligger markedet lengst fra sentralbankens egen bane? (kurver med lav sikkerhet holdes ute)
  const gaps = rows.filter((c) => c.cb_path?.level != null && reliable(c))
    .map((c) => ({ c, gap: c.curve.path[12] - c.cb_path.level }))
    .sort((a, b) => Math.abs(b.gap) - Math.abs(a.gap));
  const gapText = gaps.length ? `<p class="lead">Markedet ligger lengst fra sentralbankens eget anslag for
    ${gaps.slice(0, 3).map(({ c, gap }) => `<b>${c.currency}</b> (${gap > 0 ? "over" : "under"} med ${nb2.format(Math.abs(gap))} pp)`).join(", ")}.
    Der har kursen mest å tape hvis banken får rett.</p>` : "";
  const list = rows.map((c) => {
    const r = c.curve.repricing?.w1;
    const week = r == null || Math.abs(r) < 5 ? "" : ` <span class="${cls(r)}">${r > 0 ? "↑" : "↓"} ${r > 0 ? "høyere" : "lavere"} enn for en uke siden</span>${repricingNote(c, "m1")}`;
    const src = c.rates.policy_unconfirmed ? ` <small class="neg" title="${c.rates.policy_source}">⚠ ubekreftet etter møtet ${shortDate(c.rates.policy_unconfirmed)}</small>`
      : c.rates.policy_source?.startsWith("vedtak") ? ` <small>(manuelt registrert)</small>` : "";
    const bank = c.cb_path ? ` · banken selv: ${rate(c.cb_path.level)} ${c.cb_path.horizon}${c.cb_path.stale ? " ⚠ utdatert anslag" : ""}` : "";
    const kind = curveKind(c) ? ` <small class="muted" title="${c.curve.source}">${curveKind(c)}${confidence(c) === "lav" ? " · syntetisk nåpunkt, lav sikkerhet" : ""}</small>` : "";
    return `<li><b>${c.flag} ${c.bank}</b>${kind} · ${rate(c.rates.policy)} nå${src} → <b>${moves(i12(c))}</b> neste 12 mnd
      <span class="muted">(${pp(i12(c))}, ${extremeText(c.curve)}${bank})</span>${week}</li>`;
  }).join("");
  el.innerHTML = `
    <div id="dumbbell"></div>
    ${gapText}
    <details class="more"><summary>Vis som liste</summary><ul class="plain">${list}</ul></details>
    <p class="note">Én heving eller ett kutt = 0,25 prosentpoeng. Lest ut av futures (USD, AUD, CAD, NZD), OIS (GBP) eller statskurven (øvrige, med terminpremie), oppdatert hver ukedag.
      ${rows.some((c) => !reliable(c)) ? `Kurver med syntetisk nåpunkt (${rows.filter((c) => !reliable(c)).map((c) => c.currency).join(", ")}) holdes ute av tallene øverst.` : ""}
      ${missing.length ? `Ingen kurve tilgjengelig for ${missing.join(" og ")}.` : ""}</p>`;
  // Kompakt graf på smale skjermer; tegnes på nytt når bredden krysser grensen
  const mq = window.matchMedia("(max-width: 640px)");
  const draw = () => { document.getElementById("dumbbell").innerHTML = dumbbellChart(chartRows, { compact: mq.matches }); };
  mq.addEventListener("change", draw);
  draw();
}

/** Seksjon 2: kronen – hvem har gått mest mot NOK, valgbar horisont, pluss risikobildet. */
export function renderKrone(countries, market) {
  const no = countries.find((c) => c.id === "no");
  const horizons = [["w1", "uke"], ["m1", "måned"], ["m3", "3 mnd"], ["y1", "år"]];
  const el = document.getElementById("krone");
  const draw = (h) => {
    const rows = countries.filter((c) => c.fx && !c.fx.index && c.fx.changes?.[h] != null)
      .map((c) => ({ label: c.currency, flag: c.flag, value: c.fx.changes[h] })).sort((a, b) => b.value - a.value);
    document.getElementById("kroneBars").innerHTML = barList(rows, (v) => pct1(v));
    document.querySelectorAll("#kroneChips button").forEach((b) => b.classList.toggle("on", b.dataset.h === h));
  };
  const nokChange = no?.fx?.changes?.w1 != null ? -no.fx.changes.w1 : null; // I-44: lavere = sterkere krone
  const risk = (() => {
    if (!market.vix) return "";
    const v = market.vix.value, aj = market.audjpy?.changes?.m1;
    const score = (v < 18 ? 1 : v > 25 ? -1 : 0) + (aj == null ? 0 : aj > 1 ? 1 : aj < -2 ? -1 : 0);
    const word = score > 0 ? "høy" : score < 0 ? "lav" : "nøytral";
    return `Risikoappetitten er <b>${word}</b> (VIX ${nb1.format(v)}${aj != null ? `, AUD/JPY ${pct1(aj)} siste måned` : ""})${score > 0 ? ", som normalt støtter kronen" : score < 0 ? ", som normalt svekker kronen" : ""}.`;
  })();
  const oil = (() => {
    if (!market.brent && !market.brent_fut) return "";
    const parts = [];
    if (market.brent_fut) parts.push(`Brent-futures koster <b>${nb0.format(market.brent_fut.value)} USD</b> (${pct1(market.brent_fut.changes?.m1)} siste måned, ${market.brent_fut.contract ?? "front-kontrakten"})`);
    if (market.brent) parts.push(`fysisk Brent (Dated, ${shortDate(market.brent.date)}) <b>${nb0.format(market.brent.value)} USD</b>`);
    let premium = "";
    if (market.brent_premium) {
      const d = market.brent_premium.value, avg = market.brent_premium.avg90;
      const vsAvg = avg != null ? ` mot ${nb0.format(avg)} USD i snitt siste 90 dager` : "";
      premium = Math.abs(d) >= 3 ? ` Spotpremien på ${nb0.format(d)} USD samme dag${vsAvg} er et ${d > 0 ? "tegn på stramt fysisk marked" : "tegn på slakt fysisk marked"}.` : "";
    }
    let spread = "";
    if (market.brent_spread && Math.abs(market.brent_spread.value) >= 1) {
      const v = market.brent_spread.value;
      spread = v > 0 ? ` Front-kontrakten ligger ${nb1.format(v)} USD over neste måned (backwardation: markedet betaler for olje nå).`
        : ` Front-kontrakten ligger ${nb1.format(-v)} USD under neste måned (contango: lagrene fylles).`;
    }
    const corr = market.brent_nok_corr != null ? ` Kronen har fulgt oljen med korrelasjon ${nb2.format(market.brent_nok_corr)} siste 90 dager${market.ttf_nok_corr != null ? `, gassen med ${nb2.format(market.ttf_nok_corr)}` : ""}.${
      market.energy_driver === "gass" ? " Det er gassen, ikke oljen, som har forklart kronen best." : market.energy_driver === "olje" && market.ttf_nok_corr != null ? " Oljen forklarer kronen bedre enn gassen." : market.energy_driver === "begge" ? " Olje og gass forklarer kronen omtrent like godt." : ""}` : "";
    return `<p class="lead">${parts.join(", ")}.${premium}${spread}${corr}</p>`;
  })();
  const gas = market.ttf ? `<p class="lead">Gass (TTF) koster <b>${nb0.format(market.ttf.value)} EUR/MWh</b> (${pct1(market.ttf.changes?.m1)} siste måned${market.ttf.contract ? `, ${market.ttf.contract}` : ""}).</p>` : "";
  el.innerHTML = `
    <p class="lead">${nokChange != null ? `Kronen er <b class="${cls(nokChange)}">${pct1(nokChange)}</b> mot handelspartnerne denne uken (I-44).` : ""}
      ${risk}</p>${oil}${gas}
    <div class="chips" id="kroneChips">${horizons.map(([h, l]) => `<button type="button" data-h="${h}">${l}</button>`).join("")}</div>
    <div id="kroneBars"></div>
    <p class="note">Positivt = valutaen har styrket seg mot kronen. Kilde: ECBs referansekurser.</p>`;
  el.querySelectorAll("#kroneChips button").forEach((b) => b.addEventListener("click", () => draw(b.dataset.h)));
  draw("w1");
}

/** Seksjon 3: tre ting å legge merke til – automatisk fra dataene. */
export function renderIdeas(countries, market) {
  const ideas = [];
  const withCurve = countries.filter((c) => c.curve);
  const solid = withCurve.filter(reliable);
  if (solid.length >= 2) {
    const by12 = [...solid].sort((a, b) => i12(a) - i12(b));
    const dove = by12[0], hawk = by12[by12.length - 1], gap = i12(hawk) - i12(dove);
    if (gap >= 25) {
      // Kontekst i vanlige setninger: hva er priset for neste møte, nylig vedtak, bankens eget anslag
      const context = (c, name) => {
        const nm = c.next_meeting, pc = c.policy_change, out = [];
        if (pc && pc.to > pc.from && daysUntil(pc.date) > -45) out.push(`${name} hevet nettopp (${shortDate(pc.date)}).`);
        // bp gjelder selve møtet (futures/OIS); bp_3m er det kurven priser innen 3 mnd, ikke for møtet
        if (nm?.bp != null) out.push(Math.abs(nm.bp) < 10
          ? `Bare ${pp(nm.bp)} er priset for ${out.length ? "møtet" : name + "s møte"} ${shortDate(nm.date)} – syklusen ligger lenger ut.`
          : `${pp(nm.bp)} er priset for ${out.length ? "møtet" : name + "s møte"} ${shortDate(nm.date)}.`);
        else if (nm?.bp_3m != null) out.push(Math.abs(nm.bp_3m) < 10
          ? `Kurven priser bare ${pp(nm.bp_3m)} innen 3 mnd (neste møte ${shortDate(nm.date)}) – syklusen ligger lenger ut.`
          : `Kurven priser ${pp(nm.bp_3m)} innen 3 mnd (neste møte ${shortDate(nm.date)}).`);
        if (c.cb_path) out.push(`${out.length ? "Banken" : name} sier selv ${rate(c.cb_path.level)} ${c.cb_path.horizon}.`);
        return out.join(" ");
      };
      ideas.push({ tag: "Størst sprik", text:
        `Markedet venter <b>${moves(i12(hawk))}</b> fra ${hawk.bank}, men bare <b>${moves(i12(dove))}</b> fra ${dove.bank}. Renteforskjellen
         ${hawk.currency}–${dove.currency} ventes altså å øke med ${nb2.format(gap / 100)} pp. ${context(hawk, hawk.bank)} ${context(dove, dove.bank)}
         Tror du markedet tar feil, er ${hawk.currency}/${dove.currency} paret å se på.` });
    }
    const rep = solid.filter((c) => c.curve.repricing?.w1 != null).sort((a, b) => Math.abs(b.curve.repricing.w1) - Math.abs(a.curve.repricing.w1));
    if (rep.length && Math.abs(rep[0].curve.repricing.w1) >= 8) {
      const r = rep[0].curve.repricing.w1;
      const m = rep[0].curve.repricing_detail?.m1;
      const month = m && m.delivered !== 0 ? ` Siste måned er renten ventet om 12 mnd ${pp(m.level)}, hvorav ${pp(m.delivered)} allerede er levert av banken.` : "";
      ideas.push({ tag: "I bevegelse", text: `Forventningene til <b>${rep[0].bank}</b> har flyttet seg mest siste uke: ${r > 0 ? "høyere" : "lavere"} rente
        ventet (${pp(r)}).${month} Slike skift smitter ofte over på valutaen – sjekk om ${rep[0].currency} har hengt med.` });
    }
    for (const c of withCurve) {
      // Det banken styrer etter: målvariabelen der vi har den (kjerne-PCE, trimmet gjennomsnitt, KPIF …), ellers samlet KPI
      const t = targetInflation(c), cpi = t.value;
      if (cpi == null) continue;
      const which = t.label && t.label !== "KPI" ? ` (${t.label})` : "";
      if (i12(c) <= -25 && cpi >= 3) ideas.push({ tag: "Kutt tross høy inflasjon", text: `Markedet venter <b>${moves(i12(c))}</b> fra ${c.bank} selv om
        inflasjonen${which} er ${nb1.format(cpi)} %. Faller ikke inflasjonen, kan kuttene forsvinne fra kursen – det ville støtte ${c.currency}.` });
      else if (i12(c) >= 25 && cpi <= 1.5) ideas.push({ tag: "Hevinger tross lav inflasjon", text: `Markedet venter <b>${moves(i12(c))}</b> fra ${c.bank} med en
        inflasjon${which} på bare ${nb1.format(cpi)} %. Uteblir hevingene, er ${c.currency} sårbar.` });
    }
  }
  // Heving levert, men kursen (målt mot handelspartnerne, I-44-justert) har falt. Hva banken
  // signaliserte leses ut av markedet: renten ventet om 12 mnd før og etter vedtaket.
  // Uten måling av forwardene rundt vedtaket (tone mangler) vet vi ikke hva banken signaliserte – da hoppes idéen over
  const delivered = countries.filter((c) => c.policy_change && c.policy_change.to > c.policy_change.from && c.policy_change.fx_since != null && c.policy_change.fx_since < 0
      && c.policy_change.tone && c.policy_change.path12_change_bp != null)
    .sort((a, b) => a.policy_change.fx_since - b.policy_change.fx_since);
  for (const c of delivered.slice(0, 1)) {
    const pc = c.policy_change;
    const carry = c.fwd_fx_1y && c.fwd_fx_1y.diff > 0 ? ` Renteforskjellen mot kronen er likevel ${signed(c.fwd_fx_1y.diff, nb2)} pp i ${c.currency}s favør.` : "";
    const head = `${c.bank} hevet til <b>${rate(pc.to)}</b> ${shortDate(pc.date)}, men ${c.currency} er <b>${pct1(pc.fx_since)}</b> mot handelspartnerne siden.`;
    if (pc.tone === "duete") ideas.push({ tag: "Duete heving", text: `${head} Markedet leste vedtaket som duete: renten ventet om 12 mnd falt
      ${nb2.format(Math.abs(pc.path12_change_bp) / 100)} pp gjennom vedtaket. Kursen fulgte signalet om pause, ikke hevingen.${carry}` });
    else if (pc.tone === "haukete") ideas.push({ tag: "Haukete heving, kurs ikke fulgt", text: `${head} Forwardene steg ${pp(pc.path12_change_bp)} gjennom vedtaket,
      så signalet var haukete – kursfallet handler om noe annet enn renten.${carry}` });
    else ideas.push({ tag: "Heving levert, kurs ikke fulgt", text: `${head} Forwardene flyttet seg bare ${pp(pc.path12_change_bp)}
      gjennom vedtaket: hevingen var alt i kursen – «selg på nyheten».${carry}` });
  }
  const carry = countries.filter((c) => c.fwd_fx_1y).sort((a, b) => b.fwd_fx_1y.diff - a.fwd_fx_1y.diff);
  if (carry.length >= 2) {
    const lo = carry[carry.length - 1];
    ideas.push({ tag: "Betalt for å vente", text: `Å eie kroner mot <b>${lo.currency}</b> gir ${nb2.format(-lo.fwd_fx_1y.diff)} prosentpoeng i året i renteforskjell.
      Kursen må gå ${nb2.format(Math.abs(lo.fwd_fx_1y.pct))} % mot deg før det spises opp – det er terminkursen ${nb2.format(lo.fwd_fx_1y.rate)}.` });
  }
  const crowded = countries.filter((c) => c.cot?.pct_oi != null && Math.abs(c.cot.pct_oi) >= 25).sort((a, b) => Math.abs(b.cot.pct_oi) - Math.abs(a.cot.pct_oi));
  if (crowded.length) {
    const c = crowded[0];
    const check = c.cot.unusual ? (c.cot.confirmed === true ? " Ukens sving er uvanlig stort, men finnes i alle CFTC-rapportene." : " Ukens sving er uvanlig stort og ikke bekreftet i de andre CFTC-rapportene.") : "";
    const funds = c.cot.lev_net != null ? ` Hedgefondene alene (TFF) er ${signed(c.cot.lev_net / 1000, nb1)}k kontrakter netto${c.cot.lev_pct_oi != null ? ` (${signed(c.cot.lev_pct_oi)} % av åpen interesse)` : ""}.` : "";
    ideas.push({ tag: "Alle på samme side", text: `Ikke-kommersielle aktører (spekulanter og kapitalforvaltere) er tungt <b>${c.cot.net > 0 ? "long" : "short"} ${c.currency}</b> (${signed(c.cot.pct_oi)} % av åpen
      interesse).${funds} Når alle sitter likt, blir reverseringene brå – særlig rundt rentemøtet ${shortDate(c.meeting)}.${check}` });
  }
  const shown = ideas.slice(0, 4);
  const words = ["Ingenting", "Én ting", "To ting", "Tre ting", "Fire ting"];
  const h = document.getElementById("ideasHeading");
  if (h) h.textContent = `${words[shown.length]} å legge merke til`;
  document.getElementById("ideas").innerHTML = shown.map((i, n) =>
    `<div class="idea"><div class="num">0${n + 1}</div><div><div class="tag">${i.tag}</div><p>${i.text}</p></div></div>`).join("")
    || `<p class="note">For lite data til å peke på noe ennå.</p>`;
}

/** Kildestatus i bunnteksten. */
export function renderSources(sources, updated) {
  const el = document.getElementById("sources");
  if (!el || !sources) return;
  const labels = { fx: "Valutakurser (ECB)", i44: "I-44 (Norges Bank)", policy: "Styringsrenter (BIS)", irlt: "10-års renter (OECD)",
    ir3: "3-mnd renter (OECD)", cpi: "KPI (OECD/Eurostat)", unemployment: "Ledighet (OECD/Eurostat)", brent: "Brent (FRED)", vix: "VIX (FRED)",
    cot: "COT (CFTC)", ppp: "PPP (World Bank)", cpi_core: "Kjerne-KPI (OECD/Eurostat)", ons_cpi: "KPI Storbritannia (ONS)", ssb_kpi_jae: "KPI-JAE (SSB)", scb_kpif: "KPIF (SCB)", pce_core: "Kjerne-PCE (FRED)", abs_trimmed: "Trimmet gjennomsnitt (ABS)", boc_core: "CPI-trim/median (BoC)",
    brent_fut: "Brent-futures (Yahoo)", ttf: "TTF-gass (Yahoo)", curve_us: "Kurve USD", curve_ea: "Kurve EUR", curve_jp: "Kurve JPY", curve_gb: "Kurve GBP",
    curve_ca: "Kurve CAD", curve_au: "Kurve AUD", curve_se: "Kurve SEK", curve_no: "Kurve NOK",
    curve_nz: "Kurve NZD", curve_ch: "Kurve CHF", tbill_jp: "Statsveksler JPY (JSDA, valgfri)",
    policy_no: "Styringsrente NOK (Norges Bank)", policy_se: "Styringsrente SEK (Riksbanken)", policy_ca: "Styringsrente CAD (BoC)",
    policy_ea: "Styringsrente EUR (ECB)", policy_us: "Styringsrente USD (FRED)", policy_gb: "Styringsrente GBP (BoE)",
    policy_au: "Styringsrente AUD (RBA)", policy_ch: "Styringsrente CHF (SNB)", policy_jp: "Styringsrente JPY (BIS + manuell)", policy_nz: "Styringsrente NZD (BIS + manuell)",
    cb_path_us: "Fed dot plot (SEP)", cb_path_no: "Norges Banks rentebane (PPR)", cb_path_se: "Riksbankens prognos", cb_path_nz: "RBNZ-bane (manuell)",
    futures_us: "Fed funds-futures (CME/Yahoo)", futures_au: "Cash rate-futures (ASX)", futures_ca: "CORRA-futures (TMX)", futures_nz: "Bankvekselfutures NZ (ASX)",
    manual_meetings: "Rentemøter (meetings.json)", manual_policy_overrides: "Registrerte vedtak (policy_overrides.json)",
    manual_meeting_odds: "Møteodds som reserve (meeting_odds.json)", manual_cb_paths: "Bankenes baner som reserve (cb_paths.json)" };
  const today = new Date(updated);
  const age = (iso) => (iso ? Math.round((today - new Date(iso.length === 4 ? `${iso}-12-31` : iso.length === 7 ? `${iso}-28` : iso)) / 86400000) : null);
  const limit = (k) => (k === "ppp" ? 800 : k.startsWith("cb_path_") ? 120 : k === "cot" || k === "policy_ch" ? 14 : ["irlt", "ir3", "cpi", "cpi_core", "ons_cpi", "ssb_kpi_jae", "scb_kpif", "pce_core", "abs_trimmed", "boc_core", "unemployment"].includes(k) ? 75 : 10);
  // Manuelle filer måles på gyldighet (ok/warn), ikke på alder
  const items = Object.entries(sources).map(([k, s]) => {
    const manual = k.startsWith("manual_");
    const a = age(s.latest);
    // Valgfrie kilder (s.optional) teller ikke som forsinket: feilen vises som merknad
    return { key: k, manual, optional: !!s.optional, label: labels[k] || k, ok: s.ok, latest: s.latest, error: s.error, warn: s.warn, note: s.note,
      valid: s.valid_until, stale: !s.optional && (!s.ok || !!s.warn || (!manual && (a == null || a > limit(k)))) };
  });
  const bad = items.filter((i) => i.stale);
  const line = (i) => `<li class="${i.stale ? "neg" : i.optional && !i.ok ? "muted" : ""}">${i.stale ? "⚠" : i.optional && !i.ok ? "–" : "✓"} ${i.label}: ${i.latest ?? "ingen data"}${i.ok ? "" : ` (feilet: ${i.error ?? "ukjent"})`}${i.warn ? ` (${i.warn})` : i.note ? ` <span class="muted">(${i.note})</span>` : ""}${i.valid ? ` <span class="muted">· gyldig til ${shortDate(i.valid)}</span>` : ""}</li>`;
  const auto = items.filter((i) => !i.manual), manual = items.filter((i) => i.manual);
  el.innerHTML = `<details class="more"><summary>Kildestatus: ${items.length - bad.length} av ${items.length} oppdatert${bad.length ? ` · <span class="neg">${bad.length} bak</span>` : ""}</summary>
    <ul class="sources">${auto.map(line).join("")}</ul>
    ${manual.length ? `<p class="note">Manuelt vedlikeholdt (dato = sist oppdatert):</p><ul class="sources">${manual.map(line).join("")}</ul>` : ""}</details>`;
}
