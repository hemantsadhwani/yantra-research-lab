"""The four RAGAS metric definitions in eval/ragas_eval.py, checked with a scripted judge.

Stdlib only (no backend, no model): runs in the CI ``core`` job.
"""

import importlib
import os
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:  # `eval/` is a repo-root package; the pytest script skips the cwd
    sys.path.insert(0, _ROOT)
rg = importlib.import_module("eval.ragas_eval")


class Scripted:
    """A judge whose every verdict is fixed by the test."""

    name = "scripted"

    def __init__(self, stmts=(), supported=(), gens=(), noncommittal=False, useful=(),
                 attrib=()):
        self._stmts, self._sup = list(stmts), list(supported)
        self._gens, self._nc = list(gens), noncommittal
        self._useful, self._attrib = list(useful), list(attrib)

    def statements(self, q, a):
        return self._stmts

    def supported(self, s, c):
        return self._sup

    def regenerate_questions(self, a, n):
        return self._gens[:n], self._nc

    def useful(self, q, c, gt):
        return self._useful.pop(0)

    def attributable(self, g, c):
        return self._attrib


def test_faithfulness_is_supported_claims_over_all_claims():
    j = Scripted(stmts=["a", "b", "c", "d"], supported=[1, 1, 0, 1])
    assert rg.faithfulness("q", "ans", ["ctx"], j) == pytest.approx(0.75)
    assert rg.faithfulness("q", "", ["ctx"], Scripted()) == 0.0


def test_context_precision_is_rank_aware():
    # useful at ranks 1 and 3: (1/1 + 2/3) / 2
    j = Scripted(useful=[1, 0, 1, 0])
    assert rg.context_precision("q", ["c1", "c2", "c3", "c4"], "gt", j) == pytest.approx(5 / 6)
    # the same two useful chunks ranked last score lower: (1/3 + 2/4) / 2
    j = Scripted(useful=[0, 0, 1, 1])
    assert rg.context_precision("q", ["c1", "c2", "c3", "c4"], "gt", j) == pytest.approx(5 / 12)
    assert rg.context_precision("q", ["c1"], "gt", Scripted(useful=[0])) == 0.0


def test_context_recall_is_attributable_gt_sentences():
    gt = "Drawdown is the peak to trough decline. It is always zero or negative."
    j = Scripted(attrib=[1, 0])
    assert rg.context_recall(["ctx"], gt, j) == pytest.approx(0.5)


def test_answer_relevancy_is_mean_cosine_and_zero_if_noncommittal():
    q = "what is maximum drawdown"
    same = Scripted(gens=[q, q])
    assert rg.answer_relevancy(q, "ans", same, rg.hashed_embed) == pytest.approx(1.0)
    off = Scripted(gens=["options gamma theta vega"])
    assert rg.answer_relevancy(q, "ans", off, rg.hashed_embed) < 0.5
    assert rg.answer_relevancy(q, "ans", Scripted(gens=[q], noncommittal=True),
                               rg.hashed_embed) == 0.0


def test_lexical_judge_is_deterministic_and_bounded():
    j = rg.LexicalJudge()
    ctx = "Maximum drawdown is the largest peak-to-trough decline over the sample."
    assert j.supported(["the largest peak-to-trough decline"], ctx) == [1]
    assert j.supported(["sharpe divides excess return by volatility"], ctx) == [0]
    assert j.useful("q", ctx, "largest peak-to-trough decline") == 1


def test_golden_set_shape():
    rows = rg.load_golden()
    assert len(rows) == 12
    assert len({r["id"] for r in rows}) == 12
    assert all(r["expected_source"].startswith("backend/") for r in rows)
