# Checks before handing over

## 1. One A4 page

Run `pdfinfo onepager.pdf | grep Pages`. It must print 1.

## 2. Phone width without horizontal scroll

Headless Chrome (always with `--use-mock-keychain --password-store=basic`) cannot make a window narrower than about 500 px, so measure inside an iframe. In the scratchpad, write a page like the one below, then load it with `--headless --use-mock-keychain --password-store=basic --user-data-dir="<scratchpad>/chrome-profile" --allow-file-access-from-files --virtual-time-budget=6000 --dump-dom` and read the `SW=` value. `--allow-file-access-from-files` lets the test page read the iframe; use it only for this check, on pages this skill generated (they render data as text and carry a Content-Security-Policy that blocks network loads). Build the iframe address with `"$PY" -I -c 'import pathlib,sys;print(pathlib.Path(sys.argv[1]).resolve().as_uri())' "<ws>/report.html"`, which encodes spaces and `#`. It must be 375 for both pages.

```html
<!doctype html><html><body style="margin:0"><iframe id="f" src="<address of report.html>" style="width:375px;height:3000px;border:0"></iframe><pre id="o"></pre>
<script>f.onload=()=>setTimeout(()=>{const d=f.contentDocument;o.textContent='SW='+d.documentElement.scrollWidth},1500)</script></body></html>
```

## 3. Screenshots

To screenshot one section, use a wrapper with a tall iframe and set its `marginTop` to minus the offset of the heading you want. Use `--screenshot` with `--window-size=1200,1700`, and `375,1700` for phone width inside an iframe 375 px wide. Look at:
- the value-over-time chart;
- the donuts;
- the treemap;
- the one-pager.

Check for overlapping labels, truncated legends and empty charts.

## 4. JavaScript errors

An empty chart container or a missing KPI row usually means a script error. A common cause is a data string the page compares literally, for example a sector bucket name. Those strings are listed in the comments of `analyze.py`, and both sides must match.

## 5. Text

- **Dashes.** No em or en dashes in the pages outside the embedded data.
- **Critique.** Read the critique and the "general criteria" once. They are generated from thresholds, so a newly bought sector or ETF can make a sentence stale or odd. If it does, tell the user and propose a change to `critique()` in analyze.py (SKILL.md rule 7); never edit the output by hand. The criteria must stay general: no named security or sector to buy, sell, add or cut.

## 6. The shared PDF

With poppler installed, `pdftotext onepager-hidden.pdf - | grep -E '€ ?[0-9]'` must print nothing.

## 7. Leftover Chrome

Run `ps ax | grep -- --headless | grep -v grep`. It must print nothing that you started.
