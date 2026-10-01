# slm_regime_classifier/

What exists here is a **page-layout classifier**, not the regime classifier, in two modes:
a small CPU LoRA kata, and a GPU QLoRA run on real arXiv pages with a versioned dataset and an
MLflow registry. Both prove the pipeline shape (teacher labels → fine-tune → base vs tuned on
held-out data) on a task whose labels are free: page-layout classes from the ingestion parser.

The regime classifier itself (market context → regime label, frontier teacher, 4-bit QLoRA,
vLLM serving under 50 ms, CI drift gate) is still **designed, not built**. See `ROADMAP.md`
and [architecture/07](../architecture/07-model-routing-finetune.md).

## What is here

| File | What it is |
|---|---|
| `distill_layout.py` | LoRA fine-tune of `HuggingFaceTB/SmolLM2-135M-Instruct` on CPU to emit one of five layout labels from a one-line feature string. At most 300 training examples, 300 steps, and a 25-minute training cap. Base vs tuned on 60 held-out examples: accuracy and p50 latency |
| `adapter_card.md` | The numbers from the last CPU kata run (committed) |
| `build_layout_dataset.py` | Dataset from the arXiv PDFs in S3: parse every page, label with the rule, split 80/10/10 **by paper** (salted hash), cache features and write the versioned dataset to `s3://…/ml/` |
| `distill_layout.py --dataset …` | GPU mode: QLoRA, val-slice checkpoint selection, base vs tuned on val and the locked test split per label, MLflow run + registered version (`@candidate`) |
| `layout_pyfunc.py` | MLflow pyfunc: base model + adapter → one label per feature string |
| `adapter_card_dataset.md` | The numbers from the last GPU run (committed); history in `results/layout_qlora_2026-10-01.md` |
| `adapters/` | The saved LoRA adapter (git-ignored, rebuilt by the script) |

The teacher is `ingestion/layout_labels.derive_label`, a deterministic rule over the parser's
output. The frontier-as-teacher flow is designed in [ADR-0012](../docs/adr/0012-slm-cascade.md),
not run.

## Run it

```bash
pip install -e '.[slm]'                          # torch, transformers, peft, datasets
python slm_regime_classifier/distill_layout.py   # or: make distill-layout
python slm_regime_classifier/distill_layout.py --qlora   # GPU only: refuses without CUDA
bash deploy/ec2/layout_session.sh                        # GPU box: dataset → QLoRA → MLflow (see deploy/ec2/SESSION_LIFECYCLE.md)
```

On an Intel Mac with Python 3.13, `pip install torch` finds no wheel: PyTorch stopped publishing
Intel-macOS wheels after 2.2.2, which supports Python up to 3.12. The dev-Mac run used a
separate Python 3.12 venv with torch 2.2.2, transformers 4.46.3 and peft 0.13.2 (newer
transformers requires torch 2.5 or later). Details: `results/distill_2026-09-30.md`.

## What the numbers can and cannot say

The student is distilled from the rule's labels, so it cannot beat the rule; it can only get
close to it at a higher cost per page than the rule itself. The point is the pipeline, and the
measured cost of running a 135M model on a laptop CPU. It says nothing about reading layout
from pixels.
