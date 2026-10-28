/* "Hide amounts" switch. Masks every euro figure on the page (text, SVG labels, tooltips) and keeps the percentages.
   The data stays inside the file: this only changes what the screen and the printout show.
   #hide in the address starts the page hidden, #show starts it visible; otherwise the last choice is remembered. */
(function () {
  const RE = /[+\-−]?€\s?\d[\d,]*(?:\.\d+)?(?:\s?[kKmM]\b)?/g;
  const KEY = "portfolio-report-hide";
  const orig = new Map();   // text node -> original text
  const shown = new Map();  // text node -> masked text we wrote
  let on = false, busy = false;

  function maskNode(n) {
    const t = n.nodeValue;
    if (shown.get(n) === t) return;          // already masked by us
    if (!t || t.indexOf("€") < 0) { orig.delete(n); shown.delete(n); return; }
    const m = t.replace(RE, "€•••");
    if (m === t) return;
    orig.set(n, t); shown.set(n, m); n.nodeValue = m;
  }
  function walk(root) {
    if (root.nodeType === 3) return maskNode(root);
    if (root.nodeType !== 1 || root.id === "hide-amounts") return;
    const w = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    for (let n = w.nextNode(); n; n = w.nextNode()) if (!n.parentNode.closest || !n.parentNode.closest("#hide-amounts,script,style")) maskNode(n);
  }
  function unmaskAll() {
    for (const [n, t] of orig) if (n.isConnected && n.nodeValue === shown.get(n)) n.nodeValue = t;
    orig.clear(); shown.clear();
  }
  const obs = new MutationObserver(ms => {
    if (!on || busy) return;
    busy = true;
    for (const m of ms) {
      if (m.type === "characterData") maskNode(m.target);
      else m.addedNodes.forEach(walk);
    }
    busy = false;
  });

  function set(v) {
    on = v;
    try { localStorage.setItem(KEY, v ? "1" : "0"); } catch (e) {}
    document.documentElement.classList.toggle("amounts-hidden", v);
    const b = document.getElementById("hide-amounts");
    if (b) { b.setAttribute("aria-pressed", String(v)); b.title = v ? "Amounts hidden. Click to show them." : "Masks euro figures on screen and in print. The data is still inside the file."; }
    if (v) { busy = true; walk(document.body); busy = false; obs.observe(document.body, { subtree: true, childList: true, characterData: true }); }
    else { obs.disconnect(); unmaskAll(); }
  }

  function init() {
    const st = document.createElement("style");
    st.textContent = "#hide-amounts{display:inline-flex;align-items:center;gap:8px;font:inherit;font-size:13px;line-height:1;padding:7px 12px;border-radius:999px;border:1px solid var(--line,#ccc);background:var(--card,transparent);color:var(--ink,inherit);cursor:pointer;white-space:nowrap}" +
      "#hide-amounts i{width:28px;height:16px;border-radius:999px;background:var(--line,#bbb);position:relative;flex:none;transition:background .15s}" +
      "#hide-amounts i::after{content:'';position:absolute;top:2px;left:2px;width:12px;height:12px;border-radius:50%;background:#fff;transition:left .15s}" +
      "#hide-amounts[aria-pressed=true] i{background:var(--accent,#3b6fd8)}#hide-amounts[aria-pressed=true] i::after{left:14px}" +
      "#hide-amounts:focus-visible{outline:2px solid var(--accent,#3b6fd8);outline-offset:2px}" +
      "@media print{#hide-amounts{display:none}}";
    document.head.appendChild(st);
    const b = document.createElement("button");
    b.id = "hide-amounts"; b.type = "button";
    b.title = "Masks euro figures on screen and in print. The data is still inside the file.";
    b.innerHTML = "<i aria-hidden=\"true\"></i><span>Hide amounts</span>";
    b.addEventListener("click", () => set(!on));
    const slot = document.getElementById("hide-slot") || document.querySelector("header");
    if (slot) slot.appendChild(b); else document.body.insertBefore(b, document.body.firstChild);
    let v = false;
    try { v = localStorage.getItem(KEY) === "1"; } catch (e) {}
    if (location.hash === "#hide") v = true;
    if (location.hash === "#show") v = false;
    set(v);
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init); else init();
})();
