"""Generate yantra_dev_provisioning.drawio (3 pages) — uncompressed XML, opens in draw.io / VS Code."""
import re
import xml.etree.ElementTree as ET
from pathlib import Path

# draw.io renders <code> as dark text on a dark chip; use plain blue monospace instead.
CODE = re.compile(r"<code>(.*?)</code>", re.S)


def readable(value):
    return CODE.sub(r'<font face="Courier New" color="#0b5394">\1</font>', value)

OUT = str(Path(__file__).with_name("yantra_dev_provisioning.drawio"))

BOX = "rounded=1;whiteSpace=wrap;html=1;arcSize=6;align=left;verticalAlign=top;spacingLeft=10;spacingTop=6;spacingRight=8;fontSize=12;"
DONE = "fillColor=#d5e8d4;strokeColor=#82b366;"
PEND = "fillColor=#fff2cc;strokeColor=#d6b656;"
NEXT = "fillColor=#f5f5f5;strokeColor=#999999;dashed=1;fontColor=#333333;"
GONE = "fillColor=#f8cecc;strokeColor=#b85450;"
INFO = "fillColor=#dae8fc;strokeColor=#6c8ebf;"
NOTE = "fillColor=#ffffff;strokeColor=#bbbbbb;"
TITLE = "text;html=1;align=left;verticalAlign=middle;fontSize=24;fontStyle=1;"
SUB = "text;html=1;align=left;verticalAlign=top;fontSize=13;fontColor=#555555;whiteSpace=wrap;"
EDGE = "edgeStyle=orthogonalEdgeStyle;rounded=1;html=1;fontSize=11;labelBackgroundColor=#ffffff;endArrow=block;endFill=1;strokeWidth=1.5;"
EDGE_NEXT = EDGE + "dashed=1;strokeColor=#888888;fontColor=#555555;"
AWS_CLOUD = ("shape=mxgraph.aws4.group;grIcon=mxgraph.aws4.group_aws_cloud_alt;strokeColor=#232F3E;fillColor=none;"
             "verticalAlign=top;align=left;spacingLeft=30;fontColor=#232F3E;dashed=0;html=1;whiteSpace=wrap;fontSize=14;fontStyle=1;")
REGION = ("shape=mxgraph.aws4.group;grIcon=mxgraph.aws4.group_region;strokeColor=#00A4A6;fillColor=none;"
          "verticalAlign=top;align=left;spacingLeft=30;fontColor=#147EBA;dashed=1;html=1;whiteSpace=wrap;fontSize=14;fontStyle=1;")
VPC = ("shape=mxgraph.aws4.group;grIcon=mxgraph.aws4.group_vpc2;strokeColor=#8C4FFF;fillColor=none;"
       "verticalAlign=top;align=left;spacingLeft=30;fontColor=#AAB7B8;dashed=0;html=1;whiteSpace=wrap;fontSize=13;")
SG = ("rounded=0;html=1;whiteSpace=wrap;fillColor=none;strokeColor=#DD3522;dashed=1;verticalAlign=top;align=left;"
      "spacingLeft=10;fontColor=#DD3522;fontSize=12;")
IAMGRP = ("rounded=1;arcSize=2;html=1;whiteSpace=wrap;fillColor=#fdf3f4;strokeColor=#DD344C;verticalAlign=top;align=left;"
          "spacingLeft=10;spacingTop=6;fontColor=#B0084D;fontSize=14;fontStyle=1;")
GHGRP = ("rounded=1;arcSize=3;html=1;whiteSpace=wrap;fillColor=#f6f8fa;strokeColor=#24292e;verticalAlign=top;align=left;"
         "spacingLeft=10;spacingTop=6;fontColor=#24292e;fontSize=14;fontStyle=1;")
HEAD = "text;html=1;align=left;verticalAlign=middle;fontSize=12;fontStyle=1;fontColor=#B0084D;"


class Page:
    def __init__(self, name, w=1820, h=1180):
        self.name, self.w, self.h, self.cells, self.n = name, w, h, [], 0

    def _id(self):
        self.n += 1
        return f"p{self.name[0]}-{self.n}"

    def box(self, x, y, w, h, value, style=BOX + NOTE):
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

    def legend(self, x, y):
        self.box(x, y, 90, 26, "<b>Legend</b>", "text;html=1;align=left;verticalAlign=middle;fontSize=12;")
        for i, (label, st) in enumerate([("Done ✓", DONE), ("Waiting on AWS ⏳", PEND),
                                         ("Next — not created yet", NEXT), ("Removed / to delete", GONE),
                                         ("Existing, untouched", INFO)]):
            self.box(x + 80 + i * 175, y, 165, 26, label,
                     "rounded=1;whiteSpace=wrap;html=1;fontSize=11;align=center;verticalAlign=middle;" + st)

    def xml(self, parent):
        d = ET.SubElement(parent, "diagram", name=self.name, id=self.name.replace(" ", "_"))
        m = ET.SubElement(d, "mxGraphModel", dx="1400", dy="900", grid="1", gridSize="10", guides="1", tooltips="1",
                          connect="1", arrows="1", fold="1", page="1", pageScale="1", pageWidth=str(self.w),
                          pageHeight=str(self.h), math="0", shadow="0", background="#FFFFFF")
        r = ET.SubElement(m, "root")
        ET.SubElement(r, "mxCell", id="0")
        ET.SubElement(r, "mxCell", id="1", parent="0")
        for c in self.cells:
            r.append(c)


# ---------------------------------------------------------------- page 1: big picture
p1 = Page("1 Big picture")
p1.box(40, 10, 800, 40, "Yantra GPU dev box — how it is provisioned on AWS", TITLE)
p1.box(40, 48, 1000, 40, "State as of 1 Oct 2026, evening. Green = built and verified. The GPU box is now <b>disposable</b>: created per session, terminated at the end. Fine-tuning detail: <b>yantra_slm_finetuning.drawio</b>.", SUB)
p1.legend(860, 15)

mac = p1.box(40, 130, 330, 110, "<b>💻 Your Mac</b><br>VS Code + Remote-SSH<br>AWS console (your admin login)<br>"
             "<i>you created the temp admin key here</i>", BOX + INFO)

p1.box(40, 720, 330, 420, "GitHub · hemantsadhwani", GHGRP)
p1.box(60, 760, 290, 95, "<b>yantra-research-lab</b> (public)<br>deploy/ec2/launch.sh · setup_account.sh<br>"
       "bootstrap.sh · iam/*.json · HANDOVER.md", BOX + INFO)
p1.box(60, 865, 290, 50, "<b>agentic-reporting</b> (public, 2nd showcase)", BOX + INFO)
p1.box(60, 925, 290, 50, "<b>founder-profile</b> (career workspace)", BOX + INFO)
actions = p1.box(60, 985, 290, 135, "<b>Actions: ingest-corpus</b><br>daily 02:17 UTC<br>uses <b>yantra-ingest</b> key "
                 "(repo secret)<br>→ S3 yantra-research-lab-data<br><i>not part of the dev box</i>", BOX + INFO)

p1.box(400, 100, 1400, 1060, "AWS account", AWS_CLOUD)

# IAM (account-wide)
p1.box(420, 150, 420, 990, "IAM — account-wide (who can do what)", IAMGRP)
p1.box(440, 185, 200, 22, "Users (long-term keys)", HEAD)
p1.box(440, 212, 380, 45, "<b>hemant-window</b> · your Windows CLI user · untouched", BOX + INFO)
ingest = p1.box(440, 265, 380, 60, "<b>yantra-ingest</b> · S3-only · used by GitHub Actions<br>untouched — never reuse it for admin",
                BOX + INFO)
launcher = p1.box(440, 335, 380, 135,
                  "<b>claude-dev-launcher</b> ✓ created<br>policy <b>yantra-dev-launcher</b> (managed)<br>"
                  "can launch / stop / resize <u>only</u> boxes tagged<br>purpose=dev-public-repos, allowed types, Mumbai<br>"
                  "key → nifty_dev ~/.aws profile <b>yantra-launcher</b>", BOX + DONE)
admin = p1.box(440, 480, 380, 80, "<b>yantra-admin-temp</b> · AdministratorAccess<br>used 30 Sep (setup) + 1 Oct (S3 access);<br>"
               "a fresh key each time, deleted right after", BOX + GONE)
p1.box(440, 575, 200, 22, "Roles (no keys — temporary creds)", HEAD)
role = p1.box(440, 602, 380, 115, "<b>yantra-dev-bedrock</b> ✓ role + instance profile<br>trusted by: EC2<br>"
              "Bedrock: InvokeModel on anthropic.*<br>S3: read <b>yantra-corpus/*</b> · read+write <b>ml/*</b> · no delete<br>"
              "attached to the dev box",
              BOX + DONE)
p1.box(440, 727, 380, 60, "<b>AWSServiceRoleForCloudWatchEvents</b> ✓<br>lets the idle alarm stop the box", BOX + DONE)
p1.box(440, 805, 380, 110, "<b>Source of truth (in the repo)</b><br>deploy/ec2/iam/launcher-policy.json<br>"
       "deploy/ec2/iam/bedrock-dev-role-policy.json<br>deploy/ec2/setup_account.sh re-applies them", BOX + NOTE)
p1.box(440, 930, 380, 190, "<b>Why two identities?</b><br>• <b>Admin</b> used once, then its key deleted.<br>"
       "• <b>Launcher</b> (daily) can only touch tagged dev resources — it cannot see or stop the trading bot.<br>"
       "• <b>Role</b> gives the dev box Bedrock with no keys stored on it (auto-rotating creds from instance metadata).",
       BOX + NOTE)

# Region
p1.box(860, 150, 920, 990, "Region ap-south-1 (Mumbai)", REGION)
nifty = p1.box(880, 195, 420, 265,
               "<b>🖥 nifty_dev</b> — EC2 c7g.2xlarge (Graviton, 8 vCPU, 16 GB)<br>AZ 1c · Amazon Linux 2023<br>"
               "<i>Live trading monitor host · cron 08:15–15:15 IST</i><hr>"
               "~/index-options-trading-bot · data_pull · shadow_bt* — <b>never touched</b><br>"
               "~/work/ yantra-research-lab · agentic-reporting · founder-profile<br>"
               "~/.aws → profile <b>yantra-launcher</b> only<br>"
               "Job here: run setup_account.sh (once) and launch.sh.<br>No Docker · no GPU · no model downloads",
               BOX + INFO)
quota = p1.box(1320, 195, 440, 125, "<b>Service Quotas</b> ✓<br>Running On-Demand G and VT: 0 → <b>8 vCPU approved</b> (20:34)<br>All G and VT Spot: 0 → <b>8</b> (applied by 1 Oct)<br>g5.xlarge needs 4 · first launch hit a short capacity gap in Mumbai",
               BOX + DONE)
bedrock = p1.box(1320, 335, 440, 125, "<b>Amazon Bedrock</b> ✓ — Claude Haiku 4.5<br>in.anthropic.claude-haiku-4-5-20251001-v1:0<br>"
                 "global.anthropic.claude-haiku-4-5-20251001-v1:0<br>test call answered “ok” (18 tokens)<br>"
                 "role check from the box ✓ · ⚠ <b>not</b> apac.", BOX + DONE)

p1.box(880, 500, 880, 460, "Default VPC", VPC)
p1.box(900, 545, 520, 400, "Security group yantra-dev-ssh — inbound: port 22 from nifty_dev IP (+ home IP) only", SG.replace("verticalAlign=top", "verticalAlign=bottom"))
dev = p1.box(920, 590, 480, 315,
             "<b>🧠 yantra_dev</b> ✓ disposable — none running between sessions<br>g6.xlarge (L4) → g5.xlarge (A10G) → <b>g4dn.xlarge (T4)</b>, whichever Mumbai has; 1 Oct used g4dn · new IP each launch<br>"
             "AMI: Deep Learning Base OSS NVIDIA, Ubuntu 24.04<br>disk <b>100 GB</b> gp3 (AMI uses ~54) · tag purpose=dev-public-repos<br>"
             "instance profile <b>yantra-dev-bedrock</b> (no keys on box)<hr>"
             "bootstrap ✓ yantra 164 passed · agentic-reporting 70 passed<br>EVAL-GATE PASS (both arms) · REPORT-EVAL PASS · SCHEMA-EVAL PASS<br>"
             "then: Claude Code + gh auth login<br>AWS_REGION=ap-south-1<br>LLM_MODEL=in.anthropic.claude-haiku-4-5-…<br>"
             "≈ $1–1.4/h while running — <b>stop when idle</b>", BOX + DONE)
key = p1.box(1440, 590, 300, 70, "<b>Key pair yantra-dev</b> ✓<br>private key → nifty_dev ~/.ssh/yantra-dev.pem",
             BOX + DONE)
alarm = p1.box(1440, 680, 300, 80, "<b>CloudWatch alarm yantra-dev-idle-stop</b> ✓<br>CPU &lt; 2% for 60 min → stop the box",
               BOX + DONE)
p1.box(1440, 780, 300, 145, "<b>Session policy (1 Oct)</b><br>MLflow store + adapters live in S3, so each session ends with <code>launch.sh terminate --yes</code>.<br>Runbook: deploy/ec2/SESSION_LIFECYCLE.md", BOX + NOTE)
p1.box(900, 975, 400, 150, "<b>How the box gets AWS access (no keys)</b><br>"
       "1. Code calls Bedrock or S3 (boto3).<br>"
       "2. The SDK gets short-lived creds for role <b>yantra-dev-bedrock</b> from instance metadata.<br>"
       "3. IAM checks the role policy → allowed / denied.<br>"
       "4. Bedrock bills per token; S3 per GB.",
       BOX + NOTE)
s3 = p1.box(1320, 975, 440, 150, "<b>🪣 S3 yantra-research-lab-data</b> ✓ (AES256)<br>"
            "<b>yantra-corpus/</b> — owned by the nightly ingest job<br>"
            "&nbsp;&nbsp;raw/ <b>426 arXiv PDFs</b> (807 MB, since 5 Jul) · images/ · figures/<br>"
            "<b>ml/</b> — dev box writes here (empty yet)<br>"
            "&nbsp;&nbsp;datasets/ · mlflow/ · models/", BOX + DONE)

p1.edge(mac, nifty, "VS Code Remote-SSH", pts=[(385, 150), (385, 94), (1000, 94)],
        exitX=1, exitY=0.18, entryX=0.2857, entryY=0)
p1.edge(mac, admin, "console: temp admin key (now deleted)", EDGE + "strokeColor=#b85450;fontColor=#b85450;",
        pts=[(205, 520)], exitX=0.5, exitY=1, entryX=0, entryY=0.5)
p1.edge(nifty, launcher, "uses profile<br>yantra-launcher", exitX=0, exitY=0.62, entryX=1, entryY=0.18)
p1.edge(launcher, dev, "launch / stop / resize<br>(tag-scoped)", EDGE, pts=[(850, 440), (850, 820)],
        exitX=1, exitY=0.78, entryX=0, entryY=0.73)
p1.edge(role, dev, "attached", EDGE, exitX=1, exitY=0.4, entryX=0, entryY=0.18)
p1.edge(nifty, dev, "SSH · yantra-dev.pem", EDGE, exitX=0.45, exitY=1, entryX=0.31, entryY=0)
p1.edge(dev, bedrock, "InvokeModel<br>via instance role", EDGE, pts=[(1420, 610), (1420, 480), (1540, 480)],
        exitX=1, exitY=0.06, entryX=0.5, entryY=1)
p1.edge(alarm, dev, "stops", EDGE, exitX=0, exitY=0.5, entryX=1, entryY=0.4)
p1.edge(dev, s3, "read corpus · write ml/<br>via instance role", EDGE, pts=[(1352, 960)],
        exitX=0.9, exitY=1, entryX=0.07, entryY=0)
p1.edge(actions, ingest, "repo secret", pts=[(390, 1050), (390, 295)], exitX=1, exitY=0.48, entryX=0, entryY=0.5)

# ---------------------------------------------------------------- page 2: the steps
p2 = Page("2 What we did - steps", h=1100)
p2.box(40, 10, 800, 40, "What we did, step by step — and what comes next", TITLE)
p2.box(40, 48, 1100, 40, "Read left → right on the top row, then right → left on the bottom row. Steps 1–10 done on 30 Sep. On 1 Oct: S3 access for the box, two QLoRA sessions, and terminate-after-session.", SUB)
p2.legend(860, 15)

W, H, GAP, X0 = 260, 190, 50, 40
row1 = [
    ("1 · Tidy nifty_dev", "Home folder 30 → 15 GB (Cursor, stale data copy, old VS Code servers, caches).<br>"
     "Repos cloned into <b>~/work</b>. Dotfiles hidden in VS Code.", DONE),
    ("2 · Temp admin (you)", "Console: user <b>yantra-admin-temp</b> + AdministratorAccess → access key.<br>"
     "<code>aws configure --profile yantra-admin</code>", DONE),
    ("3 · setup_account.sh (me)", "Role + instance profile <b>yantra-dev-bedrock</b>, alarm service-linked role, user "
     "<b>claude-dev-launcher</b> + managed policy, key → profile <b>yantra-launcher</b>, GPU quota requests.", DONE),
    ("4 · Verify", "preflight as launcher ✓<br>dry-run RunInstances / CreateKeyPair / CreateSecurityGroup → "
     "“would have succeeded” ✓<br>Bedrock Haiku call → “ok” ✓", DONE),
    ("5 · Remove admin", "Admin access key deleted in AWS, profile removed from nifty_dev.<br>"
     "<b>You: delete user yantra-admin-temp in the console.</b>", GONE),
    ("6 · GPU quota ✓", "On-demand G/VT 0 → 8 approved after ~1.5 h (spot stayed 0).<br>Then the EC2 limit took ~20 min more to apply, and Mumbai had no g5 capacity for ~20 min.", DONE),
]
row2 = [
    ("7 · Plan (free)", "<code>launch.sh plan</code> prints type, AMI, subnet, disk, role, key pair, SSH IP, idle alarm. "
     "Nothing is created.", DONE),
    ("8 · Your gate", None, NEXT),
    ("9 · Launch (bills)", "<code>launch.sh launch --yes</code><br>key pair + SG (SSH from this IP) + g5.xlarge + "
     "idle-stop alarm. Launched with DISK_GB=100 (not 200) to halve disk cost.", DONE),
    ("10 · Bootstrap", "SSH once: git clone yantra → tmux runs <b>bootstrap.sh</b> → poll ~/bootstrap.log.<br>"
     "All PASS. First try died on the first-boot apt lock → bootstrap.sh now waits for it.", DONE),
    ("11 · Hand-off", "On the box: install Claude Code, <code>gh auth login</code> (fine-grained token, 2 repos). "
     "Set LLM_MODEL=in.anthropic… <b>(you, now)</b>", PEND),
    ("12 · Day to day", "<code>launch.sh stop</code> when idle · <code>start</code> (new IP) · "
     "<code>resize t4g.large --yes</code> after training · never terminate unless you say so.", NEXT),
]
ids1 = []
for i, (t, body, st) in enumerate(row1):
    ids1.append(p2.box(X0 + i * (W + GAP), 130, W, H, f"<b>{t}</b><hr>{body}", BOX + st))
ids2 = []
for i, (t, body, st) in enumerate(row2):
    x = X0 + (5 - i) * (W + GAP)
    if body is None:
        ids2.append(p2.box(x, 420, W, H, "<b>8 · You said<br>“yes launch” ✓</b><br><span style='font-size:11px'>"
                           "(+ approval rule: anything &gt; $1)</span>",
                           "rhombus;whiteSpace=wrap;html=1;fontSize=13;align=center;verticalAlign=middle;"
                           "fillColor=#d5e8d4;strokeColor=#82b366;"))
    else:
        ids2.append(p2.box(x, 420, W, H, f"<b>{t}</b><hr>{body}", BOX + st))
for a, b in zip(ids1, ids1[1:]):
    p2.edge(a, b, "", exitX=1, exitY=0.5, entryX=0, entryY=0.5)
p2.edge(ids1[-1], ids2[0], "quota approved", EDGE, exitX=0.5, exitY=1, entryX=0.5, entryY=0)
for a, b in zip(ids2, ids2[1:]):
    p2.edge(a, b, "", EDGE if b not in ids2[-2:] else EDGE_NEXT, exitX=0, exitY=0.5, entryX=1, entryY=0.5)
here = p2.box(405, 620, 150, 30, "📍 you are here",
              "rounded=1;html=1;fontSize=12;fontStyle=1;fillColor=#d6b656;fontColor=#ffffff;strokeColor=none;align=center;")

p2.box(40, 660, 1760, 30, "Five ideas worth remembering", "text;html=1;fontSize=16;fontStyle=1;align=left;")
ideas = [
    ("Least privilege", "Admin power was used <b>once</b> and its key deleted. The daily login can only act on resources "
     "tagged purpose=dev-public-repos — it cannot touch the trading bot."),
    ("No keys on servers", "The dev box gets Bedrock through an <b>instance role</b>. Credentials are short-lived and "
     "rotate automatically — nothing to leak from ~/.aws on the box."),
    ("Money gates", "Quota, plan and dry-runs are free. Only <b>launch</b>, <b>start</b> and <b>resize</b> bill. "
     "The idle alarm stops the box after 60 quiet minutes."),
    ("Keep the live host clean", "nifty_dev runs the market-hours monitor. It only launches the box — "
     "no Docker, GPU jobs or model downloads there."),
    ("Mumbai model IDs", "Use <b>in.</b> (India) or <b>global.</b> inference profiles. <b>us.</b> and <b>apac.</b> "
     "do not route from ap-south-1 here."),
]
for i, (t, body) in enumerate(ideas):
    p2.box(40 + i * 355, 700, 335, 150, f"<b>{t}</b><br>{body}", BOX + NOTE)

p2.box(40, 880, 1760, 180,
       "<b>Files involved</b><br>"
       "~/work/yantra-research-lab/deploy/ec2/<b>setup_account.sh</b> — one-time account setup (new, not committed yet)<br>"
       "~/work/yantra-research-lab/deploy/ec2/<b>launch.sh</b> — preflight · quota · plan · launch · status · ssh · stop · start · "
       "resize · terminate<br>"
       "~/work/yantra-research-lab/deploy/ec2/<b>bootstrap.sh</b> — runs on the dev box<br>"
       "~/work/yantra-research-lab/deploy/ec2/iam/<b>launcher-policy.json</b>, <b>bedrock-dev-role-policy.json</b>, <b>dev-box-s3-policy.json</b><br>"
       "~/.aws/credentials — profile <b>yantra-launcher</b> (only profile on nifty_dev) · ~/.ssh/yantra-dev.pem — created at launch",
       BOX + NOTE)

# ---------------------------------------------------------------- page 3: who can do what + commands
p3 = Page("3 Who can do what", h=1000)
p3.box(40, 10, 1200, 40, "Who can do what — and the commands you will use", TITLE)
TD = "style='border:1px solid #bbb;padding:6px;vertical-align:top'"
TH = "style='border:1px solid #bbb;padding:6px;background:#eeeeee;text-align:left'"
rows = [
    ("yantra-admin-temp", "#f8cecc", "none — key deleted", "everything (AdministratorAccess)",
     "Used once for setup_account.sh. Delete the user in the console."),
    ("claude-dev-launcher", "#d5e8d4", "nifty_dev ~/.aws profile yantra-launcher",
     "describe EC2 · launch g5/g6/g4dn/t4g/c7g/m7i with tag purpose=dev-public-repos · start/stop/resize/terminate "
     "tagged boxes · create key pair + SG · pass role yantra-dev-bedrock · request GPU quota · idle alarm yantra-dev-*",
     "IAM changes · untagged resources (the trading bot) · other regions · Bedrock · S3"),
    ("yantra-dev-bedrock (role)", "#d5e8d4", "none stored — instance metadata, auto-rotating",
     "bedrock:InvokeModel(+stream) on anthropic.* models and *.anthropic.* profiles · list models/profiles · S3 read yantra-corpus/* · S3 read+write ml/* (policy dev-box-s3-policy.json)",
     "EC2 · IAM · writing yantra-corpus/ · deleting anything in S3 · other buckets · non-Anthropic models"),
    ("yantra-ingest", "#dae8fc", "GitHub Actions secret", "S3 corpus bucket (unchanged)", "everything else"),
    ("hemant-window", "#dae8fc", "your Windows machine", "unchanged", "—"),
]
html = (f"<table style='border-collapse:collapse;font-size:12px;width:100%'><tr><th {TH}>Identity</th>"
        f"<th {TH}>Where its credentials live</th><th {TH}>Can do</th><th {TH}>Cannot / notes</th></tr>")
for name, col, where, can, cannot in rows:
    html += (f"<tr><td {TD[:-1]};background:{col}'><b>{name}</b></td><td {TD}>{where}</td>"
             f"<td {TD}>{can}</td><td {TD}>{cannot}</td></tr>")
html += "</table>"
p3.box(40, 70, 1740, 360, html, "text;html=1;whiteSpace=wrap;align=left;verticalAlign=top;overflow=fill;")

CMD = ("<table style='border-collapse:collapse;font-size:12px;width:100%'><tr><th {th}>Command (from ~/work/yantra-research-lab)</th>"
       "<th {th}>What it does</th><th {th}>Cost</th></tr>").format(th=TH)
cmds = [
    ("bash deploy/ec2/launch.sh preflight", "who am I, GPU quota, AZs, role, AMI, existing box", "free"),
    ("bash deploy/ec2/launch.sh plan", "print exactly what launch would create", "free"),
    ("bash deploy/ec2/launch.sh launch --yes", "key pair + SG + g5.xlarge + idle alarm", "💰 bills (~$1/h)"),
    ("bash deploy/ec2/launch.sh status", "instance id, type, state, public IP", "free"),
    ("bash deploy/ec2/launch.sh ssh", "log in as ubuntu", "—"),
    ("bash deploy/ec2/launch.sh stop", "stop the box (disk kept, ~$9/month for 100 GB)", "stops GPU billing"),
    ("bash deploy/ec2/launch.sh start", "start again — public IP changes", "💰 bills"),
    ("bash deploy/ec2/launch.sh resize t4g.large --yes", "switch to a cheap CPU type after training", "💰 bills (cheaper)"),
    ("bash deploy/ec2/launch.sh terminate --yes", "delete box and disk — only if you say so", "irreversible"),
    ("bash deploy/ec2/setup_account.sh", "re-apply IAM + quota (needs a temp admin profile)", "free"),
]
for c, what, cost in cmds:
    bg = "#fff2cc" if "💰" in cost else ("#f8cecc" if cost == "irreversible" else "#ffffff")
    CMD += (f"<tr><td {TD}><code>{c}</code></td><td {TD}>{what}</td>"
            f"<td {TD[:-1]};background:{bg}'>{cost}</td></tr>")
CMD += "</table>"
p3.box(40, 460, 1740, 420, CMD, "text;html=1;whiteSpace=wrap;align=left;verticalAlign=top;overflow=fill;")

root = ET.Element("mxfile", host="drawio", agent="Claude Code", version="24.0.0")
for p in (p1, p2, p3):
    p.xml(root)
ET.indent(root)
ET.ElementTree(root).write(OUT, encoding="utf-8", xml_declaration=True)
print("wrote", OUT)
