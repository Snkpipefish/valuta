#!/usr/bin/env python3
"""Feiler (exit 1) hvis en kilde i data/dashboard.json er for gammel. Kjøres etter publisering
i GitHub Actions, så en rød kjøring fungerer som varsel uten å stoppe oppdateringen."""
import json
import sys
from datetime import date
from pathlib import Path

MONTHLY = {"irlt", "ir3", "cpi", "cpi_core", "ons_cpi", "ssb_kpi_jae", "scb_kpif", "pce_core", "abs_trimmed", "boc_core", "unemployment", "ppp"}
LIMITS = {"cot": 14, "ppp": 800, "policy_ch": 14,  # ukentlig / årlig med 1–2 års etterslep / SNB publiserer ukentlig
          **{f"cb_path_{c}": 120 for c in ("us", "no", "se", "nz")}}  # kvartalsvise rapporter
DEFAULT_DAYS, MONTHLY_DAYS = 10, 75


def age_days(period):
    if not period:
        return None
    if len(period) == 4:  # YYYY: årsdata
        period += "-12-31"
    elif len(period) == 7:  # YYYY-MM: regn fra månedsslutt-ish
        period += "-28"
    return (date.today() - date.fromisoformat(period)).days


def main():
    sources = json.loads((Path(__file__).resolve().parent.parent / "data" / "dashboard.json").read_text()).get("sources", {})
    stale, notes = [], []
    for name, st in sources.items():
        limit = LIMITS.get(name, MONTHLY_DAYS if name in MONTHLY else DEFAULT_DAYS)
        age = age_days(st.get("latest"))
        if name.startswith("manual_"):  # manuelle filer: gyldighet ligger i ok/warn, ikke i alder
            if not st.get("ok"):
                stale.append(f"{name}: {st.get('error')}")
            if st.get("warn"):
                notes.append(f"{name}: {st['warn']}")
            continue
        if st.get("optional"):  # valgfri kilde (f.eks. JSDA): feil er merknad, ikke forsinkelse
            if not st.get("ok") or age is None or age > limit:
                notes.append(f"{name}: valgfri, {'siste henting feilet: ' + str(st.get('error')) if not st.get('ok') else f'nyeste {st.get('latest')}'}")
            continue
        if age is None or age > limit:
            stale.append(f"{name}: nyeste {st.get('latest')} ({age} dager, grense {limit}){'' if st.get('ok') else ' – siste henting feilet: ' + str(st.get('error'))}")
        if st.get("warn"):  # f.eks. «ubekreftet etter møtet»: vises, men gir ikke rød kjøring
            notes.append(f"{name}: {st['warn']}")
    if notes:
        print("MERKNADER:\n  " + "\n  ".join(notes))
    if stale:
        print("GAMLE KILDER:\n  " + "\n  ".join(stale))
        sys.exit(1)
    print(f"Alle {len(sources)} kilder er ferske.")


if __name__ == "__main__":
    main()
