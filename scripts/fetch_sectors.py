"""Sector prices (Select Sector SPDR ETFs, US market, in dollars) to measure how much
each sector moves with the portfolio. Only these tickers are sent to Yahoo.
Usage: .venv/bin/python fetch_sectors.py [--workspace DIR]  -> data/sectors_yahoo.json
The keys are the sector display names used by analyze.py."""
import json
import time
from pathlib import Path

from fetch import DATA, chart, write_out
SECTOR_ETF = {"Technology": "XLK", "Communication": "XLC", "Consumer discretionary": "XLY",
              "Consumer staples": "XLP", "Health care": "XLV", "Financials": "XLF",
              "Industrials": "XLI", "Energy": "XLE", "Utilities": "XLU", "Materials": "XLB",
              "Real estate": "XLRE"}


def main():
    out = {}
    for name, sym in SECTOR_ETF.items():
        c = chart(sym)
        if c:
            out[name] = c
            print(f"{name:24} {sym:5} {len(c['dates'])} days from {c['dates'][0]} ({c['currency']})")
        else:
            print("NO DATA", name, sym)
        time.sleep(0.3)
    write_out(DATA / "sectors_yahoo.json", json.dumps(out))


if __name__ == "__main__":
    main()
