"""Tests for portfolio-report. Offline: they use the fictional demo workspace from make_demo.py.

Run from the repo root: python3 -m unittest discover -s tests -v"""
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

DASHES = ("\u2013", "\u2014")


def run(script, *args, cwd=None):
    return subprocess.run([sys.executable, str(SCRIPTS / script), *args], cwd=cwd,
                          capture_output=True, text=True, timeout=300)


class TestExportParsing(unittest.TestCase):
    HEAD = ["Titolo", "ISIN", "Simbolo", "Mercato", "Strumento", "Valuta", "Quantità",
            "P.zo medio di carico", "Valore di carico", "P.zo di mercato", "Valore di mercato €", "Var%"]

    def setUp(self):
        import fetch
        self.fetch = fetch

    def test_reads_rows_until_total(self):
        cells = [["Portafoglio"], [""], self.HEAD,
                 ["DEMO CLOUD SOFTWARE", "ZZ0000000101", "DMSFT", "DEMO", "Azione", "USD", 6, 95, 528, 120, 660, 25],
                 ["", "", "", "", "", "", "", "", "", "", "", ""],
                 ["DEMO WORLD ETF", "ZZ0000000201", "DMWLD", "DEMO", "ETF", "EUR", 15, 95, 1425, 100, 1500, 5.3],
                 ["Totale", "", "", "", "", "", "", "", 1953, "", 2160, ""],
                 ["NOT A HOLDING", "ZZ9", "", "", "", "", "", "", "", "", "", ""]]
        rows = self.fetch.parse_table(cells)
        self.assertEqual([r["isin"] for r in rows], ["ZZ0000000101", "ZZ0000000201"])
        self.assertEqual(rows[0]["qty"], 6.0)
        self.assertEqual(rows[1]["value_eur"], 1500.0)
        self.assertIsNone(rows[0]["fx_mkt"])  # column absent from this export

    def test_refuses_other_files(self):
        with self.assertRaises(SystemExit):
            self.fetch.parse_table([["Date", "Amount"], ["2026-01-01", 5]])
        with self.assertRaises(SystemExit):  # header found, required column missing
            self.fetch.parse_table([["Titolo", "ISIN"], ["X", "ZZ1"]])

    def test_italian_number_text_and_empty_price(self):
        cells = [self.HEAD, ["DEMO FOODS", "ZZ0000000104", "DMFOD", "DEMO", "Azione", "EUR", "1.000,5", "", "62,0", "",
                             "1.234,56", "-3,1"]]
        r = self.fetch.parse_table(cells)[0]
        self.assertEqual(r["qty"], 1000.5)
        self.assertEqual(r["value_eur"], 1234.56)
        self.assertIsNone(r["price"])
        with self.assertRaises(SystemExit):
            self.fetch.parse_table([self.HEAD, ["X", "ZZ1", "", "", "Azione", "EUR", "abc", "", 1, "", 1, 0]])

    def test_more_number_formats(self):
        f = self.fetch.to_float
        self.assertEqual(f("1.000"), 1000.0)        # Italian thousands
        self.assertEqual(f("12.345.678"), 12345678.0)
        self.assertEqual(f("1.5"), 1.5)
        self.assertIsNone(f("-"))
        self.assertIsNone(f("n.d."))
        for bad in ("nan", "inf", float("nan")):
            with self.assertRaises(SystemExit):
                f(bad)

    def test_empty_value_or_cost_stops_with_a_message(self):
        with self.assertRaises(SystemExit) as e:
            self.fetch.parse_table([self.HEAD, ["DEMO FOODS", "ZZ0000000104", "", "", "Azione", "EUR", 1, 1, "", 1, 1, 0]])
        self.assertIn("Valore di carico", str(e.exception))

    def test_non_xls_file_stops_with_a_message(self):
        with tempfile.TemporaryDirectory() as d:
            f = pathlib.Path(d) / "portafoglio.xls"
            f.write_text("<html>not a spreadsheet</html>")
            with self.assertRaises(SystemExit) as cm:
                self.fetch.read_holdings(f)
            self.assertIn(".xls", str(cm.exception))

    def test_control_characters_are_stripped(self):
        self.assertEqual(self.fetch.clean("Evil\x1b]0;title\x07 Corp\x1b[31m"), "Evil]0;title Corp[31m")
        rows = self.fetch.parse_table([self.HEAD, ["BAD\x1b[2J NAME", "ZZ9", "", "", "Azione", "EUR", 1, 1, 1, 1, 1, 0]])
        self.assertEqual(rows[0]["name"], "BAD[2J NAME")

    def test_symbols_are_checked_and_fully_encoded(self):
        self.assertIsNone(self.fetch.chart("../../v7/finance/quote?symbols=AAPL#"))
        self.assertIsNone(self.fetch.chart("A B"))
        seen = []
        orig = self.fetch.http_json
        self.fetch.http_json = lambda url, tries=4: seen.append(url) or None
        try:
            self.assertIsNone(self.fetch.chart("BRK-B"))
            self.assertIsNone(self.fetch.chart("^STOXX50E"))
        finally:
            self.fetch.http_json = orig
        self.assertTrue(seen[0].startswith("https://query1.finance.yahoo.com/v8/finance/chart/BRK-B?"))
        self.assertIn("/chart/%5ESTOXX50E?", seen[1])
        for bad in ("..", ".", "AAPL\n", "-X", "=X"):
            self.assertIsNone(self.fetch.chart(bad), bad)
        self.assertEqual(len(seen), 2)  # none of them reached the network

    def test_malformed_yahoo_reply_is_no_data(self):
        orig = self.fetch.http_json
        try:
            for reply in ({"chart": {"result": [{"timestamp": [1]}]}}, {"chart": {"result": [None]}}, ["x"]):
                self.fetch.http_json = lambda url, tries=4, r=reply: r
                self.assertIsNone(self.fetch.chart("DMSFT"))
            q = {"quote": [{"close": [1.0]}]}
            for ts, meta in ((["x"], {}), ([1e20], {}), ([1], [])):
                reply = {"chart": {"result": [{"timestamp": ts, "meta": meta, "indicators": q}]}}
                self.fetch.http_json = lambda url, tries=4, r=reply: r
                self.assertIsNone(self.fetch.chart("DMSFT"))
        finally:
            self.fetch.http_json = orig

    def test_non_json_reply_is_a_network_error(self):
        import subprocess as sp
        orig = sp.run
        sp.run = lambda *a, **k: sp.CompletedProcess(a, 0, "<html>rate limited</html>\n200", "")
        try:
            with self.assertRaises(RuntimeError):
                self.fetch.http_json("https://query1.finance.yahoo.com/x", tries=1)
            self.assertIsNone(self.fetch.chart("DMSFT"))
            self.assertEqual(self.fetch.search("ZZ0000000101"), [])
        finally:
            sp.run = orig

    def test_write_out_does_not_follow_a_planted_temp_link(self):
        d = pathlib.Path(tempfile.mkdtemp())
        try:
            victim = d / "victim.txt"
            victim.write_text("precious")
            ws = d / "ws"
            ws.mkdir()
            for pid in range(os.getpid() - 50, os.getpid() + 50):
                (ws / f".out.json.tmp-{pid}").symlink_to(victim)
            orig = self.fetch.WS
            self.fetch.WS = ws
            try:
                self.fetch.write_out(ws / "out.json", "new")
            finally:
                self.fetch.WS = orig
            self.assertEqual(victim.read_text(), "precious")
            self.assertFalse((ws / "out.json").is_symlink())
            self.assertEqual((ws / "out.json").read_text(), "new")
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_csv_formulas_are_quoted(self):
        self.assertEqual(self.fetch.csv_cell("=HYPERLINK(1)"), "'=HYPERLINK(1)")
        self.assertEqual(self.fetch.csv_cell("@SUM(A1)"), "'@SUM(A1)")
        self.assertEqual(self.fetch.csv_cell("DEMO FOODS"), "DEMO FOODS")
        self.assertEqual(self.fetch.csv_cell(-3.1), -3.1)

    def test_new_isins_listed_once(self):
        rows = [{"isin": "ZZ1", "name": "A", "kind": "Azione", "market": "M"},
                {"isin": "ZZ1", "name": "A", "kind": "Azione", "market": "N"},
                {"isin": "ZZ2", "name": "B", "kind": "ETF", "market": "M"}]
        new = self.fetch.new_isins(rows, {"ZZ2": "B.MI"}, {"ZZ1": {"symbol": "A", "sector": "Technology"}})
        self.assertEqual(len(new), 1)
        self.assertEqual(new[0]["isin"], "ZZ1")
        self.assertEqual(new[0]["yahoo_found"], "A")


class TestDemoBuild(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.ws = pathlib.Path(cls.tmp) / "ws"
        r = run("make_demo.py", "--out", str(cls.ws))
        assert r.returncode == 0, r.stderr
        cls.build = run("analyze.py", "--workspace", str(cls.ws))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_build_succeeds(self):
        self.assertEqual(self.build.returncode, 0, self.build.stderr[-2000:])
        for f in ("report.html", "onepager.html", "data/analysis.json"):
            self.assertTrue((self.ws / f).exists(), f)

    def test_pages_have_data_charts_and_switch(self):
        for f in ("report.html", "onepager.html"):
            html = (self.ws / f).read_text()
            self.assertNotIn("__DATA__", html)
            self.assertNotIn("/*__CHARTS__*/", html)
            self.assertIn("hide-amounts", html)
            self.assertIn('id="hide-slot"', html)
            self.assertIn("not financial advice", html)

    def test_analysis_numbers_are_consistent(self):
        a = json.loads((self.ws / "data/analysis.json").read_text())
        self.assertEqual(a["totals"]["n_assets"], 14)
        self.assertAlmostEqual(sum(x["w"] for x in a["assets"]), 1.0, places=3)
        self.assertTrue(a["critique"]["weak"], "the critique should find weak points in the demo")
        # the alias in portfolio_meta.json maps the ETF's DMSFTX to the direct holding DMSFT
        sft = next(o for o in a["overlap"] if o["ticker"] == "DMSFT")
        self.assertEqual(sft["via"][0]["etf"], "DMWLD")
        self.assertTrue(a["demo"])
        self.assertEqual(a["no_prices"], [])

    def test_demo_pages_say_they_are_simulated(self):
        for f in ("report.html", "onepager.html"):
            html = (self.ws / f).read_text()
            self.assertIn("simulated prices", html)
            self.assertIn("Content-Security-Policy", html)

    def test_criteria_name_no_holding(self):
        a = json.loads((self.ws / "data/analysis.json").read_text())
        names = {x["name"] for x in a["assets"]} | {x["ticker"] for x in a["assets"]}
        for lv in a["critique"]["levers"]:
            for n in names:
                self.assertNotIn(n, lv["text"], lv["title"])

    def test_demo_refuses_a_folder_in_use(self):
        r = run("make_demo.py", "--out", str(self.ws))
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("new folder", r.stderr)
        self.assertTrue((self.ws / "report.html").exists())

    def test_holding_without_prices_is_left_out_and_listed(self):
        ws4 = pathlib.Path(self.tmp) / "ws4"
        shutil.copytree(self.ws, ws4)
        y = json.loads((ws4 / "data/yahoo.json").read_text())
        y["assets"].pop("ZZ0000000105")
        (ws4 / "data/yahoo.json").write_text(json.dumps(y))
        r = run("analyze.py", "--workspace", str(ws4))
        self.assertEqual(r.returncode, 0, r.stderr[-2000:])
        self.assertIn("NO PRICES", r.stdout)
        a = json.loads((ws4 / "data/analysis.json").read_text())
        self.assertEqual([x["isin"] for x in a["no_prices"]], ["ZZ0000000105"])
        self.assertEqual(a["totals"]["n_assets"], 13)
        self.assertEqual(a["totals"]["n_lines"], 13)
        self.assertAlmostEqual(sum(x["w"] for x in a["ccy_quote"]), 1.0, places=3)

    def test_symlinked_output_is_refused(self):
        ws5 = pathlib.Path(self.tmp) / "ws5"
        shutil.copytree(self.ws, ws5)
        victim = pathlib.Path(self.tmp) / "victim.txt"
        victim.write_text("precious")
        (ws5 / "onepager.html").unlink()
        (ws5 / "onepager.html").symlink_to(victim)
        r = run("analyze.py", "--workspace", str(ws5))
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("symlink", r.stderr)
        self.assertEqual(victim.read_text(), "precious")

    def test_extra_country_from_meta(self):
        ws6 = pathlib.Path(self.tmp) / "ws6"
        shutil.copytree(self.ws, ws6)
        meta = json.loads((ws6 / "portfolio_meta.json").read_text())
        meta["securities"]["ZZ0000000104"]["country"] = "Demo Union"
        meta["countries"] = {"Demo Union": ["Europe", "EUR"]}
        (ws6 / "portfolio_meta.json").write_text(json.dumps(meta))
        r = run("analyze.py", "--workspace", str(ws6))
        self.assertEqual(r.returncode, 0, r.stderr[-2000:])
        a = json.loads((ws6 / "data/analysis.json").read_text())
        foods = next(x for x in a["assets"] if x["isin"] == "ZZ0000000104")
        self.assertEqual(foods["country"], "Demo Union")
        self.assertIn("Europe", [r["k"] for r in a["regions"]])

    def test_malformed_countries_are_ignored(self):
        ws7 = pathlib.Path(self.tmp) / "ws7"
        shutil.copytree(self.ws, ws7)
        meta = json.loads((ws7 / "portfolio_meta.json").read_text())
        for bad in (["x"], "abc", {"Demo Union": "Europe"}):
            meta["countries"] = bad
            (ws7 / "portfolio_meta.json").write_text(json.dumps(meta))
            r = run("analyze.py", "--workspace", str(ws7))
            self.assertEqual(r.returncode, 0, r.stderr[-2000:])
            self.assertIn("ignored", r.stdout)

    def test_unknown_pnl_is_allowed(self):
        ws8 = pathlib.Path(self.tmp) / "ws8"
        shutil.copytree(self.ws, ws8)
        h = json.loads((ws8 / "data/holdings.json").read_text())
        h["rows"][0]["pnl_pct"] = None
        (ws8 / "data/holdings.json").write_text(json.dumps(h))
        r = run("analyze.py", "--workspace", str(ws8))
        self.assertEqual(r.returncode, 0, r.stderr[-2000:])

    def test_no_dashes_in_generated_text(self):
        text = (self.ws / "data/analysis.json").read_text()
        for d in DASHES:
            self.assertNotIn(d, text)
        for f in ("report_template.html", "onepager_template.html", "charts_extra.js", "hide_amounts.js"):
            body = (SCRIPTS / f).read_text()
            for d in DASHES:
                self.assertNotIn(d, body, f)

    def test_hostile_name_cannot_close_the_data_script(self):
        ws3 = pathlib.Path(self.tmp) / "ws3"
        shutil.copytree(self.ws, ws3)
        meta = json.loads((ws3 / "portfolio_meta.json").read_text())
        evil = "Evil</script><img src=x onerror=alert(1)><!--<script>"
        meta["securities"]["ZZ0000000101"]["name"] = evil
        (ws3 / "portfolio_meta.json").write_text(json.dumps(meta))
        r = run("analyze.py", "--workspace", str(ws3))
        self.assertEqual(r.returncode, 0, r.stderr[-2000:])
        for f in ("report.html", "onepager.html"):
            html = (ws3 / f).read_text()
            block = html.split('<script id="data" type="application/json">', 1)[1].split("</script>", 1)[0]
            self.assertNotIn("<", block)
            self.assertIn(evil, json.dumps(json.loads(block), ensure_ascii=False))

    def test_missing_security_stops_with_exit_2(self):
        ws2 = pathlib.Path(self.tmp) / "ws2"
        shutil.copytree(self.ws, ws2)
        meta = json.loads((ws2 / "portfolio_meta.json").read_text())
        meta["securities"].pop("ZZ0000000105")
        (ws2 / "portfolio_meta.json").write_text(json.dumps(meta))
        r = run("analyze.py", "--workspace", str(ws2))
        self.assertEqual(r.returncode, 2)
        self.assertIn("ZZ0000000105", r.stdout)


class TestFormats(unittest.TestCase):
    def setUp(self):
        self.cwd = os.getcwd()
        self.tmp = tempfile.mkdtemp()
        os.chdir(self.tmp)  # analyze reads portfolio_meta.json from the workspace, here an empty folder
        import analyze
        self.a = analyze

    def tearDown(self):
        os.chdir(self.cwd)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_industry_names(self):
        self.assertEqual(self.a.industry_name("Software\u2014Infrastructure"), "Software, infrastructure")
        self.assertEqual(self.a.industry_name("Oil & Gas Integrated"), "Oil and gas integrated")
        self.assertEqual(self.a.industry_name("REIT - Industrial"), "REIT, industrial")
        self.assertIsNone(self.a.industry_name(None))

    def test_euro_and_lists(self):
        self.assertEqual(self.a._seu(7.2), "+€7")
        self.assertEqual(self.a._seu(-243.4), "-€243")
        self.assertEqual(self.a._seu(0.3), "€0")
        self.assertEqual(self.a._seu(10636), "+€10,636")
        self.assertEqual(self.a._lst(["A", "B", "C"]), "A, B and C")
        self.assertEqual(self.a._lst(["A"]), "A")


@unittest.skipUnless(shutil.which("node"), "node not installed")
class TestHideAmounts(unittest.TestCase):
    def test_regex_masks_euros_not_percentages(self):
        js = (SCRIPTS / "hide_amounts.js").read_text()
        start = js.index("const RE = ") + len("const RE = ")
        regex = js[start:js.index(";", start)]
        probe = ("const RE=" + regex + ";const s=process.argv[1];"
                 "process.stdout.write(s.replace(RE,'€•••'))")
        sample = "Value €10,636, gain +€7, loss -€243, axis €10k, weight 17.6%, beta 1.18"
        out = subprocess.run(["node", "-e", probe, sample], capture_output=True, text=True, timeout=30).stdout
        self.assertNotRegex(out, r"€\s?\d")
        self.assertIn("17.6%", out)
        self.assertIn("1.18", out)
        self.assertEqual(out.count("€•••"), 4)


if __name__ == "__main__":
    unittest.main()
