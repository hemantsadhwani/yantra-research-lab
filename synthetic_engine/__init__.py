"""Public, self-contained synthetic backtest engine — ZERO proprietary IP.

Stands in for the private production engine so the whole platform is reproducible
by a stranger. The real engine is referenced verbally only; nothing here reveals
any live strategy. The three named strategies (``nifty-weekday``, ``nifty-expiry``,
``sensex-expiry``) are synthetic stand-ins behind the same ``run_backtest`` contract;
the real entry/exit logic is private and served server-side.
"""

from .engine import (
    BASELINE_PARAMS,
    DEFAULT_STRATEGY,
    PARAM_SPACE,
    STRATEGIES,
    get_baseline,
    list_strategies,
    run_backtest,
)

__all__ = [
    "run_backtest",
    "BASELINE_PARAMS",
    "PARAM_SPACE",
    "DEFAULT_STRATEGY",
    "STRATEGIES",
    "get_baseline",
    "list_strategies",
]
