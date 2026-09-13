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

Accuracy rules (see CLAUDE.md "Claims discipline"): every solid box is something
that actually runs today; everything aspirational is dashed and labelled. No
secrets, no strategy parameters, no indicator names appear in any diagram.
"""

from __future__ import annotations

import itertools
import argparse
import hashlib
import json
import sys
from pathlib import Path

# ---------------------------------------------------------------- palette

INK = "#1e1e1e"
LANE_STROKE = "#868e96"
NOTE_STROKE = "#0c8599"

FRONTEND = "#e7f5ff"  # frontend / serving
DATA = "#ebfbee"  # data / storage
LLM = "#f3f0ff"  # LLM / AI
GUARD = "#fff4e6"  # guardrails / boundaries
CI = "#fff9db"  # CI / compute
PLAIN = "#ffffff"

FS_BODY = 13
FS_TITLE = 15
FS_HEAD = 20

# A fixed timestamp keeps output deterministic (Excalidraw only uses it for ordering).
UPDATED = 1751720000000

CANVAS_W = 1400
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

# Excalidraw's hand-drawn font at fontSize N is roughly 0.56*N per char wide and
# 1.25*N per line tall. We only need this to wrap text and size boxes sanely.
def _char_w(font_size: int) -> float:
    return font_size * 0.56


def line_h(font_size: int) -> float:
    return round(font_size * 1.25, 1)


def wrap(text: str, width_px: float, font_size: int) -> list[str]:
    """Greedy wrap honouring explicit newlines. width_px is the usable text width."""
    max_chars = max(4, int(width_px / _char_w(font_size)))
    out: list[str] = []
    for para in text.split("\n"):
        if not para:
            out.append("")
            continue
        cur = ""
        for word in para.split(" "):
            cand = word if not cur else cur + " " + word
            if len(cand) <= max_chars:
                cur = cand
            else:
                if cur:
                    out.append(cur)
                cur = word
        out.append(cur)
    return out


def text_w(lines: list[str], font_size: int) -> float:
    return round(max((len(ln) for ln in lines), default=0) * _char_w(font_size), 1)


# ---------------------------------------------------------------- element factories

class Diagram:
    """Accumulates elements and knows where every rectangle sits (for validation)."""

    def __init__(self, name: str, title: str, subtitle: str = "") -> None:
        self.name = name
        self.elements: list[dict] = []
        self.rects: list[tuple[str, float, float, float, float]] = []  # label,x,y,w,h
        self.lanes: set[str] = set()  # ids of lane/group rects, exempt from overlap
        self._n = 0
        if title:
            self.text(20, 18, title, font_size=FS_HEAD)
        if subtitle:
            self.text(20, 48, subtitle, font_size=FS_BODY, color=LANE_STROKE)

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
    ) -> dict:
        key = key or f"{self.name}:text:{content}:{x}:{y}"
        lines = content.split("\n")
        el = self._base("text", key, x, y, text_w(lines, font_size), line_h(font_size) * len(lines))
        el.update(
            {
                "strokeColor": color,
                "text": content,
                "originalText": content,
                "fontSize": font_size,
                "fontFamily": 1,
                "textAlign": align,
                "verticalAlign": "top",
                "containerId": None,
                "autoResize": True,
                "lineHeight": 1.25,
                "baseline": round(font_size * 0.77, 1),
            }
        )
        self.elements.append(el)
        return el

    # -- box with bound (editable) label ---------------------------------

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
    ) -> str:
        """Rounded rectangle with text bound into it. Returns the rectangle id."""
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

        tkey = f"{self.name}:boxtext:{key}"
        lines = wrap(label, w - 16, font_size)
        txt = self._base(
            "text",
            tkey,
            x + 8,
            y + max(4.0, (h - line_h(font_size) * len(lines)) / 2),
            w - 16,
            line_h(font_size) * len(lines),
        )
        txt.update(
            {
                "strokeColor": stroke if stroke != LANE_STROKE else INK,
                "text": "\n".join(lines),
                "originalText": label,
                "fontSize": font_size,
                "fontFamily": 1,
                "textAlign": "center",
                "verticalAlign": "center",
                "containerId": rect["id"],
                "autoResize": False,
                "lineHeight": 1.25,
                "baseline": round(font_size * 0.77, 1),
            }
        )
        rect["boundElements"] = [{"id": txt["id"], "type": "text"}]

        self.elements.append(rect)
        self.elements.append(txt)
        self.rects.append((key, x, y, w, h))
        return rect["id"]

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
        """Group container: white fill, grey stroke, header text above the contents."""
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
        self.elements.append(rect)
        self.lanes.add(rect["id"])
        self.rects.append((f"lane:{key}", x, y, w, h))
        self.text(x + 10, y + 8, header, font_size=FS_TITLE, color=LANE_STROKE,
                  key=f"{self.name}:laneheader:{key}")
        return rect["id"]

    def note(self, key: str, x: float, y: float, w: float, h: float, label: str) -> str:
        """Annotation: transparent fill, teal stroke."""
        return self.box(key, x, y, w, h, label, fill="transparent", stroke=NOTE_STROKE,
                        dashed=True)

    # -- arrows ----------------------------------------------------------

    def arrow(
        self,
        key: str,
        x: float,
        y: float,
        dx: float,
        dy: float,
        src: str | None = None,
        dst: str | None = None,
        label: str = "",
        dashed: bool = False,
        color: str = INK,
        label_side: str = "above",
    ) -> str:
        akey = f"{self.name}:arrow:{key}"
        el = self._base("arrow", akey, x, y, abs(dx), abs(dy))
        el.update(
            {
                "strokeColor": color,
                "roundness": {"type": 2},
                "strokeStyle": "dashed" if dashed else "solid",
                "points": [[0, 0], [round(dx, 1), round(dy, 1)]],
                "lastCommittedPoint": None,
                "startBinding": {"elementId": src, "focus": 0, "gap": 4} if src else None,
                "endBinding": {"elementId": dst, "focus": 0, "gap": 4} if dst else None,
                "startArrowhead": None,
                "endArrowhead": "arrow",
            }
        )
        self.elements.append(el)

        if label:
            # Place the label near the arrow midpoint as free text (kept out of the
            # binding graph so it never distorts the arrow geometry).
            lines = label.split("\n")
            lw = text_w(lines, 11)
            mx = x + dx / 2
            my = y + dy / 2
            if abs(dy) < 6:  # horizontal
                lx, ly = mx - lw / 2, my - (line_h(11) * len(lines) + 5)
            else:
                lx = mx + 7 if label_side == "above" else mx - lw - 7
                ly = my - line_h(11) * len(lines) / 2
            self.text(lx, ly, label, font_size=11, color=color,
                      key=f"{self.name}:arrowlabel:{key}")
        return el["id"]

    # -- convenience edges between known boxes ---------------------------

    def hedge(self, key: str, a: tuple, b: tuple, label: str = "", dashed: bool = False,
              color: str = INK, src: str | None = None, dst: str | None = None) -> str:
        """Horizontal arrow from the right edge of rect a to the left edge of rect b.

        a, b are (x, y, w, h) tuples.
        """
        ax, ay, aw, ah = a
        bx, by, _bw, bh = b
        x0 = ax + aw + 4
        y0 = ay + ah / 2
        x1 = bx - 4
        y1 = by + bh / 2
        return self.arrow(key, x0, y0, x1 - x0, y1 - y0, src=src, dst=dst, label=label,
                          dashed=dashed, color=color)

    def vedge(self, key: str, a: tuple, b: tuple, label: str = "", dashed: bool = False,
              color: str = INK, src: str | None = None, dst: str | None = None) -> str:
        """Vertical arrow from the bottom edge of a to the top edge of b."""
        ax, ay, aw, ah = a
        bx, by, bw, _bh = b
        x0 = ax + aw / 2
        y0 = ay + ah + 4
        x1 = bx + bw / 2
        y1 = by - 4
        return self.arrow(key, x0, y0, x1 - x0, y1 - y0, src=src, dst=dst, label=label,
                          dashed=dashed, color=color)

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


# A helper so layout code can talk in rect tuples.
class B:
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


def place(d: Diagram, key: str, x, y, w, h, label, **kw) -> B:
    return B(d.box(key, x, y, w, h, label, **kw), x, y, w, h)


def place_note(d: Diagram, key: str, x, y, w, h, label) -> B:
    return B(d.note(key, x, y, w, h, label), x, y, w, h)


# =================================================================== 00

def diagram_00() -> Diagram:
    """System end-to-end: who talks to whom, and what crosses each hop."""
    d = Diagram(
        "00",
        "yantra-research-lab - system end to end",
        "Solid = deployed and serving today.  Dashed = target / not served yet.  "
        "Generated by gen_diagrams.py",
    )

    lane_y, lane_h = 80, 470
    # Six lanes across the canvas.
    lanes = [
        ("visitor", 20, 150, "VISITOR"),
        ("vercel", 186, 250, "VERCEL"),
        ("fly", 452, 268, "FLY.IO  (sin)"),
        ("managed", 736, 250, "MANAGED SERVICES"),
        ("github", 1002, 200, "GITHUB"),
        ("sources", 1214, 166, "DATA SOURCES"),
    ]
    for key, lx, lw, header in lanes:
        d.lane(key, lx, lane_y, lw, lane_h, header)

    # --- visitor
    vis = place(d, "browser", 36, 128, 118, 62,
                "Browser\nrecruiter / interviewer", fill=FRONTEND)

    # --- vercel: the Next.js app and its six routes
    nextapp = place(d, "next", 202, 122, 218, 56,
                    "Next.js 14.2.5 app\nReact 18.3.1 - TypeScript", fill=FRONTEND,
                    font_size=FS_TITLE)
    routes = place(d, "routes", 202, 192, 218, 116,
                   "6 routes\n/ . /strategies . /research-lab\n/chat . /ops . /pipeline",
                   fill=FRONTEND)
    static = place(d, "static", 202, 322, 218, 86,
                   "static JSON in public/data/\nbooks/*.json . run.json\ningestion.json",
                   fill=DATA)
    d.vedge("next-routes", nextapp.rect, routes.rect, src=nextapp.id, dst=routes.id)
    d.vedge("routes-static", routes.rect, static.rect, label="fetch\n(no API)",
            src=routes.id, dst=static.id)

    # --- fly: the FastAPI request pipeline
    api = place(d, "api", 468, 122, 236, 50,
                "FastAPI + uvicorn  (Python 3.11)", fill=FRONTEND, font_size=FS_TITLE)
    guard = place(d, "guard", 468, 186, 236, 58,
                  "guardrails\nrate limit - PII redact - injection - IP refusal",
                  fill=GUARD)
    router = place(d, "router", 468, 258, 236, 50,
                   "book router (deterministic keywords)", fill=GUARD)
    retr = place(d, "retr", 468, 322, 236, 50, "vector retrieval  search(k=4)", fill=DATA)
    claude = place(d, "claudecall", 468, 386, 236, 50,
                   "Claude claude-haiku-4-5", fill=LLM)
    for a, b, k in ((api, guard, "a1"), (guard, router, "a2"), (router, retr, "a3"),
                    (retr, claude, "a4")):
        d.vedge(k, a.rect, b.rect, src=a.id, dst=b.id)

    d.text(468, 452, "1 shared-cpu / 1GB machine, kept warm\n(min_machines_running = 1)",
           font_size=11, color=LANE_STROKE, key="00:flynote")

    # --- managed services
    qdrant = place(d, "qdrant", 752, 122, 218, 128,
                   "Qdrant Cloud  (AWS us-west-2)\n\n"
                   "methodology  16 docs / 18 chunks  READ\n"
                   "research_corpus  376 indexed  NOT READ",
                   fill=DATA)
    anthropic = place(d, "anthropic", 752, 266, 218, 62,
                      "Anthropic API\nclaude-haiku-4-5 + prompt caching", fill=LLM)
    logfire = place(d, "logfire", 752, 344, 218, 62,
                    "Logfire  (OpenTelemetry)\nchat_request > retrieve > llm", fill=LLM)
    d.text(752, 420, "LangSmith / Langfuse / CloudWatch:\ndocumented targets, not wired",
           font_size=11, color=LANE_STROKE, key="00:obsnote")

    d.hedge("retr-qdrant", retr.rect, qdrant.rect, label="embed + search\nbge-small 384d",
            src=retr.id, dst=qdrant.id)
    d.hedge("claude-anthropic", claude.rect, anthropic.rect, label="messages.create",
            src=claude.id, dst=anthropic.id)
    d.arrow("api-logfire", api.x + api.w + 4, api.y + 20, 258, 336,
            src=api.id, dst=logfire.id, label="spans, safe\naggregates only")

    # --- github
    repo = place(d, "repo", 1018, 122, 168, 56, "repo  main branch", fill=CI)
    ci = place(d, "ci", 1018, 192, 168, 78,
               "ci.yml\nchanges > core > eval-gate", fill=CI)
    cron = place(d, "cron", 1018, 284, 168, 78,
                 "ingest.yml cron\n17 2 * * *  daily", fill=CI)
    hook = place(d, "hook", 1018, 376, 168, 56,
                 "Vercel git integration", fill=FRONTEND)
    d.vedge("repo-ci", repo.rect, ci.rect, src=repo.id, dst=ci.id)
    d.vedge("ci-cron", ci.rect, cron.rect, src=None, dst=None, dashed=True)
    d.vedge("cron-hook", cron.rect, hook.rect, label="commit-back\n[skip ci]",
            src=cron.id, dst=hook.id)

    # --- data sources
    arxiv = place(d, "arxiv", 1230, 122, 138, 56, "arXiv q-fin API", fill=DATA)
    s3 = place(d, "s3", 1230, 192, 138, 70,
               "AWS S3 bronze\nyantra-research-lab-data", fill=DATA)
    place(d, "private", 1230, 316, 138, 92,
                 "private repo\nindex-options-trading-bot\nmonthly report PDFs",
                 fill=GUARD, dashed=True)
    d.text(1230, 276, "outputs-only boundary (ADR-0001)", font_size=11, color=NOTE_STROKE,
           key="00:boundary")

    d.arrow("arxiv-cron", arxiv.x - 4, arxiv.y + 28, -(arxiv.x - 4 - (cron.x + cron.w + 4)),
            (cron.y + 30) - (arxiv.y + 28), src=arxiv.id, dst=cron.id, label="fetch PDFs")
    d.arrow("cron-s3", s3.x - 4, s3.y + 30, -(s3.x - 4 - (cron.x + cron.w + 4)),
            (cron.y + 46) - (s3.y + 30), src=s3.id, dst=cron.id,
            label="content-hashed,\nincremental")
    d.arrow("cron-qdrant", cron.x - 4, cron.y + 40, -(cron.x - 4 - (qdrant.x + qdrant.w + 4)),
            (qdrant.y + 100) - (cron.y + 40), src=cron.id, dst=qdrant.id,
            label="upsert research_corpus")

    # --- visitor traffic
    d.hedge("vis-next", vis.rect, nextapp.rect, label="HTTPS", src=vis.id, dst=nextapp.id)
    d.arrow("next-api", routes.x + routes.w + 4, routes.y + 60, 40, -(routes.y + 60 - (api.y + 25)),
            src=routes.id, dst=api.id, label="/chat, /ops:\nHTTPS JSON")
    d.arrow("hook-vercel", hook.x - 4, hook.y + 28,
            -(hook.x - 4 - (nextapp.x + nextapp.w + 4)),
            (nextapp.y + 40) - (hook.y + 28), src=hook.id, dst=nextapp.id,
            label="build + deploy on push")

    # --- boundary note
    place_note(d, "note-priv", 1002, 470, 366, 72,
               "Outputs cross this boundary: labelled backtest results only. "
               "Engine parameters, exit logic and trade rows never do.")

    # --- what is NOT here
    place_note(d, "note-target", 20, 570, 620, 74,
               "TARGET, not deployed: Tier-2 slm_regime_classifier (empty stub dirs, "
               "0 lines of Python); AWS Fargate / S3+CloudFront hosting; "
               "auth + RBAC (ADR-0006); LLM proposer in the research loop.")
    place_note(d, "note-loop", 664, 570, 704, 74,
               "Tier-1 research loop (research_lab/, stdlib only, no LLM calls) runs in CI "
               "via eval/run_gate.py and ships a cached run.json to /research-lab. "
               "It is not on the website request path.")
    return d


# =================================================================== 01

def diagram_01() -> Diagram:
    """Tech stack board: product, version, role, where it runs."""
    d = Diagram(
        "01",
        "Tech stack - what is actually running",
        "Each card: product / version / role / where it runs.  "
        "The bottom strip is documented targets, not built.",
    )

    CW, CH = 196, 92  # card size
    GX = 208  # grid pitch (x)

    groups: list[tuple[str, str, list[tuple[str, str]]]] = [
        ("frontend", FRONTEND, [
            ("Next.js 14.2.5", "App Router UI, 6 routes\nruns on Vercel"),
            ("React 18.3.1 + TypeScript 5.5", "components, inline SVG charts\nbuilt on Vercel"),
            ("react-markdown 9", "renders chat answers\nin the browser"),
        ]),
        ("backend", FRONTEND, [
            ("FastAPI + uvicorn", "/health /api/chat /api/metrics /docs\nPython 3.11-slim image"),
            ("Fly.io  app yantra-chatbot", "1 shared-cpu/1GB, region sin\nkept warm, manual fly deploy"),
            ("Vercel", "static + SSR hosting\nauto-deploy on push to main"),
        ]),
        ("llm", LLM, [
            ("Claude claude-haiku-4-5", "chat answers + figure captions\nAnthropic API, prompt caching"),
            ("Anthropic Python SDK", "messages.create, max_tokens 1024\ncalled from Fly + CI"),
            ("LangGraph", "ingestion StateGraph, 8 nodes\nruns on GitHub Actions"),
        ]),
        ("vectors", DATA, [
            ("fastembed (ONNX)", "BAAI/bge-small-en-v1.5, 384d\nsame model in serving + ingestion"),
            ("Qdrant Cloud", "cosine; methodology + research_corpus\nAWS us-west-2"),
            ("AWS S3", "bronze layer, content-hashed\nbucket set by CI secret"),
        ]),
        ("guardrails", GUARD, [
            ("guardrails.py", "PII redact, injection detect, IP refusal\nin-process on Fly"),
            ("books.py router", "deterministic keyword routing\nto books_corpus docs"),
            ("eval/ suite", "run_gate . redteam . chatbot_books_eval\nGitHub Actions + local"),
        ]),
        ("ops", LLM, [
            ("Logfire (OpenTelemetry)", "spans chat_request>retrieve>llm\nsends only when token present"),
            ("/api/metrics", "queries Logfire back, feeds /ops\nLOGFIRE_READ_TOKEN"),
            ("Research loop (Tier-1)", "stdlib Python, deterministic\nMCP run_backtest contract"),
        ]),
        ("tooling", CI, [
            ("GitHub Actions", "ci.yml path-filtered + ingest.yml cron\nephemeral ubuntu runners"),
            ("ruff + pytest", "lint and tests in the core job\nPython 3.12 in CI"),
            ("PyMuPDF + Tesseract", "PDF text/tables/images, OCR fallback\ningestion runner"),
        ]),
    ]

    labels = {
        "frontend": "FRONTEND", "backend": "BACKEND & HOSTING", "llm": "LLM / ORCHESTRATION",
        "vectors": "EMBEDDINGS, VECTOR DB & STORAGE", "guardrails": "GUARDRAILS & EVALS",
        "ops": "OBSERVABILITY & RESEARCH LOOP", "tooling": "CI/CD & TOOLING",
    }

    # Each group is a lane holding one row of three cards. Seven such lanes will not fit
    # in 900px of height, so they are dealt into two columns of a fixed pitch.
    LANE_W = 3 * GX + 22
    LANE_H = CH + 32
    PITCH = LANE_H + 12
    col_x = (20, 20 + LANE_W + 24)

    for gi, (gkey, fill, cards) in enumerate(groups):
        col, row = gi // 4, gi % 4
        lx, ly = col_x[col], 78 + row * PITCH
        d.lane(gkey, lx, ly, LANE_W, LANE_H, labels[gkey])
        for i, (name, role) in enumerate(cards):
            place(d, f"{gkey}-{i}", lx + 10 + i * GX, ly + 26, CW, CH,
                  f"{name}\n\n{role}", fill=fill)

    # Fourth slot of the right column: the targets strip.
    tx, ty = col_x[1], 78 + 3 * PITCH
    d.lane("targets", tx, ty, LANE_W, LANE_H, "DOCUMENTED TARGETS - NOT BUILT")
    targets = [
        "AWS Fargate\ncontainer hosting (ADR-0005)\nFly.io today",
        "S3 + CloudFront\nstatic hosting\nVercel today",
        "Cognito / Clerk\nauth + RBAC, none in v1\n(ADR-0006)",
    ]
    targets2 = [
        "LiteLLM gateway\nmodel routing / fallback\ndirect Anthropic SDK today",
        "LangSmith / Langfuse\nLLM tracing\nLogfire today",
        "ColQwen visual retrieval\npage-image retrieval\ncaption-then-embed today",
    ]
    for i, label in enumerate(targets):
        place(d, f"target-{i}", tx + 10 + i * GX, ty + 26, CW, CH, label,
              fill=PLAIN, dashed=True)
    ty2 = ty + PITCH
    d.lane("targets2", tx, ty2, LANE_W, LANE_H, "DOCUMENTED TARGETS - NOT BUILT (cont.)")
    for i, label in enumerate(targets2):
        place(d, f"target2-{i}", tx + 10 + i * GX, ty2 + 26, CW, CH, label,
              fill=PLAIN, dashed=True)

    # Honest footnotes, full width under both columns.
    fy = ty2 + PITCH
    place_note(d, "note-tier2", col_x[0], fy, LANE_W, 62,
               "Tier-2 slm_regime_classifier (distill > QLoRA > serve > eval-gate) is a "
               "README plus four EMPTY directories - 0 lines of Python. TARGET, and not "
               "on the website request path either way.")
    place_note(d, "note-css", col_x[1], fy, LANE_W, 62,
               "Styling: Tailwind 3.4.6 is configured and its directives are in "
               "globals.css, alongside hand-written CSS custom-property tokens. "
               "Charts are inline SVG - no charting library.")
    return d


# =================================================================== 02

def diagram_02() -> Diagram:
    """One /api/chat request, including the paths that never reach the LLM."""
    d = Diagram(
        "02",
        "/api/chat - one request, end to end",
        "Left to right is the happy path. Branches downward are early exits that "
        "never call the model.",
    )

    row_y = 150
    H = 74
    stages = [
        ("in", "POST /api/chat\n{message, history}", FRONTEND, 168),
        ("rl", "rate limit\n20 / min / IP", GUARD, 132),
        ("cap", "daily cap\n500 / day", GUARD, 122),
        ("pii", "redact_pii\nemails, phones,\n7+ digit runs", GUARD, 150),
        ("inj", "detect_injection", GUARD, 138),
        ("ref", "should_refuse\nIP policy", GUARD, 138),
        ("route", "book router\nbooks.py", DATA, 138),
    ]
    x = 24
    placed: dict[str, B] = {}
    for key, label, fill, w in stages:
        placed[key] = place(d, key, x, row_y, w, H, label, fill=fill)
        x += w + 44

    order = [s[0] for s in stages]
    for a, b in itertools.pairwise(order):
        d.hedge(f"e-{a}-{b}", placed[a].rect, placed[b].rect,
                src=placed[a].id, dst=placed[b].id)

    # Second row: retrieval, merge, LLM, response.
    row2 = 320
    retr = place(d, "retr", 24, row2, 200, 84,
                 "vector retrieval\nQdrant methodology\nsearch(k=4)", fill=DATA)
    bookdocs = place(d, "bookdocs", 24, row2 + 120, 200, 84,
                     "routed book docs\noverview / per-book /\nrisk gates", fill=DATA)
    merge = place(d, "merge", 272, row2 + 46, 186, 100,
                  "context assembly\nbook docs first,\nthen vector chunks\ndedup by title",
                  fill=DATA)
    sysp = place(d, "sysp", 272, row2 + 176, 186, 76,
                 "system prompt\nSYSTEM_PROMPT +\nBOOKS_SYSTEM_ADDENDUM", fill=GUARD)
    llm = place(d, "llm", 506, row2 + 46, 210, 100,
                "Claude claude-haiku-4-5\nmax_tokens 1024\ncache_control: ephemeral",
                fill=LLM)
    resp = place(d, "resp", 764, row2 + 46, 210, 100,
                 "200 response\n{answer, refused,\nsources[], leak_rate}", fill=FRONTEND)

    # router -> retrieval (wraps to row 2)
    d.arrow("route-retr", placed["route"].cx, placed["route"].y + H + 4,
            (retr.cx - placed["route"].cx), (retr.y - 4) - (placed["route"].y + H + 4),
            src=placed["route"].id, dst=retr.id, label="routed doc titles")
    d.vedge("retr-books", retr.rect, bookdocs.rect, src=None, dst=None, dashed=True)

    d.hedge("retr-merge", retr.rect, merge.rect, src=retr.id, dst=merge.id)
    d.hedge("books-merge", bookdocs.rect, merge.rect, src=bookdocs.id, dst=merge.id)
    d.hedge("merge-llm", merge.rect, llm.rect, label="context", src=merge.id, dst=llm.id)
    d.arrow("sysp-llm", sysp.x + sysp.w + 4, sysp.y + 38,
            (llm.x - 4) - (sysp.x + sysp.w + 4), (llm.y + 76) - (sysp.y + 38),
            src=sysp.id, dst=llm.id, label="cached prefix")
    d.hedge("llm-resp", llm.rect, resp.rect, src=llm.id, dst=resp.id)

    # Early exits.
    exit_y = 268
    e429 = place(d, "e429", 200, exit_y, 176, 44, "429  too many requests",
                 fill=GUARD, dashed=True)
    erefuse = place(d, "erefuse", 690, exit_y, 244, 44,
                    "200 refused=true - no LLM call", fill=GUARD, dashed=True)
    d.arrow("rl-429", placed["rl"].cx, placed["rl"].y + H + 4, 0, exit_y - 4 - (placed["rl"].y + H + 4),
            src=placed["rl"].id, dst=e429.id, label="over limit")
    d.arrow("cap-429", placed["cap"].cx, placed["cap"].y + H + 4,
            (e429.cx + 50) - placed["cap"].cx, exit_y - 4 - (placed["cap"].y + H + 4),
            src=placed["cap"].id, dst=e429.id, label="cap hit")
    d.arrow("inj-refuse", placed["inj"].cx, placed["inj"].y + H + 4,
            (erefuse.x + 40) - placed["inj"].cx, exit_y - 4 - (placed["inj"].y + H + 4),
            src=placed["inj"].id, dst=erefuse.id, label="injection")
    d.arrow("ref-refuse", placed["ref"].cx, placed["ref"].y + H + 4,
            (erefuse.cx + 40) - placed["ref"].cx, exit_y - 4 - (placed["ref"].y + H + 4),
            src=placed["ref"].id, dst=erefuse.id, label="IP terms /\nproduct + mechanism")

    # Logfire side box.
    lf = place(d, "logfire", 1010, row2 + 46, 300, 160,
               "Logfire span tree\n\nchat_request > retrieve > llm\n"
               "latency split - token cost estimate\nrefused / leak_rate flags\n\n"
               "safe aggregates only - never user text", fill=LLM)
    d.arrow("resp-lf", resp.x + resp.w + 4, resp.cy, (lf.x - 4) - (resp.x + resp.w + 4), 0,
            src=resp.id, dst=lf.id)
    d.arrow("ops-lf", lf.cx, lf.y + lf.h + 4, 0, 60, src=lf.id, dst=None)
    ops = place(d, "opspage", 1010, lf.y + lf.h + 64, 300, 60,
                "/api/metrics > /ops page\nLOGFIRE_READ_TOKEN", fill=FRONTEND)
    d.rects[-1] = ("opspage", ops.x, ops.y, ops.w, ops.h)

    # The rule that governs the router + refusal boxes.
    place_note(d, "note-rule", 24, 610, 950, 92,
               "Outputs vs mechanism: the router may serve labelled backtest RESULTS from "
               "books_corpus. should_refuse blocks mechanism - a product name plus a "
               "mechanism ask counts as specific and is refused. PII is redacted from the "
               "user message before anything is logged or sent to the model.")
    place_note(d, "note-cold", 24, 716, 950, 56,
               "As of 2026-08-17 /api/metrics reported queries_served: 1 all-time, "
               "p50 = p95 ~ 20s from a single cold-start sample. Deployed and observable, "
               "not a trafficked product.")
    return d


# =================================================================== 03

def diagram_03() -> Diagram:
    """What writes to Qdrant, what reads from it, and the gap in between."""
    d = Diagram(
        "03",
        "Data flows into Qdrant Cloud - and the one gap",
        "Two write pipelines, one reader. research_corpus is indexed nightly but the "
        "chatbot does not read it.",
    )

    # --- pipeline A: Tier-3 ingestion (medallion)
    d.lane("ingest", 20, 76, 900, 214,
           "TIER-3 INGESTION  (LangGraph StateGraph, GitHub Actions cron 17 2 * * *)")
    ay, AH = 128, 92
    steps = [
        ("discover", "discover\narXiv q-fin API", DATA, 116),
        ("fetch", "fetch\nPDFs > S3 bronze\ncontent-hashed", DATA, 128),
        ("parse", "parse\nPyMuPDF text /\ntables / images\nOCR fallback", DATA, 128),
        ("caption", "caption\nfigure raster >\nHaiku vision", LLM, 122),
        ("enrich", "enrich\nchunk + summary\nbudget $3/run", LLM, 122),
        ("quality", "quality gate\ndedup - relevance\nIP-leak quarantine", GUARD, 132),
    ]
    x = 32
    ip: dict[str, B] = {}
    for key, label, fill, w in steps:
        ip[key] = place(d, key, x, ay, w, AH, label, fill=fill)
        x += w + 26
    ks = [s[0] for s in steps]
    for a, b in itertools.pairwise(ks):
        d.hedge(f"i-{a}-{b}", ip[a].rect, ip[b].rect, src=ip[a].id, dst=ip[b].id)

    # medallion labels
    d.text(38, 236, "BRONZE  raw PDFs in S3", font_size=11, color=NOTE_STROKE, key="03:bronze")
    d.text(310, 236, "SILVER  parsed + captioned + chunked", font_size=11, color=NOTE_STROKE,
           key="03:silver")
    d.text(700, 236, "GOLD  accepted > indexed", font_size=11, color=NOTE_STROKE, key="03:gold")

    dlq = place(d, "dlq", 660, 262, 150, 52, "dead-letter\nrejected chunks",
                fill=GUARD, dashed=True)
    d.rects[-1] = ("dlq", dlq.x, dlq.y, dlq.w, dlq.h)

    gate = place(d, "gate", 952, ay, 136, AH,
                 "HITL gate\nauto-approve\nin CI", fill=GUARD)
    idx = place(d, "index", 1114, ay, 150, AH,
                "index\nbge-small 384d\nembed + upsert", fill=DATA)
    d.hedge("i-quality-gate", ip["quality"].rect, gate.rect, src=ip["quality"].id, dst=gate.id)
    d.hedge("i-gate-index", gate.rect, idx.rect, src=gate.id, dst=idx.id)
    d.arrow("quality-dlq", ip["quality"].cx - 30, ip["quality"].y + AH + 4,
            (dlq.cx) - (ip["quality"].cx - 30), (dlq.y - 4) - (ip["quality"].y + AH + 4),
            src=ip["quality"].id, dst=dlq.id, label="quarantine")

    # --- Qdrant Cloud
    d.lane("qc", 560, 396, 400, 250, "QDRANT CLOUD  (AWS us-west-2)", dashed=False)
    research = place(d, "research", 578, 430, 364, 88,
                     "research_corpus\n419 chunks parsed - 376 indexed\n18 captioned figures",
                     fill=DATA)
    methodology = place(d, "methodology", 578, 540, 364, 88,
                        "methodology\n16 docs / 18 chunks\n8 seed notes + 8 book docs",
                        fill=DATA)
    d.vedge("idx-research", (idx.x, idx.y + AH - 4, idx.w, 4), research.rect,
            src=idx.id, dst=research.id, label="upsert")

    # --- pipeline B: books
    d.lane("books", 20, 676, 900, 200,
           "STRATEGY BOOKS  (outputs only - manual, not on a schedule)")
    by, BH = 726, 92
    priv = place(d, "priv", 32, by, 154, BH,
                 "private repo\nindex-options-\ntrading-bot", fill=GUARD, dashed=True)
    pdfs = place(d, "pdfs", 212, by, 146, BH,
                 "7 monthly\nreport PDFs\nquick_reference/", fill=GUARD, dashed=True)
    extract = place(d, "extract", 384, by, 168, BH,
                    "extract_monthly_\nfrom_reports.py\nbar geometry >\nprinted totals",
                    fill=CI)
    booksjson = place(d, "booksjson", 578, by, 158, BH,
                      "public/data/books/\n7 books + index\n+ risk_gates", fill=DATA)
    sync = place(d, "sync", 762, by, 146, BH,
                 "sync_books_\ncorpus.py >\nbooks_corpus/*.md", fill=CI)
    d.hedge("b1", priv.rect, pdfs.rect, src=priv.id, dst=pdfs.id)
    d.hedge("b2", pdfs.rect, extract.rect, src=pdfs.id, dst=extract.id)
    d.hedge("b3", extract.rect, booksjson.rect, src=extract.id, dst=booksjson.id)
    d.hedge("b4", booksjson.rect, sync.rect, src=booksjson.id, dst=sync.id)

    # seed corpus
    seed = place(d, "seed", 380, 540, 152, 88,
                 "backend/seed_corpus/\n8 methodology notes", fill=DATA)
    d.hedge("seed-meth", seed.rect, methodology.rect, src=seed.id, dst=methodology.id)
    d.arrow("sync-meth", sync.cx, sync.y - 4, (methodology.cx + 120) - sync.cx,
            (methodology.y + methodology.h + 4) - (sync.y - 4),
            src=sync.id, dst=methodology.id, label="ingest.py\nembed + upsert")

    # strategy explorer reads the JSON directly
    explorer = place(d, "explorer", 952, 676, 174, 86,
                     "/strategies page\nStrategy Explorer\ncumulative + monthly\nSVG charts",
                     fill=FRONTEND)
    d.hedge("books-explorer", (booksjson.x, booksjson.y + 6, booksjson.w, 10), explorer.rect,
            src=booksjson.id, dst=explorer.id, label="static fetch")

    # --- the reader and the gap
    chatbot = place(d, "chatbot", 1010, 430, 260, 88,
                    "chatbot on Fly.io\nreads methodology only\n(no QDRANT_COLLECTION override)",
                    fill=FRONTEND)
    d.arrow("meth-chat", methodology.x + methodology.w + 4, methodology.cy,
            (chatbot.x - 4) - (methodology.x + methodology.w + 4),
            (chatbot.cy + 20) - methodology.cy,
            src=methodology.id, dst=chatbot.id, label="search(k=4)")
    d.arrow("research-chat", research.x + research.w + 4, research.cy,
            (chatbot.x - 4) - (research.x + research.w + 4), (chatbot.cy - 20) - research.cy,
            src=research.id, dst=chatbot.id, label="NOT SERVED YET", dashed=True,
            color=NOTE_STROKE)

    place_note(d, "note-ssh", 1010, 540, 366, 106,
               "Re-ingest gotcha: the Dockerfile's build-time ingest writes a LOCAL index the "
               "app never reads. After any corpus change the cluster must be re-indexed over "
               "SSH: fly ssh console -a yantra-chatbot -C \"sh -c 'cd /app && python "
               "ingest.py'\". A fly deploy alone changes nothing.")
    place_note(d, "note-boundary", 1146, 676, 230, 86,
               "Boundary (ADR-0001): outputs cross; engine parameters, exit logic and "
               "trade rows never do. Future exact path: scripts/export_books.py against "
               "the private trades CSV.")
    place_note(d, "note-embed", 20, 306, 520, 56,
               "One embedding model on both sides: BAAI/bge-small-en-v1.5, 384-dim, cosine. "
               "Serving and ingestion must match or retrieval silently degrades.")
    return d


# =================================================================== 04

def diagram_04() -> Diagram:
    """How code and data actually reach production."""
    d = Diagram(
        "04",
        "Deploy & CI/CD - what is automated, what is a hand",
        "Frontend deploys itself. The backend does not: it takes two manual commands.",
    )

    dev = place(d, "dev", 24, 120, 150, 70, "developer\ngit push main", fill=CI)

    # --- GitHub Actions ci.yml
    d.lane("gha", 206, 76, 700, 240, "GITHUB ACTIONS  ci.yml  (push to main + PR)")
    jy, JH = 126, 92
    changes = place(d, "changes", 222, jy, 142, JH,
                    "changes\ndorny/paths-filter\ncore . chatbot .\ningestion . slm . frontend",
                    fill=CI)
    core = place(d, "core", 390, jy, 142, JH,
                 "core\nruff check .\npytest -q\nPython 3.12", fill=CI)
    egate = place(d, "egate", 558, jy, 154, JH,
                  "eval-gate\npython -m eval.run_gate\nbest variant must\nbeat baseline",
                  fill=CI)
    stubs = place(d, "stubs", 738, jy, 152, JH,
                  "deploy-dev /\ndeploy-prod\necho stubs - TARGET\ninfra/environments empty",
                  fill=PLAIN, dashed=True)
    d.hedge("c1", changes.rect, core.rect, src=changes.id, dst=core.id)
    d.hedge("c2", core.rect, egate.rect, src=core.id, dst=egate.id)
    d.hedge("c3", egate.rect, stubs.rect, src=egate.id, dst=stubs.id, dashed=True)
    d.text(222, 250, "Other evals, run by hand: eval/redteam.py (100% block / 0 false "
                     "positives) - eval/chatbot_books_eval.py (21 graded live questions)",
           font_size=11, color=LANE_STROKE, key="04:evalnote")

    d.hedge("dev-gha", dev.rect, changes.rect, src=dev.id, dst=changes.id, label="webhook")

    # --- Vercel path
    d.lane("vercel", 940, 76, 440, 240, "VERCEL  (automatic)")
    vbuild = place(d, "vbuild", 956, jy, 194, JH,
                   "git integration\nnext build\non push to main", fill=FRONTEND)
    vprod = place(d, "vprod", 1172, jy, 192, JH,
                  "production\nyantra-research-lab\n.vercel.app", fill=FRONTEND)
    d.hedge("v1", vbuild.rect, vprod.rect, src=vbuild.id, dst=vprod.id)
    d.arrow("dev-vercel", dev.cx, dev.y - 4, (vbuild.cx - 60) - dev.cx, 0,
            src=dev.id, dst=vbuild.id, label="same push, separate trigger")

    # --- Fly path (manual)
    d.lane("fly", 206, 340, 700, 226, "FLY.IO BACKEND  (manual - NOT in CI)", dashed=False)
    fy, FH = 392, 92
    flycmd = place(d, "flycmd", 222, fy, 178, FH,
                   "fly deploy\n--remote-only\nrun from backend/", fill=CI)
    builder = place(d, "builder", 424, fy, 166, FH,
                    "Fly remote builder\nDockerfile\npython:3.11-slim", fill=CI)
    machine = place(d, "machine", 614, fy, 176, FH,
                    "machine, region sin\n1 shared-cpu / 1GB\nmin_machines_running 1",
                    fill=FRONTEND)
    d.hedge("f1", flycmd.rect, builder.rect, src=flycmd.id, dst=builder.id)
    d.hedge("f2", builder.rect, machine.rect, src=builder.id, dst=machine.id, label="image")
    d.text(222, 500, "fly.toml config changes only take effect on a deploy from backend/.",
           font_size=11, color=LANE_STROKE, key="04:flytoml")

    sshcmd = place(d, "ssh", 222, 590, 366, 76,
                   "fly ssh console -a yantra-chatbot\n-C \"sh -c 'cd /app && python "
                   "ingest.py'\"", fill=CI)
    d.arrow("dev-fly", dev.cx, dev.y + dev.h + 4, (flycmd.cx - 40) - dev.cx,
            (flycmd.y - 4) - (dev.y + dev.h + 4), src=dev.id, dst=flycmd.id,
            label="by hand")
    d.arrow("dev-ssh", dev.x + 40, dev.y + dev.h + 4, (sshcmd.x + 30) - (dev.x + 40),
            (sshcmd.y - 4) - (dev.y + dev.h + 4), src=dev.id, dst=sshcmd.id,
            label="by hand,\nafter any corpus change")

    qdrant = place(d, "qdrant", 640, 590, 250, 76,
                   "Qdrant Cloud\nmethodology rebuilt", fill=DATA)
    d.hedge("ssh-qdrant", sshcmd.rect, qdrant.rect, src=sshcmd.id, dst=qdrant.id,
            label="embed + upsert")

    # --- ingest cron
    d.lane("cron", 940, 340, 440, 326, "GITHUB ACTIONS  ingest.yml  (cron 17 2 * * *)")
    cronjob = place(d, "cronjob", 956, 392, 408, 76,
                    "ephemeral runner: LangGraph pipeline\nincremental vs content-hashed S3 bronze",
                    fill=CI)
    cronq = place(d, "cronq", 956, 490, 196, 76,
                  "Qdrant\nresearch_corpus", fill=DATA)
    commitback = place(d, "commitback", 1168, 490, 196, 76,
                       "auto-commit\ningestion.json\n+ thumbnails  [skip ci]", fill=CI)
    d.vedge("cron-q", (cronjob.x, cronjob.y + FH - 16, 196, 4), cronq.rect,
            src=cronjob.id, dst=cronq.id)
    d.vedge("cron-cb", (cronjob.x + 212, cronjob.y + FH - 16, 196, 4), commitback.rect,
            src=cronjob.id, dst=commitback.id)
    d.arrow("cb-vercel", commitback.cx, commitback.y - 4,
            (vprod.cx) - commitback.cx, (vprod.y + vprod.h + 4) - (commitback.y - 4),
            src=commitback.id, dst=vprod.id, label="[skip ci] still\ntriggers Vercel")
    d.text(956, 580, "Most nights this re-processes nothing: the content hash already matches.",
           font_size=11, color=LANE_STROKE, key="04:cronnote")

    # --- secrets (names only)
    place_note(d, "secrets", 24, 690, 880, 96,
               "Secrets, by NAME ONLY - values live in Fly secrets and GitHub Actions "
               "secrets, never in this repo: ANTHROPIC_API_KEY - QDRANT_URL - "
               "QDRANT_API_KEY - LOGFIRE_TOKEN - LOGFIRE_READ_TOKEN - FRONTEND_ORIGIN. "
               "The ingest job additionally reads its S3 bucket and AWS credentials from "
               "repository secrets.")
    place_note(d, "gap", 940, 690, 440, 96,
               "The honest gap: CI lints, tests and gates the research loop, but it does not "
               "deploy either service. Frontend ships via Vercel's own git integration; the "
               "backend ships only when someone runs fly deploy, then the SSH re-ingest.")
    return d


# =================================================================== validation

DIAGRAMS = {
    "00-system-e2e": diagram_00,
    "01-tech-stack": diagram_01,
    "02-chat-request-flow": diagram_02,
    "03-data-flows": diagram_03,
    "04-deploy-cicd": diagram_04,
}


def _overlap(a: tuple, b: tuple) -> bool:
    _, ax, ay, aw, ah = a
    _, bx, by, bw, bh = b
    return ax < bx + bw and bx < ax + aw and ay < by + bh and by < ay + ah


def validate(d: Diagram, payload: dict, verbose: bool = True) -> list[str]:
    """Structural checks. Returns a list of problems (empty == clean)."""
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

    # Bounds check.
    for key, x, y, w, h in d.rects:
        if x < 0 or y < 0 or x + w > CANVAS_W + 60 or y + h > CANVAS_H + 60:
            problems.append(f"out of bounds: {key} at ({x},{y},{w},{h})")

    if verbose:
        from collections import Counter

        counts = Counter(e["type"] for e in els)
        print(f"  elements: {len(els)} total  " + "  ".join(
            f"{k}={v}" for k, v in sorted(counts.items())))
        print(f"  content boxes: {len(content)}   lanes/groups: {len(d.rects) - len(content)}")
        w = max((x + wd for _k, x, _y, wd, _h in d.rects), default=0)
        hh = max((y + ht for _k, _x, y, _w, ht in d.rects), default=0)
        print(f"  extent: {w:.0f} x {hh:.0f}")
    return problems


def ascii_grid(d: Diagram, cols: int = 70, rows: int = 30) -> str:
    """Coarse ASCII occupancy map so collisions are eyeballable in a terminal."""
    grid = [[" "] * cols for _ in range(rows)]
    content = [r for r in d.rects if not r[0].startswith("lane:")]
    for i, (_key, x, y, w, h) in enumerate(content):
        ch = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"[
            i % 62]
        c0 = int(x / CANVAS_W * cols)
        c1 = max(c0, int((x + w) / CANVAS_W * cols) - 1)
        r0 = int(y / CANVAS_H * rows)
        r1 = max(r0, int((y + h) / CANVAS_H * rows) - 1)
        for r in range(max(0, r0), min(rows, r1 + 1)):
            for c in range(max(0, c0), min(cols, c1 + 1)):
                grid[r][c] = "*" if grid[r][c] not in (" ", ch) else ch
    body = "\n".join("  |" + "".join(row) + "|" for row in grid)
    return "  +" + "-" * cols + "+\n" + body + "\n  +" + "-" * cols + "+"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true",
                    help="regenerate in memory and exit 1 if any file on disk differs")
    ap.add_argument("--grid", action="store_true",
                    help="print the ASCII occupancy map for each diagram")
    args = ap.parse_args(argv)

    here = Path(__file__).resolve().parent
    failures: list[str] = []
    stale: list[str] = []

    for name, build in DIAGRAMS.items():
        print(f"[{name}]")
        d = build()
        text = d.dumps()
        payload = json.loads(text)  # round-trips == valid JSON

        problems = validate(d, payload)
        if problems:
            failures.extend(f"{name}: {p}" for p in problems)
            for p in problems:
                print(f"  FAIL {p}")
        else:
            print("  validation: OK (bindings resolve, no box overlaps, fields complete)")

        if args.grid:
            print(ascii_grid(d))

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
