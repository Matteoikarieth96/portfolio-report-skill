"""Build a fictional demo workspace with simulated prices, so analyze.py can run offline.

Usage: python make_demo.py --out DIR   (then: python analyze.py --workspace DIR)

Every company, fund, ISIN and price here is invented. ISINs use the unassigned
country code ZZ, prices are seeded random walks, nothing is fetched."""
import datetime as dt
import json
import pathlib
import sys

import numpy as np

END = dt.date(2026, 9, 30)
DAYS = 780
SEED = 7

FACTORS = {  # label: (symbol, currency, start level, yearly drift, yearly volatility)
    "MSCI World": ("DEMO-WORLD", "EUR", 100.0, 0.08, 0.13),
    "Nasdaq 100": ("DEMO-NDX", "USD", 400.0, 0.11, 0.20),
    "Bitcoin": ("DEMO-BTC", "EUR", 40000.0, 0.25, 0.55),
    "Gold": ("DEMO-GOLD", "USD", 2000.0, 0.12, 0.15),
    "Euro Stoxx 50": ("DEMO-SX5E", "EUR", 4300.0, 0.07, 0.15),
    "FTSE MIB": ("DEMO-MIB", "EUR", 29000.0, 0.09, 0.17),
    "EURUSD": ("DEMO-EURUSD", "USD", 1.08, 0.0, 0.07),
}

# isin, name, ticker, ccy, theme, country, factor loadings, idio vol, yahoo sector, industry, qty, avg price
# Every ticker starts with DM so that none can be a real listing.
STOCKS = [
    ("ZZ0000000101", "Demo Cloud Software", "DMSFT", "USD", "Software and retail", "United States",
     {"Nasdaq 100": 1.3}, 0.30, "Technology", "Software - Application", 14, 380.0),
    ("ZZ0000000102", "Demo Online Retail", "DMRTL", "USD", "Software and retail", "United States",
     {"Nasdaq 100": 1.1}, 0.30, "Consumer Cyclical", "Internet Retail", 20, 160.0),
    ("ZZ0000000103", "Demo Pharma", "DMPHA", "USD", "Health care", "United States",
     {"MSCI World": 0.6}, 0.20, "Healthcare", "Drug Manufacturers - General", 25, 90.0),
    ("ZZ0000000104", "Demo Foods", "DMFOD", "EUR", "Food and household", "France",
     {"Euro Stoxx 50": 0.5}, 0.16, "Consumer Defensive", "Packaged Foods", 30, 62.0),
    ("ZZ0000000105", "Demo Energy Group", "DMNRG", "EUR", "Energy and materials", "Spain",
     {"Euro Stoxx 50": 0.7}, 0.24, "Energy", "Oil & Gas Integrated", 120, 14.0),
    ("ZZ0000000106", "Demo Rail Freight", "DMRAIL", "EUR", "Transport", "Germany",
     {"Euro Stoxx 50": 0.9}, 0.22, "Industrials", "Railroads", 15, 85.0),
    ("ZZ0000000107", "Demo Insurance", "DMINS", "EUR", "Insurance", "Germany",
     {"Euro Stoxx 50": 0.9}, 0.18, "Financial Services", "Insurance - Diversified", 6, 260.0),
    ("ZZ0000000108", "Demo Telecom", "DMTEL", "EUR", "Telecoms and utilities", "Spain",
     {"Euro Stoxx 50": 0.6}, 0.18, "Communication Services", "Telecom Services", 400, 3.9),
    ("ZZ0000000109", "Demo Power Grid", "DMGRID", "EUR", "Telecoms and utilities", "Portugal",
     {"Euro Stoxx 50": 0.5}, 0.16, "Utilities", "Utilities - Regulated Electric", 250, 4.6),
    ("ZZ0000000110", "Demo Warehouse REIT", "DMREIT", "USD", "Real estate", "United States",
     {"MSCI World": 0.9}, 0.22, "Real Estate", "REIT - Industrial", 10, 115.0),
    ("ZZ0000000111", "Demo Chemicals", "DMCHM", "EUR", "Energy and materials", "Belgium",
     {"Euro Stoxx 50": 1.0}, 0.26, "Basic Materials", "Specialty Chemicals", 4, 70.0),
]
ETFS = [  # isin, name, ticker, theme, factor loadings, idio vol, qty, avg price
    ("ZZ0000000201", "Demo World Equity UCITS ETF", "DMWLD", "World equity",
     {"MSCI World": 1.0}, 0.02, 60, 98.0),
    ("ZZ0000000202", "Demo Emerging Markets UCITS ETF", "DMEM", "Emerging markets",
     {"MSCI World": 0.8}, 0.12, 80, 33.0),
    ("ZZ0000000203", "Demo Clean Energy UCITS ETF", "DMCLN", "Clean energy",
     {"Nasdaq 100": 0.6, "Euro Stoxx 50": 0.5}, 0.25, 90, 6.5),
]
SECTOR_ETF = ["Technology", "Communication", "Consumer discretionary", "Consumer staples", "Health care",
              "Financials", "Industrials", "Energy", "Utilities", "Materials", "Real estate"]


def dates():
    out, d = [], END
    while len(out) < DAYS:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d -= dt.timedelta(days=1)
    return out[::-1]


def walk(rng, start, drift, vol, n, shocks=None, load=None):
    r = rng.normal(drift / 252, vol / np.sqrt(252), n)
    if shocks is not None:
        for k, b in (load or {}).items():
            r = r + b * shocks[k]
    return start * np.exp(np.cumsum(r))


def chart(sym, ccy, ds, px, sector=None, industry=None, name=None):
    p = [round(float(x), 4) for x in px]
    return {"symbol": sym, "currency": ccy, "exchange": "DEMO", "type": "EQUITY", "name": name,
            "last": p[-1], "dates": ds, "close": p, "adj": p, "sector": sector, "industry": industry,
            "search": []}


def main():
    a = sys.argv
    if "--out" not in a or a.index("--out") + 1 >= len(a):
        raise SystemExit("Usage: make_demo.py --out NEW_FOLDER")
    out = pathlib.Path(a[a.index("--out") + 1]).expanduser()
    if out.is_symlink() or (out.exists() and (not out.is_dir() or any(out.iterdir()))):
        raise SystemExit(f"{out} already exists and is not an empty folder: the demo only goes into a new folder, "
                         "so it can never overwrite a real workspace.")
    out = out.resolve()
    (out / "data").mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(SEED)
    ds = dates()
    n = len(ds)

    fac, shocks = {}, {}
    to_world = {"Nasdaq 100": 1.2, "Bitcoin": 1.0, "Gold": 0.1, "Euro Stoxx 50": 0.9, "FTSE MIB": 1.0, "EURUSD": 0.0}
    for label, (sym, ccy, start, drift, vol) in FACTORS.items():
        b = to_world.get(label, 0.0)
        if label == "MSCI World":
            px = walk(rng, start, drift, vol, n)
        else:  # markets move together: part of each factor is the world market
            own = max(vol ** 2 - (b * FACTORS["MSCI World"][4]) ** 2, (0.3 * vol) ** 2) ** 0.5
            px = walk(rng, start, drift, own, n, {"MSCI World": shocks["MSCI World"]}, {"MSCI World": b})
        fac[label] = chart(sym, ccy, ds, px, name=f"Simulated {label}")
        shocks[label] = np.diff(np.log(np.r_[start, px]))
    eurusd = np.array(fac["EURUSD"]["close"])

    meta = {"_about": "Fictional demo portfolio: invented companies and funds, simulated prices.", "demo": True,
            "securities": {}, "cluster_names": [["DMSFT", "Software and retail"], ["DMNRG", "European cyclicals"]],
            "ticker_aliases": {"DMSFTX": "DMSFT"}}
    assets, rows = {}, []

    def add(isin, name, ticker, kind, ccy, theme, country, load, ivol, sector, industry, qty, avg, desc):
        start = avg * float(rng.uniform(0.8, 1.1))
        px = walk(rng, start, 0.02, ivol, n, shocks, load)
        assets[isin] = chart(ticker, ccy, ds, px, sector, industry, name)
        price = float(px[-1])
        fx = float(eurusd[-1]) if ccy == "USD" else 1.0
        value = qty * price / fx
        cost = qty * avg / (1.08 if ccy == "USD" else 1.0)
        rows.append({"name": name.upper(), "isin": isin, "fineco_symbol": ticker, "market": "DEMO",
                     "kind": kind, "ccy": ccy, "qty": float(qty), "avg_price": avg,
                     "fx_cost": 1.08 if ccy == "USD" else 1.0, "cost_eur": round(cost, 2), "price": round(price, 4),
                     "fx_mkt": round(fx, 4), "value_eur": round(value, 2),
                     "pnl_pct": round((value / cost - 1) * 100, 2), "pnl_eur": round(value - cost, 2),
                     "pnl_ccy": None, "accrued": None})
        meta["securities"][isin] = {"name": name, "ticker": ticker, "yahoo": ticker, "theme": theme,
                                    "country": country, "ccy": None if kind == "ETF" else ccy, "desc": desc}

    for isin, name, tk, ccy, theme, country, load, ivol, sector, ind, qty, avg in STOCKS:
        add(isin, name, tk, "Azione", ccy, theme, country, load, ivol, sector, ind, qty, avg,
            f"Fictional company used in the demo ({ind.lower()}).")
    for isin, name, tk, theme, load, ivol, qty, avg in ETFS:
        add(isin, name, tk, "ETF", "EUR", theme, None, load, ivol, None, None, qty, avg,
            "Fictional ETF used in the demo.")
        meta["securities"][isin]["etf_note"] = "Demo look-through, invented weights."

    etfs = {"etfs": [
        {"isin": "ZZ0000000201", "name": "Demo World Equity UCITS ETF", "ticker_eu": "DMWLD", "index": "Demo World Index",
         "ter_pct": 0.20, "launch_date": "2015-03-01", "aum": {"value": 4.2e9, "currency": "EUR", "as_of": "2026-09-30"},
         "n_holdings": 1400, "replication": "Physical", "distribution": "Accumulating",
         "top_holdings": [{"name": "Demo Cloud Software", "ticker": "DMSFTX", "country": "United States", "weight_pct": 4.1},
                          {"name": "Demo Online Retail", "ticker": "DMRTL", "country": "United States", "weight_pct": 3.2},
                          {"name": "Demo Megastore", "ticker": "DMMEG", "country": "United States", "weight_pct": 2.4}],
         "sectors": {"Information Technology": 26, "Financials": 15, "Health Care": 11, "Industrials": 11,
                     "Consumer Discretionary": 10, "Communication Services": 8, "Consumer Staples": 6, "Energy": 4,
                     "Materials": 4, "Utilities": 3, "Real Estate": 2},
         "sectors_source": "official",
         "countries": {"United States": 70, "Japan": 6, "United Kingdom": 4, "Canada": 3, "France": 3,
                       "Germany": 3, "Switzerland": 3, "Other": 8},
         "countries_source": "official",
         "overlap_with_direct": [{"ticker": "DMSFTX", "weight_pct": 4.1}, {"ticker": "DMRTL", "weight_pct": 3.2}],
         "overlap_checked": "top10", "as_of": "2026-09-30", "sources": ["https://example.com/demo-world"],
         "notes": "Invented for the demo."},
        {"isin": "ZZ0000000202", "name": "Demo Emerging Markets UCITS ETF", "ticker_eu": "DMEM", "index": "Demo Emerging Index",
         "ter_pct": 0.18, "launch_date": "2017-09-01", "aum": {"value": 1.5e9, "currency": "EUR", "as_of": "2026-09-30"},
         "n_holdings": 1200, "replication": "Sampled", "distribution": "Accumulating",
         "top_holdings": [{"name": "Demo Foundry Asia", "ticker": "DMFAS", "country": "Taiwan", "weight_pct": 8.0},
                          {"name": "Demo Super App", "ticker": "DMAPP", "country": "China", "weight_pct": 4.0}],
         "sectors": {"Information Technology": 24, "Financials": 22, "Consumer Discretionary": 13, "Communication Services": 9,
                     "Materials": 7, "Industrials": 7, "Energy": 5, "Consumer Staples": 5, "Health Care": 4,
                     "Utilities": 2, "Real Estate": 2},
         "sectors_source": "official",
         "countries": {"China": 26, "India": 19, "Taiwan": 18, "South Korea": 10, "Brazil": 5, "Saudi Arabia": 4,
                       "South Africa": 3, "Mexico": 2, "Other": 13},
         "countries_source": "official", "overlap_with_direct": [], "overlap_checked": "full", "as_of": "2026-09-30",
         "sources": ["https://example.com/demo-emerging"], "notes": "Invented for the demo."},
        {"isin": "ZZ0000000203", "name": "Demo Clean Energy UCITS ETF", "ticker_eu": "DMCLN", "index": "Demo Clean Energy Index",
         "ter_pct": 0.45, "launch_date": "2025-03-01", "aum": {"value": 6.0e7, "currency": "EUR", "as_of": "2026-09-30"},
         "n_holdings": 50, "replication": "Physical", "distribution": "Accumulating",
         "top_holdings": [{"name": "Demo Power Grid", "ticker": "DMGRID", "country": "Portugal", "weight_pct": 5.0},
                          {"name": "Demo Solar Works", "ticker": "DMSOL", "country": "United States", "weight_pct": 4.5}],
         "sectors": {"Utilities": 45, "Industrials": 30, "Information Technology": 20, "Cash/Other": 5},
         "sectors_source": "secondary",
         "countries": {"United States": 40, "Spain": 12, "Portugal": 10, "Denmark": 10, "China": 10, "Other": 18},
         "countries_source": "secondary", "overlap_with_direct": [{"ticker": "DMGRID", "weight_pct": 5.0}],
         "overlap_checked": "partial", "as_of": "2026-09-30", "sources": ["https://example.com/demo-clean"],
         "notes": "Invented for the demo."},
    ]}

    sectors = {}
    for i, s in enumerate(SECTOR_ETF):
        load = {"Nasdaq 100": 0.9} if s in ("Technology", "Communication") else {"MSCI World": 0.6 + 0.05 * i}
        sectors[s] = chart(f"DEMO-S{i}", "USD", ds, walk(rng, 50.0, 0.03, 0.12, n, shocks, load))

    d = out / "data"
    (out / "portfolio_meta.json").write_text(json.dumps(meta, indent=1))
    (d / "holdings.json").write_text(json.dumps({"source": "demo-export.xls", "rows": rows}, indent=1))
    (d / "yahoo.json").write_text(json.dumps({"fetched": END.isoformat() + "T18:00:00", "assets": assets,
                                              "factors": fac}))
    (d / "etf_demo.json").write_text(json.dumps(etfs, indent=1))
    (d / "sectors_yahoo.json").write_text(json.dumps(sectors))
    print(f"Demo workspace written to {out} ({len(rows)} fictional holdings, simulated prices)")


if __name__ == "__main__":
    main()
