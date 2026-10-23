"""SVG helpers for the landing page: circuit diagrams and charts.

Every function takes data and returns an SVG string; nothing here runs a
tool. Colours are CSS variables (`--accent`, `--muted`, ...), so a figure
follows the page's light and dark schemes, and the same SVG can be saved to
a file (`docs/img/`) where the variables fall back to the defaults in
`style=` attributes the page's stylesheet overrides.
"""
import html
import math

PHASE = "hsl({h:.0f} 55% {l}%)"


def esc(s):
    return html.escape(str(s), quote=True)


def circuit_svg(n, ops, label, current=None):
    """A circuit diagram. `ops` are tuples like ('h', 0), ('cx', 0, 1), ('rz', 0, 1, 3), ('m', 0).

    `current` highlights one op index (the stepper uses it from JS by id)."""
    drawn = [o for o in ops if o[0] not in ("seed", "trig")]
    col = 44
    left, top, gap = 36, 18, 34
    w = left + col * max(len(drawn), 1) + 16
    h = top * 2 + gap * (n - 1) + 8
    o = [f'<svg viewBox="0 0 {w} {h}" role="img" aria-label="{esc(label)}" class="circ">']
    for q in range(n):
        y = top + gap * q
        o.append(f'<text x="6" y="{y + 4}" class="qlab">q{q}</text>')
        o.append(f'<line x1="{left - 6}" y1="{y}" x2="{w - 8}" y2="{y}" class="wire"/>')
    for i, op in enumerate(drawn):
        x = left + col * i + col / 2
        name, a = op[0], op[1:]
        cid = f'id="op{i}" ' if current is not None else ""
        o.append(f'<g {cid}class="op">')
        if name in ("cx", "cz"):
            yc, yt = top + gap * a[0], top + gap * a[1]
            o.append(f'<line x1="{x}" y1="{yc}" x2="{x}" y2="{yt}" class="link"/>')
            o.append(f'<circle cx="{x}" cy="{yc}" r="4" class="dot"/>')
            if name == "cx":
                o.append(f'<circle cx="{x}" cy="{yt}" r="9" class="tgt"/>')
                o.append(f'<line x1="{x - 9}" y1="{yt}" x2="{x + 9}" y2="{yt}" class="link"/><line x1="{x}" y1="{yt - 9}" x2="{x}" y2="{yt + 9}" class="link"/>')
            else:
                o.append(f'<circle cx="{x}" cy="{yt}" r="4" class="dot"/>')
        elif name == "m":
            y = top + gap * a[0]
            o.append(f'<rect x="{x - 12}" y="{y - 11}" width="24" height="22" rx="3" class="box meas"/>')
            o.append(f'<path d="M {x - 8} {y + 4} A 8 8 0 0 1 {x + 8} {y + 4}" class="arc"/><line x1="{x}" y1="{y + 4}" x2="{x + 6}" y2="{y - 6}" class="link"/>')
        else:
            y = top + gap * a[0]
            lab = {"h": "H", "x": "X", "z": "Z", "s": "S", "t": "T", "rz": "Rz"}[name]
            o.append(f'<rect x="{x - 12}" y="{y - 11}" width="24" height="22" rx="3" class="box"/>')
            o.append(f'<text x="{x}" y="{y + 4}" text-anchor="middle" class="glab">{lab}</text>')
            if name == "rz":
                o.append(f'<text x="{x}" y="{y + 22}" text-anchor="middle" class="sub">{a[1]}&#960;/{a[2]}</text>')
        o.append("</g>")
    o.append("</svg>")
    return "".join(o)


def phase_color(re, im):
    ang = math.atan2(im, re)
    return PHASE.format(h=(ang / (2 * math.pi)) % 1.0 * 360, l=48)


def hbar_chart(rows, label, gate=None, unit=""):
    """Horizontal bars on a log axis. rows = [(name, value)]; values <= 0 are drawn as a stub."""
    lw, w, rh = 120, 520, 15
    h = rh * len(rows) + 34
    lo, hi = 1e-17, max([v for _, v in rows] + ([gate] if gate else [])) * 3
    def x(v):
        v = max(v, lo)
        return lw + (math.log10(v) - math.log10(lo)) / (math.log10(hi) - math.log10(lo)) * (w - lw - 10)
    o = [f'<svg viewBox="0 0 {w} {h}" role="img" aria-label="{esc(label)}" class="chart">']
    for e in range(-16, int(math.log10(hi)) + 1, 2):
        if gate and e == round(math.log10(gate)):
            continue
        xx = x(10.0 ** e)
        o.append(f'<line x1="{xx:.1f}" y1="6" x2="{xx:.1f}" y2="{h - 22}" class="grid"/><text x="{xx:.1f}" y="{h - 8}" text-anchor="middle" class="tick">1e{e}</text>')
    for i, (name, v) in enumerate(rows):
        y = 8 + i * rh
        o.append(f'<text x="{lw - 6}" y="{y + 10}" text-anchor="end" class="tick">{esc(name)}</text>')
        bw = max(x(v) - lw, 1.5)
        o.append(f'<rect x="{lw}" y="{y + 1}" width="{bw:.1f}" height="{rh - 4}" class="bar"><title>{esc(name)}: {v:.2e}{unit}</title></rect>')
    if gate:
        xg = x(gate)
        o.append(f'<line x1="{xg:.1f}" y1="4" x2="{xg:.1f}" y2="{h - 22}" class="gateline"/><text x="{xg - 4:.1f}" y="14" text-anchor="end" class="gtext">gate {gate:g}</text>')
    o.append("</svg>")
    return "".join(o)


def count_hist(labels, counts, expected, band, label):
    """Vertical bars of counts with an expected line and a +/- band."""
    w, h, pad = 360, 150, 22
    top = max(max(counts), expected + band) * 1.15 or 1
    bw = (w - 2 * pad) / len(counts)
    def y(v):
        return h - pad - (h - 2 * pad) * v / top
    o = [f'<svg viewBox="0 0 {w} {h}" role="img" aria-label="{esc(label)}" class="chart">']
    if band:
        o.append(f'<rect x="{pad}" y="{y(expected + band):.1f}" width="{w - 2 * pad}" height="{y(expected - band) - y(expected + band):.1f}" class="band"/>')
    for i, c in enumerate(counts):
        o.append(f'<rect x="{pad + i * bw + 2:.1f}" y="{y(c):.1f}" width="{bw - 4:.1f}" height="{h - pad - y(c):.1f}" class="bar"><title>{esc(labels[i])}: {c}</title></rect>')
        o.append(f'<text x="{pad + (i + .5) * bw:.1f}" y="{h - 8}" text-anchor="middle" class="tick">{esc(labels[i])}</text>')
        o.append(f'<text x="{pad + (i + .5) * bw:.1f}" y="{y(c) - 3:.1f}" text-anchor="middle" class="tick">{c}</text>')
    if expected:
        o.append(f'<line x1="{pad}" y1="{y(expected):.1f}" x2="{w - pad}" y2="{y(expected):.1f}" class="gateline"/>')
    o.append(f'<line x1="{pad}" y1="{h - pad}" x2="{w - pad}" y2="{h - pad}" class="axis"/></svg>')
    return "".join(o)


def line_chart(series, xs, label, xlab, ylab):
    """Log-y line chart. series = [(name, [y...])], xs = [x...]."""
    w, h, l, r, t, b = 520, 230, 46, 14, 12, 38
    ys = [v for _, vs in series for v in vs]
    lo, hi = 10 ** math.floor(math.log10(min(ys))), 10 ** math.ceil(math.log10(max(ys)))
    def X(v):
        return l + (v - xs[0]) / (xs[-1] - xs[0]) * (w - l - r)
    def Y(v):
        return t + (1 - (math.log10(v) - math.log10(lo)) / (math.log10(hi) - math.log10(lo))) * (h - t - b)
    o = [f'<svg viewBox="0 0 {w} {h}" role="img" aria-label="{esc(label)}" class="chart">']
    e = int(math.log10(lo))
    while 10.0 ** e <= hi * 1.0001:
        o.append(f'<line x1="{l}" y1="{Y(10.0 ** e):.1f}" x2="{w - r}" y2="{Y(10.0 ** e):.1f}" class="grid"/><text x="{l - 5}" y="{Y(10.0 ** e) + 3:.1f}" text-anchor="end" class="tick">{10.0 ** e:g}</text>')
        e += 1
    for x in xs:
        o.append(f'<text x="{X(x):.1f}" y="{h - b + 14}" text-anchor="middle" class="tick">{x}</text>')
    for k, (name, vs) in enumerate(series):
        pts = " ".join(f"{X(x):.1f},{Y(v):.1f}" for x, v in zip(xs, vs))
        o.append(f'<polyline points="{pts}" class="line s{k}"/>')
        for x, v in zip(xs, vs):
            o.append(f'<circle cx="{X(x):.1f}" cy="{Y(v):.1f}" r="2.5" class="pt s{k}"><title>{esc(name)}, {x} qubits: {v:g} s</title></circle>')
        o.append(f'<text x="{w - r - 4}" y="{Y(vs[-1]) - 6:.1f}" text-anchor="end" class="ltext s{k}">{esc(name)}</text>')
    o.append(f'<text x="{(l + w - r) / 2}" y="{h - 4}" text-anchor="middle" class="tick">{esc(xlab)}</text>')
    o.append(f'<text x="10" y="{(t + h - b) / 2}" class="tick" transform="rotate(-90 10 {(t + h - b) / 2})" text-anchor="middle">{esc(ylab)}</text>')
    o.append("</svg>")
    return "".join(o)
