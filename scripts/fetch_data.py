#!/usr/bin/env python3
"""Henter markedsdata for G10-landene og skriver data/dashboard.json + data/history.json.

Kilder (alle gratis, uten API-nøkkel):
  - Valutakurser:      Frankfurter (ECB-referansekurser)
  - I-44 kroneindeks:  Norges Bank
  - Styringsrenter:    BIS (WS_CBPOL)
  - 10-års og 3-mnd:   OECD (DSD_STES@DF_FINMARK)
  - KPI å/å:           OECD (DSD_PRICES@DF_PRICES_ALL, Japan via DF_G20_PRICES)
  - Arbeidsledighet:   OECD (DSD_LFS@DF_IALFS_UNE_M)
  - Brent og VIX:      FRED (offentlig fredgraph.csv, uten nøkkel)
  - COT-posisjonering: CFTC Socrata (legacy futures-only, datasett 6dca-aqww;
                       samme kilde som bedrock-prosjektets cot_cftc-modul)
  - PPP (kjøpekraft):  World Bank (PA.NUS.PPP; Tyskland som proxy for eurosonen)

Kjøres uten argumenter. Feiler én kilde beholdes forrige verdi fra eksisterende
JSON-filer, slik at en enkelt nede-tjeneste ikke velter hele oppdateringen.
"""

import csv
import io
import json
import math
import sys
import time
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"

COUNTRIES = [
    {"id": "us", "name": "USA", "currency": "USD", "bank": "Federal Reserve", "flag": "🇺🇸", "bis": "US", "oecd": "USA"},
    {"id": "ea", "name": "Eurosonen", "currency": "EUR", "bank": "ECB", "flag": "🇪🇺", "bis": "XM", "oecd": "EA20"},
    {"id": "jp", "name": "Japan", "currency": "JPY", "bank": "Bank of Japan", "flag": "🇯🇵", "bis": "JP", "oecd": "JPN", "per": 100},
    {"id": "gb", "name": "Storbritannia", "currency": "GBP", "bank": "Bank of England", "flag": "🇬🇧", "bis": "GB", "oecd": "GBR"},
    {"id": "ch", "name": "Sveits", "currency": "CHF", "bank": "Swiss National Bank", "flag": "🇨🇭", "bis": "CH", "oecd": "CHE"},
    {"id": "ca", "name": "Canada", "currency": "CAD", "bank": "Bank of Canada", "flag": "🇨🇦", "bis": "CA", "oecd": "CAN"},
    {"id": "au", "name": "Australia", "currency": "AUD", "bank": "Reserve Bank of Australia", "flag": "🇦🇺", "bis": "AU", "oecd": "AUS"},
    {"id": "nz", "name": "New Zealand", "currency": "NZD", "bank": "Reserve Bank of New Zealand", "flag": "🇳🇿", "bis": "NZ", "oecd": "NZL", "cpi_freq": "Q"},
    {"id": "se", "name": "Sverige", "currency": "SEK", "bank": "Riksbanken", "flag": "🇸🇪", "bis": "SE", "oecd": "SWE"},
    {"id": "no", "name": "Norge", "currency": "NOK", "bank": "Norges Bank", "flag": "🇳🇴", "bis": "NO", "oecd": "NOR"},
]

OECD_BASE = "https://sdmx.oecd.org/public/rest/data"

# CFTC-kontraktnavn per land (legacy futures-only). NOK/SEK har ingen
# likvide futures og mangler derfor COT-data.
COT_CONTRACTS = {
    "us": "USD INDEX",
    "ea": "EURO FX",
    "jp": "JAPANESE YEN",
    "gb": "BRITISH POUND",
    "ch": "SWISS FRANC",
    "ca": "CANADIAN DOLLAR",
    "au": "AUSTRALIAN DOLLAR",
    "nz": "NZ DOLLAR",
}

# World Bank-koder for PPP. Eurosonen mangler i World Bank; Tyskland brukes som proxy.
PPP_ISO = {"us": "USA", "ea": "DEU", "jp": "JPN", "gb": "GBR", "ch": "CHE",
           "ca": "CAN", "au": "AUS", "nz": "NZL", "se": "SWE", "no": "NOR"}


def fetch(url, timeout=60, attempts=4):
    # Accept-headeren er nødvendig: FRED (Akamai) lar forespørsler uten den henge til timeout
    req = urllib.request.Request(url, headers={"User-Agent": "valuta-dashboard/1.0", "Accept": "*/*"})
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read().decode("utf-8")
        except Exception:
            if attempt == attempts - 1:
                raise
            time.sleep(5 * (attempt + 1))


def to_float(value):
    """Tallverdi eller None – filtrerer bort NaN/inf som ville gitt ugyldig JSON."""
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def fetch_fx_history():
    """1 års daglig historikk: verdien av 1 enhet av hver valuta i NOK."""
    end = date.today()
    start = end - timedelta(days=370)
    symbols = ",".join(c["currency"] for c in COUNTRIES if c["currency"] != "NOK")
    url = f"https://api.frankfurter.dev/v1/{start}..{end}?base=NOK&symbols={symbols}"
    raw = json.loads(fetch(url))
    series = {}
    for day, rates in sorted(raw["rates"].items()):
        for cur, val in rates.items():
            if val:
                series.setdefault(cur, {})[day] = round(1.0 / val, 5)
    return series


def fetch_i44_history():
    """Norges Banks importveide kroneindeks (I-44). Lavere = sterkere krone."""
    start = date.today() - timedelta(days=370)
    url = (
        "https://data.norges-bank.no/api/data/EXR/B.I44.NOK.SP"
        f"?startPeriod={start}&format=csv"
    )
    raw = fetch(url)
    series = {}
    for row in csv.DictReader(io.StringIO(raw), delimiter=";"):
        value = to_float(row.get("OBS_VALUE"))
        if value is not None:
            series[row["TIME_PERIOD"]] = value
    return series


def fetch_policy_rates():
    """Styringsrenter fra BIS med 2 års historikk for trend."""
    start = date.today() - timedelta(days=730)
    areas = "+".join(c["bis"] for c in COUNTRIES)
    url = (
        f"https://stats.bis.org/api/v2/data/dataflow/BIS/WS_CBPOL/1.0/D.{areas}"
        f"?startPeriod={start}&format=csv"
    )
    raw = fetch(url, timeout=120)
    series = {}
    for row in csv.DictReader(io.StringIO(raw)):
        area, period = row.get("REF_AREA"), row.get("TIME_PERIOD")
        value = to_float(row.get("OBS_VALUE"))
        if area and period and value is not None:
            series.setdefault(area, {})[period] = value
    return series


def fetch_oecd_rates(measure):
    """Månedlige renter fra OECD: IRLT (10 år) eller IR3TIB (3 mnd)."""
    start = date.today() - timedelta(days=430)
    areas = "+".join(c["oecd"] for c in COUNTRIES)
    url = (
        f"{OECD_BASE}/OECD.SDD.STES,DSD_STES@DF_FINMARK,4.0/"
        f"{areas}.M.{measure}.PA.....?startPeriod={start:%Y-%m}&format=csvfilewithlabels"
    )
    raw = fetch(url, timeout=120)
    series = {}
    for row in csv.DictReader(io.StringIO(raw)):
        area, period = row.get("REF_AREA"), row.get("TIME_PERIOD")
        value = to_float(row.get("OBS_VALUE"))
        if area and period and value is not None:
            series.setdefault(area, {})[period] = value
    return series


def fetch_cpi():
    """KPI å/å per land. Japan ligger kun i G20-dataflyten, New Zealand er kvartalsvis."""
    start = date.today() - timedelta(days=430)
    result = {}
    monthly = [c["oecd"] for c in COUNTRIES if c["oecd"] != "JPN" and c.get("cpi_freq") != "Q"]
    queries = [
        ("DSD_PRICES@DF_PRICES_ALL,1.0", "+".join(monthly), "M"),
        ("DSD_PRICES@DF_PRICES_ALL,1.0", "NZL", "Q"),
        ("DSD_G20_PRICES@DF_G20_PRICES,1.0", "JPN", "M"),
    ]
    for flow, areas, freq in queries:
        url = (
            f"{OECD_BASE}/OECD.SDD.TPS,{flow}/"
            f"{areas}.{freq}.N.CPI.PA._T.N.GY?startPeriod={start:%Y-%m}&format=csvfilewithlabels"
        )
        try:
            raw = fetch(url, timeout=120)
        except Exception as exc:  # én delspørring skal ikke velte resten
            print(f"  ADVARSEL: KPI-spørring feilet for {areas}: {exc}", file=sys.stderr)
            continue
        for row in csv.DictReader(io.StringIO(raw)):
            area, period = row.get("REF_AREA"), row.get("TIME_PERIOD")
            value = to_float(row.get("OBS_VALUE"))
            if area and period and value is not None:
                result.setdefault(area, {})[period] = value
    return result


def fetch_fred_series(series_id):
    """Daglig serie fra FREDs offentlige CSV-endepunkt (Brent, VIX)."""
    start = date.today() - timedelta(days=400)
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}&cosd={start}"
    raw = fetch(url, timeout=120)
    series = {}
    for row in csv.DictReader(io.StringIO(raw)):
        value = to_float(row.get(series_id))
        if value is not None:
            series[row["observation_date"]] = value
    return series


def fetch_cot():
    """Netto spekulativ posisjonering (non-commercial) fra CFTC, ukentlig 1 år.

    Samme Socrata-datasett som bedrock-prosjektet bruker (6dca-aqww, legacy
    futures-only). Netto = long − short; lagres sammen med open interest.
    """
    start = date.today() - timedelta(days=400)
    contracts = "','".join(COT_CONTRACTS.values())
    query = urllib.parse.urlencode({
        "$select": "report_date_as_yyyy_mm_dd,contract_market_name,"
                   "noncomm_positions_long_all,noncomm_positions_short_all,open_interest_all",
        "$where": f"contract_market_name in('{contracts}') "
                  f"AND report_date_as_yyyy_mm_dd >= '{start}'",
        "$order": "report_date_as_yyyy_mm_dd ASC",
        "$limit": "5000",
    })
    raw = fetch(f"https://publicreporting.cftc.gov/resource/6dca-aqww.json?{query}", timeout=120)
    by_contract = {}
    for row in json.loads(raw):
        long_ = to_float(row.get("noncomm_positions_long_all"))
        short = to_float(row.get("noncomm_positions_short_all"))
        oi = to_float(row.get("open_interest_all"))
        if long_ is None or short is None:
            continue
        day = row["report_date_as_yyyy_mm_dd"][:10]
        by_contract.setdefault(row["contract_market_name"], {})[day] = {
            "net": int(long_ - short),
            "oi": int(oi) if oi else None,
        }
    return by_contract


def fetch_ppp():
    """PPP-kurs (lokal valuta per internasjonal dollar) fra World Bank, siste år."""
    isos = ";".join(sorted(set(PPP_ISO.values())))
    year = date.today().year
    url = (
        f"https://api.worldbank.org/v2/country/{isos}/indicator/PA.NUS.PPP"
        f"?format=json&date={year - 5}:{year}&per_page=300"
    )
    raw = json.loads(fetch(url).encode().decode("utf-8-sig"))
    latest_by_iso = {}
    for row in raw[1] or []:
        value = to_float(row.get("value"))
        if value is None:
            continue
        iso = row["countryiso3code"]
        if iso not in latest_by_iso or row["date"] > latest_by_iso[iso][0]:
            latest_by_iso[iso] = (row["date"], value)
    return latest_by_iso


def fetch_unemployment():
    """Arbeidsledighetsrate (sesongjustert) fra OECD.

    Sveits/New Zealand publiserer kun kvartalsvis; eurosonen mangler helt hos
    OECD og hentes fra Eurostat (geo-kode EA21) i stedet.
    """
    start = date.today() - timedelta(days=430)
    series = {}
    monthly = "+".join(c["oecd"] for c in COUNTRIES if c["oecd"] not in ("CHE", "NZL", "EA20"))
    for areas, freq in [(monthly, "M"), ("CHE+NZL", "Q")]:
        url = (
            f"{OECD_BASE}/OECD.SDD.TPS,DSD_LFS@DF_IALFS_UNE_M,1.0/"
            f"{areas}.UNE_LF_M...Y._T.Y_GE15..{freq}?startPeriod={start:%Y-%m}&format=csvfilewithlabels"
        )
        try:
            raw = fetch(url, timeout=120)
        except Exception as exc:
            print(f"  ADVARSEL: ledighet feilet for {areas}: {exc}", file=sys.stderr)
            continue
        for row in csv.DictReader(io.StringIO(raw)):
            area, period = row.get("REF_AREA"), row.get("TIME_PERIOD")
            value = to_float(row.get("OBS_VALUE"))
            if area and period and value is not None:
                series.setdefault(area, {})[period] = value

    try:
        raw = fetch(
            "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/une_rt_m"
            "?format=JSON&geo=EA21&s_adj=SA&age=TOTAL&sex=T&unit=PC_ACT&lastTimePeriod=3"
        )
        data = json.loads(raw)
        periods = {v: k for k, v in data["dimension"]["time"]["category"]["index"].items()}
        # Lagres under OECD-koden EA20 slik at oppslaget i main() treffer
        series["EA20"] = {periods[int(i)]: v for i, v in data["value"].items()}
    except Exception as exc:
        print(f"  ADVARSEL: Eurostat-ledighet feilet: {exc}", file=sys.stderr)
    return series


def realized_vol(series, window=30):
    """Annualisert realisert volatilitet (%) fra daglige logavkastninger."""
    values = [v for _, v in sorted(series.items())][-(window + 1):]
    if len(values) < window // 2:
        return None
    returns = [math.log(b / a) for a, b in zip(values, values[1:]) if a > 0 and b > 0]
    if len(returns) < 2:
        return None
    mean = sum(returns) / len(returns)
    variance = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)
    return round(math.sqrt(variance) * math.sqrt(252) * 100, 1)


def correlation(series_a, series_b, window=90):
    """Pearson-korrelasjon mellom daglige avkastninger på felles datoer."""
    common = sorted(set(series_a) & set(series_b))[-(window + 1):]
    if len(common) < 20:
        return None
    ra = [series_a[b] / series_a[a] - 1 for a, b in zip(common, common[1:])]
    rb = [series_b[b] / series_b[a] - 1 for a, b in zip(common, common[1:])]
    n = len(ra)
    ma, mb = sum(ra) / n, sum(rb) / n
    cov = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    var_a = sum((x - ma) ** 2 for x in ra)
    var_b = sum((y - mb) ** 2 for y in rb)
    if var_a == 0 or var_b == 0:
        return None
    return round(cov / math.sqrt(var_a * var_b), 2)


def latest(series):
    """(periode, verdi) for siste observasjon i en {periode: verdi}-dict."""
    if not series:
        return None, None
    period = max(series)
    return period, series[period]


def value_at_or_before(series, target_day):
    """Siste verdi på eller før en gitt dato (håndterer helger/helligdager)."""
    candidates = [d for d in series if d <= target_day]
    return series[max(candidates)] if candidates else None


def pct_change(series, days):
    day, value = latest(series)
    if not day:
        return None
    past = value_at_or_before(series, str(date.fromisoformat(day) - timedelta(days=days)))
    if not past:
        return None
    return round((value / past - 1) * 100, 2)


def load_existing(path):
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def main():
    DATA_DIR.mkdir(exist_ok=True)
    dashboard_path = DATA_DIR / "dashboard.json"
    history_path = DATA_DIR / "history.json"
    old_dashboard = {c["id"]: c for c in load_existing(dashboard_path).get("countries", [])}
    old_history = load_existing(history_path)

    sources = {}
    for name, fn in [
        ("fx", fetch_fx_history),
        ("i44", fetch_i44_history),
        ("policy", fetch_policy_rates),
        ("irlt", lambda: fetch_oecd_rates("IRLT")),
        ("ir3", lambda: fetch_oecd_rates("IR3TIB")),
        ("cpi", fetch_cpi),
        ("unemployment", fetch_unemployment),
        ("brent", lambda: fetch_fred_series("DCOILBRENTEU")),
        ("vix", lambda: fetch_fred_series("VIXCLS")),
        ("cot", fetch_cot),
        ("ppp", fetch_ppp),
    ]:
        print(f"Henter {name} ...")
        try:
            sources[name] = fn()
        except Exception as exc:
            print(f"  ADVARSEL: {name} feilet ({exc}) – beholder forrige data", file=sys.stderr)
            sources[name] = None

    meetings = load_existing(DATA_DIR / "meetings.json")
    today = str(date.today())

    # USD-kryss trengs for PPP-verdivurdering (lokal valuta per USD)
    usd_nok = (sources["fx"] or {}).get("USD") or old_history.get("fx", {}).get("USD", {})
    _, usd_nok_last = latest(usd_nok)

    countries = []
    history = {"fx": {}, "policy": {}, "cot": {}, "market": {}}
    for c in COUNTRIES:
        cur, per = c["currency"], c.get("per", 1)
        old = old_dashboard.get(c["id"], {})

        # Valutakurs: NOK-verdi per enhet (Norge bruker I-44-indeksen)
        if cur == "NOK":
            fx_series = sources["i44"] or old_history.get("fx", {}).get("I44", {})
            fx_key, invert = "I44", True
        else:
            fx_series = (sources["fx"] or {}).get(cur) or old_history.get("fx", {}).get(cur, {})
            fx_key, invert = cur, False
        fx_day, fx_value = latest(fx_series)
        fx = old.get("fx")
        if fx_day:
            fx = {
                "value": round(fx_value * per, 4),
                "per": per,
                "date": fx_day,
                "index": invert,  # I-44: lavere indeks = sterkere valuta
                "changes": {
                    "d1": pct_change(fx_series, 1),
                    "w1": pct_change(fx_series, 7),
                    "m1": pct_change(fx_series, 30),
                    "m3": pct_change(fx_series, 91),
                    "y1": pct_change(fx_series, 365),
                },
            }
        history["fx"][fx_key] = fx_series

        # Renter
        policy_series = (sources["policy"] or {}).get(c["bis"]) or old_history.get("policy", {}).get(c["bis"], {})
        policy_day, policy = latest(policy_series)
        history["policy"][c["bis"]] = policy_series
        _, y10 = latest((sources["irlt"] or {}).get(c["oecd"], {}))
        _, m3 = latest((sources["ir3"] or {}).get(c["oecd"], {}))
        old_rates = old.get("rates", {})
        rates = {
            "policy": policy if policy is not None else old_rates.get("policy"),
            "policy_date": policy_day or old_rates.get("policy_date"),
            "m3": m3 if m3 is not None else old_rates.get("m3"),
            "y10": y10 if y10 is not None else old_rates.get("y10"),
        }

        # Endring i styringsrente siste 6 mnd (til retningsindikatoren)
        if policy_series and policy_day:
            past = value_at_or_before(policy_series, str(date.fromisoformat(policy_day) - timedelta(days=182)))
            rates["policy_6m_change"] = round(policy - past, 3) if past is not None else None

        # Inflasjon
        cpi_period, cpi_value = latest((sources["cpi"] or {}).get(c["oecd"], {}))
        cpi = {"value": cpi_value, "period": cpi_period} if cpi_period else old.get("cpi")

        # Arbeidsledighet
        une_period, une_value = latest((sources["unemployment"] or {}).get(c["oecd"], {}))
        unemployment = {"value": une_value, "period": une_period} if une_period else old.get("unemployment")

        # PPP-verdivurdering: + = valutaen er dyr mot USD ift. kjøpekraft, − = billig
        ppp = old.get("ppp")
        ppp_entry = (sources["ppp"] or {}).get(PPP_ISO[c["id"]])
        if ppp_entry and usd_nok_last and (fx or cur == "NOK"):
            year, ppp_rate = ppp_entry
            if cur == "NOK":
                market_vs_usd = usd_nok_last
            else:
                cur_nok = fx["value"] / per if fx else None
                market_vs_usd = usd_nok_last / cur_nok if cur_nok else None
            if market_vs_usd:
                ppp = {
                    "rate": ppp_rate,
                    "year": year,
                    "valuation": None if cur == "USD" else round((ppp_rate / market_vs_usd - 1) * 100, 1),
                    "proxy": "Tyskland" if c["id"] == "ea" else None,
                }

        # COT: netto spekulativ posisjonering (ukentlig)
        cot = old.get("cot")
        contract = COT_CONTRACTS.get(c["id"])
        cot_series = (sources["cot"] or {}).get(contract) if contract else None
        if not cot_series and contract:
            cot_series = old_history.get("cot", {}).get(cur)
        if cot_series:
            days = sorted(cot_series)
            last, prev = cot_series[days[-1]], cot_series[days[-2]] if len(days) > 1 else None
            cot = {
                "net": last["net"],
                "change_w": last["net"] - prev["net"] if prev else None,
                "pct_oi": round(last["net"] / last["oi"] * 100, 1) if last.get("oi") else None,
                "date": days[-1],
            }
            history["cot"][cur] = cot_series

        # Neste rentemøte fra den statiske kalenderen
        upcoming = [d for d in meetings.get(c["id"], []) if d >= today]
        countries.append({
            **{k: c[k] for k in ("id", "name", "currency", "bank", "flag")},
            "fx": fx,
            "rates": rates,
            "cpi": cpi,
            "unemployment": unemployment,
            "ppp": ppp,
            "cot": cot,
            "vol30": realized_vol(fx_series) if fx_series else None,
            "meeting": min(upcoming) if upcoming else None,
        })

    # Markedsindikatorer på tvers av landene
    fx_all = sources["fx"] or old_history.get("fx", {})
    brent = sources["brent"] or old_history.get("market", {}).get("brent", {})
    vix = sources["vix"] or old_history.get("market", {}).get("vix", {})
    audjpy = {}
    aud, jpy = fx_all.get("AUD", {}), fx_all.get("JPY", {})
    for day in sorted(set(aud) & set(jpy)):
        if jpy[day]:
            audjpy[day] = round(aud[day] / jpy[day], 3)
    history["market"] = {"brent": brent, "vix": vix, "audjpy": audjpy}

    def snapshot(series, decimals=2):
        day, value = latest(series)
        if not day:
            return None
        return {
            "value": round(value, decimals),
            "date": day,
            "changes": {"d1": pct_change(series, 1), "w1": pct_change(series, 7),
                        "m1": pct_change(series, 30), "y1": pct_change(series, 365)},
        }

    # Oljekorrelasjon for NOK: daglige avkastninger Brent vs. kronestyrke (invertert I-44)
    i44 = history["fx"].get("I44", {})
    nok_strength = {d: 1 / v for d, v in i44.items() if v}
    market = {
        "brent": snapshot(brent),
        "vix": snapshot(vix),
        "audjpy": snapshot(audjpy, 3),
        "brent_nok_corr": correlation(brent, nok_strength),
    }

    dashboard_path.write_text(json.dumps(
        {"updated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
         "countries": countries, "market": market},
        ensure_ascii=False, indent=1, allow_nan=False))
    history_path.write_text(json.dumps(history, ensure_ascii=False, allow_nan=False))
    print(f"Skrev {dashboard_path} og {history_path}")


if __name__ == "__main__":
    main()
