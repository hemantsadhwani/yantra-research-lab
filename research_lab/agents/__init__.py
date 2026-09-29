"""Specialist agents driven by the supervisor: propose, backtest, evaluate."""

from .backtester import Backtester, MCPBacktester, close_mcp_clients, make_backtester
from .evaluator import Evaluator, score_result
from .proposer import Proposer

__all__ = [
    "Backtester",
    "Evaluator",
    "MCPBacktester",
    "Proposer",
    "close_mcp_clients",
    "make_backtester",
    "score_result",
]
