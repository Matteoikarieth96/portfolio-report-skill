# Adding a new security to portfolio_meta.json

`fetch.py` writes the newcomers to `data/new_isins.json`. Each entry there has:
- isin, export name, kind, market;
- the Yahoo symbol it found by searching the ISIN, if any;
- the Yahoo sector and industry.

Add one entry per ISIN under `"securities"`:

```json
"US0000000000": {
  "name": "Short company or fund name",
  "ticker": "TICK",
  "yahoo": "TICK",
  "theme": "Semiconductors and AI",
  "country": "United States",
  "ccy": "USD",
  "desc": "One line on what the company does, or what the ETF holds."
}
```

## Fields

- **yahoo**: the symbol whose price history is used.
  - Stocks bought on an Italian or German exchange in euro: use the primary listing (`XYZ`, not `1XYZ.MI`). It is the same company, and the price is converted to euro.
  - ETFs: use a euro listing (`.MI`, `.DE`, `.PA`, `.AS`). Check that it has at least a year of history and that its last close is near the export's price.
  - `null` means search by ISIN every time. Avoid it.
- **ticker**: the short label used in every chart and table. It must be unique in the file.
- **theme**: reuse an existing theme whenever one fits, because themes are what the risk and value charts group by. Create a new one only when nothing fits, and name it in plain English (2 to 4 words). Read the current list with `"$PY" -I -c "import json,sys;print(sorted({v['theme'] for v in json.load(open(sys.argv[1]))['securities'].values()}))" "<ws>/portfolio_meta.json"` (`-I` keeps a stray `json.py` in the workspace from running).
- **country** and **ccy**: for stocks, the country and currency where the business is based, which is not necessarily the listing currency. For ETFs set both to `null`: country and currency then come from the look-through file. The country name must be one that `COUNTRY` in `scripts/analyze.py` knows (check with `grep -in '"<country>"' "$SKILL/scripts/analyze.py"`). If it is missing, add it to `portfolio_meta.json`, not to the code: `"countries": {"<Country>": ["<North America | Europe | Emerging markets | Asia-Pacific>", "<currency code>"]}`.
- **desc**: one factual line, no opinion, no em or en dashes.
- **etf_note** (ETFs only, optional): one or two lines on data quality, saying where the look-through came from, as of when, and anything partial. The report shows it on the ETF card.

## Cluster names

`cluster_names` is a list of `[ticker, name]` pairs. The analysis groups securities that move together. A group takes the name of the first pair whose ticker is in it. Groups that match no pair get a generic name. After a run, if a new group has a generic or misleading name, add a pair for it, naming it by what really drives it, for example `["DMNRG", "European cyclicals"]`.

## Ticker aliases

ETF holdings lists sometimes spell a company you hold directly with another ticker (another share class or listing, for example `ABCX` for `ABC`). Without help, the overlap check misses it. Add the pair to `ticker_aliases` in `portfolio_meta.json`: `{"ABCX": "ABC"}`, mapping the ETF's spelling to the `ticker` you use.
