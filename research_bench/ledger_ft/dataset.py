"""Build the training set: code-verified wins only, chat format, with a SHA-256 hash.

    python -m research_bench.ledger_ft.dataset          # -> .cache/ledger_ft/train.jsonl + manifest.json

Each record is one researcher turn exactly as the local model will see it at serving time:
system = the researcher prompt + the JSON-schema instruction (the gateway's prompt-mode suffix),
user = the ledger brief, assistant = the teacher's validated RoundProposal as compact JSON.

Rules (asserted, tested): every record's seed is a calibration seed; only studies with no
fallbacks, no errors and no cap cut are used; only proposals labelled "win" by code are kept.
The hash is over the exact bytes of train.jsonl; the trainer refuses a file whose hash differs.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

from research_bench.ledger_ft import label
from research_bench.ledger_ft.seeds import require_calibration, require_calibration_source

ROOT = Path(".cache") / "ledger_ft"


def system_prompt() -> str:
    from llm_gateway.base import schema_instruction
    from research_bench.agents import SYSTEM
    from research_bench.schemas import RoundProposal
    return SYSTEM["researcher"] + schema_instruction(RoundProposal)


def target(output: dict) -> str:
    return json.dumps(output, separators=(",", ":"), ensure_ascii=False)


def records_from(traces: list[dict], system: str) -> tuple[list[dict], dict]:
    recs, skipped = [], {"studies_with_fallbacks_or_errors": 0, "losses": 0}
    for t in traces:
        require_calibration(int(t["seed"]))
        require_calibration_source(t["source"])
        if t.get("agent_failures") or "error" in t or t.get("cut_by_cap"):
            skipped["studies_with_fallbacks_or_errors"] += 1
            continue
        labels = {r["round"]: r for r in label.label_trace(t)}
        for p in t["proposals"]:
            lab = labels[p["round"]]
            if lab["label"] != "win":
                skipped["losses"] += 1
                continue
            recs.append({"id": lab["id"], "seed": t["seed"], "kind": t["kind"], "round": p["round"],
                         "reason": lab["reason"], "teacher": p["model"],
                         "messages": [{"role": "system", "content": system},
                                      {"role": "user", "content": p["user"]},
                                      {"role": "assistant", "content": target(p["output"])}]})
    recs.sort(key=lambda r: (r["seed"], r["round"]))
    return recs, skipped


def to_bytes(recs: list[dict]) -> bytes:
    return "".join(json.dumps(r, sort_keys=True, ensure_ascii=False) + "\n" for r in recs).encode("utf-8")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def verify(path: str | Path, manifest: dict) -> list[dict]:
    """Recompute the hash and re-check every seed; returns the records or raises."""
    data = Path(path).read_bytes()
    if sha256(data) != manifest["sha256"]:
        raise ValueError(f"dataset hash mismatch: {sha256(data)} != manifest {manifest['sha256']}")
    recs = [json.loads(x) for x in data.decode("utf-8").splitlines() if x.strip()]
    for r in recs:
        require_calibration(int(r["seed"]))
    if len(recs) != manifest["records"]:
        raise ValueError("record count differs from the manifest")
    return recs


def build(traces: list[dict], out_dir: str | Path = ROOT) -> dict:
    out = Path(out_dir)
    recs, skipped = records_from(traces, system_prompt())
    data = to_bytes(recs)
    out.mkdir(parents=True, exist_ok=True)
    (out / "train.jsonl").write_bytes(data)
    reasons: dict[str, int] = {}
    for r in recs:
        reasons[r["reason"]] = reasons.get(r["reason"], 0) + 1
    seeds = sorted({r["seed"] for r in recs})
    manifest = {"file": "train.jsonl", "sha256": sha256(data), "records": len(recs),
                "label_rule": label.LABEL_RULE, "studies_read": len(traces), "skipped": skipped,
                "seeds": {"min": min(seeds, default=None), "max": max(seeds, default=None), "count": len(seeds),
                          "list": seeds},
                "kinds": {k: sum(r["kind"] == k for r in recs) for k in ("trend", "meanrev", "noise")},
                "reasons": reasons, "teacher_models": sorted({r["teacher"] for r in recs})}
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    return manifest


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    from research_bench.ledger_ft.teacher import load_traces
    m = build(load_traces(["pilot", "collect"]))
    print(json.dumps({k: v for k, v in m.items() if k != "seeds"} | {"seeds": {k: v for k, v in m["seeds"].items()
                                                                                if k != "list"}}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
