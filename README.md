# G10 Valutadashboard

Dashboard over G10-valutaene (USD, EUR, JPY, GBP, CHF, CAD, AUD, NZD, SEK, NOK) sett fra et norsk perspektiv. Per land vises:

- **Valutakurs mot NOK** med endring siste dag/uke/måned/3 mnd/år, realisert volatilitet og 1 års kursgraf (Norge vises som Norges Banks importveide kroneindeks I-44)
- **Renter**: styringsrente (BIS) med 2 års historikk-graf, 3-mnd pengemarkedsrente, 10-års statsrente og rentekurve-helning (OECD)
- **Inflasjon og arbeidsledighet**: siste KPI å/å og ledighetsrate (OECD)
- **PPP-verdivurdering**: over-/undervurdering mot USD basert på kjøpekraftsparitet (World Bank; Tyskland som proxy for eurosonen)
- **Spekulativ posisjonering (COT)**: netto non-commercial posisjon fra CFTC per valuta-future (ukentlig; finnes ikke for NOK/SEK)
- **Neste rentemøte** per sentralbank (fra [data/meetings.json](data/meetings.json))
- **Retningssignal**: en enkel heuristikk basert på rentedifferanse (3 mnd minus styringsrente), kursmomentum og realrente – *ikke* en prognose eller investeringsråd

Øverst på siden ligger en oversiktsseksjon med:

- **Toppmovers**: sterkeste og svakeste valuta mot NOK siste uke
- **Sammenligningsgraf**: alle valutaene mot NOK, rebasert til 100 for ett år siden
- **Risikobarometer**: AUD/JPY, VIX og Brent-olje (med 90-dagers korrelasjon olje↔krone)
- **Rentedifferanse-tabell**: hvert lands renter minus de norske

## Slik virker det

- [scripts/fetch_data.py](scripts/fetch_data.py) henter data fra gratis API-er (Frankfurter/ECB, Norges Bank, BIS, OECD – ingen nøkler) og skriver `data/dashboard.json` og `data/history.json`.
- GitHub Actions ([.github/workflows/update.yml](.github/workflows/update.yml)) kjører skriptet hver ukedag kl. 06:45 UTC, committer nye data og publiserer siden til GitHub Pages. Alt skjer i skyen – ingen lokal maskin trengs.
- Frontenden er statisk HTML/CSS/JS med [Chart.js](https://www.chartjs.org/) fra CDN.

## Manuelt vedlikehold

Rentemøtedatoene i [data/meetings.json](data/meetings.json) må oppdateres når sentralbankene publiserer neste års kalender (typisk én gang i året). Datoer i fortiden ignoreres automatisk.

## Kjør lokalt

```bash
python3 scripts/fetch_data.py   # hent ferske data
python3 -m http.server 8000     # åpne http://localhost:8000
```
