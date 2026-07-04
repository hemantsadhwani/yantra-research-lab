"""Specialist agents driven by the supervisor: propose, backtest, evaluate."""

from .backtester import Backtester
from .evaluator import Evaluator, score_result
from .proposer import Proposer

__all__ = ["Proposer", "Backtester", "Evaluator", "score_result"]
