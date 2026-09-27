"""Tester for beregningene i scripts/fetch_data.py (kjør: python3 -m unittest discover tests)."""
import importlib.util
import json
import io
import unittest
import zipfile
from pathlib import Path

spec = importlib.util.spec_from_file_location("fetch_data", Path(__file__).resolve().parent.parent / "scripts" / "fetch_data.py")
fd = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fd)


class CurveMetricsTest(unittest.TestCase):
    def test_flat_curve_prices_no_change(self):
        m = fd.curve_metrics({"0.25": 4.0, "1": 4.0, "2": 4.0, "5": 4.0}, 4.0)
        self.assertEqual(m["implied"], {"3m": 0, "6m": 0, "12m": 0, "24m": 0})
        self.assertTrue(all(abs(p - 4.0) < 1e-9 for p in m["path"]))
        self.assertFalse(m["synthetic_anchor"])

    def test_steep_curve_prices_hikes(self):
        m = fd.curve_metrics({"0.25": 4.0, "0.5": 4.25, "1": 4.5, "2": 5.0}, 4.0)
        self.assertGreater(m["implied"]["6m"], 0)
        self.assertGreater(m["implied"]["12m"], m["implied"]["6m"])
        self.assertEqual(m["extreme"]["bp"], round((max(m["path"]) - m["path"][0]) * 100))

    def test_basis_cancels_out(self):
        """Et konstant påslag mellom statspapirer og styringsrente skal ikke gi priset endring."""
        m = fd.curve_metrics({"0.25": 4.4, "1": 4.4, "2": 4.4}, 4.0)
        self.assertEqual(m["implied"]["12m"], 0)
        self.assertEqual(m["path"][0], 4.0)

    def test_synthetic_anchor_when_short_end_missing(self):
        m = fd.curve_metrics({"1": 1.6, "2": 1.9, "5": 2.4, "10": 3.0}, 1.0)
        self.assertTrue(m["synthetic_anchor"])
        self.assertGreater(m["implied"]["12m"], 0)

    def test_pchip_gives_monotone_front_where_linear_kinks(self):
        """SEK 24. sep 2026: 6-mnd-vekselen ligger høyt mot 3 mnd og 2 år. Lineær spot ga 3 mnd-terminen
        om 3 mnd (2,37) over den om 6 mnd (2,32); glatt spot gir stigende bane i front."""
        pts = {"0.25": 1.908, "0.5": 2.234, "2": 2.79, "5": 3.088, "10": 3.252}
        m = fd.curve_metrics(pts, 1.75, 0.188)
        front = m["path"][:9]
        self.assertTrue(all(b >= a for a, b in zip(front, front[1:])), front)
        self.assertAlmostEqual(m["path"][3], 2.372, places=3)  # knutepunktene er uendret
        # Interpolanten går gjennom punktene og er monoton mellom dem
        sorted_pts = sorted((float(t), v) for t, v in pts.items())
        for t, v in sorted_pts:
            self.assertAlmostEqual(fd.spot_rate(sorted_pts, t), v)
        self.assertTrue(2.234 < fd.spot_rate(sorted_pts, 1.0) < 2.79)
        self.assertEqual(fd.spot_rate([(0.25, 4.0), (2, 5.0)], 1.0), 4.0 + (1.0 - 0.25) / 1.75)  # to punkter: lineært

    def test_rejects_too_sparse_curves(self):
        self.assertIsNone(fd.curve_metrics({"2": 4.0, "10": 4.5}, 4.0))
        self.assertIsNone(fd.curve_metrics({"0.25": 4.0, "0.5": 4.0, "1": 4.0}, 4.0))
        self.assertIsNone(fd.curve_metrics({"0.25": 4.0, "1": 4.0, "2": 4.0}, None))


class HelpersTest(unittest.TestCase):
    def test_rate_at_tenor_interpolates(self):
        pts = {"0.5": 2.0, "2": 4.0}
        self.assertAlmostEqual(fd.rate_at_tenor(pts, 1), 2 + 2 * (0.5 / 1.5))
        self.assertEqual(fd.rate_at_tenor(pts, 0.1), 2.0)
        self.assertEqual(fd.rate_at_tenor(pts, 9), 4.0)
        self.assertIsNone(fd.rate_at_tenor({}, 1))

    def test_build_curve_uses_latest_complete_day(self):
        series = {
            "2026-09-23": {"0.25": 4.0, "1": 4.2, "2": 4.4, "5": 4.5},
            "2026-09-24": {"2": 4.4, "5": 4.5},  # korte punkter mangler
        }
        curve = fd.build_curve("no", series, {"2026-09-01": 4.0})
        self.assertEqual(curve["date"], "2026-09-23")
        self.assertIn("path_w1", curve)

    def test_newest_date(self):
        self.assertEqual(fd.newest_date({"a": {"2026-01-05": 1, "2026-02": 2}, "b": [{"2025-12-31": 3}]}), "2026-02")
        self.assertIsNone(fd.newest_date({"x": 1}))
        self.assertEqual(fd.newest_date({"2025-01-01": ("2023", 1.2)}), "2025-01-01")  # PPP: (år, verdi) teller ikke over nøkkelen
        # Futures: kontraktsperioder peker fremover; observasjonsdagen er nyeste dato
        self.assertEqual(fd.newest_date({"2026-09-25": [["2026-10-01", "2026-10-31", 4.0], ["2028-01-01", "2028-01-31", 4.2]]}), "2026-09-25")

    def test_xlsx_sheet_rows_minimal_workbook(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("xl/workbook.xml", '<workbook><sheets><sheet name="Data" sheetId="1" r:id="rId1"/></sheets></workbook>')
            z.writestr("xl/_rels/workbook.xml.rels", '<Relationships><Relationship Id="rId1" Type="ws" Target="worksheets/sheet1.xml"/></Relationships>')
            z.writestr("xl/sharedStrings.xml", "<sst><si><t>months:</t></si></sst>")
            z.writestr("xl/worksheets/sheet1.xml",
                       '<worksheet><sheetData><row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1"><f>1/12</f><v>1</v></c></row>'
                       '<row r="2"><c r="A2"><v>46266</v></c><c r="B2"><v>3.5</v></c><c r="C2" t="e"><v>#VALUE!</v></c></row></sheetData></worksheet>')
        rows = fd.xlsx_sheet_rows(buf.getvalue(), "data")
        self.assertEqual(rows[0], (1, {"A": "months:", "B": 1.0}))
        self.assertEqual(rows[1], (2, {"A": 46266.0, "B": 3.5, "C": None}))
        self.assertEqual(fd.excel_date(46266), "2026-09-01")


class MarketAnchorTest(unittest.TestCase):
    """Banen ankres på markedets 3-mnd-rente minus basis, ikke på styringsrenten."""

    def hike_fixture(self):
        # Uke før vedtak: 3 mnd-renten priser en fullt ventet heving (4,00 → 4,25) om en uke.
        # Terminrentene lenger ut er identiske før og etter; bare styringsrenten og fronten flytter.
        # Vinteren/våren: ingen heving priset, veksel 5 bp over styringsrenten (normal basis).
        calm = {"0.25": 4.05, "0.5": 4.10, "1": 4.20, "2": 4.40, "5": 4.50}
        before = {"0.25": 4.23, "0.5": 4.30, "1": 4.40, "2": 4.60, "5": 4.70}
        after = {"0.25": 4.25, "0.5": 4.30, "1": 4.40, "2": 4.60, "5": 4.70}
        series = {f"2026-0{m}-{d:02d}": dict(calm) for m in (3, 4, 5, 6, 7) for d in (5, 15, 25)}
        series.update({"2026-09-01": dict(before), "2026-09-08": dict(before), "2026-09-15": dict(after)})
        policy = {"2026-01-01": 4.0, "2026-09-15": 4.25}
        return series, policy

    def test_delivered_hike_gives_no_repricing(self):
        series, policy = self.hike_fixture()
        curve = fd.build_curve("no", series, policy)
        self.assertEqual(curve["date"], "2026-09-15")
        self.assertEqual(curve["repricing"]["w1"], 0)
        # Dekomponert: nivået om 12 mnd uendret, 25 bp levert, så 25 bp mindre gjenstår å prise
        self.assertEqual(curve["repricing_detail"]["w1"], {"level": 0, "delivered": 25, "remaining": -25})
        self.assertEqual(fd.repricing_breakdown(73, {"2026-08-01": 3.625, "2026-09-17": 3.875}, "2026-08-25", "2026-09-25"),
                         {"level": 73, "delivered": 25, "remaining": 48})
        self.assertEqual(fd.repricing_breakdown(12, {}, "2026-09-18", "2026-09-25"), {"level": 12, "delivered": 0, "remaining": 12})
        # Nivået om 12 mnd er det samme før og etter vedtaket
        self.assertAlmostEqual(curve["path"][12], curve["path_w1"][12], places=6)

    def test_implied_counts_priced_meeting_inside_3m_window(self):
        series, policy = self.hike_fixture()
        basis = fd.curve_basis(series, policy, "2026-09-08")
        before = fd.curve_metrics(series["2026-09-08"], 4.0, basis)
        after = fd.curve_metrics(series["2026-09-15"], 4.25, basis)
        # Før vedtaket: hevingen ligger i 3-mnd-vinduet og skal telles med i «priset innen 3 mnd»
        self.assertGreaterEqual(before["implied"]["3m"], 20)
        # Etter vedtaket: 25 bp er levert, så priset endring fra ny styringsrente faller tilsvarende
        self.assertAlmostEqual(before["implied"]["3m"] - after["implied"]["3m"], 25, delta=3)
        self.assertEqual(before["anchor"]["kind"], "marked")

    def test_basis_is_median_of_front_minus_policy(self):
        series = {f"2026-01-{d:02d}": {"0.25": 4.0 + b, "1": 4.5, "2": 4.6} for d, b in
                  ((1, 0.10), (2, 0.12), (3, 0.90), (4, 0.11), (5, 0.13))}  # én dag med støy
        basis = fd.curve_basis(series, {"2025-12-01": 4.0}, "2026-01-05")
        self.assertAlmostEqual(basis, 0.12)
        # Vinduet begrenses bakover fra oppgitt dag
        self.assertAlmostEqual(fd.curve_basis(series, {"2025-12-01": 4.0}, "2026-01-02"), 0.11)
        self.assertIsNone(fd.curve_basis(series, {}, "2026-01-05"))
        self.assertIsNone(fd.curve_basis({}, {"2025-12-01": 4.0}, "2026-01-05"))

    def test_basis_uses_realized_policy_when_history_is_long_enough(self):
        """Hevingssyklus: vekselen priser hevingen som kommer, så «veksel − styringsrente samme dag» er
        positiv selv om vekselen ligger under den renten som faktisk gjelder i vinduet."""
        from datetime import date as d, timedelta as td
        series, policy = {}, {"2025-01-01": 4.0}
        day = d(2025, 6, 2)
        for n in range(200):  # 200 handledager, heving 1. sep, ny heving 1. des
            day += td(days=1 if day.weekday() < 4 else 3)
            iso = str(day)
            # 3-mnd-veksel = snitt av kommende styringsrente − 0,10 (knapphet)
            nxt = 4.0 if iso < "2025-06-15" else 4.25 if iso < "2025-09-15" else 4.5
            cur = 4.0 if iso < "2025-09-01" else 4.25 if iso < "2025-12-01" else 4.5
            series[iso] = {"0.25": round((cur + nxt) / 2 - 0.10, 4), "1": 4.6, "2": 4.7}
        policy.update({"2025-09-01": 4.25, "2025-12-01": 4.5, str(day): 4.5})
        realized = fd.curve_basis(series, policy, str(day))
        naive = fd.curve_basis(series, policy, str(day), min_realized=10 ** 6)
        self.assertLess(realized, naive)          # ventede hevinger leses ikke som basis
        self.assertLess(abs(realized + 0.10), 0.05)  # nær den ekte knappheten
        self.assertGreater(naive, -0.05)
        # Kort historikk (færre enn 40 dager med kjent utfall): styringsrenten samme dag
        short = {k: v for k, v in list(sorted(series.items()))[-30:]}
        self.assertAlmostEqual(fd.curve_basis(short, policy, str(day)), fd.curve_basis(short, policy, str(day), min_realized=10 ** 6))

    def test_without_history_path_starts_at_policy(self):
        m = fd.curve_metrics({"0.25": 4.4, "1": 4.4, "2": 4.4}, 4.0)
        self.assertEqual(m["path"][0], 4.0)
        self.assertAlmostEqual(m["anchor"]["basis"], 0.4)
        self.assertEqual(m["anchor"]["rate_3m"], 4.4)

    def test_synthetic_anchor_has_zero_basis(self):
        series = {"2026-09-01": {"1": 1.6, "2": 1.9, "5": 2.4}, "2026-09-08": {"1": 1.6, "2": 1.9, "5": 2.4}}
        basis = fd.curve_basis(series, {"2026-01-01": 1.0}, "2026-09-08")
        self.assertEqual(basis, 0.0)
        m = fd.curve_metrics(series["2026-09-08"], 1.0, basis)
        self.assertTrue(m["synthetic_anchor"])
        self.assertEqual(m["anchor"]["kind"], "syntetisk")
        self.assertEqual(m["path"][0], 1.0)


class FuturesTest(unittest.TestCase):
    """Møtebaserte instrumenter: kontrakter → perioder → bane og møteprising."""

    def test_calendar_helpers(self):
        self.assertEqual(fd.month_span(2026, 12), ("2026-12-01", "2026-12-31"))
        self.assertEqual(fd.month_span(2027, 2), ("2027-02-01", "2027-02-28"))
        from datetime import date as d
        self.assertEqual(fd.add_months(d(2026, 11, 15), 3), d(2027, 2, 15))
        self.assertEqual(fd.add_months(d(2026, 1, 31), 1), d(2026, 2, 28))
        self.assertEqual(fd.third_wednesday(2026, 9), d(2026, 9, 16))
        self.assertEqual(fd.third_wednesday(2026, 12), d(2026, 12, 16))
        self.assertEqual(fd.third_wednesday(2027, 3), d(2027, 3, 17))
        self.assertEqual(fd.previous_business_day(d(2026, 9, 28)), d(2026, 9, 25))  # mandag → fredag

    def test_parse_asx_ib(self):
        payload = {"data": {"items": [
            {"symbol": "IBU2026", "pricePreviousSettlement": 95.645, "datePreviousSettlement": "2026-09-25"},
            {"symbol": "IBV2026", "pricePreviousSettlement": 95.425, "datePreviousSettlement": "2026-09-25"},
            {"symbol": "IBX2026", "pricePreviousSettlement": None, "datePreviousSettlement": "2026-09-25"},
            {"symbol": "XYZ", "pricePreviousSettlement": 95.0, "datePreviousSettlement": "2026-09-25"}]}}
        out = fd.parse_asx_ib(payload)
        self.assertEqual(out, {"2026-09-25": [["2026-09-01", "2026-09-30", 4.355], ["2026-10-01", "2026-10-31", 4.575]]})

    def test_parse_tmx_and_corra_periods(self):
        page = ("<tr data-row='{&quot;symbol&quot;:&quot;COAV26&quot;,&quot;settlement_price&quot;:97.695,&quot;expiry_date&quot;:&quot;2026-11-02&quot;}'></tr>"
                "<tr data-row='{&quot;symbol&quot;:&quot;CRAZ26&quot;,&quot;settlement_price&quot;:97.22,&quot;expiry_date&quot;:&quot;2027-03-17&quot;}'></tr>"
                "<tr data-row='{&quot;symbol&quot;:&quot;CRAH27&quot;,&quot;settlement_price&quot;:0}'></tr>")
        rows = fd.parse_tmx_rows(page)
        self.assertEqual(len(rows), 3)
        periods = fd.corra_periods(rows, "2026-09-24")["2026-09-24"]
        self.assertEqual(periods[0], ["2026-10-01", "2026-10-31", 2.305])
        self.assertEqual(periods[1], ["2026-12-16", "2027-03-17", 2.78])  # IMM-onsdag til utløp
        self.assertEqual(len(periods), 2)  # pris 0 = ingen handel, hoppes over
        # Uten expiry_date regnes sluttdatoen som IMM-onsdagen tre måneder senere
        p = fd.corra_periods([{"symbol": "CRAU26", "settlement_price": 97.625}], "d")["d"][0]
        self.assertEqual((p[0], p[1]), ("2026-09-16", "2026-12-16"))

    def monthly(self, rates, year=2026, first_month=9):
        out = []
        for i, r in enumerate(rates):
            y, m = year + (first_month - 1 + i) // 12, (first_month - 1 + i) % 12 + 1
            out.append([*fd.month_span(y, m), r])
        return out

    def test_futures_rate_at_prefers_covering_short_period(self):
        from datetime import date as d
        periods = self.monthly([4.0, 4.1, 4.2]) + [["2026-09-16", "2026-12-16", 4.3]]
        self.assertEqual(fd.futures_rate_at(periods, d(2026, 10, 10)), 4.1)
        # Mellom periodene interpoleres det mellom midtpunkter; utenfor er det flatt
        self.assertEqual(fd.futures_rate_at([["2026-09-01", "2026-09-30", 4.0], ["2026-11-01", "2026-11-30", 4.2]], d(2026, 10, 16)), 4.1)
        self.assertEqual(fd.futures_rate_at(periods, d(2030, 1, 1)), 4.2)  # flatt fra siste midtpunkt (nov)
        self.assertIsNone(fd.futures_rate_at([], d(2026, 1, 1)))

    def test_futures_basis_handles_month_with_policy_change(self):
        from datetime import date as d
        # EFFR-kontrakten ligger 4 bp under midtpunktet. 17. sep heves renten 3,96 → 4,21;
        # september-kontrakten er da et snitt: 16 dager på 3,92 og 14 dager på 4,17.
        policy = {"2026-01-01": 3.96, "2026-09-17": 4.21}
        sep_blend = round((16 * 3.92 + 14 * 4.17) / 30, 4)
        series = {}
        for day in ("2026-08-10", "2026-08-20", "2026-09-10", "2026-09-25"):
            m = int(day[5:7])
            series[day] = [[*fd.month_span(2026, m), sep_blend if m == 9 else 3.92], [*fd.month_span(2026, m + 1), 4.17]]
        # Også 10. sep (før vedtaket) måles kontrakten mot den faktiske månedsrenten, som er kjent 25. sep
        self.assertAlmostEqual(fd.futures_basis(series, policy, "2026-09-25"), -0.04, places=4)  # sep_blend er avrundet
        # Regnet 10. sep, uten kjennskap til vedtaket, ser september-kontrakten for høy ut (+0,077); august-dagene holder medianen
        self.assertAlmostEqual(fd.futures_basis(series, policy, "2026-09-10"), -0.04, places=4)
        self.assertAlmostEqual(fd.futures_basis({"2026-09-10": series["2026-09-10"]}, policy, "2026-09-10"), sep_blend - 3.96, places=4)
        self.assertAlmostEqual(fd.futures_basis(series, policy, "2026-08-20"), -0.04, places=6)
        self.assertIsNone(fd.futures_basis(series, {}, "2026-09-25"))
        # Banens startpunkt renses for vedtaket: nivået etter hevingen, ikke månedssnittet
        m = fd.futures_metrics(series["2026-09-25"], 4.21, -0.04, d(2026, 9, 25), None, policy)
        self.assertAlmostEqual(m["path"][0], 4.21, places=3)
        self.assertAlmostEqual(m["anchor"]["rate_front"], 4.17, places=3)
        self.assertEqual(fd.month_policy_average(policy, fd.month_span(2026, 8), "2026-08-20"), 3.96)
        self.assertIsNone(fd.month_policy_average({}, fd.month_span(2026, 8), "2026-08-20"))

    def test_futures_metrics_path_and_splice(self):
        from datetime import date as d
        # Sep–Nov 4,00, fra desember 4,50 (en heving priset i november), basis 0
        periods = self.monthly([4.0, 4.0, 4.0, 4.5, 4.5, 4.5])
        govt = [4.0] * 25
        govt[12], govt[24] = 4.6, 5.0  # statskurven stiger utover skjøten
        m = fd.futures_metrics(periods, 4.0, 0.0, d(2026, 9, 25), govt)
        self.assertEqual(m["path"][0], 4.0)
        self.assertEqual(m["path"][3], 4.5)
        self.assertEqual(m["implied"]["3m"], 50)
        self.assertEqual(m["horizon_months"], 5)
        # Etter siste kontrakt (feb 2027) følger banen statskurvens form fra skjøtepunktet
        self.assertAlmostEqual(m["path"][12], 4.5 + govt[12] - govt[5], places=6)
        self.assertEqual(m["anchor"]["kind"], "futures")
        # Uten statskurve holdes siste nivå
        self.assertEqual(fd.futures_metrics(periods, 4.0, 0.0, d(2026, 9, 25))["path"][24], 4.5)
        self.assertIsNone(fd.futures_metrics([], 4.0, 0.0, d(2026, 9, 25)))

    def test_meeting_implied_from_next_clean_month(self):
        from datetime import date as d
        # RBA 29. sep: september-kontrakten har bare én dag etter møtet, oktober er uten møte
        periods = self.monthly([4.355, 4.575, 4.695])
        r = fd.meeting_implied_futures(periods, "2026-09-29", ["2026-09-29", "2026-11-03"], 4.35, 0.005, today=d(2026, 9, 25))
        self.assertEqual(r, {"bp": 22, "move": "heving"})

    def test_meeting_implied_solves_partial_month(self):
        from datetime import date as d
        # Møte 10. oktober, nytt møte 15. november (november-kontrakten kan ikke brukes).
        # Oktober: 10 dager på 4,00 og 21 dager på 4,25 → kontrakt 4,169
        oct_rate = (10 * 4.0 + 21 * 4.25) / 31
        periods = self.monthly([4.0, round(oct_rate, 4), 4.4])
        r = fd.meeting_implied_futures(periods, "2026-10-10", ["2026-10-10", "2026-11-15"], 4.0, 0.0, today=d(2026, 9, 25))
        self.assertEqual(r["bp"], 25)
        # For få dager igjen i møtemåneden og møte i neste måned → ingen tall
        periods = self.monthly([4.0, 4.1, 4.4])
        self.assertIsNone(fd.meeting_implied_futures(periods, "2026-10-29", ["2026-10-29", "2026-11-15"], 4.0, 0.0, today=d(2026, 9, 25)))
        # Passert møte
        self.assertIsNone(fd.meeting_implied_futures(periods, "2026-09-01", ["2026-09-01"], 4.0, 0.0, today=d(2026, 9, 25)))

    def test_build_curve_prefers_futures_and_reprices_within_futures(self):
        govt_day = {"0.25": 4.05, "0.5": 4.1, "1": 4.2, "2": 4.4, "5": 4.5}
        series = {"2026-09-01": dict(govt_day), "2026-09-18": dict(govt_day), "2026-09-25": dict(govt_day)}
        policy = {"2026-01-01": 4.0}
        fut = {
            "2026-09-18": self.monthly([3.96] + [4.0] * 5),          # for en uke siden: ingenting priset
            "2026-09-25": self.monthly([3.96] + [4.25] * 5),         # nå: en heving priset fra oktober
        }
        curve = fd.build_curve("us", series, policy, fut)
        self.assertEqual(curve["kind"], "futures")
        self.assertEqual(curve["futures_date"], "2026-09-25")
        self.assertIn("fed funds", curve["source"])
        self.assertEqual(curve["govt_source"], fd.CURVE_SOURCES["us"][1])
        self.assertAlmostEqual(curve["anchor"]["basis"], -0.04)
        self.assertEqual(curve["path"][0], 4.0)
        self.assertEqual(curve["path"][3], 4.29)
        self.assertEqual(curve["repricing"]["w1"], 25)
        self.assertIsNone(curve["repricing"].get("m1"))  # ingen futures-historikk 30 dager tilbake
        self.assertEqual(curve["points"]["0.25"], 4.05)  # statskurvens punkter beholdes
        # Uten futures faller alt tilbake til statskurven
        self.assertEqual(fd.build_curve("us", series, policy, {})["kind"], "govt")


class RbaCurveTest(unittest.TestCase):
    def test_shift_zero_curve(self):
        zero = {"2026-08-31": {"0.25": 4.46, "1": 4.61, "2": 4.70, "10": 5.10}}
        daily = {
            "2026-08-31": {"0.083": 4.40, "2": 4.20, "10": 4.60},
            "2026-09-24": {"0.083": 4.42, "2": 4.40, "10": 4.70},  # front +2 bp, 2 år +20 bp, 10 år +10 bp
            "2026-09-25": {"2": 4.40},                              # 10 år mangler denne dagen
        }
        out = fd.shift_zero_curve(zero, daily, "2026-08-01")
        self.assertEqual(out["2026-08-31"], zero["2026-08-31"])  # F17-dato brukes direkte
        d = out["2026-09-24"]
        self.assertAlmostEqual(d["2"], 4.90)
        self.assertAlmostEqual(d["10"], 5.20)
        # 1 år ligger mellom 1 mnd (+0,02) og 2 år (+0,20): lineært i løpetid
        self.assertAlmostEqual(d["1"], 4.61 + 0.02 + (0.20 - 0.02) * (1 - 1 / 12) / (2 - 1 / 12), places=3)
        self.assertAlmostEqual(d["0.25"], 4.46 + 0.02 + (0.20 - 0.02) * (0.25 - 1 / 12) / (2 - 1 / 12), places=3)
        self.assertNotIn("0.083", d)  # vekselen lagres ikke
        # 25. sep mangler 1 mnd og 10 år: de tas fra dagen før (carry-forward), så 10 år følger sin egen endring
        self.assertAlmostEqual(out["2026-09-25"]["10"], 5.20)
        self.assertAlmostEqual(out["2026-09-25"]["2"], 4.90)
        # Uten noen nylig observasjon forskyves alt med det som finnes
        lone = fd.shift_zero_curve(zero, {"2026-08-31": daily["2026-08-31"], "2026-10-20": {"2": 4.40}}, "2026-08-01")
        self.assertAlmostEqual(lone["2026-10-20"]["10"], 5.30)
        # Dager før første F17-dato og uten daglige endringer hoppes over
        self.assertNotIn("2026-07-01", fd.shift_zero_curve(zero, {"2026-07-01": {"2": 4.0}}, "2026-01-01"))
        self.assertEqual(fd.shift_zero_curve(zero, {"2026-09-01": {"7": 1.0}}, "2026-01-01").get("2026-09-01"), None)

    def test_zero_curve_gives_smooth_path_without_synthetic_anchor(self):
        # Med tette løpetider fra 3 mnd trenger AUD verken syntetisk anker eller 1 mnd→2 år-interpolasjon
        points = {"0.25": 4.46, "0.5": 4.55, "0.75": 4.59, "1": 4.61, "1.25": 4.63, "1.5": 4.65, "1.75": 4.66,
                  "2": 4.67, "2.5": 4.69, "3": 4.70, "4": 4.74, "5": 4.78, "7": 4.90, "10": 5.05}
        m = fd.curve_metrics(points, 4.35)
        self.assertFalse(m["synthetic_anchor"])
        self.assertEqual(m["anchor"]["kind"], "marked")
        steps = [b - a for a, b in zip(m["path"], m["path"][1:])]
        self.assertTrue(all(abs(x) < 0.15 for x in steps), steps)  # ingen kink i banen

    def test_rba_zero_tenor_ids(self):
        self.assertEqual(fd.RBA_ZERO_TENORS["FZCY25D"], 0.25)
        self.assertEqual(fd.RBA_ZERO_TENORS["FZCY175D"], 1.75)
        self.assertEqual(fd.RBA_ZERO_TENORS["FZCY1000D"], 10)


class RbnzCurveTest(unittest.TestCase):
    def b2_workbook(self, id_label="Series Id"):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("xl/workbook.xml", '<workbook><sheets><sheet name="Data" sheetId="1" r:id="rId1"/></sheets></workbook>')
            z.writestr("xl/_rels/workbook.xml.rels", '<Relationships><Relationship Id="rId1" Type="ws" Target="worksheets/sheet1.xml"/></Relationships>')
            z.writestr("xl/sharedStrings.xml", f"<sst><si><t>{id_label}</t></si><si><t>INM.DP1.N</t></si><si><t>INM.DB03.NZZV</t></si>"
                       "<si><t>INM.DS01.NZZC</t></si><si><t>INM.DS10.NZZC</t></si><si><t>Unit</t></si></sst>")
            z.writestr("xl/worksheets/sheet1.xml",
                       '<worksheet><sheetData>'
                       '<row r="4"><c r="A4" t="s"><v>5</v></c></row>'
                       '<row r="5"><c r="A5" t="s"><v>0</v></c><c r="B5" t="s"><v>1</v></c><c r="C5" t="s"><v>2</v></c><c r="D5" t="s"><v>3</v></c><c r="E5" t="s"><v>4</v></c></row>'
                       '<row r="6"><c r="A6"><v>46288</v></c><c r="B6"><v>2.75</v></c><c r="C6"><v>3.19</v></c><c r="D6"><v>3.7</v></c><c r="E6"><v>4.7</v></c></row>'
                       '<row r="7"><c r="A7"><v>46289</v></c><c r="B7"><v>2.75</v></c><c r="C7"><v>3.21</v></c><c r="D7"><v>3.75</v></c><c r="E7" t="e"><v>#N/A</v></c></row>'
                       '</sheetData></worksheet>')
        return buf.getvalue()

    def test_parse_rbnz_b2(self):
        out = fd.parse_rbnz_b2(self.b2_workbook(), "2026-09-23")
        self.assertEqual(out, {"2026-09-23": {"0.25": 3.19, "1": 3.7, "10": 4.7}, "2026-09-24": {"0.25": 3.21, "1": 3.75}})
        self.assertEqual(fd.parse_rbnz_b2(self.b2_workbook(), "2026-09-25"), {})  # startdato filtrerer
        with self.assertRaises(RuntimeError):
            fd.parse_rbnz_b2(self.b2_workbook(id_label="Serie"), "2026-01-01")

    def test_fetch_curve_nz_requires_fresh_file(self):
        import os, tempfile, time as t
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "b2.xlsx")
            os.environ["RBNZ_B2_FILE"] = path
            try:
                with self.assertRaises(RuntimeError):  # mangler
                    fd.fetch_curve_nz()
                with open(path, "wb") as f:
                    f.write(self.b2_workbook())
                self.assertIn("2026-09-24", fd.fetch_curve_nz())
                os.utime(path, (t.time() - 20 * 3600, t.time() - 20 * 3600))
                with self.assertRaises(RuntimeError):  # for gammel
                    fd.fetch_curve_nz()
            finally:
                del os.environ["RBNZ_B2_FILE"]


class JsdaTbillTest(unittest.TestCase):
    ROW = '{day},01,0{n}0074,"国庫短期証券{n}",{due},99.999,999.999,99.9,0.00,"-----","--",0,0,0,{rate},99.9,{rate},99.9,{rate}," ",8,999.999,0.00,999.999,0.00,999.999,{rate},99.9,0.00'

    def csv(self, day, bills):
        rows = [self.ROW.format(day=day, n=1390 + i, due=due, rate=rate) for i, (due, rate) in enumerate(bills)]
        rows.append('20260924,02,000000000,"利付国債（10年）",20360920,1.500,0320,101.0,0.00,"-----","--",0,0,0,3.073,101.0,3.0,101.0,3.0," ",8,0,0,0,0,0,3.073,101.0,0.0')
        return "\n".join(rows)

    def test_parse_interpolates_tenors_from_bills(self):
        from datetime import date as d
        text = self.csv("20260924", [("20261005", 1.19), ("20261222", 1.20), ("20261228", 1.22), ("20270322", 1.30), ("20270921", 1.565)])
        out = fd.parse_jsda_tbills(text, today=d(2026, 9, 25))
        pts = out["2026-09-24"]
        self.assertAlmostEqual(pts["0.25"], 1.21, places=2)  # mellom 22/12 (89 d) og 28/12 (95 d)
        self.assertAlmostEqual(pts["0.5"], 1.30, places=2)   # 22/3 er 179 d ≈ 0,49 år, nærmeste innenfor 45 dager
        self.assertAlmostEqual(pts["1"], 1.565, places=3)    # 21/9 2027 er 362 d: flat siste 3 dager
        # Dager etter i dag (fila for neste oppgjørsdag) og statsobligasjoner ignoreres
        self.assertEqual(fd.parse_jsda_tbills(self.csv("20260928", [("20261222", 1.2), ("20270322", 1.3)]), today=d(2026, 9, 25)), {})
        # Uten veksel nær løpetiden hoppes den over
        short = fd.parse_jsda_tbills(self.csv("20260924", [("20261005", 1.19), ("20261222", 1.20)]), today=d(2026, 9, 25))
        self.assertEqual(set(short["2026-09-24"]), {"0.25"})

    def test_parse_handles_garbage(self):
        self.assertEqual(fd.parse_jsda_tbills("x,y\n,,,,\n", today=__import__("datetime").date(2026, 9, 25)), {})


class SnbCurveTest(unittest.TestCase):
    def test_parse_snb_cube(self):
        text = ('\ufeff"CubeId";"rendeiduebd"\n"PublishingDate";"2026-09-01 14:30"\n\n"Date";"D0";"D1";"Value"\n'
                '"2026-08-28";"CHF";"1J";"-0.12"\n"2026-08-28";"CHF";"2J";\n"2026-08-28";"CHF";"10J";"0.47"\n'
                '"2026-08-28";"CHF";"20J";"0.61"\n"2026-08-31";"CHF";"1J";"-0.1"\n')
        self.assertEqual(fd.parse_snb_cube(text, fd.SNB_ZERO_TENORS),
                         {"2026-08-28": {"1": -0.12, "10": 0.47}, "2026-08-31": {"1": -0.1}})

    def test_parse_snb_rates_reads_numeric_typed_cells(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("xl/workbook.xml", '<workbook><sheets><sheet name="Interest_Rates" sheetId="1" r:id="rId1"/></sheets></workbook>')
            z.writestr("xl/_rels/workbook.xml.rels", '<Relationships><Relationship Id="rId1" Type="ws" Target="worksheets/sheet1.xml"/></Relationships>')
            z.writestr("xl/sharedStrings.xml", "<sst><si><t>SNBLZ</t></si><si><t>SARH</t></si><si><t>R10</t></si></sst>")
            z.writestr("xl/worksheets/sheet1.xml",
                       '<worksheet><sheetData>'
                       '<row r="10"><c r="B10" t="s"><v>0</v></c><c r="H10" t="s"><v>1</v></c><c r="I10" t="s"><v>2</v></c></row>'
                       '<row r="12"><c r="A12" t="n"><v>46289.0</v></c><c r="B12" t="n"><v>0.0</v></c><c r="H12" t="n"><v>-0.04</v></c><c r="I12" t="n"><v>0.615</v></c></row>'
                       '<row r="13"><c r="A13" t="n"><v>46288.0</v></c><c r="H13" t="n"><v>-0.05</v></c><c r="I13" t="e"><v>#N/A</v></c></row>'
                       '</sheetData></worksheet>')
        out = fd.parse_snb_rates(buf.getvalue(), "2026-09-01")
        self.assertEqual(out, {"2026-09-24": {"0.003": -0.04, "10": 0.615}, "2026-09-23": {"0.003": -0.05}})

    def test_shifted_snb_curve_gets_synthetic_anchor(self):
        zero = {"2026-08-31": {"1": -0.10, "2": -0.05, "5": 0.26, "10": 0.47}}
        daily = {"2026-08-31": {"0.003": -0.04, "10": 0.47}, "2026-09-24": {"0.003": -0.04, "10": 0.615}}
        curve = fd.shift_zero_curve(zero, daily, "2026-08-01")["2026-09-24"]
        self.assertAlmostEqual(curve["10"], 0.615)
        self.assertAlmostEqual(curve["1"], -0.10 + 0.145 * (1 - 1 / 365) / (10 - 1 / 365), places=3)  # front uendret, 10 år +14,5 bp
        m = fd.curve_metrics(curve, 0.0)
        self.assertTrue(m["synthetic_anchor"])


class NzFuturesTest(unittest.TestCase):
    def test_parse_asx_bb_skips_illiquid(self):
        payload = {"data": {"items": [
            {"symbol": "BBZ2026", "dateExpiry": "2026-12-14", "datePreviousSettlement": "2026-09-25", "pricePreviousSettlement": 96.49, "priceLastTrade": 96.48},
            {"symbol": "BBH2027", "dateExpiry": "2027-03-08", "datePreviousSettlement": "2026-09-25", "pricePreviousSettlement": 96.09, "priceLastTrade": 96.09},
            {"symbol": "BBH2028", "dateExpiry": "2028-03-13", "datePreviousSettlement": "2026-09-25", "pricePreviousSettlement": 95.64, "priceLastTrade": None}]}}
        out = fd.parse_asx_bb(payload)
        self.assertEqual(out, {"2026-09-25": [["2026-12-14", "2027-03-14", 3.51], ["2027-03-08", "2027-06-06", 3.91]]})

    def test_parse_asx_bb_skips_zero_volume(self):
        payload = {"data": {"items": [
            {"symbol": "BBZ2026", "dateExpiry": "2026-12-14", "datePreviousSettlement": "2026-09-25", "pricePreviousSettlement": 96.49, "priceLastTrade": 96.5, "volume": 608},
            {"symbol": "BBZ2027", "dateExpiry": "2027-12-13", "datePreviousSettlement": "2026-09-25", "pricePreviousSettlement": 95.65, "priceLastTrade": 95.67, "volume": 0}]}}
        self.assertEqual([p[0] for p in fd.parse_asx_bb(payload)["2026-09-25"]], ["2026-12-14"])

    def test_monthly_front_basis_measures_against_realized_policy(self):
        # OCR 2,50 til 3. sep 2026, så 2,75. OECD-snitt for august (2,98) inneholder den ventede hevingen.
        policy = {"2026-01-01": 2.50, "2026-09-03": 2.75, "2026-12-31": 2.75}
        monthly = {"2026-05": 2.63, "2026-06": 2.68, "2026-07": 2.85, "2026-08": 2.98, "2026-09": None}
        b = fd.monthly_front_basis(monthly, policy, months=12)
        # august: 2,98 − snitt(15/8–13/11) ≈ 2,98 − 2,70; mai/juni/juli mot 2,50 (og litt 2,75)
        self.assertLess(b, 2.98 - 2.50)
        self.assertGreater(b, 0.10)
        self.assertIsNone(fd.monthly_front_basis({}, policy))
        self.assertIsNone(fd.monthly_front_basis(monthly, {}))
        # Ingen måned med kjent utfall ennå
        self.assertIsNone(fd.monthly_front_basis({"2026-08": 2.98}, policy, known_until="2026-09-25"))

    def test_add_monthly_front(self):
        fut = {"2026-09-25": [["2026-12-14", "2027-03-14", 3.51]], "2026-07-10": [["2026-09-14", "2026-12-13", 3.2]]}
        out = fd.add_monthly_front(fut, {"2026-06": 3.05, "2026-08": 3.10, "2026-10": None})
        self.assertEqual(out["2026-09-25"], [["2026-12-14", "2027-03-14", 3.51], ["2026-09-01", "2026-09-30", 3.10]])
        self.assertEqual(out["2026-07-10"][-1], ["2026-07-01", "2026-07-31", 3.05])
        self.assertEqual(fd.add_monthly_front(fut, {})["2026-09-25"], fut["2026-09-25"])

    def test_build_curve_from_futures_only(self):
        from datetime import date as d
        policy = {"2026-01-01": 2.75}
        fut = fd.add_monthly_front({"2026-09-25": [["2026-12-14", "2027-03-14", 3.51], ["2027-03-08", "2027-06-06", 3.91], ["2027-06-14", "2027-09-12", 4.2]]},
                                   {"2026-08": 3.05})
        curve = fd.build_curve("nz", {}, policy, fut)
        self.assertEqual(curve["kind"], "futures")
        self.assertEqual(curve["date"], "2026-09-25")
        self.assertEqual(curve["points"], {})
        self.assertIsNone(curve["govt_source"])
        self.assertIn("flat etter", curve["source"])
        # basis = OECD-månedsrente − styringsrente = 0,30; front renset → bane starter på styringsrenten
        self.assertAlmostEqual(curve["anchor"]["basis"], 0.30)
        self.assertAlmostEqual(curve["path"][0], 2.75)
        self.assertAlmostEqual(curve["path"][6], 3.91 - 0.30)  # mars 2027-kontrakten dekker midten av mars
        self.assertEqual(curve["repricing"], {})
        # OECD-fronten er et månedssnitt, ikke en markedsrente: syntetisk anker og lav sikkerhet
        self.assertTrue(curve["synthetic_anchor"])
        self.assertIn("syntetisk", curve["anchor"]["kind"])
        self.assertEqual(curve["confidence"], "lav")
        # Ferdig regnet basis for fronten overstyrer kontraktbasisen
        with_basis = fd.build_curve("nz", {}, policy, fut, front_basis=0.25)
        self.assertAlmostEqual(with_basis["anchor"]["basis"], 0.25)
        self.assertIsNone(fd.build_curve("nz", {}, policy, {}))
        self.assertIsNone(fd.build_curve("nz", {}, {}, fut))

    def test_confidence_levels(self):
        self.assertEqual(fd.curve_confidence("futures", False), "høy")
        self.assertEqual(fd.curve_confidence("ois", False), "høy")
        self.assertEqual(fd.curve_confidence("govt", False), "middels")
        self.assertEqual(fd.curve_confidence("zero", False), "middels")
        self.assertEqual(fd.curve_confidence("govt", True), "lav")
        self.assertEqual(fd.curve_confidence("futures", True), "lav")
        series = {"2026-09-23": {"0.25": 4.0, "1": 4.2, "2": 4.4, "5": 4.5}}
        self.assertEqual(fd.build_curve("no", series, {"2026-09-01": 4.0})["confidence"], "middels")
        self.assertEqual(fd.build_curve("jp", {"2026-09-23": {"1": 1.6, "2": 1.9, "5": 2.4}}, {"2026-09-01": 1.0})["confidence"], "lav")


class MeetingImpliedCurveTest(unittest.TestCase):
    """Møteprising fra 1/3-mnd-renten, kontrollert mot RBA- og BoC-tallene fra futures (22 og 13 bp)."""

    def test_single_meeting_from_3m(self):
        from datetime import date as d
        # AUD 25. sep: 3 mnd 4,63, basis 0,04, styringsrente 4,35, møte 29. sep (n = 5)
        pts = {"0.25": 4.63, "1": 4.78, "2": 4.76}
        r = fd.meeting_implied_curve(pts, 4.35, 0.04, ["2026-09-29"], today=d(2026, 9, 25))
        self.assertEqual(r["move"], "heving")
        self.assertAlmostEqual(r["bp"], round(0.24 * 90 / 85 * 100))  # 25 bp; futures sa 22, manuell fil 23
        self.assertIn("3 mnd", r["source"])
        # Med novembermøtet også innenfor 90 dager deles bevegelsen likt: 0,24·90/(85+50) = 16 bp
        r2 = fd.meeting_implied_curve(pts, 4.35, 0.04, ["2026-09-29", "2026-11-03"], today=d(2026, 9, 25))
        self.assertEqual(r2["bp"], 16)

    def test_two_meetings_split_equally(self):
        from datetime import date as d
        # Møter om 30 og 72 dager, 3-mnd-renten priser i snitt 0,20 over basis: Δ hver = 0,20·90/(60+18)
        r = fd.meeting_implied_curve({"0.25": 2.45, "1": 2.7, "2": 2.9}, 2.25, 0.0, ["2026-10-24", "2026-12-05"], today=d(2026, 9, 25))
        self.assertEqual(r["bp"], round(0.20 * 90 / 78 * 100))

    def test_one_month_rate_gives_basis_and_near_meeting(self):
        from datetime import date as d
        pts = {"0.083": 3.80, "0.25": 3.95, "0.5": 4.1, "1": 4.3, "2": 4.5}
        # Møte om 41 dager: 1 mnd-vinduet er uten møte, så basis = 3,80 − 3,75 = 0,05 (medianen ignoreres)
        r = fd.meeting_implied_curve(pts, 3.75, 0.20, ["2026-11-05"], today=d(2026, 9, 25))
        self.assertAlmostEqual(r["bp"], round((3.95 - 0.05 - 3.75) * 90 / (90 - 42) * 100))
        self.assertIn("1 og 3", r["source"])
        # Møte om 10 dager: 1 mnd-renten priser det, 3 mnd-renten gir resten til møte 2
        pts2 = {"0.083": 3.97, "0.25": 4.05, "1": 4.3, "2": 4.5}
        r2 = fd.meeting_implied_curve(pts2, 3.75, 0.05, ["2026-10-05", "2026-11-15"], today=d(2026, 9, 25))
        self.assertAlmostEqual(r2["bp"], round((3.97 - 0.05 - 3.75) * 30 / (30 - 11) * 100))

    def test_no_answer_when_uninformative(self):
        from datetime import date as d
        pts = {"0.25": 4.63, "1": 4.78, "2": 4.76}
        self.assertIsNone(fd.meeting_implied_curve({"1": 1.6, "2": 1.9, "5": 2.4}, 1.0, 0.0, ["2026-10-30"], today=d(2026, 9, 25)))  # syntetisk anker
        self.assertIsNone(fd.meeting_implied_curve(pts, 4.35, 0.04, ["2026-12-20"], today=d(2026, 9, 25)))  # møtet er utenfor 80 dager
        self.assertIsNone(fd.meeting_implied_curve(pts, 4.35, 0.04, ["2026-09-20"], today=d(2026, 9, 25)))  # passert
        self.assertIsNone(fd.meeting_implied_curve(pts, 4.35, None, ["2026-09-29"], today=d(2026, 9, 25)))  # ingen basis
        self.assertIsNone(fd.meeting_implied_curve({}, 4.35, 0.04, ["2026-09-29"], today=d(2026, 9, 25)))


class CentralBankPathTest(unittest.TestCase):
    def workbook(self, sheet, shared, rows_xml):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("xl/workbook.xml", f'<workbook><sheets><sheet name="{sheet}" sheetId="1" r:id="rId1"/></sheets></workbook>')
            z.writestr("xl/_rels/workbook.xml.rels", '<Relationships><Relationship Id="rId1" Type="ws" Target="worksheets/sheet1.xml"/></Relationships>')
            z.writestr("xl/sharedStrings.xml", "<sst>" + "".join(f"<si><t>{t}</t></si>" for t in shared) + "</sst>")
            z.writestr("xl/worksheets/sheet1.xml", f"<worksheet><sheetData>{rows_xml}</sheetData></worksheet>")
        return buf.getvalue()

    def test_parse_fed_sep(self):
        html_text = ("<table><tr><th>Variable</th><th>Median</th></tr>"
                     "<tr><th>2026</th><th>2027</th><th>2028</th><th>Longer run</th><th>2026</th></tr>"
                     "<tr><th>PCE inflation</th><td>3.7</td><td>2.3</td><td>2.1</td><td>2.0</td><td>3.5–3.7</td></tr>"
                     "<tr><th>Federal funds rate</th><td>4.1</td><td>4.1</td><td>3.9</td><td>3.2</td><td>4.1–4.4</td></tr></table>")
        self.assertEqual(fd.parse_fed_sep(html_text), {"2026-12-31": 4.1, "2027-12-31": 4.1, "2028-12-31": 3.9, "longer_run": 3.2})
        with self.assertRaises(RuntimeError):
            fd.parse_fed_sep("<table><tr><td>ingenting</td></tr></table>")

    def test_parse_nb_tallsett(self):
        xlsx = self.workbook("Data A", ["Dato", "Styringsrenten (nivå)", "Styringsrenten PPR 2/26 (nivå)"],
                             '<row r="9"><c r="A9" t="s"><v>0</v></c><c r="B9" t="s"><v>1</v></c><c r="C9" t="s"><v>2</v></c></row>'
                             '<row r="11"><c r="A11"><v>46295</v></c><c r="B11"><v>4.27</v></c><c r="C11"><v>4.32</v></c></row>'
                             '<row r="12"><c r="A12"><v>46387</v></c><c r="B12"><v>4.51</v></c></row>'
                             '<row r="13"><c r="A13"><v>46477</v></c><c r="B13" t="e"><v>#N/A</v></c></row>')
        self.assertEqual(fd.parse_nb_tallsett(xlsx), {"2026-09-30": 4.27, "2026-12-31": 4.51})
        with self.assertRaises(RuntimeError):
            fd.parse_nb_tallsett(self.workbook("Data A", ["Dato", "Noe annet"], '<row r="9"><c r="A9" t="s"><v>0</v></c><c r="B9" t="s"><v>1</v></c></row>'))

    def test_parse_rb_forecasts(self):
        xlsx = self.workbook("SEQRATENAYNA", ["PPR", "2026:3", "Publiceringsdatum", "Datum", "2027-06-30", "2027-09-30"],
                             '<row r="8"><c r="A8" t="s"><v>0</v></c><c r="B8" t="s"><v>1</v></c></row>'
                             '<row r="9"><c r="A9" t="s"><v>2</v></c><c r="B9"><v>46289</v></c></row>'
                             '<row r="11"><c r="A11" t="s"><v>3</v></c></row>'
                             '<row r="12"><c r="A12" t="s"><v>4</v></c><c r="B12"><v>2.24</v></c><c r="C12"><v>1.93</v></c></row>'
                             '<row r="13"><c r="A13" t="s"><v>5</v></c><c r="B13"><v>2.38</v></c></row>')
        out = fd.parse_rb_forecasts(xlsx)
        self.assertEqual(out["path"], {"2027-06-30": 2.24, "2027-09-30": 2.38})
        self.assertEqual((out["as_of"], out["label"]), ("2026-09-24", "Riksbanken, Penningpolitisk rapport 2026:3"))

    def test_cb_path_at_and_horizon_text(self):
        path = {"2026-12-31": 4.1, "2027-12-31": 4.1, "2028-12-31": 3.9, "longer_run": 3.2}
        self.assertEqual(fd.cb_path_at(path, "2027-09-25"), ("2027-12-31", 4.1))
        self.assertEqual(fd.cb_path_at(path, "2031-01-01"), ("2028-12-31", 3.9))  # utenfor: siste punkt
        self.assertEqual(fd.cb_path_at({"longer_run": 3.2}, "2027-09-25"), (None, None))
        self.assertEqual(fd.horizon_text("2027-12-31"), "utgangen av 2027")
        self.assertEqual(fd.horizon_text("2027-09-30"), "3. kvartal 2027")


class CotFlagsTest(unittest.TestCase):
    def series(self, nets, oi=400000, extra=None):
        from datetime import date as d, timedelta as td
        start = d(2025, 9, 16)
        out = {}
        for i, n in enumerate(nets):
            day = str(start + td(weeks=i))
            out[day] = {"net": n, "oi": oi}
            if extra and i >= len(nets) - 2:
                out[day].update(extra[i - (len(nets) - 2)])
        return out

    def test_roll_week(self):
        self.assertTrue(fd.is_roll_week("2026-09-15"))   # tredje onsdag 16. sep
        self.assertFalse(fd.is_roll_week("2026-09-08"))
        self.assertFalse(fd.is_roll_week("2026-10-13"))
        self.assertTrue(fd.is_roll_week("2026-12-15"))   # tredje onsdag 16. des

    def test_flags_large_swing_confirmed(self):
        # 52 rolige uker (±10k) og så +110k, bekreftet i futures+options og TFF med samme fortegn
        nets = [(-1) ** i * 10000 for i in range(53)] + [120000]
        s = self.series(nets, extra=[{"net_comb": 12000, "lev": -50000}, {"net_comb": 120000, "lev": 23000}])
        f = fd.cot_flags(s)
        self.assertTrue(f["unusual"])
        self.assertGreater(f["z_w"], 3)
        self.assertTrue(f["confirmed"])
        self.assertEqual(f["lev_net"], 23000)
        self.assertTrue(f["roll_week"])  # siste rapport 15. sep 2026

    def test_lev_pct_oi(self):
        series = {f"2026-0{m}-01": {"net": 100000 + m, "oi": 500000, "net_comb": 100000, "lev": 20000} for m in range(1, 10)}
        flags = fd.cot_flags(series)
        self.assertEqual(flags["lev_net"], 20000)
        self.assertEqual(flags["lev_pct_oi"], 4.0)

    def test_flags_unconfirmed_and_oi_jump(self):
        nets = [(-1) ** i * 10000 for i in range(53)] + [120000]
        # TFF går motsatt vei: ikke bekreftet
        f = fd.cot_flags(self.series(nets, extra=[{"net_comb": 12000, "lev": 50000}, {"net_comb": 120000, "lev": 20000}]))
        self.assertFalse(f["confirmed"])
        # Uten kontrollserier: confirmed er None
        self.assertIsNone(fd.cot_flags(self.series(nets))["confirmed"])
        # Rolig netto men åpen interesse +30 %: uvanlig
        s = self.series([10000] * 20)
        last = sorted(s)[-1]
        s[last]["oi"] = 520000
        f = fd.cot_flags(s)
        self.assertTrue(f["unusual"])
        self.assertEqual(f["oi_change_pct"], 30.0)
        self.assertEqual(fd.cot_flags({"2026-09-15": {"net": 1, "oi": 1}}), {})


class CoreInflationTest(unittest.TestCase):
    def test_yoy_from_index(self):
        idx = {"2025-07-01": 125.0, "2025-08-01": 125.5, "2026-07-01": 130.0, "2026-08-01": 128.638}
        self.assertEqual(fd.yoy_from_index(idx), {"2026-07": 4.0, "2026-08": 2.5})
        self.assertEqual(fd.yoy_from_index({"2026-07-01": 130.0}), {})

    def test_parse_abs_csv(self):
        text = ("DATAFLOW,MEASURE,INDEX,TSEST,REGION,FREQ,TIME_PERIOD,OBS_VALUE,UNIT_MEASURE\n"
                "ABS:CPI(1.2.0),3,999902,20,50,M,2026-06,3.6,PCT\nABS:CPI(1.2.0),3,999902,20,50,M,2026-07,3.6,PCT\n"
                "ABS:CPI(1.2.0),3,999902,20,50,M,2026-08,,PCT\n")
        self.assertEqual(fd.parse_abs_csv(text), {"2026-06": 3.6, "2026-07": 3.6})

    def test_boc_core_average(self):
        payload = {"observations": [{"d": "2026-05-01", "CPI_TRIM": {"v": "2.0"}, "CPI_MEDIAN": {"v": "1.8"}},
                                    {"d": "2026-06-01", "CPI_TRIM": {"v": "1.9"}, "CPI_MEDIAN": {"v": "1.9"}},
                                    {"d": "2026-07-01", "CPI_TRIM": {"v": "2.1"}}]}
        self.assertEqual(fd.boc_core_average(payload), {"2026-05": 1.9, "2026-06": 1.9})


class DecisionReactionTest(unittest.TestCase):
    def test_dovish_hike_lowers_forwards(self):
        # Heving 4,00 → 4,25 den 15. sep; 3 mnd følger, men 1–2 år faller: banken signaliserte pause
        before = {"0.25": 4.20, "0.5": 4.35, "1": 4.60, "2": 4.80, "5": 4.90}
        after = {"0.25": 4.27, "0.5": 4.30, "1": 4.40, "2": 4.55, "5": 4.70}
        series = {"2026-09-01": dict(before), "2026-09-14": dict(before), "2026-09-16": dict(after), "2026-09-25": dict(after)}
        policy = {"2026-01-01": 4.0, "2026-09-15": 4.25}
        curve = fd.build_curve("no", series, policy)
        r = fd.decision_reaction(curve, series, None, policy, "2026-09-15")
        self.assertEqual(r["measured"], ["2026-09-14", "2026-09-16"])
        self.assertEqual(r["tone"], "duete")
        self.assertLessEqual(r["path12_change_bp"], -fd.DECISION_TONE_BP)
        # Uendrede forwarder gjennom vedtaket: nøytral
        flat = {"2026-09-14": dict(before), "2026-09-16": dict(before)}
        curve2 = fd.build_curve("no", flat, policy)
        self.assertEqual(fd.decision_reaction(curve2, flat, None, policy, "2026-09-15")["tone"], "nøytral")
        # Ingen kurvedag etter vedtaket innen vinduet
        self.assertIsNone(fd.decision_reaction(curve, {"2026-09-14": dict(before), "2026-09-30": dict(after)}, None, policy, "2026-09-15"))

    def test_reaction_for_futures_curve(self):
        from datetime import date as d, timedelta as td
        # Futures-kurver uten statskurve krever ferske data (siste uke), så datoene settes relativt til i dag
        today = d.today()
        before, decision, after = str(today - td(days=3)), str(today - td(days=2)), str(today - td(days=1))
        policy = {"2026-01-01": 4.0, decision: 4.25}
        def monthly(rates):
            return [[*fd.month_span(today.year + (today.month - 1 + i) // 12, (today.month - 1 + i) % 12 + 1), r] for i, r in enumerate(rates)]
        fut = {before: monthly([4.0, 4.25, 4.5, 4.75] + [5.0] * 10),   # før: hevinger videre
               after: monthly([4.1, 4.25, 4.3, 4.3] + [4.3] * 10)}      # etter: levert, men banen flatet ut
        curve = fd.build_curve("us", {}, policy, fut)
        r = fd.decision_reaction(curve, {}, fut, policy, decision)
        self.assertEqual(r["tone"], "duete")
        self.assertEqual(r["measured"], [before, after])


class SnapshotTest(unittest.TestCase):
    def test_snapshot_record_and_backfill(self):
        import tempfile
        from datetime import date as d
        from pathlib import Path
        govt = {"0.25": 4.05, "0.5": 4.1, "1": 4.2, "2": 4.4, "5": 4.5}
        series = {str(d(2026, 9, 1) + __import__("datetime").timedelta(days=i)): dict(govt) for i in range(0, 25)}
        policy = {"2026-01-01": 4.0}
        history = {"fx": {"NOK": {}, "USD": {"2026-09-24": 9.5, "2026-06-25": 9.7}, "I44": {"2026-09-24": 118.0, "2026-06-25": 120.0}},
                   "policy": {"US": policy}, "cot": {"USD": {"2026-09-22": {"net": 10000, "oi": 40000}}},
                   "market": {"brent": {"2026-09-24": 100.0}, "vix": {}, "brent_fut": {}, "ttf": {}, "audjpy": {}}}
        curve = fd.build_curve("us", series, policy)
        countries = [{"id": "us", "currency": "USD", "curve": curve, "fx": {"value": 9.5, "changes": {"m3": -2.1}},
                      "rates": {"policy": 4.0}, "cpi": {"value": 3.4}, "cpi_core": {"value": 3.3, "is_target": True},
                      "cot": {"net": 10000, "pct_oi": 25.0}, "vol30": 6.4, "next_meeting": {"bp": 17}, "cb_path": {"level": 4.1}}]
        rec = fd.snapshot_record(countries, {"brent": {"value": 100.0}}, "2026-09-25", history)
        us = rec["countries"]["us"]
        self.assertEqual((rec["date"], rec["backfilled"], rec["market"]["brent"], rec["market"]["i44"]), ("2026-09-25", False, 100.0, 118.0))
        self.assertEqual((us["fx"], us["policy"], us["cpi_target"], us["cb_level"], us["next_meeting_bp"]), (9.5, 4.0, 3.3, 4.1, 17))
        self.assertAlmostEqual(us["fx_world"], 9.5 / 118.0, places=5)
        self.assertEqual(len(us["path"]), 5)
        self.assertEqual(us["path"][3], curve["path"][12])
        with tempfile.TemporaryDirectory() as tmp:
            sd = Path(tmp)
            n = fd.backfill_snapshots(sd, countries, {"USD": series}, {}, history, days=10, today=d(2026, 9, 25))
            self.assertEqual(n, 8)  # ti dager bakover uten helg
            back = json.loads((sd / "2026-09-24.json").read_text())
            self.assertTrue(back["backfilled"])
            self.assertEqual(back["countries"]["us"]["path"][3], curve["path"][12])  # samme kurve og basis → samme nivå
            self.assertAlmostEqual(back["countries"]["us"]["fx_m3"], round((9.5 / 9.7 - 1) * 100, 2))
            self.assertEqual(back["countries"]["us"]["cot_pct_oi"], 25.0)
            self.assertEqual(fd.backfill_snapshots(sd, countries, {"USD": series}, {}, history, days=10, today=d(2026, 9, 25)), 0)  # finnes alt
            (sd / "2026-09-25.json").write_text(json.dumps(rec))
            hist = fd.path12_history(sd, countries)
            self.assertEqual(len(hist["USD"]), 9)
            self.assertEqual(hist["USD"]["2026-09-25"], curve["path"][12])


class RatesByCurrencyTest(unittest.TestCase):
    def test_maps_oecd_codes_and_merges_previous(self):
        oecd = {"USA": {"2026-07": 4.2, "2026-08": 4.19}, "NOR": {"2026-08": 4.45}, "XXX": {"2026-08": 1.0}}
        prev = {"USD": {"2025-01": 4.5}, "SEK": {"2026-06": 1.9}}
        out = fd.rates_by_currency(oecd, prev)
        self.assertEqual(out["USD"], {"2025-01": 4.5, "2026-07": 4.2, "2026-08": 4.19})
        self.assertEqual(out["NOK"], {"2026-08": 4.45})
        self.assertEqual(out["SEK"], {"2026-06": 1.9})
        self.assertNotIn("XXX", out)
        self.assertEqual(prev["USD"], {"2025-01": 4.5})  # urørt


class FillIr3Test(unittest.TestCase):
    def test_fills_missing_months_from_curve_front(self):
        ir3 = {"GBP": {"2026-01": 3.71, "2026-02": 3.62}, "NOK": {"2026-08": 4.51}}
        curves = {"GBP": {"2026-02-10": {"0.25": 3.70, "1": 3.8}, "2026-03-05": {"0.25": 3.80}, "2026-03-20": {"0.25": 3.90}, "2026-04-01": {"1": 4.0}},
                  "NOK": {"2026-09-10": {"0.25": 4.45}}}
        out = fd.fill_ir3_from_curves(ir3, curves)
        self.assertEqual(out["GBP"], {"2026-01": 3.71, "2026-02": 3.62, "2026-03": 3.85})  # feb beholdes fra OECD, mars = snitt, april mangler 0.25
        self.assertEqual(out["NOK"], {"2026-08": 4.51})  # bare valutaer i CURVE_IR3_FILL
        self.assertEqual(ir3["GBP"], {"2026-01": 3.71, "2026-02": 3.62})  # urørt
        self.assertEqual(fd.fill_ir3_from_curves({}, curves)["GBP"], {"2026-02": 3.7, "2026-03": 3.85})


class EnergyDriverTest(unittest.TestCase):
    def test_energy_driver(self):
        self.assertEqual(fd.energy_driver(0.35, 0.10), "olje")
        self.assertEqual(fd.energy_driver(-0.05, -0.30), "gass")   # fortegn spiller ingen rolle
        self.assertEqual(fd.energy_driver(0.25, 0.20), "begge")
        self.assertEqual(fd.energy_driver(0.25, None), "olje")
        self.assertEqual(fd.energy_driver(None, 0.2), "gass")
        self.assertIsNone(fd.energy_driver(None, None))


class ManualFilesStatusTest(unittest.TestCase):
    def test_meetings_status(self):
        meetings = {"_kommentar": "x", "us": ["2026-09-16", "2026-10-28"], "nz": ["2026-10-28", "2026-11-25"]}
        st = fd.meetings_status(meetings, "2026-09-25", "2026-09-25")
        self.assertTrue(st["ok"])
        self.assertEqual(st["valid_until"], "2026-10-28")
        self.assertIn("us går tom", st["warn"])  # 33 dager igjen < 45
        far = {"us": ["2027-06-01"], "nz": ["2027-03-01"]}
        self.assertIsNone(fd.meetings_status(far, "2026-09-25")["warn"])
        gone = fd.meetings_status({"us": ["2026-09-16"], "nz": ["2027-03-01"]}, "2026-09-25")
        self.assertFalse(gone["ok"])
        self.assertIn("us", gone["error"])
        self.assertFalse(fd.meetings_status({"_kommentar": "x"}, "2026-09-25")["ok"])

    def test_overrides_and_odds_and_cb_paths_status(self):
        ov = {"_kommentar": "x", "no": {"date": "2026-09-23", "rate": 4.5, "as_of": "2026-09-23"}, "jp": {"date": "2026-09-18", "rate": 1.25}}
        st = fd.overrides_status(ov, {"no": "brukt", "jp": "bekreftet"}, "2026-09-25")
        self.assertEqual((st["latest"], st["entries"]), ("2026-09-23", 2))
        self.assertIn("jp er bekreftet", st["note"]); self.assertIsNone(st["warn"])  # rydding er merknad, ikke varsel
        self.assertIn("avviker", fd.overrides_status(ov, {"no": "avvik"}, "2026-09-25")["warn"])
        self.assertIsNone(fd.overrides_status(ov, {"no": "brukt"}, "2026-09-25")["warn"])
        odds = {"au": {"date": "2026-09-29", "bp": 23, "as_of": "2026-09-25"}, "ca": {"date": "2026-09-09", "bp": 13}, "gb": {"date": "2026-11-05", "bp": 20}}
        st = fd.meeting_odds_status(odds, {"gb"}, "2026-09-25")
        self.assertIsNone(st["warn"])
        self.assertIn("utgått", st["note"]); self.assertIn("ca", st["note"])
        self.assertIn("brukes ikke", st["note"]); self.assertIn("au", st["note"])
        self.assertIsNone(fd.meeting_odds_status({"_kommentar": "x"}, set(), "2026-09-25")["note"])
        paths = {"us": {"level": 4.1, "as_of": "2026-09-16", "valid_until": "2026-12-09"}, "nz": {"level": 3.28, "as_of": "2026-08-19", "valid_until": "2026-08-30"}}
        st = fd.cb_paths_status(paths, {"nz"}, "2026-09-25")
        self.assertEqual(st["latest"], "2026-08-19")
        self.assertIn("utløpt", st["warn"]); self.assertIn("nz", st["warn"])
        self.assertIsNone(fd.cb_paths_status(paths, {"us"}, "2026-09-25")["warn"])


if __name__ == "__main__":
    unittest.main()


class OverrideTest(unittest.TestCase):
    """Manuelt registrerte vedtak overstyrer serien til den har fått vedtaket med seg."""

    def test_override_within_grace(self):
        # Serien fører virkningsdato: 4,25 t.o.m. 24.9, vedtaket 4,50 annonsert 23.9
        series = {"2026-09-22": 4.25, "2026-09-23": 4.25, "2026-09-24": 4.25}
        ov = {"date": "2026-09-23", "rate": 4.5}
        out, st = fd.apply_policy_override(series, ov, "2026-09-25")
        self.assertEqual(st, "brukt")
        self.assertEqual((out["2026-09-22"], out["2026-09-23"], out["2026-09-24"]), (4.25, 4.5, 4.5))
        self.assertEqual(series["2026-09-24"], 4.25)  # original urørt
        # Serien har ikke nådd vedtaksdatoen ennå
        self.assertEqual(fd.apply_policy_override({"2026-09-20": 4.25}, ov, "2026-09-25")[1], "brukt")
        # curve_metrics ankrer på 4,50: flat kurve på 4,5 gir null priset endring
        m = fd.curve_metrics({"0.25": 4.5, "1": 4.5, "2": 4.5}, fd.latest(out)[1])
        self.assertEqual(m["implied"]["12m"], 0)

    def test_override_confirmed_or_conflicting(self):
        ov = {"date": "2026-09-23", "rate": 4.5}
        self.assertEqual(fd.apply_policy_override({"2026-09-24": 4.5}, ov, "2026-09-25")[1], "bekreftet")
        # Mer enn fem dager etter vedtaket viser serien fortsatt 4,25: serien vinner, fila avviker
        series = {"2026-09-24": 4.25, "2026-09-30": 4.25}
        out, st = fd.apply_policy_override(series, ov, "2026-10-01")
        self.assertEqual((st, out), ("avvik", series))
        # Uten egen serie (BIS eneste kilde) gjelder lengre slingringsmonn: 21 dager
        self.assertEqual(fd.apply_policy_override(series, ov, "2026-10-01", fd.OVERRIDE_GRACE_DAYS_BIS)[1], "brukt")
        # Fremtidig eller ufullstendig post ignoreres
        self.assertEqual(fd.apply_policy_override(series, {"date": "2026-10-05", "rate": 4.5}, "2026-10-01")[1], None)
        self.assertEqual(fd.apply_policy_override(series, {"date": "2026-09-23"}, "2026-10-01")[1], None)
        self.assertEqual(fd.apply_policy_override(series, None, "2026-10-01"), (series, None))


class PolicySourcesTest(unittest.TestCase):
    def test_merge_policy_official_wins_from_first_date(self):
        bis = {"2026-09-10": 4.25, "2026-09-15": 4.25, "2026-09-22": 4.25}
        official = {"2026-09-15": 4.25, "2026-09-25": 4.5}
        out = fd.merge_policy(bis, official)
        self.assertEqual(out, {"2026-09-10": 4.25, "2026-09-15": 4.25, "2026-09-22": 4.25, "2026-09-25": 4.5})
        # Trapp (ECB): endringsdato 12.3 gjelder for alle senere dager, også BIS-dager med annen verdi
        self.assertEqual(fd.merge_policy({"2026-03-11": 2.75, "2026-03-13": 2.75}, {"2026-03-12": 2.5}),
                         {"2026-03-11": 2.75, "2026-03-12": 2.5, "2026-03-13": 2.5})
        self.assertEqual(fd.merge_policy(bis, {}), bis)

    def test_unconfirmed_meeting(self):
        meetings = ["2026-08-13", "2026-09-23", "2026-11-05"]
        self.assertEqual(fd.unconfirmed_meeting(meetings, "2026-09-22", "2026-09-25"), "2026-09-23")
        self.assertIsNone(fd.unconfirmed_meeting(meetings, "2026-09-23", "2026-09-25"))
        self.assertIsNone(fd.unconfirmed_meeting(meetings, "2026-09-24", "2026-09-22"))  # møtet er ikke kommet
        self.assertEqual(fd.unconfirmed_meeting(meetings, None, "2026-09-25"), "2026-09-23")

    def test_expand_daily(self):
        out = fd.expand_daily({"2026-09-16": 2.5, "2026-09-23": 2.25}, "2026-09-25")
        self.assertEqual(out, {"2026-09-16": 2.5, "2026-09-17": 2.5, "2026-09-18": 2.5, "2026-09-21": 2.5, "2026-09-22": 2.5,
                               "2026-09-23": 2.25, "2026-09-24": 2.25, "2026-09-25": 2.25})  # helg hoppes over
        self.assertEqual(fd.expand_daily({}, "2026-09-25"), {})

    def test_parsers(self):
        nb = ('FREQ;Frequency;TIME_PERIOD;OBS_VALUE;CALC_METHOD\nB;Business;2026-09-23;4.25;\nB;Business;2026-09-24;4.25;\n')
        self.assertEqual(fd.parse_norges_bank_policy(nb), {"2026-09-23": 4.25, "2026-09-24": 4.25})
        valet = {"observations": [{"d": "2026-09-24", "V39079": {"v": "2.25"}}, {"d": "2026-09-23", "V39079": {"v": None}}]}
        self.assertEqual(fd.parse_valet(valet, "V39079"), {"2026-09-24": 2.25})
        ecb = "KEY,FREQ,TIME_PERIOD,OBS_VALUE,OBS_STATUS\nFM.B.U2.EUR.4F.KR.DFR.LEV,B,2025-03-12,2.5,A\n"
        self.assertEqual(fd.parse_ecb_csv(ecb), {"2025-03-12": 2.5})
        boe = "DATE,IUDBEDR\n23 Sep 2026,3.75\n24 Sep 2026,3.75\nrubbish,\n"
        self.assertEqual(fd.parse_boe_csv(boe), {"2026-09-23": 3.75, "2026-09-24": 3.75})


class BrentContractTest(unittest.TestCase):
    def test_front_rolls_to_next_when_front_is_stale(self):
        fut = {"front": {"2026-09-24": 105.3, "2026-09-25": 104.0}, "next": {"2026-09-24": 103.0, "2026-09-25": 102.5},
               "front_label": "nov", "next_label": "des"}
        self.assertEqual(fd.brent_front_and_next(fut), (fut["front"], "nov", fut["next"], "des"))
        fut["next"]["2026-09-30"] = 101.0  # front utløpt: neste kontrakt har nyere kurs
        front, label, nxt, nlabel = fd.brent_front_and_next(fut)
        self.assertEqual((label, nxt, nlabel), ("des", {}, None))
        self.assertEqual(front, fut["next"])
        self.assertEqual(fd.brent_front_and_next({"front": {}, "next": {}, "front_label": "a", "next_label": "b"})[0], {})

    def test_premium_series_and_trailing_mean(self):
        dated = {"2026-09-18": 118.0, "2026-09-19": 117.0, "2026-09-22": 114.89}
        fut = {"2026-09-18": 104.0, "2026-09-22": 99.25, "2026-09-25": 105.3}
        prem = fd.premium_series(dated, fut)
        self.assertEqual(prem, {"2026-09-18": 14.0, "2026-09-22": 15.64})  # bare felles datoer
        self.assertEqual(fd.trailing_mean(prem), 14.82)
        self.assertEqual(fd.trailing_mean({"2026-06-01": 2.0, "2026-09-22": 16.0}), 16.0)  # 1. juni er utenfor 90 dager
        self.assertIsNone(fd.trailing_mean({}))
        self.assertEqual(fd.brent_label("BZX26.NYM"), "nov. 2026-kontrakten (BZX26)")
        self.assertEqual(fd.brent_label("TTFV26.NYM"), "okt. 2026-kontrakten (TTFV26)")
        from datetime import date as d
        self.assertEqual(fd.ttf_front_contracts(d(2026, 9, 25)), ["TTFV26.NYM", "TTFX26.NYM"])
        self.assertEqual(fd.ttf_front_contracts(d(2026, 12, 15)), ["TTFF27.NYM", "TTFG27.NYM"])
        self.assertEqual(fd.month_contracts("BZ", 2, d(2026, 11, 30), count=3), ["BZF27.NYM", "BZG27.NYM", "BZH27.NYM"])

    def test_front_contract_rolls_after_expiry(self):
        from datetime import date as d
        self.assertEqual(fd.brent_front_contracts(d(2026, 9, 25)), ["BZX26.NYM", "BZZ26.NYM"])
        self.assertEqual(fd.brent_front_contracts(d(2026, 10, 1)), ["BZZ26.NYM", "BZF27.NYM"])
        self.assertEqual(fd.brent_front_contracts(d(2026, 11, 30))[0], "BZF27.NYM")
