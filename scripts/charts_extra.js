/* Charts shared by the report and the one-pager (analyze.py inlines this file at the placeholder).
   They use the page helpers: h, sv, svText, nf, pct, eur, seur, fmtDate, MONTHS. */
const XC = (() => {
  const tipOn = (node, fn) => {
    if (typeof bindTip === 'function') return bindTip(node, fn);
    if (node instanceof SVGElement) { const t = sv('title', {}, node); t.textContent = fn().filter(Boolean).join('\n'); }
    else node.title = fn().filter(Boolean).join('\n');
  };
  const SLOTS = [1, 2, 3, 4, 5, 6, 7].map(k => `var(--s${k})`);
  const OTHER = 'var(--other)';
  const isOther = k => /^(Other|Not broken down|ETF not broken down|Cash and other)/.test(k);
  const step = (range, n) => { const raw = range / n, p = Math.pow(10, Math.floor(Math.log10(raw))), f = raw / p; return (f < 1.5 ? 1 : f < 3 ? 2 : f < 7 ? 5 : 10) * p; };
  const eurK = v => v >= 1000 ? '€' + nf(v % 1000 ? 1 : 0).format(v / 1000) + 'k' : '€' + nf(0).format(v);

  /* top n by weight with fixed colours, the rest folded into "other" (grey); "other" items in the data stay grey */
  function topN(rows, n, otherLabel) {
    const named = rows.filter(r => !isOther(r.k) && r.w > 0).sort((a, b) => b.w - a.w);
    const keep = named.slice(0, n).map((r, i) => ({...r, c: SLOTS[i]}));
    const rest = rows.filter(r => !keep.some(k => k.k === r.k));
    const restW = rest.reduce((s, r) => s + r.w, 0);
    if (restW > 0.0005) keep.push({k: otherLabel, w: restW, c: OTHER, parts: rest.filter(r => r.w >= 0.001).map(r => r.k)});
    return keep;
  }
  function themeColors(D) {
    const top = [...D.themes].sort((a, b) => b.w - a.w).slice(0, 6).map(t => t.theme);
    return t => top.includes(t) ? SLOTS[top.indexOf(t)] : OTHER;
  }

  /* donut: slices with a 2 px gap, legend beside it with the percentages */
  function donut(root, items, o = {}) {
    const S = o.size || 140, th = o.thick || Math.round(S * 0.19), R = S / 2 - 1, r0 = R - th, cx = S / 2, cy = S / 2;
    const tot = items.reduce((s, it) => s + it.w, 0) || 1;
    const svg = sv('svg', {width: S, height: S, viewBox: `0 0 ${S} ${S}`, role: 'img', 'aria-label': o.label || 'Donut chart'});
    let a = -Math.PI / 2;
    const P = (rad, ang) => `${(cx + rad * Math.cos(ang)).toFixed(2)},${(cy + rad * Math.sin(ang)).toFixed(2)}`;
    for (const it of items) {
      const da = it.w / tot * Math.PI * 2;
      if (da <= 0) continue;
      const a1 = a + Math.min(da, Math.PI * 2 - 1e-4), big = da > Math.PI ? 1 : 0;
      const d = `M${P(R, a)}A${R},${R} 0 ${big} 1 ${P(R, a1)}L${P(r0, a1)}A${r0},${r0} 0 ${big} 0 ${P(r0, a)}Z`;
      const p = sv('path', {d, fill: it.c, stroke: 'var(--surface)', 'stroke-width': 2, 'stroke-linejoin': 'round'}, svg);
      tipOn(p, () => [it.k, `${pct(it.w / tot)}${it.eur != null ? ' · ' + eur(it.eur) : ''}`, it.parts && it.parts.length ? it.parts.slice(0, 8).join(', ') + (it.parts.length > 8 ? '…' : '') : null]);
      a += da;
    }
    if (o.center) svText(svg, cx, cy - (o.centerSub ? 5 : 0), o.center, {'text-anchor': 'middle', 'dominant-baseline': 'central', class: 'dc'});
    if (o.centerSub) svText(svg, cx, cy + 11, o.centerSub, {'text-anchor': 'middle', 'dominant-baseline': 'central', class: 'tk'});
    const leg = h('ul', {class: 'dleg'}, items.map(it => {
      const s = h('span', {class: 'sw'}); s.style.setProperty('--c', it.c);
      const li = h('li', null, s, h('span', {class: 'dk', text: it.k}), h('span', {class: 'dv', text: pct(it.w / tot, o.dec != null ? o.dec : 0)}));
      tipOn(li, () => [it.k, pct(it.w / tot), it.parts && it.parts.length ? it.parts.slice(0, 8).join(', ') : null]);
      return li;
    }));
    root.replaceChildren(h('div', {class: 'donut'}, svg, leg));
  }

  /* month axis */
  function months(svg, t0, t1, X, y, every) {
    const a = new Date(t0), b = new Date(t1);
    for (let d = new Date(a.getFullYear(), a.getMonth() + 1, 1); d <= b; d = new Date(d.getFullYear(), d.getMonth() + 1, 1)) {
      if (d.getMonth() % every) continue;
      const x = X(d.getTime());
      sv('line', {x1: x, x2: x, y1: y, y2: y + 3, class: 'ax'}, svg);
      svText(svg, x, y + 13, `${MONTHS[d.getMonth()]} ${String(d.getFullYear()).slice(2)}`, {'text-anchor': 'middle', class: 'tk'});
    }
  }
  function endLabels(svg, items, x, minGap) {
    const byY = [...items].sort((p, q) => p.y - q.y);
    for (let k = 1; k < byY.length; k++) if (byY[k].y - byY[k - 1].y < minGap) byY[k].y = byY[k - 1].y + minGap;
    for (const it of items) svText(svg, x, it.y, it.text, {'dominant-baseline': 'central', class: 'el'});
  }
  /* crosshair + tooltip (only where bindTip exists, that is in the report) */
  function crosshair(svg, box, xs, onPick) {
    if (typeof tipShow !== 'function') return;
    const xh = sv('line', {class: 'xh', y1: box.t, y2: box.b, visibility: 'hidden'}, svg);
    const hit = sv('rect', {x: box.l, y: box.t, width: box.r - box.l, height: box.b - box.t, fill: 'transparent'}, svg);
    const move = e => {
      const r = svg.getBoundingClientRect(), px = (e.clientX - r.left) * (svg.viewBox.baseVal.width / r.width);
      let best = 0, bd = Infinity;
      xs.forEach((x, i) => { const d = Math.abs(x - px); if (d < bd) { bd = d; best = i; } });
      xh.setAttribute('x1', xs[best]); xh.setAttribute('x2', xs[best]); xh.setAttribute('visibility', 'visible');
      tipShow(e, onPick(best));
    };
    const off = () => { tipHide(); xh.setAttribute('visibility', 'hidden'); };
    hit.addEventListener('pointermove', e => { if (e.pointerType !== 'touch') move(e); });
    hit.addEventListener('pointerleave', e => { if (e.pointerType !== 'touch') off(); });
    hit.addEventListener('click', e => { move(e); e.stopPropagation(); });
  }

  /* stacked euro areas by theme, with the dashed line of the same money in the MSCI World */
  function valueArea(root, VH, colorOf, o = {}) {
    const W = Math.max(280, root.clientWidth), H = o.H || (W < 560 ? 240 : 300);
    const m = {l: o.compact ? 40 : 48, r: o.compact ? 58 : 70, t: 8, b: o.compact ? 16 : 24};
    const top = VH.themes.slice(0, 6), rest = VH.themes.slice(6);
    const layers = [...top.map(t => ({name: t.theme, v: t.v, c: colorOf(t.theme)}))];
    if (rest.length) layers.push({name: 'Other themes', v: VH.dates.map((_, i) => rest.reduce((s, t) => s + t.v[i], 0)), c: 'var(--other)', parts: rest.map(t => t.theme)});
    const ts = VH.dates.map(s => new Date(s + 'T12:00:00').getTime()), n = ts.length;
    const ymax = Math.max(...VH.total, ...(VH.world || []));
    const st = step(ymax, o.compact ? 3 : 5), y1 = Math.ceil(ymax / st) * st;
    const X = t => m.l + (t - ts[0]) / (ts[n - 1] - ts[0]) * (W - m.l - m.r);
    const Y = v => m.t + (1 - v / y1) * (H - m.t - m.b);
    const svg = sv('svg', {width: W, height: H, viewBox: `0 0 ${W} ${H}`, role: 'img', 'aria-label': "Euro value of today's holdings over time, by theme"});
    for (let v = 0; v <= y1 + 1e-9; v += st) {
      sv('line', {x1: m.l, x2: W - m.r, y1: Y(v), y2: Y(v), class: v === 0 ? 'ax' : 'gl'}, svg);
      svText(svg, m.l - 5, Y(v), eurK(v), {'text-anchor': 'end', 'dominant-baseline': 'central', class: 'tk'});
    }
    const base = new Array(n).fill(0);
    for (const L of layers) {
      const lo = base.slice(), hi = base.map((b, i) => b + L.v[i]);
      const d = 'M' + ts.map((t, i) => `${X(t).toFixed(1)},${Y(hi[i]).toFixed(1)}`).join('L') + 'L' + ts.map((t, i) => [t, i]).reverse().map(([t, i]) => `${X(t).toFixed(1)},${Y(lo[i]).toFixed(1)}`).join('L') + 'Z';
      const p = sv('path', {d, fill: L.c, stroke: 'var(--surface)', 'stroke-width': 1, 'stroke-linejoin': 'round'}, svg);
      if (typeof tipShow !== 'function') tipOn(p, () => [L.name, `today ${eur(L.v[n - 1])}`]);
      hi.forEach((v, i) => { base[i] = v; });
    }
    if (VH.world) sv('path', {d: VH.world.map((v, i) => (i ? 'L' : 'M') + X(ts[i]).toFixed(1) + ',' + Y(v).toFixed(1)).join(''), fill: 'none', stroke: 'var(--ink)', 'stroke-width': 1.8, 'stroke-dasharray': '5 4'}, svg);
    months(svg, ts[0], ts[n - 1], X, H - m.b, W < 560 ? 6 : 3);
    const ends = [{y: Y(VH.total[n - 1]), text: eur(VH.total[n - 1])}];
    if (VH.world) ends.push({y: Y(VH.world[n - 1]), text: eur(VH.world[n - 1])});
    endLabels(svg, ends, W - m.r + 5, 13);
    crosshair(svg, {l: m.l, r: W - m.r, t: m.t, b: H - m.b}, ts.map(X), i => [
      `Week ending ${fmtDate(VH.dates[i])}`, `Total: ${eur(VH.total[i])}`, VH.world ? `Same money in the MSCI World: ${eur(VH.world[i])}` : null,
      ...layers.filter(L => L.v[i] >= 0.5).map(L => `${L.name}: ${eur(L.v[i])}`)]);
    root.replaceChildren(svg);
  }

  /* drawdown from the previous peak (underwater chart) */
  function drawdown(root, BT, o = {}) {
    const W = Math.max(280, root.clientWidth), H = o.H || (W < 560 ? 200 : 230), m = {l: 44, r: 52, t: 8, b: 24};
    const dd = arr => { let mx = -Infinity; return arr.map(v => { mx = Math.max(mx, v); return v / mx - 1; }); };
    const S = [{name: "Today's quantities, unchanged", v: dd([1, ...BT.hold]), c: 'var(--s3)'}, {name: 'MSCI World (in euros)', v: dd([1, ...BT.world]), c: 'var(--s2)'}];
    const d0 = new Date(BT.dates[0] + 'T12:00:00').getTime() - 7 * 864e5;
    const ts = [d0, ...BT.dates.map(s => new Date(s + 'T12:00:00').getTime())], n = ts.length;
    const lo = Math.min(...S.flatMap(s => s.v)), st = step(-lo, 4), y0 = Math.floor(lo / st) * st;
    const X = t => m.l + (t - ts[0]) / (ts[n - 1] - ts[0]) * (W - m.l - m.r), Y = v => m.t + (v / y0) * (H - m.t - m.b);
    const svg = sv('svg', {width: W, height: H, viewBox: `0 0 ${W} ${H}`, role: 'img', 'aria-label': 'Drawdown from the previous peak'});
    for (let v = 0; v >= y0 - 1e-9; v -= st) {
      sv('line', {x1: m.l, x2: W - m.r, y1: Y(v), y2: Y(v), class: Math.abs(v) < 1e-9 ? 'ax' : 'gl'}, svg);
      svText(svg, m.l - 5, Y(v), nf(0).format(v * 100) + '%', {'text-anchor': 'end', 'dominant-baseline': 'central', class: 'tk'});
    }
    const s0 = S[0];
    sv('path', {d: `M${X(ts[0])},${Y(0)}L` + s0.v.map((v, i) => `${X(ts[i]).toFixed(1)},${Y(v).toFixed(1)}`).join('L') + `L${X(ts[n - 1])},${Y(0)}Z`, fill: s0.c, 'fill-opacity': 0.16}, svg);
    for (const s of S) sv('path', {d: s.v.map((v, i) => (i ? 'L' : 'M') + X(ts[i]).toFixed(1) + ',' + Y(v).toFixed(1)).join(''), class: 'ln', stroke: s.c}, svg);
    months(svg, ts[0], ts[n - 1], X, H - m.b, W < 560 ? 6 : 3);
    /* low point of each line: dot and value */
    const mins = S.map(s => { const i = s.v.indexOf(Math.min(...s.v)); return {s, i}; });
    for (const {s, i} of mins) sv('circle', {cx: X(ts[i]), cy: Y(s.v[i]), r: 4, fill: s.c, stroke: 'var(--surface)', 'stroke-width': 2}, svg);
    endLabels(svg, mins.map(({s, i}) => ({y: Y(s.v[i]), text: pct(s.v[i], 0)})), Math.max(...mins.map(({i}) => X(ts[i]))) + 9, 14);
    crosshair(svg, {l: m.l, r: W - m.r, t: m.t, b: H - m.b}, ts.map(X), i => [i ? `Week ending ${fmtDate(BT.dates[i - 1])}` : 'Start', ...S.map(s => `${s.name}: ${pct(s.v[i])} from the peak`)]);
    root.replaceChildren(svg);
  }

  /* treemap: one rectangle per position, area = weight, colour = theme */
  function treemap(root, items, colorOf, o = {}) {
    const W = Math.max(280, root.clientWidth), H = o.H || (W < 560 ? 340 : 360);
    const tot = items.reduce((s, it) => s + it.w, 0);
    const list = [...items].sort((a, b) => b.w - a.w).map(it => ({...it, a: it.w / tot * W * H}));
    const worst = (row, s) => { const sm = row.reduce((p, r) => p + r.a, 0), mx = Math.max(...row.map(r => r.a)), mn = Math.min(...row.map(r => r.a)); return Math.max(s * s * mx / (sm * sm), sm * sm / (s * s * mn)); };
    const out = [];
    (function lay(rest, x, y, w, h) {
      if (!rest.length) return;
      if (rest.length === 1) { out.push({...rest[0], x, y, bw: w, bh: h}); return; }
      const s = Math.min(w, h);
      let row = [], i = 0, best = Infinity;
      while (i < rest.length) { const c = [...row, rest[i]], q = worst(c, s); if (row.length && q > best) break; row = c; best = q; i++; }
      const sum = row.reduce((p, r) => p + r.a, 0), t = sum / s;
      let off = 0;
      for (const r of row) { const len = r.a / t; out.push(w >= h ? {...r, x, y: y + off, bw: t, bh: len} : {...r, x: x + off, y, bw: len, bh: t}); off += len; }
      w >= h ? lay(rest.slice(i), x + t, y, w - t, h) : lay(rest.slice(i), x, y + t, w, h - t);
    })(list, 0, 0, W, H);
    const svg = sv('svg', {width: W, height: H, viewBox: `0 0 ${W} ${H}`, role: 'img', 'aria-label': 'Positions by weight, coloured by theme'});
    for (const r of out) {
      const g = sv('g', {}, svg);
      sv('rect', {x: r.x + 1, y: r.y + 1, width: Math.max(0, r.bw - 2), height: Math.max(0, r.bh - 2), rx: 3, fill: colorOf(r.theme)}, g);
      if (r.bw >= 34 && r.bh >= 15) svText(g, r.x + 5, r.y + 12, r.ticker, {class: 'tml'});
      if (r.bw >= 40 && r.bh >= 29) svText(g, r.x + 5, r.y + 25, pct(r.w / tot, 1), {class: 'tmv'});
      tipOn(g, () => [r.name, `${r.theme} · ${r.kind}`, `${eur(r.value)}, ${pct(r.w / tot)} of the total`]);
    }
    root.replaceChildren(svg);
  }

  /* gain or loss on cost by theme: diverging euro bars */
  function pnlBars(root, rows, o = {}) {
    const W = Math.max(280, root.clientWidth), rh = o.rh || 20, lw = o.lw || (W < 480 ? 118 : 170), room = o.room || 54;
    const H = rows.length * rh + 4;
    const mn = Math.min(0, ...rows.map(r => r.v)), mx = Math.max(0, ...rows.map(r => r.v));
    const pl = lw + room, pw = W - pl - room, span = (mx - mn) || 1, x0 = pl + pw * (-mn / span), k = pw / span;
    const svg = sv('svg', {width: W, height: H, viewBox: `0 0 ${W} ${H}`, role: 'img', 'aria-label': o.label || 'Gain or loss on cost by theme'});
    rows.forEach((r, i) => {
      const y = i * rh + 2, cy = y + rh / 2, bh = Math.min(12, rh - 6);
      const g = sv('g', {}, svg);
      sv('rect', {x: 0, y, width: W, height: rh, fill: 'transparent'}, g);
      const lab = r.k.length > (lw / 6.2) ? r.k.slice(0, Math.floor(lw / 6.2) - 1) + '…' : r.k;
      svText(g, lw - 6, cy, lab, {'text-anchor': 'end', 'dominant-baseline': 'central', class: 'bl'});
      const len = Math.max(2, Math.abs(r.v) * k), neg = r.v < 0;
      sv('rect', {x: neg ? x0 - len : x0, y: cy - bh / 2, width: len, height: bh, rx: 3, fill: neg ? 'var(--dp3)' : 'var(--dn3)'}, g);
      svText(g, neg ? x0 - len - 4 : x0 + len + 4, cy, seur(r.v), {'text-anchor': neg ? 'end' : 'start', 'dominant-baseline': 'central', class: 'bv'});
      tipOn(g, () => [r.k, `value ${eur(r.value)}, cost ${eur(r.cost)}`, `${seur(r.v)} (${r.cost ? (r.v > 0 ? '+' : '') + nf(1).format(r.v / r.cost * 100) + '%' : 'n/a'})`]);
    });
    sv('line', {x1: x0, x2: x0, y1: 0, y2: H, class: 'ax'}, svg);
    root.replaceChildren(svg);
  }

  return {topN, themeColors, donut, valueArea, drawdown, treemap, pnlBars, OTHER, SLOTS};
})();
