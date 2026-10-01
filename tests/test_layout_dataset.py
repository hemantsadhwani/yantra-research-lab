"""The layout dataset's split and sampling rules (stdlib only; no torch, boto3 or PDFs needed)."""

import importlib
import json
import sys
from collections import Counter
from pathlib import Path

# slm_regime_classifier is a script folder, not an installed package: put the repo root on the path.
REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))
split_of = importlib.import_module("slm_regime_classifier.build_layout_dataset").split_of
_distill = importlib.import_module("slm_regime_classifier.distill_layout")
balanced_sample, eval_sample, load_dataset_dir = (
    _distill.balanced_sample, _distill.eval_sample, _distill.load_dataset_dir)

PAPERS = [f"2607.{i:05d}v1" for i in range(2000)]


def test_split_is_stable_and_roughly_80_10_10():
    first = {p: split_of(p) for p in PAPERS}
    assert first == {p: split_of(p) for p in PAPERS}          # same paper, same split, every time
    share = Counter(first.values())
    assert 0.76 < share["train"] / len(PAPERS) < 0.84
    assert 0.07 < share["val"] / len(PAPERS) < 0.13
    assert 0.07 < share["test"] / len(PAPERS) < 0.13


def test_adding_papers_never_moves_existing_ones():
    before = {p: split_of(p) for p in PAPERS[:500]}
    after = {p: split_of(p) for p in PAPERS}                  # corpus grew 4x
    assert all(after[p] == s for p, s in before.items())


def _rows(counts):
    return [{"features": f"{lbl}-{i}", "label": lbl, "source": f"p{i}"}
            for lbl, n in counts.items() for i in range(n)]


def test_balanced_sample_keeps_rare_labels_and_caps_the_majority():
    rows = _rows({"text": 5000, "mixed": 900, "table-heavy": 120, "figure-heavy": 300, "scanned": 15})
    got = Counter(r["label"] for r in balanced_sample(rows, 1000))
    assert sum(got.values()) == 1000
    assert got["scanned"] == 15 and got["table-heavy"] == 120     # rare labels kept whole
    assert got["text"] < 400                                     # majority no longer dominates


def test_balanced_sample_is_deterministic_and_bounded():
    rows = _rows({"text": 50, "mixed": 5})
    assert balanced_sample(rows, 30, seed=1) == balanced_sample(rows, 30, seed=1)
    assert len(balanced_sample(rows, 500)) == 55                  # never more rows than exist


def test_eval_sample_keeps_small_splits_whole():
    rows = _rows({"text": 10, "mixed": 3})
    assert eval_sample(rows, 600) == rows
    assert len(eval_sample(_rows({"text": 900}), 600)) == 600


def test_load_dataset_dir_reads_the_builder_format(tmp_path):
    row = {"paper": "2607.00001v1", "page": 3, "features": "chars=10", "label": "scanned", "raw": {}}
    for name in ("train", "val", "test"):
        (tmp_path / f"{name}.jsonl").write_text(json.dumps(row) + "\n", encoding="utf-8")
    (tmp_path / "manifest.json").write_text(json.dumps({"version": "abc123"}), encoding="utf-8")
    splits, manifest = load_dataset_dir(tmp_path)
    assert manifest["version"] == "abc123"
    assert splits["test"] == [{"features": "chars=10", "label": "scanned", "source": "2607.00001v1"}]


def test_capped_sample_caps_the_majority_but_keeps_the_natural_mix():
    from slm_regime_classifier.distill_layout import capped_sample

    rows = _rows({"text": 4868, "mixed": 891, "figure-heavy": 241, "table-heavy": 16, "scanned": 6})
    got = Counter(r["label"] for r in capped_sample(rows, 3000, max_share=0.5))
    assert got["text"] == 1500                                   # capped at half of n
    assert got["mixed"] == 891 and got["table-heavy"] == 16 and got["scanned"] == 6   # kept whole
    assert got["text"] > got["mixed"] > got["figure-heavy"]      # order of the real mix survives
