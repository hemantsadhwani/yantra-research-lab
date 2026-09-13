#!/usr/bin/env python3
"""Deterministic Excalidraw generator for the yantra-research-lab architecture diagrams.

Stdlib only. Running this rewrites all five .excalidraw files byte-for-byte
identically every time, so they can be diffed and gated in CI.

    python gen_diagrams.py            # write all five files
    python gen_diagrams.py --check    # regenerate in memory, exit 1 if disk differs

Style follows tier3-architecture.excalidraw (the older hand-made diagram, kept):
canvas #ffffff, gridSize 20, fontFamily 1 (hand-drawn), strokeColor #1e1e1e,
roughness 1, rounded rectangles, pastel fills. Dashed stroke == TARGET / ROADMAP /
NOT SERVED, and always labelled as such.

Layout is computed, never hard-coded: text is measured and wrapped at
CHAR_RATIO * fontSize per character, containers grow to fit their wrap, and each
row/column is re-flowed from the measured extent of the one before it. Arrows are
anchored on box edges chosen from the two centres' relative position and elbowed
through lane gutters. `validate()` fails loudly on a text overflow, a mis-anchored
arrow, an arrow crossing a third box, or a label sitting on a box.

Visual hierarchy: each card is a darker header band carrying a 16px outcome
headline, over a body carrying 13px muted detail (product, version, where it runs).
The three things a reviewer must notice - the outputs-only boundary, the
research_corpus NOT READ gap, and the refusals that never call the model - are drawn
with a 2px #e03131 stroke and a ">>" prefix.

Accuracy rules (see CLAUDE.md "Claims discipline"): every solid box is something
that actually runs today; everything aspirational is dashed and labelled. No
secrets, no strategy parameters, no indicator names appear in any diagram.
"""


from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import sys
from pathlib import Path

# ---------------------------------------------------------------- palette

INK = "#1e1e1e"
MUTED = "#5c5f66"
LANE_INK = "#495057"
LANE_STROKE = "#868e96"
NOTE_STROKE = "#0c8599"
ALERT = "#e03131"

FRONTEND = "#e7f5ff"  # frontend / serving
DATA = "#ebfbee"  # data / storage
LLM = "#f3f0ff"  # LLM / AI
GUARD = "#fff4e6"  # guardrails / boundaries
CI = "#fff9db"  # CI / compute
PLAIN = "#ffffff"

# One shade darker per fill, used for the card header band.
BAND = {
    FRONTEND: "#d0ebff",
    DATA: "#d3f9d8",
    LLM: "#e5dbff",
    GUARD: "#ffe8cc",
    CI: "#fff3bf",
    PLAIN: "#f1f3f5",
}

FS_BODY = 13
FS_CARD = 16  # card headline
FS_TITLE = 15  # lane titles
FS_HEAD = 24  # diagram title

BAND_H = 26  # card header band height
BAND_VPAD = 4  # vertical breathing room for the headline inside its band
PAD = 12  # text padding inside a container
LANE_BAND = 16  # reserved band under a lane title, above the first box

# A fixed timestamp keeps output deterministic (Excalidraw only uses it for ordering).
UPDATED = 1751720000000

CANVAS_W = 1500
CANVAS_H = 900


# ---------------------------------------------------------------- id / seed

def _digest(key: str) -> int:
    return int(hashlib.sha256(key.encode("utf-8")).hexdigest()[:12], 16)


def eid(prefix: str, key: str) -> str:
    """Deterministic element id: stable across regeneration for the same label."""
    return f"{prefix}-{hashlib.sha256(key.encode('utf-8')).hexdigest()[:16]}"


def _seed(key: str) -> int:
    return _digest("seed:" + key) % 2_000_000_000


def _nonce(key: str) -> int:
    return _digest("nonce:" + key) % 2_000_000_000


# ---------------------------------------------------------------- text metrics

# Excalidraw's fontFamily 1 (Virgil, hand-drawn) averages ~0.62 * fontSize per
# character. We measure conservatively at 0.66 so a wrap that fits here always
# fits in the renderer, and line height is Excalidraw's own 1.25 * fontSize.
CHAR_RATIO = 0.66
LINE_RATIO = 1.25

WARNINGS: list[str] = []


def char_w(font_size: int) -> float:
    return font_size * CHAR_RATIO


def line_h(font_size: int) -> float:
    return round(font_size * LINE_RATIO, 1)


def measure_wrap(text: str, font_size: int, inner_width: float) -> list[str]:
    """Word-wrap `text` to `inner_width` px at CHAR_RATIO * font_size per char.

    Explicit newlines in the source are honoured as hard breaks. A word is never
    split: if a single word is wider than inner_width it is emitted on its own
    line (overflowing) and a warning is recorded.
    """
    out: list[str] = []
    for para in text.split("\n"):
        if not para.strip():
            out.append("")
            continue
        words = para.split()
        cur = ""
        for word in words:
            if measure_text_w(word, font_size) > inner_width:
                WARNINGS.append(
                    f"word '{word}' ({measure_text_w(word, font_size):.0f}px) exceeds "
                    f"inner width {inner_width:.0f}px at {font_size}px"
                )
            cand = word if not cur else cur + " " + word
            if measure_text_w(cand, font_size) <= inner_width:
                cur = cand
            else:
                if cur:
                    out.append(cur)
                cur = word
        out.append(cur)
    return out


def measure_text_w(text: str, font_size: int) -> float:
    """Width of a single line: every character counts, digits and punctuation too."""
    return len(text) * char_w(font_size)


def wrapped_w(lines: list[str], font_size: int) -> float:
    return round(max((measure_text_w(ln, font_size) for ln in lines), default=0.0), 1)


def wrapped_h(lines: list[str], font_size: int) -> float:
    return round(line_h(font_size) * max(1, len(lines)), 1)


def fit_height(text: str, font_size: int, inner_width: float) -> float:
    """Container height needed to hold `text` wrapped to inner_width."""
    return wrapped_h(measure_wrap(text, font_size, inner_width), font_size) + 2 * PAD


# ---------------------------------------------------------------- element factories

class Diagram:
    """Accumulates elements and knows where every rectangle sits (for validation)."""

    def __init__(self, name: str, title: str, subtitle: str = "") -> None:
        self.name = name
        self.elements: list[dict] = []
        self.rects: list[tuple[str, float, float, float, float]] = []  # label,x,y,w,h
        self.lanes: set[str] = set()  # ids of lane/group rects, exempt from overlap
        self.boxes: dict[str, tuple[float, float, float, float]] = {}  # id -> rect
        self.textfits: list[tuple[str, float, float, float, float, float]] = []
        self.labels: list[tuple[str, float, float, float, float]] = []
        self.segments: list[tuple[str, list[tuple[float, float]], str, str]] = []
        self.lane_rects: list[tuple[float, float, float, float]] = []
        self.text_rects: list[tuple[float, float, float, float]] = []
        # Lane/group title text boxes: arrows must not run through them either.
        self.title_rects: list[tuple[str, float, float, float, float]] = []
        self._n = 0
        if title:
            self.text(20, 16, title, font_size=FS_HEAD)
        if subtitle:
            self.text(20, 52, subtitle, font_size=FS_BODY, color=MUTED)

    # -- low level -------------------------------------------------------

    def _base(self, kind: str, key: str, x: float, y: float, w: float, h: float) -> dict:
        self._n += 1
        return {
            "id": eid(kind[:4], key),
            "type": kind,
            "x": round(x, 1),
            "y": round(y, 1),
            "width": round(w, 1),
            "height": round(h, 1),
            "angle": 0,
            "strokeColor": INK,
            "backgroundColor": "transparent",
            "fillStyle": "solid",
            "strokeWidth": 1,
            "strokeStyle": "solid",
            "roughness": 1,
            "opacity": 100,
            "groupIds": [],
            "frameId": None,
            "roundness": None,
            "seed": _seed(key),
            "version": 1,
            "versionNonce": _nonce(key),
            "isDeleted": False,
            "boundElements": [],
            "updated": UPDATED,
            "link": None,
            "locked": False,
        }

    # -- free text (titles, lane headers, annotations) -------------------

    def text(
        self,
        x: float,
        y: float,
        content: str,
        font_size: int = FS_BODY,
        color: str = INK,
        align: str = "left",
        key: str | None = None,
        max_width: float | None = None,
    ) -> dict:
        key = key or f"{self.name}:text:{content}:{x}:{y}"
        lines = (
            measure_wrap(content, font_size, max_width)
            if max_width
            else content.split("\n")
        )
        el = self._base(
            "text", key, x, y, wrapped_w(lines, font_size), wrapped_h(lines, font_size)
        )
        el.update(
            {
                "strokeColor": color,
                "text": "\n".join(lines),
                "originalText": content,
                "fontSize": font_size,
                "fontFamily": 1,
                "textAlign": align,
                "verticalAlign": "top",
                "containerId": None,
                "autoResize": True,
                "lineHeight": LINE_RATIO,
                "baseline": round(font_size * 0.77, 1),
            }
        )
        self.elements.append(el)
        # Free text is a no-go area for arrow labels too.
        self.text_rects.append((el["x"], el["y"], el["width"], el["height"]))
        return el

    # -- bound text inside a container ------------------------------------

    def _bind_text(
        self,
        rect: dict,
        key: str,
        content: str,
        font_size: int,
        color: str,
        label: str,
        vpad: float = PAD,
    ) -> dict:
        """Wrap `content` to the container and bind it, centred, inside."""
        inner_w = rect["width"] - 2 * PAD
        lines = measure_wrap(content, font_size, inner_w)
        th = wrapped_h(lines, font_size)
        tw = wrapped_w(lines, font_size)
        txt = self._base(
            "text",
            key,
            rect["x"] + PAD,
            rect["y"] + max(2.0, (rect["height"] - th) / 2),
            inner_w,
            th,
        )
        txt.update(
            {
                "strokeColor": color,
                "text": "\n".join(lines),
                "originalText": content,
                "fontSize": font_size,
                "fontFamily": 1,
                "textAlign": "center",
                "verticalAlign": "center",
                "containerId": rect["id"],
                "autoResize": False,
                "lineHeight": LINE_RATIO,
                "baseline": round(font_size * 0.77, 1),
            }
        )
        rect["boundElements"] = (rect["boundElements"] or []) + [
            {"id": txt["id"], "type": "text"}
        ]
        self.elements.append(txt)
        # Record for the fit assertion: wrapped box vs its container.
        self.textfits.append((label, th, tw, rect["width"], rect["height"], vpad))
        return txt

    # -- plain box with one bound label -----------------------------------

    def box(
        self,
        key: str,
        x: float,
        y: float,
        w: float,
        h: float,
        label: str,
        fill: str = PLAIN,
        stroke: str = INK,
        dashed: bool = False,
        font_size: int = FS_BODY,
        stroke_width: int = 1,
        text_color: str | None = None,
        grow: bool = True,
    ) -> str:
        """Rounded rectangle with text bound into it. Grows to fit. Returns its id."""
        if grow:
            h = max(h, fit_height(label, font_size, w - 2 * PAD))
        rkey = f"{self.name}:box:{key}"
        rect = self._base("rectangle", rkey, x, y, w, h)
        rect.update(
            {
                "strokeColor": stroke,
                "backgroundColor": fill,
                "roundness": {"type": 3},
                "strokeStyle": "dashed" if dashed else "solid",
                "strokeWidth": stroke_width,
            }
        )
        self.elements.append(rect)
        self._bind_text(
            rect,
            f"{self.name}:boxtext:{key}",
            label,
            font_size,
            text_color or (stroke if stroke != LANE_STROKE else INK),
            f"{self.name}:{key}",
        )
        self.rects.append((key, x, y, w, h))
        self.boxes[rect["id"]] = (x, y, w, h)
        return rect["id"]

    # -- card: header band + detail body ---------------------------------

    def card(
        self,
        key: str,
        x: float,
        y: float,
        w: float,
        headline: str,
        detail: str = "",
        fill: str = PLAIN,
        dashed: bool = False,
        alert: bool = False,
        min_h: float = 0.0,
    ) -> Card:
        """A two-tier card: darker header band with the outcome headline, muted body.

        The band carries the 16px headline; the body carries the 13px detail lines in
        MUTED. Height is computed from both wraps, so a card always fits its text.
        """
        stroke = ALERT if alert else INK
        sw = 2 if alert else 1
        head = (">> " + headline) if alert else headline

        inner = w - 2 * PAD
        head_lines = measure_wrap(head, FS_CARD, inner)
        band_h = max(BAND_H, wrapped_h(head_lines, FS_CARD) + 2 * BAND_VPAD)
        body_h = (
            wrapped_h(measure_wrap(detail, FS_BODY, inner), FS_BODY) + 2 * PAD
            if detail
            else 0.0
        )
        h = max(min_h, band_h + body_h)

        rkey = f"{self.name}:card:{key}"
        rect = self._base("rectangle", rkey, x, y, w, h)
        rect.update(
            {
                "strokeColor": stroke,
                "backgroundColor": fill,
                "roundness": {"type": 3},
                "strokeStyle": "dashed" if dashed else "solid",
                "strokeWidth": sw,
            }
        )
        self.elements.append(rect)

        bkey = f"{self.name}:band:{key}"
        band = self._base("rectangle", bkey, x, y, w, band_h)
        band.update(
            {
                "strokeColor": stroke,
                "backgroundColor": BAND.get(fill, "#f1f3f5"),
                "roundness": {"type": 3},
                "strokeStyle": "dashed" if dashed else "solid",
                "strokeWidth": sw,
            }
        )
        self.elements.append(band)
        self._bind_text(
            band,
            f"{self.name}:bandtext:{key}",
            head,
            FS_CARD,
            stroke if alert else INK,
            f"{self.name}:{key}:head",
            vpad=BAND_VPAD,
        )

        if detail:
            body = self._base(
                "rectangle", f"{self.name}:body:{key}", x, y + band_h, w, h - band_h
            )
            body.update(
                {
                    "strokeColor": "transparent",
                    "backgroundColor": "transparent",
                    "roundness": {"type": 3},
                    "strokeWidth": 1,
                }
            )
            self.elements.append(body)
            self._bind_text(
                body,
                f"{self.name}:bodytext:{key}",
                detail,
                FS_BODY,
                MUTED,
                f"{self.name}:{key}:body",
            )

        self.rects.append((key, x, y, w, h))
        self.boxes[rect["id"]] = (x, y, w, h)
        return Card(rect["id"], x, y, w, h)

    def lane(
        self,
        key: str,
        x: float,
        y: float,
        w: float,
        h: float,
        header: str,
        dashed: bool = True,
    ) -> str:
        """Group container. The title sits INSIDE at (x+12, y+10), never on the border.

        A lane is sized from the contents already placed inside it, so it is created
        AFTER them - but its white fill would then paint over those contents. It is
        therefore inserted at the BOTTOM of the z-order (index 0) rather than
        appended, which keeps the reflow-then-frame order and the painting order
        independent of each other.
        """
        rkey = f"{self.name}:lane:{key}"
        rect = self._base("rectangle", rkey, x, y, w, h)
        rect.update(
            {
                "strokeColor": LANE_STROKE,
                "backgroundColor": PLAIN,
                "roundness": {"type": 3},
                "strokeStyle": "dashed" if dashed else "solid",
                "strokeWidth": 1,
            }
        )
        self.elements.insert(0, rect)
        self.lanes.add(rect["id"])
        # The lane frame and its title band are no-go areas for arrow labels.
        self.lane_rects.append((x, y, w, 10 + line_h(FS_TITLE) + 4))
        self.rects.append((f"lane:{key}", x, y, w, h))
        title = self.text(
            x + 12,
            y + 10,
            header.upper(),
            font_size=FS_TITLE,
            color=LANE_INK,
            key=f"{self.name}:laneheader:{key}",
        )
        self.title_rects.append(
            (f"lanetitle:{key}", title["x"], title["y"], title["width"],
             title["height"])
        )
        return rect["id"]

    def note(self, key: str, x: float, y: float, w: float, label: str,
             h: float = 0.0) -> Card:
        """Footnote strip: transparent fill, teal stroke, grows to fit its text."""
        h = max(h, fit_height(label, FS_BODY, w - 2 * PAD))
        rid = self.box(key, x, y, w, h, label, fill="transparent", stroke=NOTE_STROKE,
                       dashed=True, grow=False)
        return Card(rid, x, y, w, h)

    # -- serialize -------------------------------------------------------

    def payload(self) -> dict:
        return {
            "type": "excalidraw",
            "version": 2,
            "source": "https://excalidraw.com",
            "elements": self.elements,
            "appState": {"viewBackgroundColor": "#ffffff", "gridSize": 20},
            "files": {},
        }

    def dumps(self) -> str:
        return json.dumps(self.payload(), indent=2, ensure_ascii=True) + "\n"

    # -- lane title helper ------------------------------------------------

    def lane_top(self, lane_y: float) -> float:
        """First row's y inside a lane: below the title plus the reserved band."""
        return lane_y + 10 + line_h(FS_TITLE) + LANE_BAND


# ---------------------------------------------------------------- geometry

class Card:
    """A placed box: keeps its geometry and its element id together."""

    __slots__ = ("h", "id", "w", "x", "y")

    def __init__(self, id_: str, x: float, y: float, w: float, h: float) -> None:
        self.id, self.x, self.y, self.w, self.h = id_, x, y, w, h

    @property
    def rect(self) -> tuple:
        return (self.x, self.y, self.w, self.h)

    @property
    def cx(self) -> float:
        return self.x + self.w / 2

    @property
    def cy(self) -> float:
        return self.y + self.h / 2

    @property
    def right(self) -> float:
        return self.x + self.w

    @property
    def bottom(self) -> float:
        return self.y + self.h


B = Card  # backwards-compatible alias


def row_bottom(cards: list[Card]) -> float:
    """Bottom of the tallest card in a row - the basis for the next row's y."""
    return max((c.bottom for c in cards), default=0.0)


def col_right(cards: list[Card]) -> float:
    """Right edge of the widest card in a column - the basis for the next column's x."""
    return max((c.right for c in cards), default=0.0)


def flow_row(
    d: Diagram,
    specs: list[dict],
    x: float,
    y: float,
    gutter: float = 26.0,
) -> dict[str, Card]:
    """Place cards left to right, each x taken from the previous card's right edge."""
    out: dict[str, Card] = {}
    cx = x
    for spec in specs:
        key = spec.pop("key")
        w = spec.pop("w")
        c = d.card(key, cx, y, w, **spec)
        out[key] = c
        cx = c.right + gutter
    return out


def _seg_rect_hit(
    p0: tuple[float, float],
    p1: tuple[float, float],
    rect: tuple[float, float, float, float],
    slack: float = 3.0,
) -> bool:
    """True if segment p0-p1 passes through rect (shrunk by `slack` so edge
    touches at the endpoints do not count)."""
    rx, ry, rw, rh = rect
    x0, y0 = rx + slack, ry + slack
    x1, y1 = rx + rw - slack, ry + rh - slack
    if x1 <= x0 or y1 <= y0:
        return False
    # Liang-Barsky clip of the segment against the box.
    dx, dy = p1[0] - p0[0], p1[1] - p0[1]
    t0, t1 = 0.0, 1.0
    for p, q in ((-dx, p0[0] - x0), (dx, x1 - p0[0]), (-dy, p0[1] - y0), (dy, y1 - p0[1])):
        if p == 0:
            if q < 0:
                return False
        else:
            t = q / p
            if p < 0:
                t0 = max(t0, t)
            else:
                t1 = min(t1, t)
            if t0 > t1:
                return False
    return True


def _rects_overlap(a: tuple, b: tuple) -> bool:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    return ax < bx + bw and bx < ax + aw and ay < by + bh and by < ay + ah


def edge_points(a: Card, b: Card, gap: float = 5.0) -> tuple[tuple, tuple, str]:
    """Pick the edge midpoints to connect, from the two centres' relative position.

    Returns (start, end, orientation) where orientation is one of
    'right', 'left', 'down', 'up'.
    """
    dx = b.cx - a.cx
    dy = b.cy - a.cy
    if abs(dx) >= abs(dy):
        if dx > 0:
            return (a.right + gap, a.cy), (b.x - gap, b.cy), "right"
        return (a.x - gap, a.cy), (b.right + gap, b.cy), "left"
    if dy > 0:
        return (a.cx, a.bottom + gap), (b.cx, b.y - gap), "down"
    return (a.cx, a.y - gap), (b.cx, b.bottom + gap), "up"


# ---------------------------------------------------------------- arrow routing

FS_LABEL = 12
LABEL_MARGIN = 2  # keep labels this far clear of any border


class Router:
    """Draws arrows anchored on box edges, elbowed through gutters, with checked
    labels. Every arrow it emits is registered for the geometry assertions."""

    def __init__(self, d: Diagram) -> None:
        self.d = d

    # -- primitive --------------------------------------------------------

    def _emit(
        self,
        key: str,
        pts: list[tuple[float, float]],
        src: str | None,
        dst: str | None,
        label: str,
        dashed: bool,
        color: str,
        stroke_width: int = 1,
        label_at: int | None = None,
    ) -> str:
        d = self.d
        x0, y0 = pts[0]
        rel = [[round(px - x0, 1), round(py - y0, 1)] for px, py in pts]
        xs = [p[0] for p in rel]
        ys = [p[1] for p in rel]
        akey = f"{d.name}:arrow:{key}"
        el = d._base(
            "arrow", akey, x0, y0, max(xs) - min(xs), max(ys) - min(ys)
        )
        el.update(
            {
                "strokeColor": color,
                "strokeWidth": stroke_width,
                "roundness": {"type": 2},
                "strokeStyle": "dashed" if dashed else "solid",
                "points": rel,
                "lastCommittedPoint": None,
                "startBinding": {"elementId": src, "focus": 0, "gap": 5} if src else None,
                "endBinding": {"elementId": dst, "focus": 0, "gap": 5} if dst else None,
                "startArrowhead": None,
                "endArrowhead": "arrow",
            }
        )
        d.elements.append(el)
        d.segments.append((f"{d.name}:{key}", list(pts), src or "", dst or ""))

        if label:
            self._label(el, key, pts, label, color, label_at)
        return el["id"]

    # -- label bound to the arrow ----------------------------------------

    def _label(
        self,
        arrow: dict,
        key: str,
        pts: list[tuple[float, float]],
        label: str,
        color: str,
        label_at: int | None,
    ) -> None:
        """Bind the label to the arrow at a segment midpoint. Dropped (and noted in
        WARNINGS) if its bbox would sit on top of any box."""
        d = self.d
        # Choose the longest segment by default, or the caller's index.
        idx = label_at
        if idx is None:
            best, blen = 0, -1.0
            for i in range(len(pts) - 1):
                seg = abs(pts[i + 1][0] - pts[i][0]) + abs(pts[i + 1][1] - pts[i][1])
                if seg > blen:
                    best, blen = i, seg
            idx = best
        p0, p1 = pts[idx], pts[idx + 1]
        mx, my = (p0[0] + p1[0]) / 2, (p0[1] + p1[1]) / 2

        lines = label.split("\n")
        lw = wrapped_w(lines, FS_LABEL)
        lh = wrapped_h(lines, FS_LABEL)
        horizontal = abs(p1[1] - p0[1]) < abs(p1[0] - p0[0])

        # Candidates in preference order: just off the segment at its midpoint,
        # then slid along the segment, then the mirrored side. The first candidate
        # that clears every box wins; if none does, the label is dropped and the
        # flow belongs in the footnote instead.
        cands: list[tuple[float, float]] = []
        if horizontal:
            for off in (-lh - 5, 3.0):
                for t in (0.5, 0.36, 0.64):
                    cx = p0[0] + (p1[0] - p0[0]) * t
                    cands.append((cx - lw / 2, my + off))
        else:
            for off in (7.0, -lw - 7):
                for t in (0.5, 0.36, 0.64):
                    cy = p0[1] + (p1[1] - p0[1]) * t
                    cands.append((mx + off, cy - lh / 2))

        # Avoid boxes, lane frames and labels already placed. Boxes are inflated
        # by LABEL_MARGIN so a label never touches a border either.
        m = LABEL_MARGIN
        def blockers(margin: float) -> list[tuple[float, float, float, float]]:
            return [
                (bx - margin, by2 - margin, bw2 + 2 * margin, bh2 + 2 * margin)
                for bx, by2, bw2, bh2 in d.boxes.values()
            ] + list(d.lane_rects) + list(d.text_rects) + [
                (lx0 - margin, ly0 - margin, lw0 + 2 * margin, lh0 + 2 * margin)
                for _k, lx0, ly0, lw0, lh0 in d.labels
            ]

        # Try with the full clearance first; if nothing fits (a short label in a
        # narrow lane gutter, say) retry touching-but-not-overlapping before giving
        # up, since a legible label in a tight gutter beats no label at all.
        rects = blockers(m)
        spot = next(
            (
                (lx, ly)
                for lx, ly in cands
                if not any(_rects_overlap((lx, ly, lw, lh), r) for r in rects)
            ),
            None,
        )
        if spot is None:
            rects = blockers(1.5)
            spot = next(
                (
                    (lx, ly)
                    for lx, ly in cands
                    if not any(_rects_overlap((lx, ly, lw, lh), r) for r in rects)
                ),
                None,
            )
        if spot is None:
            WARNINGS.append(
                f"{d.name}: dropped arrow label '{label}' ({key}) - no clear spot "
                f"beside the segment"
            )
            return
        lx, ly = spot

        tkey = f"{d.name}:arrowlabel:{key}"
        txt = d._base("text", tkey, lx, ly, lw, lh)
        txt.update(
            {
                "strokeColor": color,
                "text": label,
                "originalText": label,
                "fontSize": FS_LABEL,
                "fontFamily": 1,
                "textAlign": "center",
                "verticalAlign": "middle",
                "containerId": arrow["id"],
                "autoResize": False,
                "lineHeight": LINE_RATIO,
                "baseline": round(FS_LABEL * 0.77, 1),
            }
        )
        arrow["boundElements"] = (arrow["boundElements"] or []) + [
            {"id": txt["id"], "type": "text"}
        ]
        d.elements.append(txt)
        d.labels.append((f"{d.name}:{key}", lx, ly, lw, lh))

    # -- public: straight edge-to-edge ------------------------------------

    def straight(
        self,
        key: str,
        a: Card,
        b: Card,
        label: str = "",
        dashed: bool = False,
        color: str = INK,
        stroke_width: int = 1,
    ) -> str:
        """Anchor on the edges the two centres imply, and draw one segment."""
        start, end, _o = edge_points(a, b)
        return self._emit(key, [start, end], a.id, b.id, label, dashed, color,
                          stroke_width)

    # -- public: orthogonal elbow ----------------------------------------

    def elbow_h(
        self,
        key: str,
        a: Card,
        b: Card,
        gutter_x: float | None = None,
        label: str = "",
        dashed: bool = False,
        color: str = INK,
        stroke_width: int = 1,
    ) -> str:
        """Out horizontally to a gutter, vertical, then horizontally into the target."""
        going_right = b.cx >= a.cx
        sx = a.right + 5 if going_right else a.x - 5
        ex = b.x - 5 if going_right else b.right + 5
        if gutter_x is None:
            gutter_x = (sx + ex) / 2
        pts = [(sx, a.cy), (gutter_x, a.cy), (gutter_x, b.cy), (ex, b.cy)]
        return self._emit(key, pts, a.id, b.id, label, dashed, color, stroke_width,
                          label_at=1)

    def elbow_v(
        self,
        key: str,
        a: Card,
        b: Card,
        gutter_y: float | None = None,
        label: str = "",
        dashed: bool = False,
        color: str = INK,
        stroke_width: int = 1,
        from_x: float | None = None,
        to_x: float | None = None,
    ) -> str:
        """Down (or up) out of the source, across, then vertically into the target."""
        going_down = b.cy >= a.cy
        sx = a.cx if from_x is None else from_x
        ex = b.cx if to_x is None else to_x
        sy = a.bottom + 5 if going_down else a.y - 5
        ey = b.y - 5 if going_down else b.bottom + 5
        if gutter_y is None:
            gutter_y = (sy + ey) / 2
        pts = [(sx, sy), (sx, gutter_y), (ex, gutter_y), (ex, ey)]
        return self._emit(key, pts, a.id, b.id, label, dashed, color, stroke_width,
                          label_at=1)

    def under_lane(
        self,
        key: str,
        a: Card,
        b: Card,
        gutter_y: float,
        label: str = "",
        dashed: bool = False,
        color: str = INK,
        stroke_width: int = 1,
    ) -> str:
        """Down out of the source's BOTTOM edge, along a gutter beneath the lane,
        then up into the target's BOTTOM edge. One clean elbow, no self-crossing.
        """
        pts = [
            (a.cx, a.bottom + 5),
            (a.cx, gutter_y),
            (b.cx, gutter_y),
            (b.cx, b.bottom + 5),
        ]
        return self._emit(key, pts, a.id, b.id, label, dashed, color, stroke_width,
                          label_at=1)

    def into_left(
        self,
        key: str,
        a: Card,
        b: Card,
        gutter_x: float,
        label: str = "",
        dashed: bool = False,
        color: str = INK,
        stroke_width: int = 1,
    ) -> str:
        """Down out of the source, down a vertical gutter to the LEFT of the target
        lane, then in at the target's left-edge midpoint - which is below any lane
        title, so the arrow never runs through one.
        """
        pts = [
            (gutter_x, a.bottom + 5),
            (gutter_x, b.cy),
            (b.x - 5, b.cy),
        ]
        return self._emit(key, pts, a.id, b.id, label, dashed, color, stroke_width,
                          label_at=1)

    def side_riser(
        self,
        key: str,
        a: Card,
        b: Card,
        gutter_x: float,
        gutter_y: float,
        label: str = "",
        dashed: bool = False,
        color: str = INK,
        stroke_width: int = 1,
    ) -> str:
        """Out of the source's right edge, up (or down) an outer vertical gutter,
        then along a horizontal gutter into the target's bottom edge."""
        pts = [
            (a.right + 5, a.cy),
            (gutter_x, a.cy),
            (gutter_x, gutter_y),
            (b.cx, gutter_y),
            (b.cx, b.bottom + 5),
        ]
        return self._emit(key, pts, a.id, b.id, label, dashed, color, stroke_width,
                          label_at=1)

    def drop_into_top(
        self,
        key: str,
        a: Card,
        b: Card,
        from_x: float | None = None,
        to_x: float | None = None,
        gutter_y: float | None = None,
        label: str = "",
        dashed: bool = False,
        color: str = INK,
        stroke_width: int = 1,
    ) -> str:
        """Straight DOWN out of the source's bottom, elbow sideways, then down into
        the target's top edge. Used for 02's early-exit branches."""
        sx = a.cx if from_x is None else from_x
        ex = b.cx if to_x is None else to_x
        sy = a.bottom + 5
        ey = b.y - 5
        if gutter_y is None:
            gutter_y = (sy + ey) / 2
        pts = [(sx, sy), (sx, gutter_y), (ex, gutter_y), (ex, ey)]
        return self._emit(key, pts, a.id, b.id, label, dashed, color, stroke_width,
                          label_at=1)


# =================================================================== 00

def diagram_00() -> Diagram:
    """System end-to-end: who talks to whom, and what crosses each hop."""
    d = Diagram(
        "00",
        "System end to end",
        "Most of the site never touches the backend. Solid = serving today; "
        "dashed = documented target.",
    )
    r = Router(d)

    LY = 84  # lane top
    lanes = [
        ("visitor", 20, 140, "Visitor"),
        ("vercel", 178, 224, "Vercel"),
        ("fly", 446, 240, "Fly.io (sin)"),
        ("managed", 736, 240, "Managed services"),
        ("github", 1014, 196, "GitHub"),
        ("sources", 1240, 218, "Data sources"),
    ]
    top = LY + 10 + line_h(FS_TITLE) + LANE_BAND

    # --- visitor
    vis = d.card("browser", 32, top, 112, "Visitor", "a recruiter,\nin a browser",
                 fill=FRONTEND)

    # --- vercel column: Next.js, its routes, the static JSON they read
    nextapp = d.card("next", 190, top, 198, "Deploys on every push",
                     "Next.js 14.2.5 - React 18.3.1\nTypeScript - runs on Vercel",
                     fill=FRONTEND)
    routes = d.card("routes", 190, nextapp.bottom + 20, 198, "6 routes",
                    "/ . /strategies . /research-lab\n/chat . /ops . /pipeline",
                    fill=FRONTEND)
    static = d.card("static", 190, routes.bottom + 20, 198, "4 of 6 routes read files",
                    "static JSON in public/data/\nbooks/*.json . run.json",
                    fill=DATA)
    r.straight("next-routes", nextapp, routes)
    r.straight("routes-static", routes, static, label="build-time read")

    # --- fly column: the FastAPI request pipeline
    api = d.card("api", 458, top, 214, "Only /chat and /ops call this",
                 "FastAPI + uvicorn - Python 3.11\none warm machine, no cold start",
                 fill=FRONTEND)
    guard = d.card("guard", 458, api.bottom + 18, 214, "Refuses mechanism, serves outputs",
                   "guardrails.py . books.py\nrate limit . PII redact", fill=GUARD,
                   alert=False)
    retr = d.card("retr", 458, guard.bottom + 18, 214, "Vector retrieval",
                  "search(k=4) against methodology", fill=DATA)
    claude = d.card("claudecall", 458, retr.bottom + 18, 214,
                    "Answers from published outputs",
                    "Claude claude-haiku-4-5", fill=LLM)
    r.straight("a1", api, guard)
    r.straight("a2", guard, retr)
    r.straight("a3", retr, claude)

    # --- managed services, ordered so each sits level with its caller: Logfire
    # opposite the API, Qdrant opposite vector retrieval, Anthropic opposite Claude,
    # which keeps all three of those arrows short and horizontal.
    logfire = d.card("logfire", 748, api.y, 216, "Every request is traced",
                     "Logfire - OpenTelemetry\nchat_request > retrieve > llm",
                     fill=LLM)
    qdrant = d.card("qdrant", 748, max(retr.y, logfire.bottom + 18), 216,
                    "Two collections, one read",
                    "Qdrant Cloud - AWS us-west-2\nmethodology 16 docs READ\n"
                    "research_corpus 376 NOT READ",
                    fill=DATA, alert=True)
    anthropic = d.card("anthropic", 748, max(claude.y, qdrant.bottom + 18), 216,
                       "Anthropic API",
                       "claude-haiku-4-5\nprompt caching", fill=LLM)

    r.straight("api-logfire", api, logfire, label="spans")
    r.straight("retr-qdrant", retr, qdrant, label="search")
    r.straight("claude-anthropic", claude, anthropic, label="1 call")

    # --- github
    repo = d.card("repo", 1026, top, 172, "Single repo, main branch",
                  "monorepo - all tiers", fill=CI)
    cron = d.card("cron", 1026, repo.bottom + 22, 172, "Daily, incremental",
                  "ingest.yml - 02:17 UTC\n$3/run budget cap", fill=CI)
    hook = d.card("hook", 1026, cron.bottom + 22, 172, "Vercel git integration",
                  "build + deploy on push", fill=FRONTEND)
    r.straight("repo-cron", repo, cron)
    r.straight("cron-hook", cron, hook, label="commit-back")

    # --- data sources
    arxiv = d.card("arxiv", 1252, top, 194, "arXiv q-fin", "PDF source feed",
                   fill=DATA)
    s3 = d.card("s3", 1252, cron.y, 194, "S3 bronze layer",
                "content-hashed, so most\nnights re-process nothing", fill=DATA)
    priv = d.card("private", 1252, hook.y, 194, "Outputs only cross",
                  "private strategy repo\nmonthly report PDFs",
                  fill=GUARD, dashed=True, alert=True)

    # Short, level arrows into the cron.
    r.straight("arxiv-cron", arxiv, cron, label="fetch PDFs")
    r.straight("cron-s3", cron, s3)
    r.elbow_h("cron-qdrant", cron, qdrant, gutter_x=998, label="upsert")

    # --- visitor traffic and the deploy loop
    r.straight("vis-next", vis, nextapp, label="HTTPS")
    r.elbow_h("next-api", routes, api, gutter_x=424, label="JSON")

    # Two flows would have to span the entire canvas to be drawn: the Vercel deploy
    # hook back to the Next.js app, and the outputs-only boundary into the static
    # JSON. Per the arrow budget they go in the footnote strips instead of being
    # drawn as canvas-crossing elbows - the boxes themselves carry the same fact
    # ("Deploys on every push", ">> Outputs only cross").
    lane_bottom = max(static.bottom, claude.bottom, anthropic.bottom, priv.bottom) + 18
    for key, lx, lw, header in lanes:
        d.lane(key, lx, LY, lw, lane_bottom - LY, header)

    fy = lane_bottom + 18
    n1 = d.note("note-gap", 20, fy, 700,
                "The gap worth naming: research_corpus is indexed nightly but the "
                "chatbot never reads it. Only methodology is served, via search(k=4).")
    d.note("note-target", 740, fy, 734,
           "Not deployed: Tier-2 slm_regime_classifier, AWS Fargate hosting, auth + "
           "RBAC. The Tier-1 research loop runs in CI, not on the request path.")
    d.note("note-flows", 20, n1.bottom + 12, 1454,
           "Two flows are stated rather than drawn, to keep every arrow short: the "
           "Vercel git integration redeploys the Next.js app on each push to main, and "
           "labelled backtest outputs - never parameters or trade rows - cross from the "
           "private strategy repo into the static JSON (ADR-0001).")
    return d


# =================================================================== 01

def diagram_01() -> Diagram:
    """Tech stack board: outcome headline, then product / version / where it runs."""
    d = Diagram(
        "01",
        "Tech stack - what is actually running",
        "Every solid card is running today. Dashed = documented target, not built.",
    )

    groups: list[tuple[str, str, str, list[tuple[str, str]]]] = [
        ("frontend", "Frontend", FRONTEND, [
            ("Six routes, one build", "Next.js 14.2.5\nApp Router, on Vercel"),
            ("Typed, inline SVG", "React 18.3.1\nTypeScript 5.5"),
            ("Renders chat answers", "react-markdown 9\nin the browser"),
        ]),
        ("backend", "Backend and hosting", FRONTEND, [
            ("Four endpoints",
             "FastAPI + uvicorn\nPython 3.11, 4 routes"),
            ("Always warm",
             "Fly.io yantra-chatbot\n1 shared-cpu/1GB, sin"),
            ("Deploys on every push", "Vercel - GitHub hook\nstatic + SSR"),
        ]),
        ("llm", "LLM and orchestration", LLM, [
            ("Answers from outputs",
             "claude-haiku-4-5\nprompt caching"),
            ("One call per question",
             "Anthropic Python SDK\nmax_tokens 1024"),
            ("Ingestion as a graph",
             "LangGraph, 8 nodes\non GitHub Actions"),
        ]),
        ("vectors", "Embeddings, vector DB and storage", DATA, [
            ("Same model both sides",
             "fastembed ONNX\nbge-small-en-v1.5, 384d"),
            ("Two collections, one read",
             "Qdrant Cloud, cosine\nAWS us-west-2"),
            ("Content-hashed",
             "AWS S3 bronze\nbucket from CI secret"),
        ]),
        ("guardrails", "Guardrails and evals", GUARD, [
            ("Refuses mechanism",
             "guardrails.py\nin-process on Fly"),
            ("Routes, no model",
             "books.py router\nto books_corpus"),
            ("Gated in CI",
             "eval/ - run_gate\nredteam, books_eval"),
        ]),
        ("ops", "Observability and research loop", LLM, [
            ("Every request is traced",
             "Logfire, OpenTelemetry\nspan tree per request"),
            ("Real spans, not mocks",
             "/api/metrics > /ops\nLOGFIRE_READ_TOKEN"),
            ("Runs without an LLM",
             "Tier-1, stdlib Python\nMCP run_backtest"),
        ]),
        ("tooling", "CI/CD and tooling", CI, [
            ("Path-filtered",
             "GitHub Actions\nci.yml + ingest.yml"),
            ("Lint + tests gate",
             "ruff + pytest\nPython 3.12 in CI"),
            ("Text, tables and images",
             "PyMuPDF + Tesseract\nOCR fallback"),
        ]),
    ]

    targets = [
        ("Container hosting", "AWS Fargate\nADR-0005, Fly.io today"),
        ("Static hosting", "S3 + CloudFront\nVercel today"),
        ("Auth and RBAC", "Cognito / Clerk\nADR-0006, none in v1"),
        ("Model routing", "LiteLLM gateway\nSDK direct today"),
        ("LLM tracing", "LangSmith / Langfuse\nLogfire today"),
        ("Page-image retrieval", "ColQwen retrieval\ncaption-then-embed today"),
    ]

    # Two groups per band, six cards across: fewer lanes than one-group-per-row,
    # and each card still wide enough that its headline fits on one or two lines.
    # Every band's y comes from the measured bottom of the band above it.
    LANE_PAD = 9
    ROUGH = 4  # slack for roughness-1 stroke jitter
    GUT = 12
    BAND_W = 718  # one group's lane
    SPAN = 20  # gap between the two lanes on a band

    def deal(gkey: str, title: str, fill: str, cards: list[tuple[str, str]],
             lx: float, ly: float, dashed: bool = False) -> list[Card]:
        """Place one group as a lane of cards, sized to what it holds."""
        n = len(cards)
        cw = (BAND_W - 2 * LANE_PAD - (n - 1) * GUT) / n
        row_top = ly + 10 + line_h(FS_TITLE) + LANE_BAND
        placed: list[Card] = []
        cx = lx + LANE_PAD
        for i, (headline, detail) in enumerate(cards):
            c = d.card(f"{gkey}-{i}", cx, row_top, cw, headline, detail,
                       fill=fill, dashed=dashed)
            placed.append(c)
            cx = c.right + GUT
        # + ROUGH so the hand-drawn stroke jitter of a card never pokes through
        # the lane's own border.
        d.lane(gkey, lx, ly, BAND_W, (row_bottom(placed) + LANE_PAD + ROUGH) - ly,
               title, dashed=True)
        return placed

    LEFT, RIGHT = 20.0, 20.0 + BAND_W + SPAN
    y = 80.0
    # Four bands of two groups, then the odd group out beside the targets strip.
    for left_g, right_g in ((groups[0], groups[1]), (groups[2], groups[3]),
                            (groups[4], groups[5])):
        lp = deal(left_g[0], left_g[1], left_g[2], left_g[3], LEFT, y)
        rp = deal(right_g[0], right_g[1], right_g[2], right_g[3], RIGHT, y)
        y = row_bottom(lp + rp) + LANE_PAD + 10

    g = groups[6]
    lp = deal(g[0], g[1], g[2], g[3], LEFT, y)
    rp = deal("targets-a", "Documented targets - not built", PLAIN, targets[:3],
              RIGHT, y, dashed=True)
    y = row_bottom(lp + rp) + LANE_PAD + 10

    deal("targets-b", "Documented targets - not built (cont.)", PLAIN,
         targets[3:], RIGHT, y, dashed=True)

    # The footnotes fill the space left beside the second targets strip.
    n1 = d.note("note-tier2", LEFT, y, BAND_W,
                "Tier-2 is README-only: four empty directories, 0 lines of Python. "
                "It is a target, and not on the request path either way.")
    d.note("note-css", LEFT, n1.bottom + 12, BAND_W,
           "Styling is Tailwind 3.4.6 plus hand-written CSS custom-property tokens. "
           "Charts are inline SVG - no charting library.")
    return d


# =================================================================== 02

def diagram_02() -> Diagram:
    """One /api/chat request, including the paths that never reach the LLM."""
    d = Diagram(
        "02",
        "/api/chat - one request, end to end",
        "A refused question is the cheapest one: it exits before the model is called.",
    )
    r = Router(d)

    # --- row 1: the gate chain, left to right
    ROW1 = 96
    chain = [
        ("in", "Request in", "POST /api/chat\n{message, history}", FRONTEND, 176, False),
        ("rl", "Rate limited per IP", "20 / min", GUARD, 158, False),
        ("cap", "Capped per day", "500 / day", GUARD, 158, False),
        ("pii", "PII never reaches the model",
         "redact_pii - emails, phones\n7+ digit runs", GUARD, 208, False),
        ("inj", "Injection detected", "detect_injection", GUARD, 168, False),
        ("ref", "Mechanism refused", "should_refuse - IP policy", GUARD, 184, False),
    ]
    x = 24
    st: dict[str, Card] = {}
    for key, head, detail, fill, w, alert in chain:
        st[key] = d.card(key, x, ROW1, w, head, detail, fill=fill, alert=alert)
        x = st[key].right + 34
    router = d.card("route", x, ROW1, 196, "Routes without a model",
                    "book router - books.py\ndeterministic keywords", fill=DATA)
    st["route"] = router

    order = [c[0] for c in chain] + ["route"]
    for a, b in itertools.pairwise(order):
        r.straight(f"e-{a}-{b}", st[a], st[b])

    row1_bottom = row_bottom(list(st.values()))

    # --- the two early-exit boxes, on their own band below the gate chain
    EXIT_Y = row1_bottom + 104
    e429 = d.card("e429", 150, EXIT_Y, 250, "429 - no model call",
                  "too many requests", fill=GUARD, dashed=True, alert=True)
    erefuse = d.card("erefuse", 700, EXIT_Y, 300, "200 refused - no model call",
                     "refused=true, zero tokens spent", fill=GUARD, dashed=True,
                     alert=True)

    # Both 429 branches drop DOWN out of the box bottom, then elbow into the top.
    mid429 = row1_bottom + 52
    r.drop_into_top("rl-429", st["rl"], e429, to_x=e429.cx - 60,
                    gutter_y=mid429 - 16, label="over limit", color=ALERT,
                    stroke_width=2)
    r.drop_into_top("cap-429", st["cap"], e429, to_x=e429.cx + 60,
                    gutter_y=mid429 + 10, label="cap hit", color=ALERT,
                    stroke_width=2)
    # Both refusal branches likewise.
    # Staggered elbow heights: two branches into the same box must not share a
    # horizontal run, or they render as one doubled stroke.
    r.drop_into_top("inj-refuse", st["inj"], erefuse, to_x=erefuse.cx - 70,
                    gutter_y=mid429 - 16, label="injection", color=ALERT,
                    stroke_width=2)
    r.drop_into_top("ref-refuse", st["ref"], erefuse, to_x=erefuse.cx + 70,
                    gutter_y=mid429 + 10, label="IP terms", color=ALERT,
                    stroke_width=2)

    # --- row 2: the happy path continues
    ROW2 = row_bottom([e429, erefuse]) + 58
    retr = d.card("retr", 24, ROW2, 214, "Vector retrieval",
                  "Qdrant methodology\nsearch(k=4)", fill=DATA)
    bookdocs = d.card("bookdocs", 24, retr.bottom + 22, 214, "Routed book docs",
                      "overview / per-book / risk gates", fill=DATA)
    merge = d.card("merge", 286, ROW2 + 30, 214, "Book docs win ties",
                   "context assembly\ndedup by title", fill=DATA)
    sysp = d.card("sysp", 286, merge.bottom + 84, 214, "Cached prefix",
                  "SYSTEM_PROMPT +\nBOOKS_SYSTEM_ADDENDUM", fill=GUARD)
    llm = d.card("llm", 548, ROW2 + 30, 226, "One model call",
                 "claude-haiku-4-5 - max_tokens 1024\ncache_control: ephemeral",
                 fill=LLM)
    resp = d.card("resp", 812, ROW2 + 30, 246, "200 with its sources",
                  "{answer, refused,\nsources[], leak_rate}", fill=FRONTEND)

    r.elbow_v("route-retr", router, retr, gutter_y=ROW2 - 26,
              from_x=router.cx, to_x=retr.cx, label="routed titles")
    r.straight("retr-books", retr, bookdocs, dashed=True)
    r.straight("retr-merge", retr, merge)
    r.straight("books-merge", bookdocs, merge)
    r.straight("merge-llm", merge, llm, label="context")
    r.straight("sysp-llm", sysp, llm)
    r.straight("llm-resp", llm, resp)

    # --- Logfire and the ops page
    lf = d.card("logfire", 1106, ROW2 + 30, 290, "Safe aggregates only",
                "Logfire span tree - latency split\ntoken cost, refused / leak_rate\n"
                "never user text", fill=LLM)
    ops = d.card("opspage", 1106, lf.bottom + 44, 290, "The /ops page you can click",
                 "/api/metrics - LOGFIRE_READ_TOKEN", fill=FRONTEND)
    r.straight("resp-lf", resp, lf, label="spans")
    r.straight("lf-ops", lf, ops)

    fy = row_bottom([bookdocs, sysp, ops]) + 26
    d.note("note-rule", 24, fy, 726,
           "Outputs cross, mechanism does not: the router may serve labelled backtest "
           "results, but a product name plus a mechanism ask is refused.")
    d.note("note-cold", 766, fy, 620,
           "As of 2026-08-17 /api/metrics reported queries_served: 1 all-time, "
           "p50 = p95 ~ 20s from one cold-start sample. Deployed and observable, "
           "not trafficked.")
    return d


# =================================================================== 03

def diagram_03() -> Diagram:
    """What writes to Qdrant, what reads from it, and the gap in between."""
    d = Diagram(
        "03",
        "Data flows into Qdrant Cloud - and the one gap",
        "Two write pipelines, one reader: research_corpus is indexed nightly and never "
        "read.",
    )
    r = Router(d)

    # --- pipeline A: Tier-3 ingestion (medallion), one reflowed row
    LY = 84
    top = LY + 10 + line_h(FS_TITLE) + LANE_BAND
    steps = [
        ("discover", "Discover", "arXiv q-fin API", DATA, 148),
        ("fetch", "Fetch to bronze", "PDFs > S3\ncontent-hashed", DATA, 162),
        ("parse", "Parse", "PyMuPDF text / tables\nOCR fallback", DATA, 186),
        ("caption", "Caption figures", "figure raster >\nHaiku vision", LLM, 162),
        ("enrich", "Enrich", "chunk + summary\nbudget $3/run", LLM, 158),
        ("quality", "Quality gate", "dedup - relevance\nIP-leak quarantine", GUARD, 178),
    ]
    x = 32
    ip: dict[str, Card] = {}
    for key, head, detail, fill, w in steps:
        ip[key] = d.card(key, x, top, w, head, detail, fill=fill)
        x = ip[key].right + 22
    gate = d.card("gate", x, top, 156, "HITL gate", "auto-approve in CI", fill=GUARD)
    x = gate.right + 22
    idx = d.card("index", x, top, 168, "Embed + upsert", "bge-small 384d", fill=DATA)

    keys = [s[0] for s in steps]
    for a, b in itertools.pairwise(keys):
        r.straight(f"i-{a}-{b}", ip[a], ip[b])
    r.straight("i-quality-gate", ip["quality"], gate)
    r.straight("i-gate-index", gate, idx)

    row1_bottom = row_bottom([*ip.values(), gate, idx])

    # medallion labels, inside the lane, below the row
    mlab_y = row1_bottom + 10
    d.text(38, mlab_y, "BRONZE - raw PDFs in S3", font_size=12, color=NOTE_STROKE,
           key="03:bronze")
    d.text(360, mlab_y, "SILVER - parsed, captioned, chunked", font_size=12,
           color=NOTE_STROKE, key="03:silver")
    d.text(820, mlab_y, "GOLD - accepted and indexed", font_size=12, color=NOTE_STROKE,
           key="03:gold")

    lane_h = (mlab_y + line_h(12) + 12) - LY
    d.lane("ingest", 20, LY, idx.right + 16 - 20, lane_h,
           "Tier-3 ingestion - LangGraph on GitHub Actions, 02:17 UTC daily")

    dlq_y = LY + lane_h + 26
    dlq = d.card("dlq", ip["quality"].x - 10, dlq_y, 200, "Rejected chunks",
                 "dead-letter queue", fill=GUARD, dashed=True)
    r.straight("quality-dlq", ip["quality"], dlq, label="quarantine")

    d.note("note-embed", 20, dlq_y, 560,
           "One embedding model on both sides: BAAI/bge-small-en-v1.5, 384-dim, cosine. "
           "Serving and ingestion must match or retrieval silently degrades.")

    # --- Qdrant Cloud, the two collections
    QY = max(dlq.bottom, dlq_y + 70) + 34
    qtop = QY + 10 + line_h(FS_TITLE) + LANE_BAND
    research = d.card("research", 596, qtop, 350, "Indexed nightly, never read",
                      "research_corpus - 376 indexed\n419 chunks parsed, 18 figures",
                      fill=DATA, alert=True)
    methodology = d.card("methodology", 596, research.bottom + 20, 350,
                         "The only collection served",
                         "methodology - 16 docs / 18 chunks\n8 seed notes + 8 book docs",
                         fill=DATA)
    d.lane("qc", 578, QY, 386, (methodology.bottom + 16) - QY,
           "Qdrant Cloud - AWS us-west-2", dashed=False)

    # Down out of the index step, along the gutter above the Qdrant lane, then
    # into the research_corpus card's TOP edge: the chatbot card occupies the
    # right-hand approach, so a side entry would cross it.
    r.drop_into_top("idx-research", idx, research, from_x=idx.cx,
                    to_x=research.cx + 140, gutter_y=research.y - 30,
                    label="upsert")

    # --- the reader and the gap
    chatbot = d.card("chatbot", 1094, research.y + 6, 300, "Reads methodology only",
                     "chatbot on Fly.io\nno QDRANT_COLLECTION override",
                     fill=FRONTEND)
    r.straight("research-chat", research, chatbot, label="never read", dashed=True,
               color=ALERT, stroke_width=2)
    r.elbow_h("meth-chat", methodology, chatbot, gutter_x=1020, label="search(k=4)")

    # --- pipeline B: strategy books (manual, outputs only)
    BY = max(methodology.bottom, chatbot.bottom) + 34
    btop = BY + 10 + line_h(FS_TITLE) + LANE_BAND
    priv = d.card("priv", 32, btop, 168, "Outputs only cross",
                  "private strategy repo", fill=GUARD, dashed=True, alert=True)
    pdfs = d.card("pdfs", priv.right + 18, btop, 166, "7 monthly PDFs",
                  "quick_reference/", fill=GUARD, dashed=True)
    extract = d.card("extract", pdfs.right + 18, btop, 196, "Read printed totals",
                     "extract_monthly_\nfrom_reports.py", fill=CI)
    booksjson = d.card("booksjson", extract.right + 18, btop, 182, "7 books + index",
                       "public/data/books/\n+ risk_gates", fill=DATA)
    sync = d.card("sync", booksjson.right + 18, btop, 186, "Sync to corpus",
                  "sync_books_\ncorpus.py > *.md", fill=CI)
    for a, b, k in ((priv, pdfs, "b1"), (pdfs, extract, "b2"),
                    (extract, booksjson, "b3"), (booksjson, sync, "b4")):
        r.straight(k, a, b)

    books_h = (row_bottom([priv, pdfs, extract, booksjson, sync]) + 16) - BY
    d.lane("books", 20, BY, sync.right + 16 - 20, books_h,
           "Strategy books - manual, outputs only, not on a schedule")

    # seed corpus feeds methodology from the left
    seed = d.card("seed", 300, methodology.y, 214, "8 methodology notes",
                  "backend/seed_corpus/", fill=DATA)
    r.straight("seed-meth", seed, methodology)
    r.elbow_v("sync-meth", sync, methodology, gutter_y=BY - 17,
              from_x=sync.cx, to_x=methodology.cx + 150, label="embed + upsert")

    explorer = d.card("explorer", 1094, btop, 300, "Charts straight from JSON",
                      "/strategies - Strategy Explorer\ninline SVG, no API call",
                      fill=FRONTEND)
    r.under_lane("books-explorer", booksjson, explorer,
                 gutter_y=max(booksjson.bottom, explorer.bottom) + 26,
                 label="static fetch")

    fy = max(row_bottom([explorer]), BY + books_h) + 26
    d.note("note-ssh", 20, fy, 700,
           "Re-ingest gotcha: a fly deploy changes nothing. The cluster must be "
           "re-indexed over SSH after any corpus change, or the app keeps serving the "
           "old index.")
    d.note("note-boundary", 740, fy, 620,
           "The boundary holds in one direction: labelled outputs cross, engine "
           "parameters and trade rows never do (ADR-0001).")
    return d


# =================================================================== 04

def diagram_04() -> Diagram:
    """How code and data actually reach production."""
    d = Diagram(
        "04",
        "Deploy and CI/CD - what is automated, what is a hand",
        "The frontend ships itself. The backend ships only when someone runs two "
        "commands.",
    )
    r = Router(d)

    # --- GitHub Actions ci.yml lane
    LY = 92
    top = LY + 10 + line_h(FS_TITLE) + LANE_BAND
    dev = d.card("dev", 24, top + 30, 168, "One push", "developer > git push main",
                 fill=CI)

    changes = d.card("changes", 258, top, 190, "Only what changed runs",
                     "dorny/paths-\nfilter - 5 filters", fill=CI)
    core = d.card("core", changes.right + 20, top, 172, "Lint and tests block merge",
                  "ruff check . - pytest -q\nPython 3.12", fill=CI)
    egate = d.card("egate", core.right + 20, top, 184, "Agent must beat baseline",
                   "eval-gate\npython -m eval.run_gate", fill=CI)
    stubs = d.card("stubs", egate.right + 20, top, 176, "Deploy stubs - not built",
                   "deploy-dev / deploy-prod\necho only, TARGET", fill=PLAIN,
                   dashed=True)
    r.straight("c1", changes, core)
    r.straight("c2", core, egate)
    r.straight("c3", egate, stubs, dashed=True)
    r.straight("dev-gha", dev, changes, label="webhook")

    gha_bottom = row_bottom([changes, core, egate, stubs])
    evalnote_y = gha_bottom + 10
    d.text(258, evalnote_y,
           "Run by hand: eval/redteam.py (100% block, 0 false positives) - "
           "eval/chatbot_books_eval.py (21 graded live questions)",
           font_size=12, color=MUTED, key="04:evalnote")
    gha_h = (evalnote_y + line_h(12) + 12) - LY
    d.lane("gha", 242, LY, stubs.right + 16 - 242, gha_h,
           "GitHub Actions ci.yml - push to main and PR")

    # --- Fly path (manual)
    FY = LY + gha_h + 30
    ftop = FY + 10 + line_h(FS_TITLE) + LANE_BAND
    flycmd = d.card("flycmd", 236, ftop, 196, "Backend ships by hand",
                    "fly deploy --remote-only\nrun from backend/", fill=CI, alert=False)
    builder = d.card("builder", flycmd.right + 26, ftop, 176, "Remote build",
                     "Fly builder - Dockerfile\npython:3.11-slim", fill=CI)
    machine = d.card("machine", builder.right + 40, ftop, 198,
                     "One warm machine, no cold start",
                     "region sin - 1 shared-cpu / 1GB\nmin_machines_running 1",
                     fill=FRONTEND)
    r.straight("f1", flycmd, builder)
    r.straight("f2", builder, machine, label="image")

    fly_row_bottom = row_bottom([flycmd, builder, machine])
    tomlnote_y = fly_row_bottom + 10
    d.text(236, tomlnote_y,
           "fly.toml changes only take effect on a deploy from backend/.",
           font_size=12, color=MUTED, key="04:flytoml")
    fly_h = (tomlnote_y + line_h(12) + 12) - FY
    d.lane("fly", 220, FY, machine.right + 16 - 220, fly_h,
           "Fly.io backend - manual, NOT in CI", dashed=False)

    # --- the SSH re-ingest, below the Fly lane
    SY = FY + fly_h + 28
    sshcmd = d.card("ssh", 236, SY, 386, "Then re-index over SSH",
                    "fly ssh console -a yantra-chatbot\npython ingest.py", fill=CI)
    qdrant = d.card("qdrant", sshcmd.right + 58, SY, 262, "methodology rebuilt",
                    "Qdrant Cloud", fill=DATA)
    r.straight("ssh-qdrant", sshcmd, qdrant, label="upsert")

    r.into_left("dev-fly", dev, flycmd, gutter_x=dev.cx, label="by hand")
    r.into_left("dev-ssh", dev, sshcmd, gutter_x=dev.x + 34,
                label="after a corpus change")

    # --- Vercel lane (right column, top)
    VX = 1030
    vtop = top
    vbuild = d.card("vbuild", VX + 16, vtop, 220, "Deploys on every push",
                    "Vercel git integration\nnext build", fill=FRONTEND)
    vprod = d.card("vprod", vbuild.right + 20, vtop, 196, "Production",
                   "yantra-research-lab\n.vercel.app", fill=FRONTEND)
    r.straight("v1", vbuild, vprod)
    d.lane("vercel", VX, LY, (vprod.right + 16) - VX,
           row_bottom([vbuild, vprod]) + 16 - LY, "Vercel - automatic")
    # The same push ALSO triggers Vercel, on a separate webhook. Drawing it would
    # take an arrow across the entire canvas over two lanes, so the fact is carried
    # by the Vercel lane's "(automatic)" title and the footnote instead.

    # --- ingest cron lane (right column, below Vercel)
    CY = FY
    ctop = CY + 10 + line_h(FS_TITLE) + LANE_BAND
    cronjob = d.card("cronjob", VX + 16, ctop, 400, "Daily, incremental, budget-capped",
                     "ingest.yml - 02:17 UTC\nLangGraph on an ephemeral runner",
                     fill=CI)
    cronq = d.card("cronq", VX + 16, cronjob.bottom + 24, 190, "research_corpus",
                   "Qdrant Cloud", fill=DATA)
    commitback = d.card("commitback", cronq.right + 20, cronjob.bottom + 24, 190,
                        "Commits its manifest", "ingestion.json  [skip ci]", fill=CI)
    r.elbow_v("cron-q", cronjob, cronq, from_x=cronjob.x + 95, to_x=cronq.cx,
              gutter_y=cronjob.bottom + 12)
    r.elbow_v("cron-cb", cronjob, commitback, from_x=cronjob.x + 300,
              to_x=commitback.cx, gutter_y=cronjob.bottom + 12)

    cron_row = row_bottom([cronq, commitback])
    cronnote_y = cron_row + 10
    d.text(VX + 16, cronnote_y,
           "Most nights this re-processes nothing: the content hash already matches.",
           font_size=12, color=MUTED, key="04:cronnote")
    cron_h = (cronnote_y + line_h(12) + 12) - CY
    d.lane("cron", VX, CY, (cronjob.right + 16) - VX, cron_h,
           "GitHub Actions ingest.yml - cron 02:17 UTC")

    # Out of the commit-back box's RIGHT edge, up the canvas's outer gutter, then
    # into production's bottom: the only path that clears the cron lane's own boxes.
    r.side_riser("cb-vercel", commitback, vprod, gutter_x=commitback.right + 30,
                 gutter_y=CY - 14, label="triggers Vercel")

    fy = max(row_bottom([sshcmd, qdrant]), CY + cron_h) + 26
    d.note("secrets", 24, fy, 960,
           "Secrets by NAME ONLY - values live in Fly and GitHub Actions secrets, never "
           "in this repo: ANTHROPIC_API_KEY - QDRANT_URL - QDRANT_API_KEY - "
           "LOGFIRE_TOKEN - LOGFIRE_READ_TOKEN - FRONTEND_ORIGIN.")
    d.note("gap", 1004, fy, 470,
           "The honest gap: CI lints, tests and gates the research loop, but deploys "
           "nothing. The same push that starts ci.yml also triggers Vercel, on a "
           "separate webhook; the backend waits on a human.")
    return d


# =================================================================== validation

DIAGRAMS = {
    "00-system-e2e": diagram_00,
    "01-tech-stack": diagram_01,
    "02-chat-request-flow": diagram_02,
    "03-data-flows": diagram_03,
    "04-deploy-cicd": diagram_04,
}

MAX_W = 1520
MAX_H = 940


def _overlap(a: tuple, b: tuple) -> bool:
    _, ax, ay, aw, ah = a
    _, bx, by, bw, bh = b
    return ax < bx + bw and bx < ax + aw and ay < by + bh and by < ay + ah


def check_text_fits(d: Diagram) -> list[str]:
    """Every bound text must fit its container: wrapped height + 2*padding <=
    container height, and the longest line <= container width - 2*padding."""
    problems: list[str] = []
    for label, th, tw, cw, ch, vpad in d.textfits:
        if th + 2 * vpad > ch + 0.5:
            problems.append(
                f"TEXT OVERFLOW {label}: wrapped {th:.0f}px + 2*{vpad:.0f} > container "
                f"height {ch:.0f}px"
            )
        if tw > cw - 2 * PAD + 0.5:
            problems.append(
                f"TEXT TOO WIDE {label}: longest line {tw:.0f}px > container width "
                f"{cw:.0f} - 2*{PAD}px"
            )
    return problems


def check_arrows(d: Diagram) -> list[str]:
    """Arrow endpoints land on their target's edge, and no segment crosses a box
    that is not one of its own endpoints."""
    problems: list[str] = []
    by_id = d.boxes
    for key, pts, src, dst in d.segments:
        # End point within 2px (plus the 5px binding gap) of the target's edge.
        if dst and dst in by_id:
            ex, ey = pts[-1]
            bx, byy, bw, bh = by_id[dst]
            dx = max(bx - ex, ex - (bx + bw), 0.0)
            dy = max(byy - ey, ey - (byy + bh), 0.0)
            dist = max(dx, dy)
            if dist > 7.5:
                problems.append(
                    f"ARROW END {key}: end point ({ex:.0f},{ey:.0f}) is {dist:.0f}px "
                    f"off the target edge"
                )
        # No segment may cross a third box.
        for i in range(len(pts) - 1):
            for bid, rect in by_id.items():
                if bid in (src, dst):
                    continue
                if _seg_rect_hit(pts[i], pts[i + 1], rect):
                    problems.append(
                        f"ARROW CROSSES BOX {key}: segment {i} passes through a box "
                        f"at ({rect[0]:.0f},{rect[1]:.0f})"
                    )
            # Nor may it run through a lane/group title.
            for tkey, tx, ty, tw, th in d.title_rects:
                if _seg_rect_hit(pts[i], pts[i + 1], (tx, ty, tw, th), slack=1.0):
                    problems.append(
                        f"ARROW CROSSES TITLE {key}: segment {i} passes through "
                        f"{tkey}"
                    )

    problems.extend(_check_collinear(d))
    return problems


def _check_collinear(d: Diagram) -> list[str]:
    """No two arrows may share a collinear, overlapping run.

    Two arrows that lie on the same horizontal or vertical line and overlap along
    it render as one doubled stroke, which reads as a single ambiguous arrow.
    """
    problems: list[str] = []
    segs: list[tuple[str, tuple[float, float], tuple[float, float]]] = []
    for key, pts, _src, _dst in d.segments:
        for i in range(len(pts) - 1):
            segs.append((key, pts[i], pts[i + 1]))

    tol = 2.0
    for i, (ka, a0, a1) in enumerate(segs):
        for kb, b0, b1 in segs[i + 1:]:
            if ka == kb:
                continue
            # Horizontal pair on the same y.
            if (
                abs(a0[1] - a1[1]) < tol
                and abs(b0[1] - b1[1]) < tol
                and abs(a0[1] - b0[1]) < tol
            ):
                lo = max(min(a0[0], a1[0]), min(b0[0], b1[0]))
                hi = min(max(a0[0], a1[0]), max(b0[0], b1[0]))
                if hi - lo > 12:
                    problems.append(
                        f"ARROWS COLLINEAR {ka} and {kb}: share {hi - lo:.0f}px "
                        f"of horizontal line y={a0[1]:.0f}"
                    )
            # Vertical pair on the same x.
            if (
                abs(a0[0] - a1[0]) < tol
                and abs(b0[0] - b1[0]) < tol
                and abs(a0[0] - b0[0]) < tol
            ):
                lo = max(min(a0[1], a1[1]), min(b0[1], b1[1]))
                hi = min(max(a0[1], a1[1]), max(b0[1], b1[1]))
                if hi - lo > 12:
                    problems.append(
                        f"ARROWS COLLINEAR {ka} and {kb}: share {hi - lo:.0f}px "
                        f"of vertical line x={a0[0]:.0f}"
                    )
    return problems


def check_labels(d: Diagram) -> list[str]:
    """No arrow label bbox may sit on top of a box."""
    problems: list[str] = []
    for key, lx, ly, lw, lh in d.labels:
        for rect in d.boxes.values():
            if _rects_overlap((lx - 1, ly - 1, lw + 2, lh + 2), rect):
                problems.append(f"LABEL OVER BOX {key} at ({lx:.0f},{ly:.0f})")
                break
    return problems


def validate(d: Diagram, payload: dict, verbose: bool = True) -> list[str]:
    """Structural + geometric checks. Returns a list of problems (empty == clean)."""
    problems: list[str] = []
    els = payload["elements"]
    ids = {e["id"] for e in els}
    if len(ids) != len(els):
        problems.append("duplicate element ids")

    required = {
        "id", "type", "x", "y", "width", "height", "angle", "strokeColor",
        "backgroundColor", "fillStyle", "strokeWidth", "strokeStyle", "roughness",
        "opacity", "groupIds", "frameId", "seed", "version", "versionNonce",
        "isDeleted", "boundElements", "updated", "link", "locked",
    }
    for e in els:
        missing = required - set(e)
        if missing:
            problems.append(f"{e['id']} missing {sorted(missing)}")
        if e["type"] == "text":
            for f in ("text", "originalText", "fontSize", "fontFamily", "textAlign",
                      "verticalAlign", "containerId", "lineHeight", "baseline"):
                if f not in e:
                    problems.append(f"text {e['id']} missing {f}")
            cid = e.get("containerId")
            if cid is not None and cid not in ids:
                problems.append(f"text {e['id']} containerId {cid} not found")
            if e["fontSize"] < 12:
                problems.append(f"text {e['id']} fontSize {e['fontSize']} below 12")
        if e["type"] == "arrow":
            for side in ("startBinding", "endBinding"):
                b = e.get(side)
                if b and b["elementId"] not in ids:
                    problems.append(f"arrow {e['id']} {side} {b['elementId']} not found")
        for b in e.get("boundElements") or []:
            if b["id"] not in ids:
                problems.append(f"{e['id']} boundElements -> {b['id']} not found")

    # No two content rectangles may overlap (lanes and their contents are exempt).
    content = [r for r in d.rects if not r[0].startswith("lane:")]
    for i, a in enumerate(content):
        for b in content[i + 1:]:
            if _overlap(a, b):
                problems.append(f"overlap: {a[0]} vs {b[0]}")

    problems.extend(check_text_fits(d))
    problems.extend(check_arrows(d))
    problems.extend(check_labels(d))

    # Bounds: everything must fit one screen.
    w = max((x + wd for _k, x, _y, wd, _h in d.rects), default=0.0)
    hh = max((y + ht for _k, _x, y, _w, ht in d.rects), default=0.0)
    if w > MAX_W:
        problems.append(f"too wide: extent {w:.0f} > {MAX_W}")
    if hh > MAX_H:
        problems.append(f"too tall: extent {hh:.0f} > {MAX_H}")
    for key, x, y, wd, ht in d.rects:
        if x < 0 or y < 0:
            problems.append(f"out of bounds: {key} at ({x},{y},{wd},{ht})")

    if verbose:
        from collections import Counter

        counts = Counter(e["type"] for e in els)
        print(f"  elements: {len(els)} total  " + "  ".join(
            f"{k}={v}" for k, v in sorted(counts.items())))
        print(f"  content boxes: {len(content)}   lanes/groups: "
              f"{len(d.rects) - len(content)}   arrows: {len(d.segments)}")
        print(f"  extent: {w:.0f} x {hh:.0f}")
        print(f"  text fits checked: {len(d.textfits)}   labels checked: "
              f"{len(d.labels)}")
    return problems


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true",
                    help="regenerate in memory and exit 1 if any file on disk differs")
    args = ap.parse_args(argv)

    here = Path(__file__).resolve().parent
    failures: list[str] = []
    stale: list[str] = []

    for name, build in DIAGRAMS.items():
        print(f"[{name}]")
        WARNINGS.clear()
        d = build()
        text = d.dumps()
        payload = json.loads(text)  # round-trips == valid JSON

        problems = validate(d, payload)
        for w in WARNINGS:
            print(f"  warn: {w}")
        if problems:
            failures.extend(f"{name}: {p}" for p in problems)
            for p in problems:
                print(f"  FAIL {p}")
        else:
            print("  validation: OK (text fits, arrows anchored, no crossings, "
                  "bindings resolve)")

        path = here / f"{name}.excalidraw"
        if args.check:
            current = path.read_text(encoding="utf-8") if path.exists() else None
            if current != text:
                stale.append(name)
                print("  CHECK: differs from disk")
            else:
                print("  CHECK: up to date")
        else:
            path.write_text(text, encoding="utf-8")
            print(f"  wrote {path.name} ({len(text)} bytes)")

    if failures:
        print(f"\n{len(failures)} validation failure(s).")
        return 1
    if args.check and stale:
        print(f"\nstale: {', '.join(stale)} - run: python gen_diagrams.py")
        return 1
    print("\nall diagrams OK." if not args.check else "\nall diagrams up to date.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
