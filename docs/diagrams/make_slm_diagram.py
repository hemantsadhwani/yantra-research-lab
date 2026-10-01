"""Generate yantra_slm_finetuning.drawio — the layout SLM: data → fine-tuning → S3 → MLflow → serving.

Four pages: 1 architecture end to end · 2 v1 vs v2 (champion) · 3 S3 bucket layout · 4 session lifecycle.
Numbers are from the runs of 2026-10-01 (adapter_card_dataset.md, MLflow, `aws s3 ls`).
"""
import re
import xml.etree.ElementTree as ET
from pathlib import Path

# draw.io renders <code> as dark text on a dark chip; use plain blue monospace instead.
CODE = re.compile(r"<code>(.*?)</code>", re.S)


def readable(value):
    return CODE.sub(r'<font face="Courier New" color="#0b5394">\1</font>', value)

OUT = str(Path(__file__).with_name("yantra_slm_finetuning.drawio"))

FONT = "fontFamily=Helvetica;"
CARD = "rounded=1;whiteSpace=wrap;html=1;arcSize=8;align=left;verticalAlign=top;spacingLeft=10;spacingTop=6;spacingRight=8;fontSize=12;" + FONT
DONE = "fillColor=#d5e8d4;strokeColor=#82b366;"
NEXT = "fillColor=#f5f5f5;strokeColor=#999999;dashed=1;fontColor=#333333;"
BAD = "fillColor=#f8cecc;strokeColor=#b85450;"
DATA = "fillColor=#dae8fc;strokeColor=#6c8ebf;"
GOLD = "fillColor=#fff2cc;strokeColor=#d6b656;"
NOTE = "fillColor=#ffffff;strokeColor=#cccccc;"
TITLE = "text;html=1;align=left;verticalAlign=middle;fontSize=26;fontStyle=1;" + FONT
SUB = "text;html=1;align=left;verticalAlign=top;fontSize=13;fontColor=#555555;whiteSpace=wrap;" + FONT
LANE = ("rounded=1;arcSize=2;whiteSpace=wrap;html=1;verticalAlign=top;align=center;fontSize=15;fontStyle=1;"
        "spacingTop=8;" + FONT)
EDGE = ("edgeStyle=orthogonalEdgeStyle;rounded=1;html=1;fontSize=11;labelBackgroundColor=#ffffff;endArrow=block;"
        "endFill=1;strokeWidth=2;strokeColor=#555555;" + FONT)
EDGE_NEXT = EDGE + "dashed=1;strokeColor=#999999;fontColor=#666666;"


class Page:
    def __init__(self, name, w=1900, h=1150):
        self.name, self.w, self.h, self.cells, self.n = name, w, h, [], 0

    def _id(self):
        self.n += 1
        return f"p{self.name[0]}-{self.n}"

    def box(self, x, y, w, h, value, style=CARD + NOTE):
        cid = self._id()
        c = ET.Element("mxCell", id=cid, value=readable(value), style=style, vertex="1", parent="1")
        ET.SubElement(c, "mxGeometry", x=str(x), y=str(y), width=str(w), height=str(h), attrib={"as": "geometry"})
        self.cells.append(c)
        return cid

    def edge(self, src, tgt, label="", style=EDGE, pts=(), **ports):
        s = style + "".join(f"{k}={v};" for k, v in ports.items())
        c = ET.Element("mxCell", id=self._id(), value=label, style=s, edge="1", parent="1", source=src, target=tgt)
        g = ET.SubElement(c, "mxGeometry", relative="1", attrib={"as": "geometry"})
        if pts:
            arr = ET.SubElement(g, "Array", attrib={"as": "points"})
            for px, py in pts:
                ET.SubElement(arr, "mxPoint", x=str(px), y=str(py))
        self.cells.append(c)

    def legend(self, x, y, items):
        for i, (label, st) in enumerate(items):
            self.box(x + i * 170, y, 160, 26, label,
                     "rounded=1;whiteSpace=wrap;html=1;fontSize=11;align=center;verticalAlign=middle;" + FONT + st)

    def xml(self, parent):
        d = ET.SubElement(parent, "diagram", name=self.name, id=self.name.replace(" ", "_"))
        m = ET.SubElement(d, "mxGraphModel", dx="1400", dy="900", grid="1", gridSize="10", guides="1",
                          tooltips="1", connect="1", arrows="1", fold="1", page="1", pageScale="1",
                          pageWidth=str(self.w), pageHeight=str(self.h), math="0", shadow="0",
                          background="#FFFFFF")
        r = ET.SubElement(m, "root")
        ET.SubElement(r, "mxCell", id="0")
        ET.SubElement(r, "mxCell", id="1", parent="0")
        for c in self.cells:
            r.append(c)


LEGEND = [("Built and measured ✓", DONE), ("Data in S3", DATA), ("Champion / human gate", GOLD),
          ("Rejected", BAD), ("Designed, not built", NEXT)]

# ============================================================ page 1: architecture
p = Page("1 Architecture")
p.box(40, 14, 1100, 40, "Layout SLM — fine-tuning → infra → S3 → MLflow → serving", TITLE)
p.box(40, 54, 1100, 44, "A 1.5B model learns to label a PDF page (text · table-heavy · figure-heavy · scanned · mixed) "
      "from the parser's one-line page summary. Teacher = the parser's own rule. Everything that must survive lives in "
      "S3 or GitHub; the GPU box is disposable.", SUB)
p.legend(1040, 20, LEGEND)

cols = [(40, "① Control plane", "#f0f0f0", "#888888"), (410, "② Data — S3", "#eef4fb", "#6c8ebf"),
        (780, "③ Fine-tuning — GPU box", "#eef7ec", "#82b366"), (1150, "④ Registry — MLflow", "#fdf8e6", "#d6b656"),
        (1520, "⑤ Serving — next", "#f7f7f7", "#aaaaaa")]
for x, name, fill, stroke in cols:
    p.box(x, 110, 340, 1000, name, LANE + f"fillColor={fill};strokeColor={stroke};")

# ① control plane
nifty = p.box(55, 160, 310, 175, "<b>🖥 nifty_dev</b> (trading monitor host)<br>"
              "<code>launch.sh</code> · profile <b>yantra-launcher</b><br>"
              "can only launch/stop/terminate boxes tagged <i>purpose=dev-public-repos</i>, "
              "in Mumbai or Virginia<br>never runs training itself", CARD + NOTE)
p.box(55, 350, 310, 120, "<b>🔑 Box identity</b> — role <b>yantra-dev-bedrock</b><br>"
      "no keys on the box (instance metadata)<br>S3: read <b>yantra-corpus/*</b> · read+write <b>ml/*</b> · no delete",
      CARD + DONE)
p.box(55, 485, 310, 135, "<b>One command per session</b><br><code>layout_session.sh</code><br>"
      "install → pull mlflow.db → dataset → QLoRA → eval → register → push mlflow.db "
      "(pushed even if a step fails)", CARD + DONE)
p.box(55, 635, 310, 150, "<b>Capacity fallbacks</b> (Mumbai ran out, 1 Oct)<br>"
      "g6.xlarge (L4) → g5.xlarge (A10G) → <b>g4dn.xlarge (T4)</b>, zones 1a/1b<br>"
      "us-east-1: launcher allowed, GPU quota 8 vCPU (approved)", CARD + NOTE)
p.box(55, 800, 310, 120, "<b>Session end</b><br>copy the card → <b>terminate</b><br>"
      "nothing on the box is needed again (see page 4)", CARD + NOTE)
p.box(55, 935, 310, 155, "<b>Cost, 1 Oct</b><br>2 training sessions on a T4 ≈ $1.1 total<br>"
      "S3 ≈ 1.2 GB ≈ $0.03/month<br>LLM API calls: none", CARD + NOTE)

# ② data
raw = p.box(425, 160, 310, 150, "<b>🥉 Bronze — raw PDFs</b><br><code>yantra-corpus/raw/</code><br>"
            "<b>426</b> arXiv q-fin papers · 807 MB<br>written daily by the ingest job (GitHub Actions)<br>"
            "box: <b>read only</b>", CARD + DATA)
silver = p.box(425, 380, 310, 150, "<b>🥈 Silver — page features</b><br><code>ml/silver/layout_features/</code><br>"
               "426 files · <b>7,506 pages</b><br>first parse 8 min · later rebuilds 10 s", CARD + DATA)
ds = p.box(425, 600, 310, 230, "<b>🥇 Dataset 87060948b499</b><br><code>ml/datasets/layout/87060948b499/</code><hr>"
           "split <b>by paper</b> (hash, 80/10/10)<br>"
           "<b>train</b> 344 papers · 6,022 pages<br><b>val</b> 41 papers · 741 pages<br>"
           "<b>test</b> 41 papers · 743 pages — <b>locked</b><br>+ manifest.json (sha256 of every file)",
           CARD + DATA)
p.box(425, 845, 310, 125, "<b>Labels</b> = <code>layout_labels.derive_label</code><br>"
      "a fixed rule over the parser's counts — free, not human<br>rare in real papers: table-heavy 22, scanned 6",
      CARD + NOTE)
p.edge(raw, silver, "parse every page<br>(PyMuPDF, tables on all pages)", exitX=0.5, exitY=1, entryX=0.5, entryY=0)
p.edge(silver, ds, "label + split by paper", exitX=0.5, exitY=1, entryX=0.5, entryY=0)

# ③ fine-tuning
box = p.box(795, 160, 310, 125, "<b>🧠 GPU box (disposable)</b><br>g4dn.xlarge · NVIDIA T4 16 GB · 4 vCPU<br>"
            "Deep Learning AMI, Ubuntu 24.04<br>fp16 on T4 · bf16 on A10G/L4", CARD + DONE)
samp = p.box(795, 300, 310, 95, "<b>Training sample (v2)</b><br>2,654 rows · natural mix, <b>text capped at 50%</b><br>"
             "rare labels kept whole", CARD + DONE)
ql = p.box(795, 410, 310, 140, "<b>QLoRA</b> on <b>Qwen2.5-1.5B-Instruct</b><br>base frozen in 4-bit (nf4)<br>"
           "LoRA r=16 on q/k/v/o · <b>4.36 M</b> trainable of 893 M<br>lr 2e-4 · grad clip 1.0 · 1,000 steps · 15 min",
           CARD + DONE)
sel = p.box(795, 565, 310, 110, "<b>Checkpoint selection</b><br>every 200 steps, score a 200-page <b>val</b> slice<br>"
            "keep the best → step 400", CARD + DONE)
ev = p.box(795, 690, 310, 140, "<b>Evaluation</b><br>base vs tuned on 600 val + 600 <b>test</b> pages<br>"
           "per-label accuracy · p50 latency<br>test touched <b>once</b>, at the end", CARD + DONE)
p.box(795, 845, 310, 125, "<b>Result (champion v2)</b><br>test <b>0.978</b> vs 0.787 always-'text'<br>"
      "base model 0.032 · 152 ms/page on the T4", CARD + GOLD)
p.edge(samp, ql, "", exitX=0.5, exitY=1, entryX=0.5, entryY=0)
p.edge(ql, sel, "", exitX=0.5, exitY=1, entryX=0.5, entryY=0)
p.edge(sel, ev, "", exitX=0.5, exitY=1, entryX=0.5, entryY=0)

# ④ registry
db = p.box(1165, 160, 310, 150, "<b>📒 Tracking</b> — SQLite <code>mlflow.db</code><br>"
           "lives in <code>ml/mlflow/mlflow.db</code><br>pulled at session start, pushed at the end<br>"
           "params · metrics · loss curve · val-selection curve", CARD + DONE)
art = p.box(1165, 325, 310, 150, "<b>📦 Artifacts</b> → <code>ml/mlflow/artifacts/</code><br>"
            "adapter_model.safetensors (17 MB)<br>pyfunc wrapper + code · MLmodel<br>card · dataset manifest",
            CARD + DATA)
reg = p.box(1165, 490, 310, 120, "<b>Registered model</b> <code>layout-classifier</code><br>"
            "each version tagged with dataset_version + test_accuracy", CARD + DONE)
v1 = p.box(1165, 625, 145, 120, "<b>v1</b><br>test 0.662<br><i>rejected</i><br>below baseline", CARD + BAD)
v2 = p.box(1330, 625, 145, 120, "<b>v2</b><br>test 0.978<br>@candidate<br><b>@champion</b>", CARD + GOLD)
p.box(1165, 760, 310, 125, "<b>👤 Promotion = human gate</b><br>new versions get <b>@candidate</b> automatically;"
      "<br><b>@champion</b> is set by a person after reading the card", CARD + GOLD)
p.box(1165, 900, 310, 90, "backup before every manual change:<br><code>ml/mlflow/backups/</code>", CARD + NOTE)
p.edge(reg, v1, "", exitX=0.25, exitY=1, entryX=0.5, entryY=0)
p.edge(reg, v2, "", exitX=0.75, exitY=1, entryX=0.5, entryY=0)

# ⑤ serving (not built)
load = p.box(1535, 160, 310, 140, "<b>Load the champion</b><br><code>mlflow.pyfunc.load_model(<br>"
             "&nbsp;\"models:/layout-classifier@champion\")</code><br>= base model (Hugging Face) + adapter",
             CARD + NEXT)
p.box(1535, 315, 310, 150, "<b>Where it would plug in</b><br><code>ingestion/layout_router.py</code>, "
      "tier <b>slm</b><br>today that tier calls Ollama qwen2.5:1.5b through <code>llm_gateway</code> — "
      "<b>not this adapter</b>", CARD + NEXT)
p.box(1535, 480, 310, 175, "<b>Serving options</b><br>a) pyfunc inside the batch ingest job (CPU, slow)<br>"
      "b) merge adapter → GGUF → Ollama (CPU/T4)<br>c) vLLM with the LoRA on a T4/L4 (fast, always-on cost)",
      CARD + NEXT)
p.box(1535, 670, 310, 170, "<b>Gate before serving</b> (ADR-0012)<br>swap in only at <b>≥95% agreement with the "
      "frontier model</b> on held-out pages<br>v2 is measured against the <b>rule</b>, not the frontier — "
      "that eval is still to do", CARD + NEXT)
p.box(1535, 855, 310, 135, "<b>Why it is not served yet</b><br>the rule is 100% on its own labels, in "
      "microseconds, at $0 — a model earns its place only with frontier-made labels", CARD + NOTE)

p.edge(nifty, box, "launch · ssh · terminate", pts=[(380, 222), (380, 104), (760, 104), (760, 200)],
       exitX=1, exitY=0.35, entryX=0, entryY=0.3)
p.edge(ds, samp, "read", exitX=1, exitY=0.15, entryX=0, entryY=0.5)
p.edge(ql, silver, "", EDGE_NEXT, exitX=0, exitY=0.15, entryX=1, entryY=0.5)
p.edge(ev, db, "log run", pts=[(1135, 760), (1135, 235)], exitX=1, exitY=0.5, entryX=0, entryY=0.5)
p.edge(ev, art, "adapter + card", pts=[(1125, 800), (1125, 400)], exitX=1, exitY=0.8, entryX=0, entryY=0.5)
p.edge(v2, load, "@champion", EDGE_NEXT, pts=[(1500, 685), (1500, 230)], exitX=1, exitY=0.5, entryX=0, entryY=0.5)

# ============================================================ page 2: v1 vs v2
q = Page("2 v1 vs v2 champion", h=1100)
q.box(40, 14, 1200, 40, "v1 vs v2 (champion) — same data, same model, three changes", TITLE)
q.box(40, 54, 1300, 40, "Both runs: dataset 87060948b499 · Qwen2.5-1.5B-Instruct · QLoRA 4-bit, LoRA r=16 · "
      "1,000 steps · batch 8 · NVIDIA T4. Only the training recipe changed.", SUB)
q.legend(1040, 20, LEGEND)

q.box(40, 120, 560, 460, "<b style='font-size:16px'>v1 — rejected</b><hr>"
      "<b>learning rate</b> 1e-3 (fine for the 135M CPU kata, too high for 1.5B)<br><br>"
      "<b>batches</b> class-balanced: round-robin over the 5 labels, so every batch is ~equal parts "
      "text / mixed / figure / table / scanned (6 scanned pages repeated over and over)<br><br>"
      "<b>gradient clipping</b> none<br><br><b>checkpoint</b> the final weights, step 1000<br><br>"
      "<b>what happened</b> loss fell to 0.09 by step 700, <b>spiked to 2.07 at step 900</b>; the saved "
      "model came from just after the spike. Trained on a balanced world, it over-guessed rare labels on "
      "real pages, where 79% are text.", CARD + BAD)
q.box(640, 120, 560, 460, "<b style='font-size:16px'>v2 — champion</b><hr>"
      "<b>learning rate</b> 2e-4<br><br>"
      "<b>batches</b> shuffled over a <b>natural mix with text capped at 50%</b> (1,500 text · 891 mixed · "
      "241 figure · 16 table · 6 scanned): rare labels kept whole, the model still learns that most pages "
      "are text<br><br><b>gradient clipping</b> norm 1.0<br><br>"
      "<b>checkpoint</b> scored a 200-page val slice every 200 steps, kept the best: <b>step 400</b> "
      "(val slice 0.97 → 1.00 → 1.00 → 1.00 → 1.00)<br><br>"
      "<b>what happened</b> stable all the way, no spike. Test set used once, at the end.", CARD + GOLD)

# bar chart: test accuracy
cx, cy, ch, cw = 1260, 140, 380, 70
q.box(1240, 110, 600, 30, "<b>Test accuracy (600 pages, 41 unseen papers)</b>", "text;html=1;fontSize=13;" + FONT)
for i, (lbl, val, st) in enumerate([("base", 0.032, NOTE), ("v1", 0.662, BAD), ("v2", 0.978, GOLD)]):
    h = round(ch * val)
    x = cx + 40 + i * 150
    q.box(x, cy + ch - h + 20, cw, h, "", "rounded=0;html=1;" + st)
    q.box(x - 15, cy + ch - h - 2, cw + 30, 22, f"<b>{val:.3f}</b>", "text;html=1;align=center;fontSize=13;" + FONT)
    q.box(x - 15, cy + ch + 24, cw + 30, 22, lbl, "text;html=1;align=center;fontSize=13;" + FONT)
yb = cy + 20 + ch - round(ch * 0.787)
q.box(cx + 20, yb, 470, 2, "", "rounded=0;html=1;fillColor=#333333;strokeColor=none;")
q.box(cx + 20, yb - 24, 470, 22, "always answering 'text' = 0.787", "text;html=1;align=right;fontSize=11;fontColor=#333333;" + FONT)
q.box(cx + 20, cy + ch + 20, 470, 2, "", "rounded=0;html=1;fillColor=#999999;strokeColor=none;")

TH = "style='border:1px solid #bbb;padding:6px;background:#eeeeee;text-align:left'"
TD = "style='border:1px solid #bbb;padding:6px'"
rows = [("text", "472", "375 (79%)", "<b>472 (100%)</b>"), ("mixed", "104", "14 (13%)", "<b>92 (88%)</b>"),
        ("figure-heavy", "19", "6 (32%)", "<b>18 (95%)</b>"), ("table-heavy", "5", "2 (40%)", "<b>5 (100%)</b>"),
        ("scanned", "0", "—", "—"), ("<b>all</b>", "<b>600</b>", "<b>397 (0.662)</b>", "<b>587 (0.978)</b>")]
tbl = (f"<table style='border-collapse:collapse;font-size:13px;width:100%'><tr><th {TH}>Test, per label</th>"
       f"<th {TH}>pages</th><th {TH}>v1 correct</th><th {TH}>v2 correct</th></tr>")
for r in rows:
    tbl += "<tr>" + "".join(f"<td {TD}>{c}</td>" for c in r) + "</tr>"
tbl += "</table>"
q.box(40, 610, 760, 260, tbl, "text;html=1;whiteSpace=wrap;align=left;verticalAlign=top;overflow=fill;" + FONT)

q.box(840, 610, 1000, 260, "<b>How to read this honestly</b><br>"
      "• v2 copies the parser's rule at 97.8% on papers it never saw. It does <b>not</b> beat the rule: the rule "
      "is 100% on its own labels, in microseconds.<br>"
      "• <b>table-heavy</b> was tested on only 5 pages and <b>scanned</b> on 0 — no claim either way.<br>"
      "• <b>mixed</b> (88%) is the weak spot: it needs both a table and a figure signal.<br>"
      "• Quote 0.978 with its baseline (0.787) and the command that reproduces it: "
      "<code>bash deploy/ec2/layout_session.sh</code> on dataset 87060948b499.", CARD + NOTE)

q.box(40, 900, 1800, 160, "<b>Where each version lives</b><br>"
      "<b>v1</b> — MLflow run 83b7eeba… · artifacts <code>ml/mlflow/artifacts/models/m-5feda329…/</code> · "
      "tag status = rejected (below baseline)<br>"
      "<b>v2</b> — MLflow run 7e312cdc… · artifacts <code>ml/mlflow/artifacts/models/m-ae63ce79…/</code> · "
      "aliases <b>@candidate @champion</b> (promoted by hand, 1 Oct)<br>"
      "both read the same dataset <code>ml/datasets/layout/87060948b499/</code>", CARD + DATA)

# ============================================================ page 3: S3 layout
s = Page("3 S3 bucket layout", h=1050)
s.box(40, 14, 1200, 40, "S3 — what lives where, who writes it", TITLE)
s.box(40, 54, 1300, 40, "Bucket <b>yantra-research-lab-data</b> · ap-south-1 (Mumbai) · encrypted (AES256) · "
      "the only durable store besides GitHub. Sizes from <code>aws s3 ls</code>, 1 Oct 2026.", SUB)
s.legend(1040, 20, LEGEND)

bucket = s.box(40, 120, 380, 110, "<b style='font-size:15px'>🪣 yantra-research-lab-data</b><br>"
               "≈ 1.2 GB in total · ≈ $0.03/month", CARD + DATA)
corp = s.box(520, 120, 520, 120, "<b>yantra-corpus/</b> — owned by the <b>nightly ingest job</b><br>"
             "GitHub Actions, IAM user <b>yantra-ingest</b> (S3 only)<br>dev box: <b>read only</b>",
             CARD + NOTE)
ml = s.box(520, 520, 520, 120, "<b>ml/</b> — owned by the <b>dev box role</b> (yantra-dev-bedrock)<br>"
           "read + write, <b>no delete</b><br>everything the fine-tuning needs to survive a terminate",
           CARD + NOTE)
s.edge(bucket, corp, "", exitX=1, exitY=0.3, entryX=0, entryY=0.5)
s.edge(bucket, ml, "", pts=[(470, 200), (470, 580)], exitX=1, exitY=0.7, entryX=0, entryY=0.5)
items = [
    (corp, 120, "raw/", "426 PDFs · 807 MB", "bronze: the source of every dataset"),
    (corp, 225, "images/", "3,776 files · 262 MB", "embedded images (chatbot pipeline)"),
    (corp, 330, "figures/", "892 files · 52 MB", "captioned figures (chatbot pipeline)"),
    (ml, 520, "silver/layout_features/pymupdf-p20-tables-all/", "426 JSON · 2.8 MB",
     "parsed page features, one file per paper — the cache"),
    (ml, 625, "datasets/layout/87060948b499/", "train · val · test .jsonl + manifest · 2.8 MB",
     "versioned by content hash; test split is locked"),
    (ml, 730, "mlflow/mlflow.db", "SQLite · 1.4 MB", "runs, metrics, registry, aliases (pulled/pushed)"),
    (ml, 835, "mlflow/artifacts/models/", "v1 + v2 · 35 MB", "adapter, pyfunc code, MLmodel, card"),
    (ml, 940, "mlflow/backups/", "1 file", "copy taken before the manual promotion"),
]
for parent, y, path, size, what in items:
    st = DATA if parent == corp else DONE
    c = s.box(1120, y, 740, 90, f"<b><code>{path}</code></b><br>{size}<br><i>{what}</i>", CARD + st)
    s.edge(parent, c, "", exitX=1, exitY=0.5, entryX=0, entryY=0.5)
s.box(40, 300, 420, 200, "<b>Who can do what</b><br>"
      "<b>ingest job</b> writes yantra-corpus/<br><b>dev box role</b> reads yantra-corpus/, writes ml/, "
      "deletes nothing<br><b>launcher</b> (nifty_dev) has no S3 access at all<br>"
      "<b>admin</b> (temporary key) used for cleanup and the promotion backup", CARD + NOTE)
s.box(40, 680, 420, 200, "<b>Lineage of one model</b><br>raw PDF → silver features → dataset "
      "87060948b499 (manifest has every file's sha256) → MLflow run (tags dataset_version, git sha) → "
      "registered version → @champion<br>any number can be traced back to exact PDFs", CARD + GOLD)

# ============================================================ page 4: session lifecycle
f = Page("4 Session lifecycle", h=1050)
f.box(40, 14, 1200, 40, "One retraining session — the box is disposable", TITLE)
f.box(40, 54, 1400, 40, "Runbook: <code>deploy/ec2/SESSION_LIFECYCLE.md</code>. Times from a T4 on 1 Oct 2026. "
      "Only the inner loop costs money; S3 and GitHub carry everything to the next session.", SUB)
f.legend(1040, 20, LEGEND)
steps = [
    ("1 · Launch", "<code>launch.sh launch --yes</code><br>g6 → g5 → g4dn, zone 1a/1b<br>~2 min", DONE),
    ("2 · Bootstrap", "<code>bootstrap.sh</code><br>tools + venvs + 170 tests<br>~4 min", DONE),
    ("3 · Pull state", "<code>mlflow.db</code> from S3<br>seconds", DATA),
    ("4 · Dataset", "build from S3 bronze<br>cached: 10 s (first time 8 min)", DATA),
    ("5 · Train", "QLoRA, select best on val<br>~15 min", DONE),
    ("6 · Evaluate", "val + locked test, per label<br>~3 min", DONE),
    ("7 · Register", "new version @candidate<br>push mlflow.db to S3", DONE),
    ("8 · Review (human)", "read the card<br>promote → @champion?", GOLD),
    ("9 · Terminate", "copy the card, then<br><code>launch.sh terminate --yes</code>", BAD),
]
cxy = [(60, 180), (360, 180), (660, 180), (960, 180), (1260, 180), (1560, 180),
       (1560, 470), (1110, 470), (660, 470)]
ids = []
for (t, body, st), (x, y) in zip(steps, cxy):
    ids.append(f.box(x, y, 260, 150, f"<b style='font-size:14px'>{t}</b><hr>{body}", CARD + st))
for i in range(len(ids) - 1):
    a, b = ids[i], ids[i + 1]
    if i < 5:
        f.edge(a, b, "", exitX=1, exitY=0.5, entryX=0, entryY=0.5)
    elif i == 5:
        f.edge(a, b, "", exitX=0.5, exitY=1, entryX=0.5, entryY=0)
    else:
        f.edge(a, b, "", exitX=0, exitY=0.5, entryX=1, entryY=0.5)
nxt = f.box(60, 470, 400, 150, "<b style='font-size:14px'>Next session</b><hr>starts again at step 1 on a "
            "fresh box — nothing is lost", CARD + NOTE)
f.edge(ids[-1], nxt, "", EDGE_NEXT, exitX=0, exitY=0.5, entryX=1, entryY=0.5)
f.edge(nxt, ids[0], "", EDGE_NEXT, exitX=0.25, exitY=0, entryX=0.25, entryY=1)
f.box(60, 690, 820, 300, "<b>Survives the terminate</b><br>"
      "• GitHub: code, tests, runbook, the committed card<br>• S3 bronze: raw PDFs (ingest job)<br>"
      "• S3 ml/: page-feature cache, datasets, mlflow.db, adapters<br><br><b>Thrown away</b><br>"
      "• the box and its 100 GB disk: packages, Hugging Face model cache, logs<br><br>"
      "<b>Cost</b> one session on a T4 ≈ $0.30–0.70 · idle cost between sessions ≈ $0", CARD + DATA)
f.box(920, 690, 900, 300, "<b>Safety rails</b><br>• nothing bills until <code>launch --yes</code>; anything "
      "over $1 needs the owner's yes<br>• idle alarm stops a forgotten box after 60 min below 2% CPU<br>"
      "• <code>layout_session.sh</code> pushes mlflow.db even when a step fails<br>"
      "• a 20-step smoke run before every long run (two bugs caught that way on 1 Oct)<br>"
      "• the box role cannot delete anything in S3; promotion to @champion is a human step<br>"
      "• terminate only on the owner's words", CARD + NOTE)

root = ET.Element("mxfile", host="drawio", agent="Claude Code", version="24.0.0")
for pg in (p, q, s, f):
    pg.xml(root)
ET.indent(root)
ET.ElementTree(root).write(OUT, encoding="utf-8", xml_declaration=True)
print("wrote", OUT)
