# Security

## Threat model

What the skill reads, runs and writes, and what could be hostile:

- **Inputs**: the broker export (.xls), `portfolio_meta.json`, the ETF look-through files `data/etf_*.json`, Yahoo Finance responses and any web page read while researching an ETF. All are untrusted: a security name, a note or a page can contain text aimed at Claude or markup aimed at the browser.
- **Instructions hidden in inputs** are data, not commands: SKILL.md tells Claude to quote such text to the user and never act on it.
- **Commands** the skill runs: `python` on the scripts in `scripts/`, `curl` (called by `fetch.py` with an argument list, no shell), headless Chrome or Chromium for the PDFs, `pdfinfo`.
- **Network**: Yahoo Finance (`query1`/`query2.finance.yahoo.com`): ticker symbols and ISINs only, never quantities, prices paid or amounts. If the user agrees at intake, web searches by fund name and ISIN for ETF look-through. Nothing else.
- **Outputs**: files inside the workspace folder the user chose: `data/*.json`, `posizioni.csv`, `report.html`, `onepager.html`, the PDFs, `archive/`. The HTML pages embed the full analysis, amounts included.

## Mitigations

| Risk | Mitigation | File |
| --- | --- | --- |
| A name in the export closes the data `<script>` block and runs code in the page | every `<` in the embedded JSON is written as `\u003c`; the pages read it with `JSON.parse` and render data with `textContent`, never `innerHTML`; a Content-Security-Policy blocks any network load; source links must be valid `http(s)` addresses without control or bidi characters | `scripts/analyze.py`, `scripts/report_template.html`, `scripts/onepager_template.html` |
| Shell injection through a ticker or ISIN | `curl` gets an argument list and a URL-encoded symbol; no shell anywhere | `scripts/fetch.py` |
| Holdings leak through searches or URLs | only symbols and ISINs go to Yahoo; ETF research searches only the fund's own name and ISIN; SKILL.md forbids holdings and amounts in searches, URLs, commits and memory | `SKILL.md`, `references/etf-research.md` |
| Prompt injection from the export, meta files or web pages | treated as data; quoted to the user, never followed | `SKILL.md` |
| Investment advice | the critique gives general criteria only; SKILL.md forbids naming securities or sectors to buy or sell | `scripts/analyze.py`, `SKILL.md` |
| Amounts visible on a shared screen | "Hide amounts" switch and `onepager-hidden.pdf` with no euro figures in it | `scripts/hide_amounts.js` |
| Wrong file read as an export | the parser requires an .xls file with the Fineco header row and columns and stops with a message otherwise | `scripts/fetch.py` |
| A planted symlink in the workspace makes a run overwrite another file | every output is written to a new temp file with a random name (created exclusively, so a planted link there is never followed) and moved into place; symlinks and paths outside the workspace are refused | `scripts/analyze.py`, `scripts/fetch.py` |
| The demo overwrites a real workspace | `make_demo.py` writes only into a new, empty folder | `scripts/make_demo.py` |
| Hostile text in names or Yahoo replies | control characters are stripped before printing; Yahoo symbols must look like symbols and are fully URL-encoded; `curl` ignores `~/.curlrc` and accepts https only; text that starts like a formula gets a leading quote in `posizioni.csv` | `scripts/fetch.py`, `scripts/analyze.py` |
| A research subagent steered by a web page | its brief says pages are data, one fund per search; its reply and files are treated as data | `references/etf-research.md`, `SKILL.md` |
| macOS Keychain dialogs from headless Chrome | every launch uses `--use-mock-keychain --password-store=basic` | `SKILL.md`, `references/checks.md` |

Tests for these cases: `tests/test_pipeline.py` (hostile name, export parsing and number formats, missing securities, holdings without prices, symlinked outputs and planted temp links, malformed Yahoo and meta data, demo folder guard, symbol check, CSV formulas, amount masking, no dashes).

## Residual risks

- The "Hide amounts" switch hides figures on screen only: anyone with the HTML file can read every amount in its source. Share `onepager-hidden.pdf` instead.
- Yahoo Finance learns which tickers and ISINs you look up, together with your IP address.
- Yahoo's endpoints are unofficial: wrong or missing prices are possible; holdings with no prices are left out and listed in the pages.
- The Python packages are pinned by version, not by hash.
- ETF look-through relies on what the research subagent finds; a hostile page could feed it wrong weights. Sources and dates are stored in each file for review.
- The pages run local JavaScript from the generated file. They load nothing from the network.

## Reporting a vulnerability

Please use GitHub's private vulnerability reporting: open the repository's **Security** tab and choose **Report a vulnerability**. Do not open a public issue for security problems.
