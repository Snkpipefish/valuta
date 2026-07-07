# G10 Valutadashboard

Dashboard over G10-valutaene (USD, EUR, JPY, GBP, CHF, CAD, AUD, NZD, SEK, NOK) sett fra et norsk perspektiv. Per land vises:

- **Valutakurs mot NOK** med endring siste dag/uke/måned/3 mnd/år og 1 års kursgraf (Norge vises som Norges Banks importveide kroneindeks I-44)
- **Renter**: styringsrente (BIS), 3-mnd pengemarkedsrente og 10-års statsrente (OECD)
- **Inflasjon**: siste KPI å/å (OECD)
- **Neste rentemøte** per sentralbank (fra [data/meetings.json](data/meetings.json))
- **Retningssignal**: en enkel heuristikk basert på rentedifferanse (3 mnd minus styringsrente), kursmomentum og realrente – *ikke* en prognose eller investeringsråd

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
