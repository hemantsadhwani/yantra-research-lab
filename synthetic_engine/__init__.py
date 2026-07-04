"""Public, self-contained synthetic backtest engine — ZERO proprietary IP.

Stands in for the private production engine so the whole platform is reproducible
by a stranger. The real engine is referenced verbally only; nothing here reveals
any live strategy.
"""

from .engine import BASELINE_PARAMS, PARAM_SPACE, run_backtest

__all__ = ["run_backtest", "BASELINE_PARAMS", "PARAM_SPACE"]
