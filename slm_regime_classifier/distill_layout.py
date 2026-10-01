"""LoRA-distil the layout teacher into a 135M-parameter model, on CPU, small and measured.

    python slm_regime_classifier/distill_layout.py                  # SmolLM2-135M-Instruct, LoRA, CPU
    python slm_regime_classifier/distill_layout.py --steps 150      # fewer steps
    python slm_regime_classifier/distill_layout.py --model Qwen/Qwen2.5-0.5B-Instruct
    python slm_regime_classifier/distill_layout.py --qlora          # GPU only (4-bit needs CUDA); not run here

    # Dataset mode (GPU dev box): real arXiv pages from build_layout_dataset.py, split by paper
    python slm_regime_classifier/distill_layout.py --dataset slm_regime_classifier/datasets/<version> \
        --model Qwen/Qwen2.5-1.5B-Instruct --qlora --balanced --register layout-classifier

Dataset mode reads ``train/val/test.jsonl`` from a dataset built by ``build_layout_dataset.py``,
samples a label-balanced training set (``--max-train``, all of each rare label kept), and scores
base and tuned models on ``val`` and on the locked ``test`` split with per-label accuracy. It
writes ``adapter_card_dataset.md`` (the CPU kata's ``adapter_card.md`` is left alone). With
``MLFLOW_TRACKING_URI`` set it logs the run (params, metrics, card, dataset manifest) and the
adapter as an MLflow pyfunc model; ``--register NAME`` adds a model version and points the
``candidate`` alias at it. Promoting a version to ``champion`` stays a human step.

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
# Dataset mode runs on the GPU box, so its ceilings are higher but still hard.
DS_MAX_TRAIN, DS_MAX_STEPS, DS_CAP_MINUTES, DS_EVAL_MAX = 5000, 2000, 60.0, 600
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
    # Render, then tokenize: apply_chat_template(tokenize=True) returns a list in transformers 4.x
    # but an encoding object in 5.x. The rendered text already carries the special tokens.
    text = tok.apply_chat_template(msgs, add_generation_prompt=True, tokenize=False)
    return tok(text, add_special_tokens=False)["input_ids"]


def evaluate(model, tok, test: list[dict]) -> dict:
    import torch

    model.eval()
    dev = next(model.parameters()).device
    preds, lat = [], []
    with torch.no_grad():
        for ex in test:
            ids = torch.tensor([_prompt(tok, ex["features"])], device=dev)
            t0 = time.perf_counter()
            out = model.generate(input_ids=ids, attention_mask=torch.ones_like(ids),
                                 max_new_tokens=6, do_sample=False,
                                 pad_token_id=tok.pad_token_id or tok.eos_token_id)
            lat.append((time.perf_counter() - t0) * 1000)
            preds.append(parse_label(tok.decode(out[0, ids.shape[1]:], skip_special_tokens=True)))
    correct = sum(p == ex["label"] for p, ex in zip(preds, test, strict=True))
    per_label = {}
    for lbl in sorted({ex["label"] for ex in test}):
        idx = [i for i, ex in enumerate(test) if ex["label"] == lbl]
        per_label[lbl] = {"n": len(idx), "correct": sum(preds[i] == lbl for i in idx)}
    return {"accuracy": correct / len(test), "correct": correct, "n": len(test),
            "invalid": preds.count("invalid"), "p50_ms": statistics.median(lat),
            "pred_counts": dict(sorted(Counter(preds).items())), "per_label": per_label}


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
          cap_s: float, balanced: bool = False, clip: float | None = None,
          hook=None, every: int = 0) -> dict:
    """Plain training loop. ``clip`` caps the gradient norm; ``hook(step)`` runs every ``every``
    steps (dataset mode uses it to score val and keep the best adapter)."""
    import torch
    from datasets import Dataset

    ds = Dataset.from_list(train_set).map(lambda ex: _encode(tok, ex),
                                          remove_columns=["features", "label", "source"])
    rows = list(ds)
    opt = torch.optim.AdamW([p for p in model.parameters() if p.requires_grad], lr=lr)
    rng = random.Random(1)
    pad = tok.pad_token_id if tok.pad_token_id is not None else tok.eos_token_id
    dev = next(model.parameters()).device
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
                            for i in idx], device=dev)
        lab = torch.tensor([rows[i]["labels"] + [-100] * (width - len(rows[i]["labels"]))
                            for i in idx], device=dev)
        att = torch.tensor([[1] * len(rows[i]["input_ids"]) + [0] * (width - len(rows[i]["input_ids"]))
                            for i in idx], device=dev)
        loss = model(input_ids=ids, attention_mask=att, labels=lab).loss
        loss.backward()
        if clip:
            torch.nn.utils.clip_grad_norm_([p for p in model.parameters() if p.requires_grad], clip)
        opt.step()
        opt.zero_grad()
        losses.append(float(loss))
        done = step + 1
        if done % 25 == 0:
            print(f"  step {done:>3}  loss {statistics.mean(losses[-25:]):.4f}  "
                  f"{time.monotonic() - t0:.0f}s", flush=True)
        if hook and every and done % every == 0:
            hook(done)
            model.train()
    return {"steps": done, "capped": capped, "train_s": round(time.monotonic() - t0, 1),
            "losses": [round(x, 4) for x in losses],
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
understanding from pixels. The GPU QLoRA run on real pages is in `adapter_card_dataset.md`.
""", encoding="utf-8")


def _load_model(model_name: str, qlora: bool):
    """Tokenizer + base model: 4-bit on CUDA for QLoRA, bf16 on CUDA, else fp32 on CPU."""
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer

    if qlora and not torch.cuda.is_available():
        raise SystemExit("--qlora is GPU only: bitsandbytes 4-bit quantization needs CUDA. "
                         "Not run on this machine; drop --qlora for CPU LoRA.")
    tok = AutoTokenizer.from_pretrained(model_name)
    # bf16 needs Ampere or newer (A10G, L4); a T4 (g4dn) computes in fp16 instead.
    half = (torch.bfloat16 if torch.cuda.is_available() and torch.cuda.get_device_capability()[0] >= 8
            else torch.float16)
    if qlora:  # pragma: no cover - needs CUDA
        from peft import prepare_model_for_kbit_training
        from transformers import BitsAndBytesConfig

        bnb = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4",
                                 bnb_4bit_compute_dtype=half)
        model = prepare_model_for_kbit_training(AutoModelForCausalLM.from_pretrained(
            model_name, quantization_config=bnb, device_map={"": 0}))
    elif torch.cuda.is_available():  # pragma: no cover - needs CUDA
        model = AutoModelForCausalLM.from_pretrained(model_name, torch_dtype=half).to("cuda")
    else:
        model = AutoModelForCausalLM.from_pretrained(model_name, torch_dtype=torch.float32)
    return tok, model


def load_dataset_dir(path: Path) -> tuple[dict[str, list[dict]], dict]:
    """``({"train"|"val"|"test": rows}, manifest)`` from a build_layout_dataset.py output dir."""
    splits = {}
    for name in ("train", "val", "test"):
        rows = [json.loads(line) for line in (path / f"{name}.jsonl").read_text(encoding="utf-8").splitlines()
                if line.strip()]
        splits[name] = [{"features": r["features"], "label": r["label"], "source": r["paper"]} for r in rows]
    return splits, json.loads((path / "manifest.json").read_text(encoding="utf-8"))


def balanced_sample(rows: list[dict], n: int, seed: int = 0) -> list[dict]:
    """Up to ``n`` rows with an equal quota per label; a label short of its quota gives the
    remainder to the others, so rare labels are kept whole and the majority label is capped."""
    rng = random.Random(seed)
    groups: dict[str, list[dict]] = {}
    for r in rows:
        groups.setdefault(r["label"], []).append(r)
    for g in groups.values():
        rng.shuffle(g)
    out: list[dict] = []
    left = dict(groups)
    while left and len(out) < n:
        quota = max(1, (n - len(out)) // len(left))
        for lbl in sorted(left):
            take, left[lbl] = left[lbl][:quota], left[lbl][quota:]
            out.extend(take[:n - len(out)])
        left = {k: v for k, v in left.items() if v}
    rng.shuffle(out)
    return out


def capped_sample(rows: list[dict], n: int, max_share: float = 0.5, seed: int = 0) -> list[dict]:
    """Up to ``n`` rows keeping the natural mix, except that no label takes more than
    ``max_share`` of ``n``. Milder than ``balanced_sample``: rare labels are kept whole and the
    majority is capped, but the model still sees that most pages are ``text``."""
    rng = random.Random(seed)
    groups: dict[str, list[dict]] = {}
    for r in rows:
        groups.setdefault(r["label"], []).append(r)
    cap = max(1, int(n * max_share))
    out = [r for lbl in sorted(groups) for r in rng.sample(groups[lbl], min(len(groups[lbl]), cap))]
    rng.shuffle(out)
    return out[:n]


def eval_sample(rows: list[dict], n: int, seed: int = 0) -> list[dict]:
    """All rows if there are at most ``n``, else a fixed random sample (natural label mix)."""
    return list(rows) if len(rows) <= n else random.Random(seed).sample(rows, n)


def _fmt_per_label(r: dict) -> str:
    return " · ".join(f"{k} {v['correct']}/{v['n']}" for k, v in r["per_label"].items())


def write_card_dataset(s: dict) -> Path:
    card = HERE / "adapter_card_dataset.md"
    rows = "\n".join(
        f"| {split} | {who} | {r['accuracy']:.3f} ({r['correct']}/{r['n']}) | {r['invalid']} | "
        f"{r['p50_ms']:.0f} ms | {_fmt_per_label(r)} |"
        for split in ("val", "test") for who, r in (("base", s["base"][split]), ("tuned", s["tuned"][split])))
    card.write_text(f"""# Layout-label adapter card — dataset mode

Written by `python slm_regime_classifier/distill_layout.py --dataset ...` on {s['date']}.
Dataset `{s['dataset_version']}` (built by `build_layout_dataset.py`, split by paper, labels from
`layout_labels.derive_label`). The adapter lives under `slm_regime_classifier/adapters/{s['adapter_name']}/`
(git-ignored){' and in MLflow run `' + s['mlflow_run_id'] + '`' if s.get('mlflow_run_id') else ''}.

| | |
|---|---|
| base model | `{s['model']}` |
| method | {'QLoRA (4-bit nf4)' if s['qlora'] else 'LoRA'} r={s['lora_r']}, alpha={s['lora_alpha']}, targets {', '.join(s['targets'])} |
| trainable params | {s['trainable_params']:,} of {s['total_params']:,} |
| training set | {s['n_train']} rows from the train split, {'natural mix with no label above ' + str(s.get('max_share')) + ' of the set' if s.get('sample') == 'capped' else 'equal quota per label'}: {s['train_labels']} |
| training | {s['train']['steps']} steps, batch {s['batch']}, lr {s['lr']}, grad clip {s.get('clip')}, sample `{s.get('sample')}`{' (max share ' + str(s.get('max_share')) + ')' if s.get('sample') == 'capped' else ''}, {'class-balanced' if s['balanced'] else 'shuffled'} batches, {s['train']['train_s']} s{' (hit the time cap)' if s['train']['capped'] else ''} |
| checkpoint | {'step ' + str(s['train']['selected_step']) + ' of ' + str(s['train']['steps']) + ', best on a 200-row val slice: ' + ', '.join(f'{st}: {a:.3f}' for st, a in s['train']['select_curve']) if s['train'].get('select_curve') else 'final weights (no selection)'} |
| loss | {s['train']['first_loss']} at step 1 to {s['train']['last_loss']} (mean of the last 25 steps) |
| machine | {s['machine']} |

| split | model | accuracy | invalid | p50 latency | per label (correct/n) |
|---|---|---:|---:|---:|---|
{rows}

`val` and `test` are scored on their natural label mix (sampled to at most {s['eval_max']} rows each);
always answering the most common label would score {s['majority_test']:.3f} on test. `test` is the
locked split: quote it once per model, and tune nothing against it. The student learns the rule's
labels, so it cannot beat the rule; the numbers say how well a small model copies it on unseen papers.
""", encoding="utf-8")
    return card


def log_mlflow(s: dict, adapter_dir: Path, card: Path, dataset_dir: Path, register: str | None) -> str | None:
    """Log the run + the adapter as a pyfunc model; register a version and alias it ``candidate``."""
    if not os.environ.get("MLFLOW_TRACKING_URI", "").strip():
        return None
    import mlflow
    from mlflow import MlflowClient

    exp_name = os.environ.get("MLFLOW_EXPERIMENT_NAME", "yantra-layout-slm")
    if mlflow.get_experiment_by_name(exp_name) is None:
        mlflow.create_experiment(exp_name, artifact_location=os.environ.get("MLFLOW_ARTIFACT_ROOT") or None)
    mlflow.set_experiment(exp_name)
    with mlflow.start_run(run_name=f"{s['adapter_name']}-{s['dataset_version']}") as run:
        mlflow.set_tags({"dataset_version": s["dataset_version"], "git_sha": s["git_sha"],
                         "teacher": "layout_labels.derive_label"})
        mlflow.log_params({"model": s["model"], "qlora": s["qlora"], "lora_r": s["lora_r"],
                           "batch": s["batch"], "lr": s["lr"], "steps": s["train"]["steps"],
                           "n_train": s["n_train"], "balanced": s["balanced"], "eval_max": s["eval_max"],
                           "sample": s.get("sample"), "max_share": s.get("max_share"), "clip": s.get("clip"),
                           "selected_step": s["train"].get("selected_step")})
        for step, acc in s["train"].get("select_curve", []):
            mlflow.log_metric("val_select_accuracy", acc, step=step)
        for split in ("val", "test"):
            for who in ("base", "tuned"):
                r = s[who][split]
                mlflow.log_metric(f"{split}_{who}_accuracy", r["accuracy"])
                mlflow.log_metric(f"{split}_{who}_p50_ms", r["p50_ms"])
                for lbl, v in r["per_label"].items():
                    mlflow.log_metric(f"{split}_{who}_acc_{lbl}", v["correct"] / v["n"])
        for i, loss in enumerate(s["train"].get("losses", []), 1):
            mlflow.log_metric("train_loss", loss, step=i)
        mlflow.log_artifact(str(card))
        mlflow.log_artifact(str(dataset_dir / "manifest.json"), "dataset")
        from slm_regime_classifier.layout_pyfunc import LayoutAdapter

        info = mlflow.pyfunc.log_model(
            name="model", python_model=LayoutAdapter(), artifacts={"adapter": str(adapter_dir)},
            code_paths=[str(HERE / "layout_pyfunc.py"), str(HERE / "distill_layout.py")],
            model_config={"base_model": s["model"]},
            pip_requirements=["torch", "transformers", "peft", "accelerate", "bitsandbytes"],
            registered_model_name=register)
        if register and info.registered_model_version:
            client, v = MlflowClient(), str(info.registered_model_version)
            client.set_model_version_tag(register, v, "dataset_version", s["dataset_version"])
            client.set_model_version_tag(register, v, "test_accuracy", f"{s['tuned']['test']['accuracy']:.4f}")
            client.set_registered_model_alias(register, "candidate", v)
            print(f"registered {register} v{v} (alias: candidate). Promote by hand once reviewed:\n"
                  f"  python -c \"from mlflow import MlflowClient as C; "
                  f"C().set_registered_model_alias('{register}', 'champion', '{v}')\"")
        return run.info.run_id


def run_dataset(args) -> int:
    """Dataset mode: real pages, split by paper, val + locked test, optional MLflow."""
    import platform

    import torch
    from peft import LoraConfig, get_peft_model

    ds_dir = Path(args.dataset)
    splits, manifest = load_dataset_dir(ds_dir)
    n_train = min(args.max_train, DS_MAX_TRAIN)
    train_set = (capped_sample(splits["train"], n_train, args.max_share) if args.sample == "capped"
                 else balanced_sample(splits["train"], n_train))
    evals = {k: eval_sample(splits[k], min(args.eval_max, DS_EVAL_MAX)) for k in ("val", "test")}
    # Checkpoint selection uses its own slice of val (seed 1); test is never looked at until the end.
    select = eval_sample(splits["val"], args.select_n, seed=1) if args.select_every else []
    steps = min(args.steps, DS_MAX_STEPS)
    cap_s = min(args.cap_minutes, DS_CAP_MINUTES) * 60
    torch.manual_seed(0)
    tok, model = _load_model(args.model, args.qlora)
    print(f"dataset {manifest['version']} · model {args.model} · train {len(train_set)} · "
          f"val {len(evals['val'])} · test {len(evals['test'])}", flush=True)
    base = {k: evaluate(model, tok, v) for k, v in evals.items()}
    print(f"base   val {base['val']['accuracy']:.3f}  test {base['test']['accuracy']:.3f}", flush=True)

    targets = ["q_proj", "k_proj", "v_proj", "o_proj"]
    model = get_peft_model(model, LoraConfig(r=args.lora_r, lora_alpha=2 * args.lora_r, lora_dropout=0.05,
                                             target_modules=targets, task_type="CAUSAL_LM"))
    trainable = sum(p.numel() for p in model.parameters() if p.requires_grad)
    total = sum(p.numel() for p in model.parameters())
    best = {"acc": -1.0, "step": 0, "state": None, "curve": []}

    def keep_best(step: int) -> None:
        r = evaluate(model, tok, select)
        best["curve"].append((step, r["accuracy"]))
        mark = ""
        if r["accuracy"] > best["acc"]:
            best.update(acc=r["accuracy"], step=step, state={
                k: v.detach().clone() for k, v in model.state_dict().items() if "lora_" in k})
            mark = "  <- best so far"
        print(f"  select@{step}  val-slice accuracy {r['accuracy']:.3f}{mark}", flush=True)

    tr = train(model, tok, train_set, steps, args.batch, args.lr, cap_s, args.balanced,
               clip=args.clip, hook=keep_best if select else None, every=args.select_every)
    if tr["capped"]:
        print(f"STOPPED: hit the {cap_s / 60:.0f}-minute training cap at step {tr['steps']}")
    if best["state"] is not None:
        if tr["steps"] % args.select_every:
            keep_best(tr["steps"])                    # score the final weights too
        model.load_state_dict(best["state"], strict=False)
        print(f"restored the best adapter: step {best['step']} (val-slice {best['acc']:.3f})", flush=True)
    tr["selected_step"], tr["select_curve"] = best["step"], best["curve"]
    tuned = {k: evaluate(model, tok, v) for k, v in evals.items()}
    print(f"tuned  val {tuned['val']['accuracy']:.3f}  test {tuned['test']['accuracy']:.3f}", flush=True)
    for k in ("val", "test"):
        print(f"  {k:<4} per label (tuned): {_fmt_per_label(tuned[k])}")

    name = "layout-" + args.model.split("/")[-1].lower() + ("-qlora" if args.qlora else "")
    adapter_dir = ADAPTERS / name
    ADAPTERS.mkdir(parents=True, exist_ok=True)
    model.save_pretrained(str(adapter_dir))
    gpu = torch.cuda.get_device_name(0) if torch.cuda.is_available() else "no GPU"
    test_counts = Counter(e["label"] for e in evals["test"])
    summary = {
        "date": time.strftime("%Y-%m-%d"), "model": args.model, "adapter_name": name, "qlora": args.qlora,
        "dataset_version": manifest["version"], "git_sha": manifest.get("git_sha", "unknown"),
        "lora_r": args.lora_r, "lora_alpha": 2 * args.lora_r, "targets": targets,
        "trainable_params": trainable, "total_params": total, "n_train": len(train_set),
        "batch": args.batch, "lr": args.lr, "balanced": args.balanced, "eval_max": args.eval_max,
        "sample": args.sample, "max_share": args.max_share, "clip": args.clip,
        "train": tr, "train_labels": dict(sorted(Counter(e["label"] for e in train_set).items())),
        "base": base, "tuned": tuned, "majority_test": max(test_counts.values()) / len(evals["test"]),
        "machine": f"{platform.machine()}, {gpu}, torch {torch.__version__}, Python {platform.python_version()}",
    }
    card = write_card_dataset(summary)
    run_id = log_mlflow(summary, adapter_dir, card, ds_dir, args.register)
    if run_id:
        summary["mlflow_run_id"] = run_id
        write_card_dataset(summary)
        print(f"mlflow run {run_id}")
    print(json.dumps({k: v for k, v in summary.items() if k not in ("base", "tuned")}, indent=2, default=str))
    print(f"wrote {card}")
    return 0


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
    ap.add_argument("--dataset", help="dataset dir from build_layout_dataset.py (enables dataset mode)")
    ap.add_argument("--max-train", type=int, default=3000, help="dataset mode: balanced training rows")
    ap.add_argument("--eval-max", type=int, default=DS_EVAL_MAX, help="dataset mode: rows per eval split")
    ap.add_argument("--register", help="dataset mode + MLFLOW_TRACKING_URI: registered model name")
    ap.add_argument("--sample", choices=("balanced", "capped"), default="balanced",
                    help="dataset mode: equal quota per label, or natural mix with the majority capped")
    ap.add_argument("--max-share", type=float, default=0.5, help="--sample capped: largest share of one label")
    ap.add_argument("--clip", type=float, default=None, help="max gradient norm (off by default)")
    ap.add_argument("--select-every", type=int, default=0,
                    help="dataset mode: score a val slice every N steps and keep the best adapter")
    ap.add_argument("--select-n", type=int, default=200, help="rows in the val slice used for selection")
    args = ap.parse_args(argv)
    if args.dataset:
        return run_dataset(args)
    steps = min(args.steps, MAX_STEPS)
    cap_s = min(args.cap_minutes, CAP_MINUTES) * 60

    import torch
    from peft import LoraConfig, get_peft_model

    torch.manual_seed(0)
    torch.set_num_threads(os.cpu_count() or 2)
    train_set, test = build_examples()
    tok, model = _load_model(args.model, args.qlora)

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
