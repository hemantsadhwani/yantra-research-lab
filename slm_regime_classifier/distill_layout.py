"""LoRA-distil the layout teacher into a 135M-parameter model, on CPU, small and measured.

    python slm_regime_classifier/distill_layout.py                  # SmolLM2-135M-Instruct, LoRA, CPU
    python slm_regime_classifier/distill_layout.py --steps 150      # fewer steps
    python slm_regime_classifier/distill_layout.py --model Qwen/Qwen2.5-0.5B-Instruct
    python slm_regime_classifier/distill_layout.py --qlora          # GPU only (4-bit needs CUDA); not run here

Task: read the one-line feature string (``layout_labels.feature_string``) and emit one of the
five layout labels. Labels are the free teacher labels from ``layout_labels.derive_label``.
Examples: the locally cached silver pages (if any) plus deterministic synthetic pages,
shuffled with a fixed seed; the first 60 are held out, the next <= 300 are the training set.

Bounds: at most 300 training examples, at most 300 optimizer steps, and a hard 25-minute
training cap. If the cap is hit, training stops and the run reports ``capped: true``.

Evaluation: the base model and the tuned model answer the same 60 held-out examples with greedy
decoding (6 new tokens max); the first label found in the reply is the prediction, anything
else counts as wrong. Reports accuracy and p50 latency per example.

Output: the adapter under ``slm_regime_classifier/adapters/<name>/`` (git-ignored), a JSON
summary on stdout, and ``slm_regime_classifier/adapter_card.md`` (committed) with the numbers.

Dependencies: the ``slm`` extra (torch, transformers, peft, datasets). PyTorch publishes no
wheels for Intel macOS on Python 3.13, so on the dev Mac this runs from a Python 3.12 venv with
torch 2.2.2, transformers 4.46.3 and peft 0.13.2 (see ``results/distill_2026-09-30.md``).
"""

from __future__ import annotations

import argparse
import json
import os
import random
import statistics
import sys
import time
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(REPO))

DEFAULT_MODEL = "HuggingFaceTB/SmolLM2-135M-Instruct"
ADAPTERS = HERE / "adapters"
CARD = HERE / "adapter_card.md"
MAX_TRAIN, N_TEST, MAX_STEPS, CAP_MINUTES = 300, 60, 300, 25.0
LABEL_ORDER = ("table-heavy", "figure-heavy", "scanned", "mixed", "text")  # search order
SYSTEM = ("Classify the layout of one PDF page from its parser features. Answer with exactly "
          "one label: text, table-heavy, figure-heavy, scanned, mixed.")


def build_examples(seed: int = 0, n_test: int = N_TEST, max_train: int = MAX_TRAIN):
    """``(train, test)`` lists of ``{"features", "label", "source"}``. Deterministic."""
    from ingestion import config
    from ingestion.layout_labels import derive_label, feature_string, page_features, synthetic_pages
    from ingestion.state import ParsedDoc

    pages = []
    for p in sorted(config.SILVER_DIR.glob("*.json")):
        doc = ParsedDoc.model_validate_json(p.read_text(encoding="utf-8"))
        pages.extend(("silver", f) for f in page_features(doc))
    pages.extend(("synthetic", f) for f in synthetic_pages(400, seed=2027))
    rng = random.Random(seed)
    rng.shuffle(pages)
    ex = [{"features": feature_string(f), "label": derive_label(f), "source": src}
          for src, f in pages]
    return ex[n_test:n_test + max_train], ex[:n_test]


def parse_label(reply: str) -> str:
    low = reply.lower()
    for lbl in LABEL_ORDER:
        if lbl in low:
            return lbl
    return "invalid"


def _prompt(tok, features: str) -> list[int]:
    msgs = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": features}]
    return tok.apply_chat_template(msgs, add_generation_prompt=True, tokenize=True)


def evaluate(model, tok, test: list[dict]) -> dict:
    import torch

    model.eval()
    preds, lat = [], []
    with torch.no_grad():
        for ex in test:
            ids = torch.tensor([_prompt(tok, ex["features"])])
            t0 = time.perf_counter()
            out = model.generate(input_ids=ids, attention_mask=torch.ones_like(ids),
                                 max_new_tokens=6, do_sample=False,
                                 pad_token_id=tok.pad_token_id or tok.eos_token_id)
            lat.append((time.perf_counter() - t0) * 1000)
            preds.append(parse_label(tok.decode(out[0, ids.shape[1]:], skip_special_tokens=True)))
    correct = sum(p == ex["label"] for p, ex in zip(preds, test, strict=True))
    return {"accuracy": correct / len(test), "correct": correct, "n": len(test),
            "invalid": preds.count("invalid"), "p50_ms": statistics.median(lat),
            "pred_counts": dict(sorted(Counter(preds).items()))}


def _encode(tok, ex: dict) -> dict:
    prompt = _prompt(tok, ex["features"])
    answer = tok(ex["label"], add_special_tokens=False)["input_ids"] + [tok.eos_token_id]
    return {"input_ids": prompt + answer, "labels": [-100] * len(prompt) + answer}


def _epoch_order(labels: list[str], rng: random.Random, balanced: bool) -> list[int]:
    """One pass over the indices: shuffled, or round-robin across labels (class-balanced)."""
    if not balanced:
        return rng.sample(range(len(labels)), len(labels))
    groups: dict[str, list[int]] = {}
    for i, lbl in enumerate(labels):
        groups.setdefault(lbl, []).append(i)
    pools = {k: rng.sample(v, len(v)) for k, v in sorted(groups.items())}
    out: list[int] = []
    while len(out) < len(labels):
        for k, pool in pools.items():
            if not pool:
                pool.extend(rng.sample(groups[k], len(groups[k])))   # minority classes repeat
            out.append(pool.pop())
    return out[:len(labels)]


def train(model, tok, train_set: list[dict], steps: int, batch: int, lr: float,
          cap_s: float, balanced: bool = False) -> dict:
    import torch
    from datasets import Dataset

    ds = Dataset.from_list(train_set).map(lambda ex: _encode(tok, ex),
                                          remove_columns=["features", "label", "source"])
    rows = list(ds)
    opt = torch.optim.AdamW([p for p in model.parameters() if p.requires_grad], lr=lr)
    rng = random.Random(1)
    pad = tok.pad_token_id if tok.pad_token_id is not None else tok.eos_token_id
    model.train()
    losses, t0, done, capped = [], time.monotonic(), 0, False
    order: list[int] = []
    for step in range(steps):
        if time.monotonic() - t0 > cap_s:
            capped = True
            break
        if len(order) < batch:
            order += _epoch_order([e["label"] for e in train_set], rng, balanced)
        idx, order = order[:batch], order[batch:]
        width = max(len(rows[i]["input_ids"]) for i in idx)
        ids = torch.tensor([rows[i]["input_ids"] + [pad] * (width - len(rows[i]["input_ids"]))
                            for i in idx])
        lab = torch.tensor([rows[i]["labels"] + [-100] * (width - len(rows[i]["labels"]))
                            for i in idx])
        att = torch.tensor([[1] * len(rows[i]["input_ids"]) + [0] * (width - len(rows[i]["input_ids"]))
                            for i in idx])
        loss = model(input_ids=ids, attention_mask=att, labels=lab).loss
        loss.backward()
        opt.step()
        opt.zero_grad()
        losses.append(float(loss))
        done = step + 1
        if done % 25 == 0:
            print(f"  step {done:>3}  loss {statistics.mean(losses[-25:]):.4f}  "
                  f"{time.monotonic() - t0:.0f}s", flush=True)
    return {"steps": done, "capped": capped, "train_s": round(time.monotonic() - t0, 1),
            "first_loss": round(losses[0], 4) if losses else None,
            "last_loss": round(statistics.mean(losses[-25:]), 4) if losses else None}


def write_card(s: dict) -> None:
    b, t = s["base"], s["tuned"]
    CARD.write_text(f"""# Layout-label LoRA adapter card

Written by `python slm_regime_classifier/distill_layout.py` on {s['date']}. The adapter itself
lives under `slm_regime_classifier/adapters/{s['adapter_name']}/` and is git-ignored.

| | |
|---|---|
| base model | `{s['model']}` |
| method | LoRA (r={s['lora_r']}, alpha={s['lora_alpha']}, dropout 0.05, targets {', '.join(s['targets'])}), CPU, fp32 |
| trainable params | {s['trainable_params']:,} of {s['total_params']:,} |
| data | {s['n_train']} training examples, {s['n_test']} held out; teacher = `layout_labels.derive_label` (free labels from the parser) |
| training | {s['train']['steps']} steps, batch {s['batch']}, lr {s['lr']}, {'class-balanced batches' if s['balanced'] else 'shuffled batches'}, {s['train']['train_s']} s{' (hit the 25-minute cap)' if s['train']['capped'] else ''} |
| training labels | {s['train_labels']} |
| loss | {s['train']['first_loss']} at step 1 to {s['train']['last_loss']} (mean of the last 25 steps) |
| machine | {s['machine']} |

## Held-out result ({s['n_test']} examples, greedy, 6 new tokens)

| model | accuracy | invalid replies | p50 latency per example | predictions |
|---|---:|---:|---:|---|
| base | {b['accuracy']:.2f} ({b['correct']}/{b['n']}) | {b['invalid']} | {b['p50_ms']:.0f} ms | {b['pred_counts']} |
| LoRA-tuned | {t['accuracy']:.2f} ({t['correct']}/{t['n']}) | {t['invalid']} | {t['p50_ms']:.0f} ms | {t['pred_counts']} |

Held-out labels: {s['test_labels']} (always answering the most common label scores
{s['majority']:.2f}). Held-out sources: {s['test_sources']}.

What this shows: a 135M model can learn most of a deterministic five-way rule from a one-line
feature string on a laptop CPU. What it does not show: that it beats the rules backend (it is
distilled *from* those labels and cannot exceed them), or anything about real layout
understanding from pixels. QLoRA (4-bit) needs CUDA and was not run.
""", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python slm_regime_classifier/distill_layout.py")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--steps", type=int, default=MAX_STEPS)
    ap.add_argument("--batch", type=int, default=8)
    ap.add_argument("--lr", type=float, default=1e-3)
    ap.add_argument("--lora-r", type=int, default=16)
    ap.add_argument("--cap-minutes", type=float, default=CAP_MINUTES)
    ap.add_argument("--qlora", action="store_true",
                    help="4-bit QLoRA via bitsandbytes: GPU only (CUDA); not run here")
    ap.add_argument("--balanced", action="store_true",
                    help="class-balanced batches (round-robin over labels; same 300 examples)")
    ap.add_argument("--no-card", action="store_true", help="do not rewrite adapter_card.md")
    args = ap.parse_args(argv)
    steps = min(args.steps, MAX_STEPS)
    cap_s = min(args.cap_minutes, CAP_MINUTES) * 60

    import torch
    from peft import LoraConfig, get_peft_model
    from transformers import AutoModelForCausalLM, AutoTokenizer

    if args.qlora and not torch.cuda.is_available():
        raise SystemExit("--qlora is GPU only: bitsandbytes 4-bit quantization needs CUDA. "
                         "Not run on this machine; drop --qlora for CPU LoRA.")
    torch.manual_seed(0)
    torch.set_num_threads(os.cpu_count() or 2)
    train_set, test = build_examples()
    tok = AutoTokenizer.from_pretrained(args.model)
    if args.qlora:  # pragma: no cover - needs CUDA
        from peft import prepare_model_for_kbit_training
        from transformers import BitsAndBytesConfig

        bnb = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4",
                                 bnb_4bit_compute_dtype=torch.bfloat16)
        model = prepare_model_for_kbit_training(
            AutoModelForCausalLM.from_pretrained(args.model, quantization_config=bnb))
    else:
        model = AutoModelForCausalLM.from_pretrained(args.model, torch_dtype=torch.float32)

    print(f"model {args.model} · train {len(train_set)} · test {len(test)}", flush=True)
    base = evaluate(model, tok, test)
    print(f"base   accuracy {base['accuracy']:.2f}  p50 {base['p50_ms']:.0f} ms", flush=True)

    targets = ["q_proj", "k_proj", "v_proj", "o_proj"]
    cfg = LoraConfig(r=args.lora_r, lora_alpha=2 * args.lora_r, lora_dropout=0.05,
                     target_modules=targets, task_type="CAUSAL_LM")
    model = get_peft_model(model, cfg)
    trainable = sum(p.numel() for p in model.parameters() if p.requires_grad)
    total = sum(p.numel() for p in model.parameters())
    tr = train(model, tok, train_set, steps, args.batch, args.lr, cap_s, args.balanced)
    if tr["capped"]:
        print(f"STOPPED: hit the {cap_s / 60:.0f}-minute training cap at step {tr['steps']}")
    tuned = evaluate(model, tok, test)
    print(f"tuned  accuracy {tuned['accuracy']:.2f}  p50 {tuned['p50_ms']:.0f} ms", flush=True)

    name = "layout-" + args.model.split("/")[-1].lower()
    ADAPTERS.mkdir(parents=True, exist_ok=True)
    model.save_pretrained(str(ADAPTERS / name))

    import platform

    summary = {
        "date": time.strftime("%Y-%m-%d"), "model": args.model, "adapter_name": name,
        "lora_r": args.lora_r, "lora_alpha": 2 * args.lora_r, "targets": targets,
        "trainable_params": trainable, "total_params": total, "n_train": len(train_set),
        "n_test": len(test), "batch": args.batch, "lr": args.lr, "balanced": args.balanced,
        "train": tr, "train_labels": dict(sorted(Counter(e["label"] for e in train_set).items())),
        "base": base, "tuned": tuned,
        "test_labels": dict(sorted(Counter(e["label"] for e in test).items())),
        "majority": max(Counter(e["label"] for e in test).values()) / len(test),
        "test_sources": dict(sorted(Counter(e["source"] for e in test).items())),
        "machine": f"{platform.machine()} CPU, {os.cpu_count()} logical cores, "
                   f"torch {torch.__version__}, Python {platform.python_version()}",
    }
    print(json.dumps(summary, indent=2))
    if not args.no_card:
        write_card(summary)
        print(f"wrote {CARD}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
