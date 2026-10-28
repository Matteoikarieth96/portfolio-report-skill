#!/usr/bin/env python3
"""Step 1: read the Fineco export and download from Yahoo Finance the symbol, sector
and daily price history (3 years) of every security and of a few market factors.

Usage:  python fetch.py "/path/portafoglio-export.xls" [--workspace DIR]
Writes data/holdings.json, data/yahoo.json and posizioni.csv (cleaned export).
"""
import csv
import datetime as dt
import io
import json
import math
import os
import pathlib
import re
import subprocess
import sys
import tempfile
import time
import urllib.parse


ROOT = pathlib.Path(__file__).resolve().parent

def _workspace():
    """Folder with portfolio_meta.json, data/ and the outputs: --workspace DIR, else the current folder."""
    a = sys.argv
    if "--workspace" in a:
        k = a.index("--workspace") + 1
        if k >= len(a) or a[k].startswith("--"):
            raise SystemExit("--workspace needs a folder")
        return pathlib.Path(a[k]).expanduser().resolve()
    return pathlib.Path.cwd()


WS = _workspace()
DATA = WS / "data"
META_FILE = WS / "portfolio_meta.json"
# Yahoo answers 429 to a full browser user agent without cookies, not to this one
UA = {"User-Agent": "Mozilla/5.0"}

# Yahoo symbol for the price history. US stocks bought in Milan in euros (symbols like 1XYZ.MI)
# use the main listing in dollars, then converted to euros: it is the same security.
# None = to be found with the ISIN search.
def _load_yahoo():
    if not META_FILE.exists():
        return {}
    sec = json.loads(META_FILE.read_text())["securities"]
    return {i: v.get("yahoo") for i, v in sec.items()}


YAHOO = _load_yahoo()
# Market factors used to measure the dependencies
FACTORS = {"MSCI World": "EUNL.DE", "Nasdaq 100": "QQQ", "Bitcoin": "BTC-EUR",
           "Gold": "GC=F", "Euro Stoxx 50": "^STOXX50E", "FTSE MIB": "FTSEMIB.MI",
           "EURUSD": "EURUSD=X"}

# keys = column headers of the broker's export file (in Italian): they must match it
COLS = {"Titolo": "name", "ISIN": "isin", "Simbolo": "fineco_symbol", "Mercato": "market",
        "Strumento": "kind", "Valuta": "ccy", "Quantità": "qty",
        "P.zo medio di carico": "avg_price", "Cambio di carico": "fx_cost",
        "Valore di carico": "cost_eur", "P.zo di mercato": "price",
        "Cambio di mercato": "fx_mkt", "Valore di mercato €": "value_eur",
        "Var%": "pnl_pct", "Var €": "pnl_eur", "Var in valuta": "pnl_ccy", "Rateo": "accrued"}
NUM = ("qty", "avg_price", "fx_cost", "cost_eur", "price", "fx_mkt", "value_eur",
       "pnl_pct", "pnl_eur", "pnl_ccy", "accrued")
# what a Yahoo symbol looks like (used with fullmatch: no trailing newline; never "." or "..")
SYMBOL = re.compile(r"[A-Za-z0-9^][A-Za-z0-9.=^-]{0,19}")


def clean(x):
    """Text from the export or from Yahoo, without control characters (terminal escapes)."""
    return "".join(ch for ch in str(x) if ch.isprintable())


def to_float(v):
    """Numbers from the export: floats, or text in Italian ("1.000,5") or English format."""
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        x = float(v)
    else:
        t = str(v).strip().replace("€", "").replace("%", "").replace(" ", "").replace("\u00a0", "")
        if t.lower() in ("", "-", "n.d.", "nd", "n/a"):
            return None
        if "," in t or re.fullmatch(r"[+-]?\d{1,3}(\.\d{3})+", t):  # Italian: "1.000,5", "1.000"
            t = t.replace(".", "").replace(",", ".")
        try:
            x = float(t)
        except ValueError:
            raise SystemExit(f"Not a number in the export: {clean(v)!r}")
    if not math.isfinite(x):
        raise SystemExit(f"Not a finite number in the export: {clean(v)!r}")
    return x


def csv_cell(v):
    """posizioni.csv opens in spreadsheets: text that starts like a formula gets a leading quote."""
    return "'" + v if isinstance(v, str) and v[:1] in ("=", "+", "-", "@", "\t", "\r") else v


def write_out(path, text):
    """Write a workspace file: refuse symlinks and paths outside the workspace, replace atomically."""
    path = pathlib.Path(path)
    for p in (path, path.parent):
        if p.is_symlink():
            raise SystemExit(f"Refusing to write through a symlink: {p}")
    if not path.resolve().is_relative_to(WS.resolve()):
        raise SystemExit(f"Refusing to write outside the workspace: {path}")
    # random temp name created with O_EXCL: a planted file or symlink at that name makes it fail, not follow
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        pathlib.Path(tmp).unlink(missing_ok=True)
        raise


def parse_table(cells):
    """cells: the export's first sheet as a list of rows (lists of cell values).
    Finds the header row (first cell "Titolo"), stops at the "Totale" or "EUR" summary row."""
    head = next((r for r, row in enumerate(cells) if row and str(row[0]).strip() == "Titolo"), None)
    if head is None:
        raise SystemExit("No header row starting with 'Titolo': is this a Fineco portfolio export?")
    names = [str(c).strip() for c in cells[head]]
    lost = [k for k in ("Titolo", "ISIN", "Strumento", "Valuta", "Valore di carico", "Valore di mercato €")
            if k not in names]
    if lost:
        raise SystemExit("Columns missing from the export: " + ", ".join(lost))
    rows = []
    for row in cells[head + 1:]:
        first = str(row[0]).strip() if row else ""
        if first in ("Totale", "EUR"):
            break
        if not first:
            continue
        rec = {COLS[n]: row[c] for c, n in enumerate(names) if n in COLS and c < len(row)}
        for k in NUM:
            rec[k] = to_float(rec.get(k))
        for k in ("name", "isin", "fineco_symbol", "market", "kind", "ccy"):
            rec[k] = clean(rec.get(k, "")).strip()
        for k, col in (("value_eur", "Valore di mercato €"), ("cost_eur", "Valore di carico")):
            if rec[k] is None:
                raise SystemExit(f"Empty '{col}' for {rec['name'] or rec['isin']}: the export looks incomplete.")
        rows.append(rec)
    return rows


def read_holdings(path):
    import xlrd
    path = pathlib.Path(path)
    if not path.is_file():
        raise SystemExit(f"Export file not found: {path}")
    try:
        sh = xlrd.open_workbook(str(path)).sheet_by_index(0)
    except Exception as e:  # xlrd 2 reads only the old .xls format
        raise SystemExit(f"Cannot read {path.name} as an .xls spreadsheet ({type(e).__name__}): "
                         "use the portfolio export from the Fineco web app, saved as .xls.")
    return parse_table([[sh.cell_value(r, c) for c in range(sh.ncols)] for r in range(sh.nrows)])


def new_isins(rows, known, assets):
    """ISINs in the export that portfolio_meta.json does not describe yet, once each."""
    new = []
    for r in rows:
        if r["isin"] not in known and r["isin"] not in [n["isin"] for n in new]:
            a = assets.get(r["isin"]) or {}
            new.append({"isin": r["isin"], "name": r["name"], "kind": r["kind"], "market": r["market"],
                        "yahoo_found": a.get("symbol"),
                        "sector": clean(a["sector"]) if a.get("sector") else None,
                        "industry": clean(a["industry"]) if a.get("industry") else None})
    return new


def http_json(url, tries=4):
    """GET with curl: Yahoo answers 429 to Python HTTP clients, not to curl."""
    code = ""
    for i in range(tries):
        # -q first: ignore ~/.curlrc; https only; no file over 50 MB
        p = subprocess.run(["curl", "-q", "-sS", "--proto", "=https", "--max-filesize", "50M", "-m", "25",
                            "-A", UA["User-Agent"], "-w", "\n%{http_code}", url], capture_output=True, text=True)
        body, _, code = p.stdout.rpartition("\n")
        if code == "200":
            try:
                return json.loads(body)
            except ValueError:
                raise RuntimeError(f"HTTP 200 from {url} but not JSON")
        if code in ("400", "404"):
            return None
        time.sleep((5 if code == "429" else 1.5) * (i + 1))
    err = clean(p.stderr.strip())[:200]
    raise RuntimeError(f"HTTP {code or '000'} from {url}" + (f" ({err})" if err else ""))


def search(q):
    """Yahoo search, used only if the expected symbol has no data (often rate-limited: 429)."""
    qs = urllib.parse.urlencode({"q": q, "quotesCount": 12, "newsCount": 0, "listsCount": 0})
    try:
        js = http_json("https://query2.finance.yahoo.com/v1/finance/search?" + qs, tries=2) or {}
    except RuntimeError:
        return []
    return [x for x in js.get("quotes", []) if x.get("symbol")]


def chart(sym, rng="3y"):
    if not sym or not SYMBOL.fullmatch(str(sym)):
        print("SKIP symbol that does not look like a Yahoo symbol:", repr(clean(sym))[:40])
        return None
    url = ("https://query1.finance.yahoo.com/v8/finance/chart/" + urllib.parse.quote(sym, safe="")
           + f"?range={rng}&interval=1d&includeAdjustedClose=true&events=div%2Csplits")
    try:
        js = http_json(url)
    except RuntimeError as e:
        print("NETWORK", e)
        return None
    try:
        res = js["chart"]["result"][0]
        ts = res.get("timestamp") or []
        meta = res["meta"]
        close = res["indicators"]["quote"][0].get("close") or []
        adj = (res["indicators"].get("adjclose") or [{}])[0].get("adjclose") or close
    except (TypeError, KeyError, IndexError, AttributeError):
        return None
    if not ts or not isinstance(meta, dict):
        return None
    try:
        off = meta.get("gmtoffset") or 0
        dates, c_out, a_out = [], [], []
        for t, c, a in zip(ts, close, adj):
            if c is None or a is None:
                continue
            c, a = float(c), float(a)
            d = dt.datetime.fromtimestamp(t + off, dt.timezone.utc).date().isoformat()
            if dates and dates[-1] == d:  # same day twice: keep the last one
                c_out[-1], a_out[-1] = c, a
                continue
            dates.append(d)
            c_out.append(c)
            a_out.append(a)
    except (TypeError, ValueError, OverflowError, OSError, AttributeError):
        return None
    return {"symbol": sym, "currency": meta.get("currency"), "exchange": meta.get("exchangeName"),
            "type": meta.get("instrumentType"),
            "name": meta.get("longName") or meta.get("shortName"),
            "last": meta.get("regularMarketPrice"), "dates": dates, "close": c_out, "adj": a_out}


def pick(kind, quotes, guess):
    """Try the expected symbol, then the listings found by ISIN in order of preference."""
    order = (["MIL", "GER", "AMS", "PAR", "FRA", "EBS", "LSE"] if kind == "ETF"
             else ["NMS", "NYQ", "NGM", "NCM", "ASE", "MIL", "GER", "AMS", "PAR"])
    ranked = sorted(quotes, key=lambda q: order.index(q["exchange"]) if q.get("exchange") in order else 99)
    cands = [guess] if guess else []
    cands += [q["symbol"] for q in ranked if q["symbol"] not in cands and SYMBOL.fullmatch(str(q["symbol"]))]
    for s in cands:
        c = chart(s)
        if c and len(c["dates"]) > 5:
            return c
        time.sleep(0.3)
    return None


def sector_of(quotes, sym):
    best = (next((q for q in quotes if q.get("symbol") == sym and q.get("sector")), None)
            or next((q for q in quotes if q.get("sector")), None) or {})
    return (best.get("sectorDisp") or best.get("sector"),
            best.get("industryDisp") or best.get("industry"))


def main():
    args = [x for k, x in enumerate(sys.argv[1:], 1) if not x.startswith("--") and sys.argv[k - 1] != "--workspace"]
    if not args:
        raise SystemExit('Usage: fetch.py "<export.xls>" --workspace DIR')
    src = pathlib.Path(args[0]).expanduser()
    if DATA.is_symlink():
        raise SystemExit(f"Refusing to write through a symlink: {DATA}")
    DATA.mkdir(parents=True, exist_ok=True)
    rows = read_holdings(src)
    write_out(DATA / "holdings.json", json.dumps({"source": clean(src.name), "rows": rows}, indent=1, ensure_ascii=False))
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=list(COLS.values()), lineterminator="\n")
    w.writeheader()
    w.writerows({k: csv_cell(v) for k, v in r.items()} for r in rows)
    write_out(WS / "posizioni.csv", buf.getvalue())

    out = {"fetched": dt.datetime.now().isoformat(timespec="seconds"), "assets": {}, "factors": {}}
    for r in rows:
        isin = r["isin"]
        if isin in out["assets"]:  # same security bought on two markets
            continue
        guess = YAHOO.get(isin)
        c = chart(guess) if guess else None
        quotes = []
        if c is None or len(c["dates"]) <= 5:
            quotes = search(isin)
            c = pick(r["kind"], quotes, None)
        if c is None:
            print("NO DATA", isin, r["name"], clean(guess), "(analyze.py leaves it out and lists it)")
            continue
        c["sector"], c["industry"] = sector_of(quotes, c["symbol"])
        if not c["sector"] and r["kind"] != "ETF":
            c["sector"], c["industry"] = sector_of(search(c["symbol"]), c["symbol"])
        c["search"] = [{k: q.get(k) for k in ("symbol", "exchange", "quoteType", "longname")}
                       for q in quotes]
        out["assets"][isin] = c
        time.sleep(0.3)
    for label, sym in FACTORS.items():
        c = chart(sym)
        if c:
            out["factors"][label] = c
        else:
            print("NO FACTOR", label, sym)
    write_out(DATA / "yahoo.json", json.dumps(out))
    new = new_isins(rows, YAHOO, out["assets"])
    write_out(DATA / "new_isins.json", json.dumps(new, indent=1, ensure_ascii=False))
    if new:
        print(f"\nNEW ISIN not in portfolio_meta.json ({len(new)}): see data/new_isins.json")
        for n in new:
            print(f"  {n['isin']}  {n['kind']:8} {n['yahoo_found'] or 'NO DATA':12} {n['name']}")

    print(f"{'ISIN':13} {'Yahoo':10} {'val':4} {'days':>6} {'from':10} {'last':>9} "
          f"{'Fineco':>9}     sector / industry")
    seen = set()
    for r in rows:
        a = out["assets"].get(r["isin"])
        if not a or r["isin"] in seen:
            continue
        seen.add(r["isin"])
        price = f"{r['price']:>9.2f}" if r["price"] is not None else f"{'-':>9}"
        print(f"{r['isin']:13} {a['symbol']:10} {clean(a['currency'] or ''):4} {len(a['dates']):>6} "
              f"{a['dates'][0]:10} {a['close'][-1]:>9.2f} {price} {r['ccy']} "
              f"{clean(a.get('sector'))} / {clean(a.get('industry'))}")
    for label, f in out["factors"].items():
        print(f"factor {label:14} {f['symbol']:10} {len(f['dates'])} days from {f['dates'][0]}, "
              f"last {f['close'][-1]:.4f}")


if __name__ == "__main__":
    main()
