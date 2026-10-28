#!/usr/bin/env python3
"""Step 2: compute the portfolio analysis and build report.html.

Usage:  python analyze.py [--workspace DIR]
Reads data/holdings.json and data/yahoo.json (from fetch.py), the ETF data in data/etf_*.json
(if present) and the templates; writes data/analysis.json, report.html and onepager.html.
"""
import builtins
import datetime as dt
import json
import math
import os
import pathlib
import tempfile
from decimal import ROUND_HALF_UP, Decimal

import numpy as np
import pandas as pd
from scipy.cluster.hierarchy import fcluster, leaves_list, linkage
from scipy.spatial.distance import squareform

import sys

ROOT = pathlib.Path(__file__).resolve().parent

def _workspace():
    """Folder with portfolio_meta.json, data/ and the outputs: --workspace DIR, else the current folder."""
    a = sys.argv
    if "--workspace" in a:
        k = a.index("--workspace") + 1
        if k >= len(a) or a[k].startswith("--"):
            raise SystemExit("--workspace needs a folder")
        ws = pathlib.Path(a[k]).expanduser().resolve()
        if not ws.is_dir():
            raise SystemExit(f"Workspace folder not found: {ws}")
        return ws
    return pathlib.Path.cwd()


WS = _workspace()
DATA = WS / "data"
META_FILE = WS / "portfolio_meta.json"
WEEKS = 104         # window: 2 years of weekly returns in euros
MIN_WEEKS = 12      # below this overlap the correlation is not shown
SHORT = 52          # less than a year of history: flagged as "short history"
CLUSTER_CUT = 0.55  # distance sqrt((1-rho)/2); 0.55 means an average correlation above ~0.4

# Per-security data lives in the workspace (portfolio_meta.json), not in the code.
# META[isin] = (name, ticker, theme, country, currency of the business, description); for ETFs
# country and currency are None and come from the look-through files data/etf_*.json.
_M = json.loads(META_FILE.read_text()) if META_FILE.exists() else {"securities": {}, "cluster_names": []}
META = {i: (v["name"], v["ticker"], v["theme"], v.get("country"), v.get("ccy"), v.get("desc") or "")
        for i, v in _M["securities"].items()}
NOTE_IT = {i: v["etf_note"] for i, v in _M["securities"].items() if v.get("etf_note")}
# cluster names: the first listed ticker found in a cluster gives it its name
CLUSTER_NAMES = [tuple(x) for x in _M.get("cluster_names", [])]
# other spellings of the same ticker in ETF holdings lists (another share class or listing),
# mapped to the ticker used in portfolio_meta.json: {"ABCX": "ABC"}. Used for the overlap check.
ALIAS = {str(k).upper(): str(v).upper() for k, v in _M.get("ticker_aliases", {}).items()}
# instrument type from the broker export ("Strumento" column) -> label used in the outputs
KIND = {"Azione": "Stock", "Azioni": "Stock"}
# the demo workspace says so in its meta file: the pages then say "fictional demo, simulated prices"
DEMO = bool(_M.get("demo"))

YAHOO_SECTOR = {"Technology": "Information Technology", "Communication Services": "Communication Services",
                "Consumer Cyclical": "Consumer Discretionary", "Consumer Defensive": "Consumer Staples",
                "Financial Services": "Financials", "Industrials": "Industrials",
                "Basic Materials": "Materials", "Utilities": "Utilities", "Energy": "Energy",
                "Healthcare": "Health Care", "Real Estate": "Real Estate"}
NOT_SPLIT = "ETF not broken down"
SECTOR_NAME = {"Information Technology": "Technology", "Communication Services": "Communication",
               "Consumer Discretionary": "Consumer discretionary", "Consumer Staples": "Consumer staples",
               "Financials": "Financials", "Industrials": "Industrials", "Materials": "Materials",
               "Utilities": "Utilities", "Energy": "Energy", "Health Care": "Health care",
               "Real Estate": "Real estate", "Cash/Other": "Cash and other",
               NOT_SPLIT: NOT_SPLIT}
SECTOR_KEYS = [("information", "Information Technology"), ("technology", "Information Technology"),
               ("semicond", "Information Technology"), ("communication", "Communication Services"),
               ("telecom", "Communication Services"), ("discretionary", "Consumer Discretionary"),
               ("cyclical", "Consumer Discretionary"), ("staples", "Consumer Staples"),
               ("defensive", "Consumer Staples"), ("financ", "Financials"), ("industr", "Industrials"),
               ("material", "Materials"), ("utilit", "Utilities"), ("energy", "Energy"),
               ("health", "Health Care"), ("real estate", "Real Estate"), ("cash", "Cash/Other"),
               ("other", "Cash/Other"), ("derivative", "Cash/Other")]
def industry_name(raw):
    """Yahoo industry ("Software\u2014Infrastructure", "Aerospace & Defense") -> plain label."""
    t = str(raw or "").strip()
    if not t:
        return None
    for sep in ("\u2014", "\u2013", " - "):
        t = t.replace(sep, ", ")
    t = t.replace(" & ", " and ")
    words = t.split(" ")
    return " ".join([words[0]] + [w if w.isupper() else w.lower() for w in words[1:]])


# country (English, or Italian from older meta files) -> (English name, region, currency)
NA, EU, EM, AP = "North America", "Europe", "Emerging markets", "Asia-Pacific"
COUNTRY = {
    "united states": ("United States", NA, "USD"), "usa": ("United States", NA, "USD"),
    "us": ("United States", NA, "USD"), "stati uniti": ("United States", NA, "USD"),
    "canada": ("Canada", NA, "CAD"), "brazil": ("Brazil", EM, "BRL"), "brasile": ("Brazil", EM, "BRL"),
    "united kingdom": ("United Kingdom", EU, "GBP"), "uk": ("United Kingdom", EU, "GBP"),
    "regno unito": ("United Kingdom", EU, "GBP"), "germany": ("Germany", EU, "EUR"),
    "germania": ("Germany", EU, "EUR"), "france": ("France", EU, "EUR"), "francia": ("France", EU, "EUR"),
    "italy": ("Italy", EU, "EUR"), "italia": ("Italy", EU, "EUR"),
    "netherlands": ("Netherlands", EU, "EUR"), "paesi bassi": ("Netherlands", EU, "EUR"),
    "spain": ("Spain", EU, "EUR"), "belgium": ("Belgium", EU, "EUR"),
    "finland": ("Finland", EU, "EUR"), "ireland": ("Ireland", EU, "EUR"),
    "austria": ("Austria", EU, "EUR"), "portugal": ("Portugal", EU, "EUR"),
    "luxembourg": ("Luxembourg", EU, "EUR"), "greece": ("Greece", EU, "EUR"),
    "switzerland": ("Switzerland", EU, "CHF"), "svizzera": ("Switzerland", EU, "CHF"),
    "denmark": ("Denmark", EU, "DKK"), "sweden": ("Sweden", EU, "SEK"),
    "norway": ("Norway", EU, "NOK"), "poland": ("Poland", EU, "PLN"),
    "japan": ("Japan", AP, "JPY"), "australia": ("Australia", AP, "AUD"),
    "new zealand": ("New Zealand", AP, "NZD"), "singapore": ("Singapore", AP, "SGD"),
    "hong kong": ("Hong Kong", AP, "HKD"), "china": ("China", EM, "CNY/HKD"),
    "taiwan": ("Taiwan", EM, "TWD"), "south korea": ("South Korea", EM, "KRW"),
    "korea": ("South Korea", EM, "KRW"), "korea, republic of": ("South Korea", EM, "KRW"),
    "india": ("India", EM, "INR"), "israel": ("Israel", EM, "ILS"),
    "south africa": ("South Africa", EM, "ZAR"), "sudafrica": ("South Africa", EM, "ZAR"),
    "chile": ("Chile", EM, "CLP"), "mexico": ("Mexico", EM, "MXN"),
    "indonesia": ("Indonesia", EM, "IDR"), "malaysia": ("Malaysia", EM, "MYR"),
    "thailand": ("Thailand", EM, "THB"), "saudi arabia": ("Saudi Arabia", EM, "SAR"),
    "peru": ("Peru", EM, "PEN"), "argentina": ("Argentina", EM, "ARS"),
}
REGIONS = {"north america": NA, "europe": EU, "emerging markets": EM, "asia-pacific": AP}
# extra countries for this portfolio, in portfolio_meta.json: {"countries": {"Name": ["Region", "CCY"]}}
_C = _M.get("countries") or {}
if not isinstance(_C, dict):
    print('portfolio_meta.json: "countries" must be an object like {"Name": ["Region", "CCY"]}: ignored')
    _C = {}
for _k, _v in _C.items():
    if not (isinstance(_v, (list, tuple)) and len(_v) == 2):
        print("portfolio_meta.json: country entry ignored (it needs [region, currency]):", _k)
    else:
        COUNTRY[str(_k).strip().lower()] = (str(_k).strip(), REGIONS.get(str(_v[0]).strip().lower(), "Other"),
                                            str(_v[1]).strip().upper()[:7])


def num(x, nd=4):
    if x is None:
        return None
    try:
        f = float(x)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(f) or math.isinf(f) else round(f, nd)


def norm_ticker(t):
    if not t:
        return ""
    t = str(t).strip().upper().split()[0].split(".")[0].split(":")[-1]
    return ALIAS.get(t, t)


def sector_key(label):
    s = str(label).lower()
    for key, gics in SECTOR_KEYS:
        if key in s:
            return gics
    return "Cash/Other"


def country_info(name):
    key = str(name).strip().lower()
    if key in COUNTRY:
        return COUNTRY[key]
    if "cash" in key or "other" in key or "altr" in key:
        return ("Cash and other", "Other", "Other")
    return (str(name).strip(), "Other", "Other")


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


def normalize(d):
    tot = sum(v for v in d.values() if v and v > 0)
    return {k: v / tot for k, v in d.items() if v and v > 0} if tot else {}


def load_etfs():
    etfs, companies = {}, []
    for f in sorted(DATA.glob("etf_*.json")):
        js = json.loads(f.read_text())
        for e in js.get("etfs", []):
            etfs[e.get("isin")] = e
        companies += js.get("companies", [])
    return etfs, companies


def series(d):
    s = pd.Series(d["adj"], index=pd.to_datetime(d["dates"]), dtype="float64")
    s = s[~s.index.duplicated(keep="last")].sort_index()
    return s[s > 0]


def pair_beta(x, y):
    d = pd.concat([x, y], axis=1).dropna()
    if len(d) < MIN_WEEKS:
        return None
    c = np.cov(d.iloc[:, 0], d.iloc[:, 1])
    return c[0, 1] / c[1, 1]


def max_dd(p):
    p = p.dropna()
    return float((p / p.cummax() - 1).min()) if len(p) > 1 else None


# ---- critical commentary: English text computed from the numbers, read by the report and the one-pager ----
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
CCY_SIGN = {"USD": "$", "EUR": "€", "GBP": "£"}
# first words of a theme that keep their capital letter inside a sentence
PROPER = {"AI", "US", "USA", "EU", "Europe", "European", "America", "American", "Asia", "Asian",
          "Brazil", "China", "Chinese", "Italy", "Italian", "Japan", "Japanese", "India", "Indian"}


def _num(x, d):
    """Number in en-GB format, rounded like Intl in JavaScript (half away from zero)."""
    q = Decimal(str(x)).quantize(Decimal(1).scaleb(-d), rounding=ROUND_HALF_UP)
    return f"{q:,.{d}f}"


def _pc(x, d=1):
    return _num(x * 100, d) + "%"


def _spc(x, d=1):
    return ("+" if x > 0 else "") + _pc(x, d)


def _seu(x):
    """Signed euro amount: +€7, -€243, €0."""
    r = round(x)
    return ("+" if r > 0 else "-" if r < 0 else "") + "€" + _num(abs(r), 0)


def _lc(t):
    """Theme name inside a sentence: lower-case first letter unless it starts with a proper noun or acronym."""
    first = t.split(" ")[0]
    return t if first in PROPER or first.isupper() else t[0].lower() + t[1:]


def _cap(s):
    return s[0].upper() + s[1:] if s else s


def _lst(a):
    a = list(a)
    return a[0] if len(a) == 1 else ", ".join(a[:-1]) + " and " + a[-1]


# titles of the weak points: the levers point back to them by title
W_CONC = "Risk is more concentrated than value"
W_SWING = "It swings more than the market"
W_MOVE = "Many themes, one movement"
W_SMALL = "Many small positions"
W_ETF = "Small or very young ETFs"
W_USD = "The dollar matters more than it seems"
W_SIM = "The simulation does not show that the stock picks beat the market"


def critique(out):
    """Weak points, strong points and general criteria (key "levers", three groups). **text** = bold.
    The actions are general portfolio-construction criteria, not instructions on what to buy or sell."""
    T, P, A = out["totals"], out["portfolio"], out["assets"]
    bt = P["bt"]
    stress = {s["factor"]: s for s in out["stress"]}
    weak, strong = [], []

    th = max(out["themes"], key=lambda t: t["rc"] - t["w"])
    ar = max(A, key=lambda a: a["rc"])
    weak.append({
        "title": W_CONC,
        "text": f"You hold {T['n_assets']} securities, but given how they move together they amount to about "
                f"**{round(P['n_bets'])} independent bets** (diversification ratio {_num(P['dr'], 2)}, squared). The "
                f"**{th['theme']}** theme is {_pc(th['w'])} of the value and carries {_pc(th['rc'])} of the swings; "
                f"**{ar['name']}** alone carries {_pc(ar['rc'])} of the risk with {_pc(ar['w'])} of the value.",
        "short": f"{T['n_assets']} securities, about {round(P['n_bets'])} independent bets. {th['theme']}: {_pc(th['w'])} of the value, "
                 f"{_pc(th['rc'])} of the risk."})

    sw = stress.get("MSCI World", {})
    weak.append({
        "title": W_SWING,
        "text": f"Over the last two years, at today's weights, volatility was {_pc(bt['port_stats']['vol'])} a year against "
                f"{_pc(bt['world_stats']['vol'])} for the MSCI World, with a beta of {_num(P['beta']['MSCI World'], 2)}: if world "
                f"stocks fell 10%, the estimate is {_spc(sw.get('impact', 0))} (about {_seu(sw.get('impact_eur', 0))}). This is an "
                "average: beta changes with the period chosen and correlations rise in a crisis, so the real fall can be larger.",
        "short": f"Volatility {_pc(bt['port_stats']['vol'])} against {_pc(bt['world_stats']['vol'])} for the world market, "
                 f"beta {_num(P['beta']['MSCI World'], 2)}."})

    c1 = out["clusters"][0] if out["clusters"] else None
    if c1 and len(c1["themes"]) >= 3:
        late = c1.get("late") or []
        many = len(late) > 1
        weak.append({
            "title": W_MOVE,
            "text": f"{len(c1['tickers'])} positions in different themes ({', '.join(_lc(t) for t in c1['themes'][:4])}) move together "
                    f"(average correlation {_num(c1['avg_corr'], 2)}): they are {_pc(c1['w'])} of the value and {_pc(c1['rc'])} of the risk. "
                    + (f"{_lst(late)} {'have' if many else 'has'} less than a year of history, so {'their' if many else 'its'} "
                       "link still needs confirming. " if late else "")
                    + "Adding different thematic ETFs does not necessarily diversify.",
            "short": f"{len(c1['tickers'])} stocks and ETFs from different themes move together: {_pc(c1['w'])} of the value, "
                     f"{_pc(c1['rc'])} of the risk" + (f" ({len(late)} with a short history)." if late else ".")})

    small = [a for a in A if a["value"] < 150]
    if len(small) >= 5:
        sw_small = sum(a["w"] for a in small)
        weak.append({
            "title": W_SMALL,
            "text": f"{len(small)} of your {T['n_assets']} securities are worth less than €150 each ({_pc(sw_small)} of the portfolio "
                    "in total). They barely move the result but each one still needs following, and the fixed cost of every order "
                    "weighs more on small amounts.",
            "short": f"{len(small)} securities under €150 each, {_pc(sw_small)} of the total."})

    gen = dt.date.fromisoformat(out["generated"][:10])
    tiny_etf, young = [], []
    for e in out["etfs"]:
        aum = (e.get("aum") or {}).get("value") if isinstance(e.get("aum"), dict) else None
        if aum and aum < 1e8:
            c = e["aum"].get("currency") or ""
            sign = CCY_SIGN.get(c, c + " " if c else "")
            tiny_etf.append(f"{e['ticker']} ({sign}{_num(aum / 1e6, 1)} million)")
        ld = e.get("launch_date")
        if ld and (gen - dt.date.fromisoformat(ld[:10])).days < 730:
            d = dt.date.fromisoformat(ld[:10])
            young.append(f"{e['ticker']} ({MONTHS[d.month - 1]} {d.year})")
    if tiny_etf or young:
        parts = []
        if tiny_etf:
            parts.append(f"assets under 100 million: {_lst(tiny_etf)}")
        if young:
            parts.append(f"launched less than two years ago: {_lst(young)}")
        weak.append({
            "title": W_ETF,
            "text": "Your ETFs include funds with " + "; ".join(parts) + ". A small fund can be closed by its issuer "
                    "and trade less liquidly; a young one has little history to judge it by.",
            "short": " ".join(x for x in (
                f"Under 100 million: {_lst(t.split(' ')[0] for t in tiny_etf)}." if tiny_etf else "",
                f"Launched less than two years ago: {_lst(t.split(' ')[0] for t in young)}." if young else "") if x)})

    qe = next((r["w"] for r in out["ccy_quote"] if r["k"] == "EUR"), 0)
    usd = next((r["w"] for r in out["ccy_eco"] if r["k"] == "USD"), 0)
    fx = stress.get("Dollar", {})
    if usd >= 0.3:
        weak.append({
            "title": W_USD,
            "text": f"{_pc(qe, 0)} of the portfolio is quoted in euros, but about {_pc(usd, 0)} of the value is in companies "
                    f"based in dollar countries (inside the ETFs too). With dollar prices unchanged, a 10% weaker dollar would mean "
                    f"about {_seu(fx.get('impact_eur', 0))} from the conversion alone. Over the two years observed, though, the "
                    f"portfolio moved little with the dollar: the measured sensitivity points to about "
                    f"{_seu(fx.get('obs_impact_eur') or 0)}, with a wide margin of error.",
            "short": f"{_pc(usd, 0)} of the value in dollar companies, even though {_pc(qe, 0)} is quoted in euros."})

    ps, hs, ws = bt["port_stats"]["total"], bt["hold_stats"]["total"], bt["world_stats"]["total"]
    if ps > ws:
        below = hs < ws
        weak.append({
            "title": W_SIM,
            "text": f"At today's weights, rebalanced every week, the last two years would have returned {_spc(ps)} against "
                    f"{_spc(ws)} for the MSCI World. But today's weights are high precisely in the securities that have already "
                    f"risen, so that figure counts the same gain twice. Holding today's quantities fixed, the result is {_spc(hs)}"
                    + (", below the world market. " if below else ". ")
                    + f"Your true return is not known: the {_spc(T['pnl_pct'])} only compares today's value with the average "
                      "cost of the open positions, leaving out dividends, sales and fees.",
            "short": f"Today's quantities held fixed: {_spc(hs)} against {_spc(ws)} for the world"
                     + ("; the stock picks do not come out ahead." if below else ".")})

    ov = sum(o["via_w"] for o in out["overlap"])
    if out["etfs"] and ov < 0.02:
        strong.append(f"The ETFs repeat few of the stocks you already hold: the overlaps are worth {_pc(ov)} of the portfolio.")
    dv = sorted([a for a in A if a["w"] >= 0.015 and not a["short"]], key=lambda a: a["corr_port"])[:4]
    if dv:
        strong.append(f"Some positions move on their own and soften the swings: {_lst(a['name'] for a in dv)}.")
    eu_w = next((r["w"] for r in out["regions"] if r["k"] == EU), 0)
    if eu_w >= 0.25:
        strong.append(f"Europe is {_pc(eu_w, 0)} of the portfolio: the result does not depend on Wall Street alone.")

    n = {w["title"]: k + 1 for k, w in enumerate(weak)}
    ref = lambda *titles: sorted(n[t] for t in titles if t in n)
    sec = {r["key"]: r["stock"] + r["etf"] for r in out["sectors"]}
    gap_keys = [("Health Care", "health care"), ("Consumer Staples", "consumer staples"), ("Energy", "energy"),
                ("Real Estate", "real estate")]
    gaps = [(lab, sec.get(k, 0)) for k, lab in gap_keys if sec.get(k, 0) < 0.03]
    R, D, O = "On risk", "On diversification", "Other criteria"
    levers = [
        {"group": R, "title": "A cap on each risk share",
         "text": f"One approach is a cap, decided in advance, on the share of risk from each security and each theme, with a "
                 "rebalance when it is exceeded, on fixed dates rather than on market swings. The weight and risk chart in "
                 "this report shows how far each position is from any cap you set.",
         "refs": ref(W_CONC, W_SWING)},
        {"group": R, "title": "A broad core, with the bets on the side",
         "text": "Many investors keep most of the value in a broad, diversified core (for example a fund on a wide world "
                 "index) and put themes and single stocks in a satellite portion with a weight decided in advance. That way "
                 "no single bet decides the result, and volatility moves closer to the market's.",
         "refs": ref(W_CONC, W_SWING, W_MOVE)},
    ]
    if gaps:
        levers.append(
            {"group": D, "title": "Sectors that are almost absent",
             "text": f"{len(gaps)} {'sector that is' if len(gaps) == 1 else 'sectors that are'} large in a broad world "
                     f"index {'is' if len(gaps) == 1 else 'are'} under 3% here, ETFs included (the sector chart shows which). "
                     "A sector that is almost absent is a fact to be aware of, not a gap that must be filled.",
             "refs": ref(W_CONC, W_MOVE)})
    levers += [
        {"group": D, "title": "Counting themes by movement, not by name",
         "text": "Before adding a stock or a thematic ETF, it helps to check what it moves with (the correlation map): if it "
                 "lands in the same group as the largest positions, it adds the same kind of risk, even if its name promises "
                 "a different theme.",
         "refs": ref(W_MOVE)},
        {"group": O, "title": "Merging the small positions",
         "text": "A minimum amount or weight below which a position is not opened, or is merged into another, cuts the "
                 "number of securities to follow and the weight of per-order costs. Before selling, it is worth checking "
                 "the tax effects.",
         "refs": ref(W_SMALL)},
        {"group": O, "title": "Checking the small or young ETFs",
         "text": "Assets, age, annual cost (TER) and trading volume: small funds are more likely to close. The ETF cards in "
                 "this report show these figures.",
         "refs": ref(W_ETF)},
        {"group": O, "title": "Deciding how much dollar exposure to keep",
         "text": "Some ETF share classes hedge the currency (hedged classes) at a slightly higher cost; the alternative is to "
                 "keep the currency risk while knowing what it is worth.",
         "refs": ref(W_USD)},
        {"group": O, "title": "Measuring the true return",
         "text": "With the export of transactions (purchases, sales, dividends, fees) you can calculate the time-weighted "
                 "return and compare it with a world-market fund bought on the same days: that is how to find out whether "
                 "picking stocks has earned more than an index.",
         "refs": ref(W_SIM)},
    ]
    levers = [lv for lv in levers if lv["refs"]]
    return {"weak": weak, "strong": strong, "levers": levers,
            "tax": "Before selling anything, it is worth considering the tax effects: in Italy, for example, capital gains "
                   "and losses are treated differently for stocks and for ETFs.",
            "caveat": "These are general portfolio-construction criteria, not instructions on what to buy or sell. This is not "
                      "financial advice, and I am not a licensed financial adviser. Decisions about this portfolio call for a "
                      "licensed financial adviser (in Italy, one registered with the OCF)."}



def print(*args, **kw):
    """The terminal summary carries names from the export, Yahoo and ETF files: no control characters."""
    builtins.print(*("".join(ch for ch in str(a) if ch.isprintable() or ch == "\n") for a in args), **kw)


def main():
    hold = json.loads((DATA / "holdings.json").read_text())
    rows = hold["rows"]
    yh = json.loads((DATA / "yahoo.json").read_text())
    etfs, companies = load_etfs()
    fx = series(yh["factors"]["EURUSD"])  # dollars per 1 euro

    def eur(s, ccy):
        if ccy == "EUR":
            return s
        f = fx.reindex(fx.index.union(s.index)).ffill().reindex(s.index)
        return s / f

    def weekly(s):
        return s.resample("W-FRI").last().dropna()

    # ---- positions (a security bought on two markets has two rows: they are added up) ----
    pos = {}
    for r in rows:
        p = pos.setdefault(r["isin"], {"isin": r["isin"], "kind": KIND.get(r["kind"], r["kind"]), "value": 0.0,
                                       "cost": 0.0, "lines": []})
        p["value"] += r["value_eur"]
        p["cost"] += r["cost_eur"]
        p["lines"].append({"market": r["market"], "ccy": r["ccy"], "qty": num(r["qty"]),
                           "avg": num(r["avg_price"]), "price": num(r["price"]),
                           "value": num(r["value_eur"], 2), "pnl_pct": num(r["pnl_pct"] / 100) if r.get("pnl_pct") is not None else None})
    isins = list(pos)
    missing = [i for i in isins if i not in META]
    if missing:
        print("MISSING in portfolio_meta.json:", ", ".join(missing))
        print("Add them (see references/new-securities.md), then run again.")
        sys.exit(2)
    # holdings fetch.py found no prices for (delisted, wrong symbol): left out of the analysis and listed
    no_prices = [{"isin": i, "name": META[i][0], "ticker": META[i][1], "value": num(pos[i]["value"], 2)}
                 for i in isins if not (yh["assets"].get(i) or {}).get("dates")]
    if no_prices:
        print("NO PRICES, left out of the analysis:", ", ".join(f"{x['ticker']} ({x['isin']})" for x in no_prices))
        for x in no_prices:
            pos.pop(x["isin"])
        isins = list(pos)
    if not isins:
        raise SystemExit("No holding has prices: run fetch.py again, or fix the yahoo symbols in portfolio_meta.json.")
    total = sum(p["value"] for p in pos.values())
    cost_total = sum(p["cost"] for p in pos.values())
    w = np.array([pos[i]["value"] / total for i in isins])

    # ---- weekly returns in euros ----
    px = pd.DataFrame({i: weekly(eur(series(yh["assets"][i]), yh["assets"][i]["currency"]))
                       for i in isins})
    rets = px.pct_change(fill_method=None).iloc[-WEEKS:]
    fac_px = {k: weekly(eur(series(f), f["currency"]))
              for k, f in yh["factors"].items() if k != "EURUSD"}
    fac_px["Dollar"] = weekly(1 / fx)
    fac = pd.DataFrame(fac_px).pct_change(fill_method=None).reindex(rets.index)
    fac_names = ["MSCI World", "Nasdaq 100", "Bitcoin", "Gold", "Dollar", "Euro Stoxx 50", "FTSE MIB"]

    n_w = rets.notna().sum()
    vol = rets.std() * math.sqrt(52)
    C = rets.corr(min_periods=MIN_WEEKS)

    # consistent covariance matrix (pairwise correlations may not be)
    R = C.fillna(0).to_numpy(copy=True)
    np.fill_diagonal(R, 1.0)
    ev, evec = np.linalg.eigh(R)
    R2 = evec @ np.diag(np.clip(ev, 1e-6, None)) @ evec.T
    dd = np.sqrt(np.diag(R2))
    R2 = R2 / np.outer(dd, dd)
    sig = vol.reindex(isins).to_numpy()
    S = np.outer(sig, sig) * R2
    var_p = float(w @ S @ w)
    vol_p = math.sqrt(var_p)
    mrc = S @ w
    rc = w * mrc / var_p
    corr_ip = mrc / (sig * vol_p)

    # ---- groups of securities that move together ----
    # Only securities with at least a year of history are clustered; the more recent ones
    # join the group they have the highest average correlation with, if it is at least 0.4.
    core = [i for i in isins if n_w[i] >= SHORT]
    Cc = C.loc[core, core].fillna(0).to_numpy()
    Dm = np.sqrt(np.clip(0.5 * (1 - Cc), 0, None))
    np.fill_diagonal(Dm, 0)
    Z = linkage(squareform(Dm, checks=False), method="average")
    order = [core[k] for k in leaves_list(Z)]
    lab = fcluster(Z, t=CLUSTER_CUT, criterion="distance")
    groups = {}
    for k, i in enumerate(core):
        groups.setdefault(int(lab[k]), []).append(i)
    late = set()
    for i in isins:
        if i in core:
            continue
        best = max(((C.loc[i, m].mean(), g) for g, m in groups.items() if len(m) > 1),
                   default=(float("nan"), None))
        if best[1] is not None and best[0] >= 0.4:
            late.add(i)
            after = max(order.index(m) for m in groups[best[1]])
            groups[best[1]].append(i)
            order.insert(after + 1, i)
        else:
            groups[f"s{i}"] = [i]
            order.append(i)

    def tick(i):
        return META[i][1]

    clusters = []
    loners = []
    for members in groups.values():
        if len(members) < 2:
            loners += members
            continue
        idx = [isins.index(i) for i in members]
        sub = C.loc[members, members].to_numpy()
        off = sub[~np.eye(len(members), dtype=bool)]
        theme_w = {}
        for i in members:
            theme_w[META[i][2]] = theme_w.get(META[i][2], 0) + pos[i]["value"]
        mem = sorted(members, key=lambda i: -pos[i]["value"])
        tk = [tick(i) for i in mem]
        name = next((n for t, n in CLUSTER_NAMES if t in tk), None)
        themes_c = [t for t, _ in sorted(theme_w.items(), key=lambda x: -x[1])]
        clusters.append({"members": mem, "tickers": tk, "late": [tick(i) for i in mem if i in late],
                         "name": name or ", ".join(themes_c[:2]),
                         "w": num(w[idx].sum()), "rc": num(rc[idx].sum()),
                         "avg_corr": num(np.nanmean(off)), "themes": themes_c})
    clusters.sort(key=lambda c: -c["rc"])
    used = set()
    for c in clusters:  # two groups with the same name: the second takes its themes
        if c["name"] in used:
            c["name"] = ", ".join(c["themes"][:2])
        used.add(c["name"])
    for n, c in enumerate(clusters, 1):
        c["id"] = n
    cluster_of = {i: c["id"] for c in clusters for i in c["members"]}

    pairs = []
    for a in range(len(isins)):
        for b in range(a + 1, len(isins)):
            v = C.iat[a, b]
            if not math.isnan(v):
                pairs.append((v, isins[a], isins[b]))
    pairs.sort(reverse=True)
    long_hist = {i for i in isins if n_w[i] >= SHORT}
    low = sorted(p for p in pairs if p[1] in long_hist and p[2] in long_hist)[:10]

    # ---- simulation: today's weights applied to the last 2 years ----
    Wser = pd.Series(w, index=isins)
    avail = rets.notna().astype(float)
    port_r = (rets.fillna(0) * Wser).sum(axis=1) / (avail * Wser).sum(axis=1)
    world_r = fac["MSCI World"]
    cum_p = (1 + port_r).cumprod()
    cum_w = (1 + world_r.fillna(0)).cumprod()
    years = len(port_r) / 52

    # second convention: today's quantities held fixed for two years (no rebalancing).
    # The fixed weights above reward the securities that already rose twice; this one does not.
    # A security listed after the start counts as cash until its first price.
    pw = px[isins].iloc[-(WEEKS + 1):].ffill().bfill()
    hold_v = (pw / pw.iloc[-1] * pd.Series([pos[i]["value"] for i in isins], index=isins)).sum(axis=1)
    cum_h = (hold_v / hold_v.iloc[0]).iloc[1:]
    hold_r = cum_h.pct_change().fillna(cum_h.iloc[0] - 1)

    def stats(r, cum):
        return {"total": num(cum.iloc[-1] - 1), "ann": num(cum.iloc[-1] ** (1 / years) - 1),
                "vol": num(r.std() * math.sqrt(52)), "mdd": num(max_dd(cum))}

    port_beta = {k: num(pair_beta(port_r, fac[k])) for k in fac_names}
    port_corr = {k: num(port_r.corr(fac[k], min_periods=MIN_WEEKS)) for k in fac_names}
    worst = port_r.nsmallest(5)
    stress_def = [("World stocks (MSCI World) -10%", "MSCI World", -0.10),
                  ("Nasdaq 100 -15%", "Nasdaq 100", -0.15),
                  ("Bitcoin -30%", "Bitcoin", -0.30),
                  ("Gold -15%", "Gold", -0.15)]
    stress = [{"label": l, "factor": f, "shock": s,
               "impact": num(port_beta[f] * s) if port_beta[f] is not None else None,
               "impact_eur": num(port_beta[f] * s * total, 0) if port_beta[f] is not None else None}
              for l, f, s in stress_def]

    # ---- breakdown by sector, country and currency (looking inside the ETFs) ----
    yahoo_sector = {i: YAHOO_SECTOR.get(yh["assets"][i].get("sector") or "", None) for i in isins}
    last_day = max(yh["assets"][i]["dates"][-1] for i in isins)  # the last week can be partial
    sec_stock, sec_etf, ctry, region, ccy_eco = {}, {}, {}, {}, {}

    def add(d, k, v):
        d[k] = d.get(k, 0.0) + v

    etf_used = {}
    for k, i in enumerate(isins):
        wi = w[k]
        if pos[i]["kind"] != "ETF":
            add(sec_stock, yahoo_sector[i] or "Cash/Other", wi)
            cn, ar, cc = country_info(META[i][3])
            add(ctry, cn, wi)
            add(region, ar, wi)
            add(ccy_eco, META[i][4], wi)
            continue
        e = etfs.get(i)
        secs = {}
        if e and e.get("sectors"):
            tmp = {}
            for s, v in e["sectors"].items():
                if v is not None:
                    add(tmp, sector_key(s), float(v))
            secs = normalize(tmp)
        if not secs:
            secs = {NOT_SPLIT: 1.0}
        for s, v in secs.items():
            add(sec_etf, s, wi * v)
        cts = {}
        if e and e.get("countries"):
            for c, v in e["countries"].items():
                if v is not None:
                    add(cts, c, float(v))
        cts = normalize(cts)
        if not cts:
            cts = {NOT_SPLIT: 1.0}
        for c, v in cts.items():
            cn, ar, cc = country_info(c) if c != NOT_SPLIT else (NOT_SPLIT, "Other", "Not broken down")
            add(ctry, cn, wi * v)
            add(region, ar, wi * v)
            add(ccy_eco, cc, wi * v)
        etf_used[i] = e

    ccy_quote = {}
    left_out = {x["isin"] for x in no_prices}
    for r in rows:
        if r["isin"] not in left_out:
            add(ccy_quote, r["ccy"], r["value_eur"] / total)
    usd = ccy_eco.get("USD", 0.0)  # direct currency effect, with dollar prices unchanged
    b_usd = port_beta.get("Dollar")
    stress.append({"label": "Dollar -10% against the euro (currency effect only)", "factor": "Dollar",
                   "shock": -0.10, "impact": num(-0.10 * usd), "impact_eur": num(-0.10 * usd * total, 0),
                   # what the sensitivity measured over the last two years would have given
                   "obs_impact": num(-0.10 * b_usd) if b_usd is not None else None,
                   "obs_impact_eur": num(-0.10 * b_usd * total, 0) if b_usd is not None else None})

    # overlaps: securities you already hold that are also inside the ETFs
    t2i = {META[i][1]: i for i in isins if pos[i]["kind"] != "ETF"}
    via = {}
    for k, i in enumerate(isins):
        e = etf_used.get(i)
        if not e:
            continue
        seen = set()
        for o in (e.get("overlap_with_direct") or []) + (e.get("top_holdings") or []):
            t = norm_ticker(o.get("ticker"))
            if t in t2i and t not in seen and o.get("weight_pct"):
                seen.add(t)
                via.setdefault(t2i[t], []).append({"etf": META[i][1],
                                                   "w_in_etf": num(o["weight_pct"] / 100),
                                                   "w": num(w[k] * o["weight_pct"] / 100, 6)})
    overlap = []
    for j, lst in via.items():
        wd = pos[j]["value"] / total
        wv = sum(x["w"] for x in lst)
        overlap.append({"ticker": META[j][1], "name": META[j][0], "direct": num(wd, 5),
                        "via": lst, "via_w": num(wv, 5), "total": num(wd + wv, 5)})
    overlap.sort(key=lambda x: -x["total"])

    # hidden exposures: main holdings inside the ETFs, added up across ETFs
    hidden = {}
    for k, i in enumerate(isins):
        e = etf_used.get(i)
        for h in (e or {}).get("top_holdings") or []:
            t = norm_ticker(h.get("ticker")) or str(h.get("name", "")).upper()
            if not h.get("weight_pct") or t in t2i:
                continue
            x = hidden.setdefault(t, {"ticker": t, "name": h.get("name"), "w": 0.0, "etfs": []})
            x["w"] += w[k] * h["weight_pct"] / 100
            x["etfs"].append(META[i][1])
    hidden = sorted(hidden.values(), key=lambda x: -x["w"])[:15]
    for x in hidden:
        x["w"] = num(x["w"], 5)

    # ETFs with holdings in common (on the main published holdings)
    etf_pairs = []
    keys = [i for i in isins if etf_used.get(i)]
    for a in range(len(keys)):
        for b in range(a + 1, len(keys)):
            ha = {norm_ticker(h.get("ticker")): h.get("weight_pct") or 0 for h in etf_used[keys[a]].get("top_holdings") or []}
            hb = {norm_ticker(h.get("ticker")): h.get("weight_pct") or 0 for h in etf_used[keys[b]].get("top_holdings") or []}
            common = [t for t in ha if t and t in hb]
            if common:
                etf_pairs.append({"a": META[keys[a]][1], "b": META[keys[b]][1], "common": common,
                                  "overlap": num(sum(min(ha[t], hb[t]) for t in common) / 100)})
    etf_pairs.sort(key=lambda x: -x["overlap"])

    # ---- per security ----
    assets = []
    for k, i in enumerate(isins):
        name, tk, theme, country, ccy, desc = META[i]
        p = pos[i]
        pi = px[i].dropna()
        last = pi.iloc[-1]
        ago = pi[pi.index <= pi.index[-1] - pd.Timedelta(weeks=52)]
        r1 = last / ago.iloc[-1] - 1 if len(ago) else None
        e = etf_used.get(i)
        assets.append({
            "isin": i, "name": name, "ticker": tk, "kind": p["kind"], "theme": theme,
            "sector": SECTOR_NAME.get(yahoo_sector[i] or "", None) if p["kind"] != "ETF" else "ETF",
            "industry": industry_name(yh["assets"][i].get("industry")),
            "country": country if p["kind"] != "ETF" else None, "ccy_eco": ccy,
            "ccy_quote": sorted({l["ccy"] for l in p["lines"]}), "markets": [l["market"] for l in p["lines"]],
            "desc": (e or {}).get("index") and f"{desc} Index: {e['index']}." or desc,
            "value": num(p["value"], 2), "w": num(w[k], 5), "cost": num(p["cost"], 2),
            "pnl": num(p["value"] - p["cost"], 2), "pnl_pct": num(p["value"] / p["cost"] - 1),
            "lines": p["lines"], "n_weeks": int(n_w[i]), "short": bool(n_w[i] < SHORT),
            "first": yh["assets"][i]["dates"][0], "vol": num(vol[i]), "ret_1y": num(r1),
            "mdd": num(max_dd(px[i].iloc[-(WEEKS + 1):])), "beta": num(pair_beta(rets[i], fac["MSCI World"])),
            "corr_port": num(corr_ip[k]), "rc": num(rc[k], 5), "cluster": cluster_of.get(i),
            "fcorr": {f: num(rets[i].corr(fac[f], min_periods=MIN_WEEKS), 3) for f in fac_names},
        })

    themes = {}
    for a in assets:
        t = themes.setdefault(a["theme"], {"theme": a["theme"], "w": 0, "rc": 0, "value": 0,
                                           "cost": 0, "n": 0, "tickers": []})
        t["w"] += a["w"]
        t["rc"] += a["rc"]
        t["value"] += a["value"]
        t["cost"] += a["cost"]
        t["n"] += 1
        t["tickers"].append(a["ticker"])
    themes = sorted(themes.values(), key=lambda t: -t["w"])
    for t in themes:
        t["pnl_pct"] = num(t["value"] / t["cost"] - 1)
        t["w"], t["rc"] = num(t["w"], 5), num(t["rc"], 5)

    # ---- world sectors (US sector ETFs in euros): how much they move with the largest exposures ----
    sector_indep = None
    sp = DATA / "sectors_yahoo.json"
    if sp.exists():
        sy = json.loads(sp.read_text())
        sret = pd.DataFrame({k: weekly(eur(series(c), c["currency"])) for k, c in sy.items()}
                            ).pct_change(fill_method=None).reindex(rets.index)
        theme_of = {a["isin"]: a["theme"] for a in assets}
        top_th = [t["theme"] for t in sorted(themes, key=lambda t: -t["rc"])[:2]]
        tgt = {"Portfolio": port_r}
        for th_name in top_th:
            m = [i for i in isins if theme_of[i] == th_name]
            tgt[th_name] = (rets[m].fillna(0) * Wser[m]).sum(axis=1) / (avail[m] * Wser[m]).sum(axis=1)

        def resid(x):
            d = pd.concat([x, world_r], axis=1).dropna()
            b = np.cov(d.iloc[:, 0], d.iloc[:, 1])[0, 1] / d.iloc[:, 1].var()
            return d.iloc[:, 0] - b * d.iloc[:, 1]

        pres = resid(port_r)
        vol_now = port_r.std() * math.sqrt(52)
        rows_s = []
        for k in sret.columns:
            x = sret[k]
            mix = (0.9 * port_r + 0.1 * x).dropna()
            rows_s.append({
                "sector": k, "symbol": sy[k]["symbol"],
                "w_port": None,
                "corr": {n: num(v.corr(x, min_periods=MIN_WEEKS), 2) for n, v in tgt.items()},
                "corr_ex_world": num(pres.corr(resid(x)), 2),
                "vol": num(x.std() * math.sqrt(52), 3),
                "beta_world": num(pair_beta(x, world_r), 2),
                "vol_mix10": num(mix.std() * math.sqrt(52), 4),
                "d_vol_mix10": num(mix.std() * math.sqrt(52) - vol_now, 4),
            })
        rows_s.sort(key=lambda r: r["corr"]["Portfolio"])
        sector_indep = {"targets": list(tgt), "vol_port": num(vol_now, 4), "rows": rows_s,
                        "weeks": int(sret.notna().all(axis=1).sum())}
        t["value"], t["cost"] = num(t["value"], 2), num(t["cost"], 2)

    sectors = [{"key": s, "sector": SECTOR_NAME.get(s, s), "stock": num(sec_stock.get(s, 0), 5),
                "etf": num(sec_etf.get(s, 0), 5)} for s in set(sec_stock) | set(sec_etf)]
    sectors.sort(key=lambda s: -(s["stock"] + s["etf"]))

    def ranked(d, nd=5):
        return [{"k": k, "w": num(v, nd)} for k, v in sorted(d.items(), key=lambda x: -x[1])]

    def breakdown(i, kind):
        d = {}
        for k, v in ((etf_used.get(i) or {}).get(kind) or {}).items():
            if v is not None:
                add(d, SECTOR_NAME.get(sector_key(k)) if kind == "sectors" else country_info(k)[0], float(v))
        return ranked(normalize(d), 4)

    off_all = C.to_numpy()[~np.eye(len(isins), dtype=bool)]
    ww = np.outer(w, w)[~np.eye(len(isins), dtype=bool)]
    m = ~np.isnan(off_all)
    # ---- euro value of today's quantities over time, by theme (not the account's real history) ----
    pxw = px.reindex(rets.index.union(px.index[-1:])).iloc[-(WEEKS + 1):]
    val = pd.DataFrame({i: pos[i]["value"] * pxw[i] / px[i].dropna().iloc[-1] for i in isins}).fillna(0)
    th_of = {i: META[i][2] for i in isins}
    th_rank = sorted({t for t in th_of.values()}, key=lambda t: -sum(pos[i]["value"] for i in isins if th_of[i] == t))
    by_th = {t: val[[i for i in isins if th_of[i] == t]].sum(axis=1) for t in th_rank}
    value_hist = {"dates": [min(str(d.date()), last_day) for d in val.index],
                  "total": [num(v, 2) for v in val.sum(axis=1)],
                  "themes": [{"theme": t, "v": [num(v, 2) for v in by_th[t]]} for t in th_rank],
                  "n_missing_start": int(sum(1 for i in isins if pd.isna(pxw[i].iloc[0])))}
    # same money in the MSCI World: each security enters when it starts trading, with the same amount
    wld = fac_px["MSCI World"].reindex(pxw.index).ffill()
    bench = pd.Series(0.0, index=pxw.index)
    late = []
    for i in isins:
        k = pxw[i].first_valid_index()
        if k is None:
            continue
        bench = bench.add((val[i].loc[k] * wld / wld.loc[k]).where(pxw.index >= k, 0.0), fill_value=0)
        if k != pxw.index[0]:
            late.append({"ticker": tick(i), "date": str(k.date()), "value": num(val[i].loc[k], 2)})
    value_hist["world"] = [num(v, 2) for v in bench]
    value_hist["late"] = sorted(late, key=lambda r: r["date"])

    if sector_indep:
        for r_ in sector_indep["rows"]:
            r_["w_port"] = num(next((x["stock"] + x["etf"] for x in sectors if x["sector"] == r_["sector"]), 0), 4)

    out = {
        "generated": dt.datetime.now().isoformat(timespec="minutes"),
        "export_file": hold.get("source"), "prices_to": last_day, "demo": DEMO, "no_prices": no_prices,
        "fetched": yh.get("fetched"), "window_weeks": int(len(rets)),
        "window_from": str(rets.index[0].date()), "window_to": min(str(rets.index[-1].date()), last_day),
        "totals": {"value": num(total, 2), "cost": num(cost_total, 2), "pnl": num(total - cost_total, 2),
                   "pnl_pct": num(total / cost_total - 1), "n_assets": len(isins), "n_lines": sum(1 for r in rows if r["isin"] in pos),
                   "n_etf": sum(1 for i in isins if pos[i]["kind"] == "ETF")},
        "portfolio": {"vol": num(vol_p), "dr": num((w @ sig) / vol_p),
                      "n_bets": num(((w @ sig) / vol_p) ** 2, 2),  # equivalent independent bets
                      "eff_n_w": num(1 / (w ** 2).sum(), 2),
                      "eff_n_rc": num(1 / (rc ** 2).sum(), 2), "beta": port_beta, "corr": port_corr,
                      "avg_corr": num(np.nanmean(off_all)),
                      "avg_corr_w": num(float((off_all[m] * ww[m]).sum() / ww[m].sum())),
                      "top5_w": num(np.sort(w)[-5:].sum()), "top10_w": num(np.sort(w)[-10:].sum()),
                      "bt": {"dates": [min(str(d.date()), last_day) for d in cum_p.index],
                             "port": [num(v) for v in cum_p], "world": [num(v) for v in cum_w],
                             "hold": [num(v) for v in cum_h],
                             "port_stats": stats(port_r, cum_p), "world_stats": stats(world_r.fillna(0), cum_w),
                             "hold_stats": stats(hold_r, cum_h),
                             "worst": [{"date": min(str(d.date()), last_day), "r": num(v)} for d, v in worst.items()]}},
        "value_hist": value_hist, "stress": stress, "assets": assets, "themes": themes, "sectors": sectors, "sector_indep": sector_indep,
        "countries": ranked(ctry), "regions": ranked(region),
        "ccy_quote": ranked(ccy_quote), "ccy_eco": ranked(ccy_eco),
        "corr": {"order": order, "tickers": [tick(i) for i in order],
                 "m": [[num(C.at[a, b], 2) if a != b else 1.0 for b in order] for a in order]},
        "clusters": [{k: v for k, v in c.items() if k != "members"} for c in clusters],
        "loners": [tick(i) for i in sorted(loners, key=lambda i: -pos[i]["value"])],
        "pairs_top": [{"a": tick(a), "b": tick(b), "rho": num(v, 2), "short": bool(n_w[a] < SHORT or n_w[b] < SHORT)}
                      for v, a, b in pairs[:12]],
        "pairs_low": [{"a": tick(a), "b": tick(b), "rho": num(v, 2)} for v, a, b in low],
        "factor_names": fac_names, "overlap": overlap, "hidden": hidden, "etf_pairs": etf_pairs,
        "etfs": [{"ticker": META[i][1], "isin": i, "name": (etf_used.get(i) or {}).get("name") or META[i][0],
                  "w": num(pos[i]["value"] / total, 5),
                  **{k: (etf_used.get(i) or {}).get(k) for k in ("index", "ter_pct", "launch_date", "aum",
                                                                  "n_holdings", "replication", "distribution",
                                                                  "top_holdings", "sectors_source",
                                                                  "countries_source", "overlap_checked",
                                                                  "as_of", "sources", "notes", "ticker_eu",
                                                                  "overlap_with_direct")},
                  "note_it": NOTE_IT.get(i), "sectors_it": breakdown(i, "sectors"),
                  "countries_it": breakdown(i, "countries")}
                 for i in isins if pos[i]["kind"] == "ETF"],
        "companies": companies,
    }
    out["critique"] = critique(out)
    write_out(DATA / "analysis.json", json.dumps(out, ensure_ascii=False))
    # "<" only occurs inside strings: \u003c keeps "</script>" and "<!--" in names from ending the script block
    blob = json.dumps(out, ensure_ascii=False).replace("<", "\\u003c")
    for tpl, dst in (("report_template.html", "report.html"), ("onepager_template.html", "onepager.html")):
        if (ROOT / tpl).exists():
            page = (ROOT / tpl).read_text().replace(
                "/*__CHARTS__*/", (ROOT / "charts_extra.js").read_text() + "\n" + (ROOT / "hide_amounts.js").read_text())
            write_out(WS / dst, page.replace("__DATA__", blob))

    # ---- terminal summary ----
    T = out["totals"]
    P = out["portfolio"]
    print(f"Value €{T['value']:,.0f}, cost €{T['cost']:,.0f}, P&L {_seu(T['pnl'])} ({T['pnl_pct']:.1%}); "
          f"{T['n_assets']} securities ({T['n_etf']} ETFs), {T['n_lines']} rows")
    print(f"Window {out['window_from']} to {out['window_to']} ({out['window_weeks']} weeks)")
    print(f"Estimated annual vol {P['vol']:.1%}, diversification ratio {P['dr']:.2f}, "
          f"effective N by weight {P['eff_n_w']}, by risk {P['eff_n_rc']}, avg corr {P['avg_corr']:.2f} "
          f"(weighted {P['avg_corr_w']:.2f}), top5 {P['top5_w']:.1%}, top10 {P['top10_w']:.1%}")
    print("Portfolio beta:", P["beta"])
    print("Portfolio corr:", P["corr"])
    bt = P["bt"]
    print("2-year simulation:", bt["port_stats"], "MSCI World:", bt["world_stats"])
    print("Worst weeks:", bt["worst"])
    print("Stress:", [(s["label"], s["impact"], s["impact_eur"]) for s in stress])
    print("\nThemes (weight, risk, P&L):")
    for t in themes:
        print(f"  {t['theme']:24} {t['w']:6.1%} {t['rc']:6.1%} {t['pnl_pct']:7.1%}  {' '.join(t['tickers'])}")
    print("\nGroups (weight, risk, avg corr):")
    for c in out["clusters"]:
        print(f"  {c['id']}: {c['w']:.1%} {c['rc']:.1%} {c['avg_corr']:.2f}  {' '.join(c['tickers'])}  [{', '.join(c['themes'])}]")
    print("  independent:", " ".join(out["loners"]))
    print("\nMost correlated pairs:", [(p['a'], p['b'], p['rho']) for p in out["pairs_top"]])
    print("Least correlated pairs:", [(p['a'], p['b'], p['rho']) for p in out["pairs_low"]])
    print("\nSecurities: ticker weight rc vol beta corr_port n_weeks  corrBTC corrGold corrUSD")
    for a in sorted(assets, key=lambda a: -a["rc"]):
        fc = a["fcorr"]
        print(f"  {a['ticker']:6} {a['w']:6.1%} {a['rc']:6.1%} {a['vol'] or 0:6.1%} {a['beta'] or 0:5.2f} "
              f"{a['corr_port']:5.2f} {a['n_weeks']:4d}  {fc['Bitcoin'] or 0:5.2f} {fc['Gold'] or 0:5.2f} "
              f"{fc['Dollar'] or 0:5.2f}  1y {a['ret_1y'] if a['ret_1y'] is None else round(a['ret_1y']*100)}%")
    print("\nSectors:", [(s["sector"], round(s["stock"] * 100, 1), round(s["etf"] * 100, 1)) for s in sectors])
    print("Regions:", [(r["k"], round(r["w"] * 100, 1)) for r in out["regions"]])
    print("Quote currency:", [(r["k"], round(r["w"] * 100, 1)) for r in out["ccy_quote"]])
    print("Business currency:", [(r["k"], round(r["w"] * 100, 1)) for r in out["ccy_eco"]])
    print("Overlaps:", [(o["ticker"], o["direct"], o["via_w"]) for o in overlap])
    print("Hidden exposures:", [(h["ticker"], h["w"], h["etfs"]) for h in hidden[:10]])
    print("ETFs in common:", [(p["a"], p["b"], p["overlap"], p["common"]) for p in etf_pairs])
    print("No sector:", [a["ticker"] for a in assets if a["kind"] != "ETF" and not a["sector"]])
    print("Industries:", sorted({a["industry"] for a in assets if a["industry"]}))
    print("Countries:", [(r["k"], round(r["w"] * 100, 1)) for r in out["countries"]])


if __name__ == "__main__":
    main()
