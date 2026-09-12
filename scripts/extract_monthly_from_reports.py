"""Extract the monthly P&L series from the private monthly-report PDFs.

Reads ONLY the "P&L by month" bar chart: signed bar geometry (vector paths,
identified by their uniform width and a shared zero line) scaled by the factor
that reconciles the series to the book's PRINTED total. Cross-checked against
the 1-3 months matplotlib labels as text. Nothing about engines, exits or
individual trades is read or emitted -- outputs only (ADR-0001).
"""
import json
import pathlib
import re
import sys
import zlib
from collections import Counter

REPORTS = pathlib.Path(r"D:\Projects\index-options-trading-bot\quick_reference\monthly_reports")
MONTH_RE = re.compile(r'^(Sep|Oct|Nov|Dec|Jan|Feb|Mar|Apr|May|Jun|Jul|Aug)\s*(\d{2})$')
MON2NUM = {m: i for i, m in enumerate(
    ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"], 1)}

def streams(path):
    raw = path.read_bytes(); out = []
    for m in re.finditer(rb'stream\r?\n(.*?)endstream', raw, re.DOTALL):
        try:
            out.append(zlib.decompress(m.group(1)).decode('latin-1'))
        except zlib.error:
            continue  # not a Flate stream (image/font data) -- skip it
    return out

def blocks(blob):
    return [s.strip() for bt in re.finditer(r'BT(.*?)ET', blob, re.DOTALL)
            if (s := "".join(re.findall(r'\(([^)]*)\)', bt.group(1)))).strip()]

def subpaths(blob):
    out = []
    for m in re.finditer(r'([\d.\s\-]+?)(m[\s\S]{0,400}?)(f\*?|S|B)\b', blob):
        pts = [(float(a), float(b)) for a, b in
               re.findall(r'([-\d.]+)\s+([-\d.]+)\s+[ml]', m.group(0))]
        if len(pts) == 4:                     # a bar is exactly 4 corners
            xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
            out.append((min(xs), max(xs), min(ys), max(ys), m.group(3)))
    return out

def monthly_bars(blob):
    """Signed bars of the month chart: uniform width, sharing one zero line."""
    paths = [p for p in subpaths(blob) if p[4] == 'f']
    if not paths: return None
    widths = Counter(round(p[1] - p[0], 1) for p in paths)
    for w, _ in widths.most_common(4):
        if w < 5 or w > 120: continue         # skip hairlines and panel frames
        grp = [p for p in paths if abs((p[1] - p[0]) - w) < 0.15]
        if len(grp) < 6: continue
        # the zero line is the y shared by the most bars (bottom for +, top for -)
        edges = Counter()
        for x0, x1, y0, y1, _ in grp: edges[round(y0, 1)] += 1; edges[round(y1, 1)] += 1
        zero, n = edges.most_common(1)[0]
        if n < len(grp) * 0.7: continue
        bars = []
        for x0, x1, y0, y1, _ in sorted(grp, key=lambda p: p[0]):
            if abs(y0 - zero) < 0.2: bars.append((x0, y1 - y0))      # positive
            elif abs(y1 - zero) < 0.2: bars.append((x0, -(y1 - y0))) # negative
        if len(bars) >= 6: return [h for _, h in bars]
    return None

def extract(pdf, printed_total):
    for blob in streams(pdf):
        heights = monthly_bars(blob)
        if not heights: continue
        txt = blocks(blob)
        months = [t for t in txt if MONTH_RE.match(t)]
        if len(months) < len(heights): continue
        seq = months[len(months) - len(heights):]   # the bar chart's own axis
        labels = [float(t.replace('+', '').replace('\u2212', '-'))
                  for t in txt if re.fullmatch(r'[+\u2212-]?\d{1,5}\.\d{2}', t)]
        total_h = sum(heights)
        if abs(total_h) < 1e-6: continue
        k = printed_total / total_h                 # scale that reconciles the sum
        vals = [round(h * k, 2) for h in heights]
        # verify against every printed bar label
        checks = []
        for lab in labels:
            if abs(lab) < 10: continue
            near = min(vals, key=lambda v: abs(v - lab))
            if abs(near - lab) < max(1.0, abs(lab) * 0.01): checks.append((lab, near))
        return seq, vals, round(sum(vals), 2), checks
    return None

BOOKS = {
    "sensex-expiry": ("sensex_expiry_entry2_report.pdf", 5930.64),
    "nifty-weekday-high-vix": ("nifty_weekday_high_vix_report.pdf", 901.08),
    "nifty-weekday-low-vix": ("nifty_weekday_low_vix_report.pdf", 1327.39),
    "nifty-weekday-r1s1": ("nifty_weekday_r1s1_report.pdf", 513.75),
    "nifty-expiry-high-vix": ("nifty_expiry_high_vix_report.pdf", 796.62),
    "nifty-expiry-low-vix": ("nifty_expiry_low_vix_report.pdf", 339.11),
    "sensex-weekday-r1s1": ("sensex_weekday_r1s1_report.pdf", 1313.82),
}
out, bad = {}, []
for bid, (fn, total) in BOOKS.items():
    r = extract(REPORTS / fn, total)
    if not r:
        print(f"{bid:26} FAILED"); bad.append(bid); continue
    seq, vals, s, checks = r
    ok = all(abs(a - b) < max(1.0, abs(a) * 0.01) for a, b in checks)
    print(f"{bid:26} months={len(vals):2} sum={s:9.2f} printed={total:9.2f} "
          f"diff={s-total:+6.2f} labels_matched={len(checks)} {'OK' if ok else 'LABEL MISMATCH'}")
    for a, b in checks: print(f"    printed {a:+9.2f}  derived {b:+9.2f}  delta {b-a:+.2f}")
    rows = []
    for label, v in zip(seq, vals):
        mm = MONTH_RE.match(label)
        rows.append({"month": f"20{mm.group(2)}-{MON2NUM[mm.group(1)]:02d}", "pnl_points": v})
    out[bid] = {"rows": rows, "sum": s, "printed": total}
with open(sys.argv[1], "w", encoding="utf-8") as fh:
    json.dump(out, fh, indent=2)
print(f"\nwrote {sys.argv[1]}  ({len(out)}/7 books)" + (f"  FAILED: {bad}" if bad else ""))
