"""QLoRA-train the researcher on the code-verified wins, on the local GPU. No cloud GPU.

    python -m research_bench.ledger_ft.train_qlora --base Qwen/Qwen2.5-3B-Instruct --tag a1
    -> .cache/ledger_ft/adapters/a1/  (LoRA adapter + training_meta.json)

The dataset's SHA-256 is re-verified against the manifest before training and written into
training_meta.json; ``evaluate`` re-verifies it again before any eval. Every training seed is
re-checked to be a calibration seed. The base is loaded in 4-bit NF4 (double quant, bf16 compute);
LoRA r=16 on every attention and MLP projection; loss on the assistant turn only. A validation
split is held out by seed (no study is in both), and its loss is reported per epoch.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import sys
import time
from pathlib import Path

from research_bench.ledger_ft import dataset

ROOT = Path(".cache") / "ledger_ft"
TARGETS = ["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"]


def encode(tok, rec: dict, max_len: int) -> dict | None:
    msgs = rec["messages"]
    prompt = tok.apply_chat_template(msgs[:2], tokenize=False, add_generation_prompt=True)
    full = tok.apply_chat_template(msgs, tokenize=False)
    if not full.startswith(prompt):
        raise ValueError("chat template: the full conversation does not start with the prompt")
    p_ids = tok(prompt, add_special_tokens=False)["input_ids"]
    f_ids = tok(full, add_special_tokens=False)["input_ids"]
    if f_ids[:len(p_ids)] != p_ids:
        raise ValueError("tokenisation of the prompt is not a prefix of the full conversation")
    if len(f_ids) > max_len:
        return None
    return {"input_ids": f_ids, "labels": [-100] * len(p_ids) + f_ids[len(p_ids):], "seed": rec["seed"]}


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="Qwen/Qwen2.5-3B-Instruct")
    ap.add_argument("--tag", required=True)
    ap.add_argument("--epochs", type=int, default=3)
    ap.add_argument("--lr", type=float, default=2e-4)
    ap.add_argument("--r", type=int, default=16)
    ap.add_argument("--alpha", type=int, default=32)
    ap.add_argument("--accum", type=int, default=8, help="examples per optimizer step")
    ap.add_argument("--max-len", type=int, default=6144)
    ap.add_argument("--val-frac", type=float, default=0.1)
    ap.add_argument("--data-dir", default=str(ROOT), help="folder with manifest.json + train.jsonl")
    ap.add_argument("--max-records", type=int, default=None, help="dry runs only")
    a = ap.parse_args(argv)

    data_dir = Path(a.data_dir)
    manifest_path = data_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    recs = dataset.verify(data_dir / manifest["file"], manifest)      # hash + calibration seeds
    if a.max_records:
        recs = recs[:a.max_records]

    import peft
    import torch
    import transformers
    from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

    torch.manual_seed(0)
    tok = AutoTokenizer.from_pretrained(a.base)
    enc = [encode(tok, r, a.max_len) for r in recs]
    too_long = sum(e is None for e in enc)
    enc = [e for e in enc if e is not None]
    seeds = sorted({e["seed"] for e in enc})
    rng = random.Random(0)
    val_seeds = set(rng.sample(seeds, max(1, int(len(seeds) * a.val_frac)))) if len(seeds) > 5 else set()
    train = [e for e in enc if e["seed"] not in val_seeds]
    val = [e for e in enc if e["seed"] in val_seeds]
    lens = sorted(len(e["input_ids"]) for e in enc)
    print(f"records {len(recs)} -> train {len(train)}, val {len(val)} (by seed), too long {too_long}; "
          f"tokens median {lens[len(lens) // 2]}, max {lens[-1]}", flush=True)

    bnb = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4", bnb_4bit_use_double_quant=True,
                             bnb_4bit_compute_dtype=torch.bfloat16)
    model = AutoModelForCausalLM.from_pretrained(a.base, quantization_config=bnb, device_map="cuda",
                                                 dtype=torch.bfloat16)
    model = prepare_model_for_kbit_training(model, use_gradient_checkpointing=True)
    model = get_peft_model(model, LoraConfig(r=a.r, lora_alpha=a.alpha, lora_dropout=0.05,
                                             target_modules=TARGETS, task_type="CAUSAL_LM"))
    trainable = sum(p.numel() for p in model.parameters() if p.requires_grad)
    total = sum(p.numel() for p in model.parameters())
    opt = torch.optim.AdamW([p for p in model.parameters() if p.requires_grad], lr=a.lr, weight_decay=0.0)
    steps_total = math.ceil(len(train) / a.accum) * a.epochs
    warm = max(1, int(0.05 * steps_total))
    sched = torch.optim.lr_scheduler.LambdaLR(
        opt, lambda s: (s + 1) / warm if s < warm else 0.5 * (1 + math.cos(math.pi * (s - warm) / max(1, steps_total - warm))))

    def loss_of(e: dict) -> torch.Tensor:
        """Cross-entropy on the assistant tokens only. They sit at the end of the sequence, so
        only their logits are computed (``logits_to_keep``): a full-vocab logit tensor over a
        3k-token prompt would be ~2 GiB in fp32 for no training signal."""
        ids = torch.tensor([e["input_ids"]], device="cuda")
        p = sum(1 for x in e["labels"] if x == -100)          # prompt length (prefix)
        k = len(e["input_ids"]) - p + 1                       # logits at positions p-1 .. L-1
        with torch.autocast("cuda", dtype=torch.bfloat16):
            logits = model(input_ids=ids, logits_to_keep=k).logits[:, :-1].float()
        return torch.nn.functional.cross_entropy(logits.reshape(-1, logits.shape[-1]), ids[0, p:])

    def val_loss() -> float | None:
        if not val:
            return None
        model.eval()
        with torch.no_grad():
            out = sum(float(loss_of(e)) for e in val) / len(val)
        model.train()
        return round(out, 4)

    torch.cuda.reset_peak_memory_stats()
    t0, step, curve, vals = time.perf_counter(), 0, [], [{"epoch": 0, "val_loss": val_loss()}]
    print(f"trainable {trainable:,} of {total:,} params; {steps_total} optimizer steps; val loss before "
          f"{vals[0]['val_loss']}", flush=True)
    model.train()
    for ep in range(1, a.epochs + 1):
        order = list(range(len(train)))
        rng.shuffle(order)
        run, n = 0.0, 0
        for i, j in enumerate(order, 1):
            loss = loss_of(train[j]) / a.accum
            loss.backward()
            run += float(loss) * a.accum
            n += 1
            if i % a.accum == 0 or i == len(order):
                torch.nn.utils.clip_grad_norm_([p for p in model.parameters() if p.requires_grad], 1.0)
                opt.step()
                sched.step()
                opt.zero_grad(set_to_none=True)
                step += 1
                curve.append({"step": step, "loss": round(run / n, 4)})
                if step % 5 == 0 or step == steps_total:
                    print(f"  epoch {ep} step {step}/{steps_total} loss {run / n:.4f} "
                          f"{time.perf_counter() - t0:.0f}s peak {torch.cuda.max_memory_allocated() / 2**30:.2f} GiB",
                          flush=True)
                run, n = 0.0, 0
        vals.append({"epoch": ep, "val_loss": val_loss()})
        print(f"epoch {ep} val loss {vals[-1]['val_loss']}", flush=True)

    secs = time.perf_counter() - t0
    out = ROOT / "adapters" / a.tag
    model.save_pretrained(out)
    meta = {"base": a.base, "tag": a.tag, "dataset": str(data_dir / manifest["file"]), "manifest": str(manifest_path),
            "dataset_sha256": manifest["sha256"], "records": len(recs), "train_examples": len(train),
            "val_examples": len(val), "val_seeds": sorted(val_seeds), "too_long_skipped": too_long,
            "train_seed_range": [min(seeds), max(seeds)], "epochs": a.epochs, "steps": step,
            "examples_per_step": a.accum, "lr": a.lr, "lora_r": a.r, "lora_alpha": a.alpha, "lora_dropout": 0.05,
            "target_modules": TARGETS, "quant": "4-bit NF4, double quant, bf16 compute",
            "trainable_params": trainable, "total_params": total, "max_len": a.max_len,
            "token_lengths": {"median": lens[len(lens) // 2], "max": lens[-1]},
            "seconds": round(secs, 1), "peak_vram_allocated_gib": round(torch.cuda.max_memory_allocated() / 2**30, 2),
            "peak_vram_reserved_gib": round(torch.cuda.max_memory_reserved() / 2**30, 2),
            "gpu": torch.cuda.get_device_name(0), "loss_curve": curve, "val_loss": vals,
            "versions": {"torch": torch.__version__, "transformers": transformers.__version__,
                         "peft": peft.__version__}}
    (out / "training_meta.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
    print(f"saved {out} in {secs / 60:.1f} min; peak {meta['peak_vram_allocated_gib']} GiB allocated")
    return 0


if __name__ == "__main__":
    sys.exit(main())
