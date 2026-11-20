"""Seed separation. Benchmark seeds 1-20 are for the final eval only; everything else uses 1000+.

The teacher, the labeller, the dataset builder and the trainer all call ``require_calibration``;
only ``evaluate --final`` calls ``require_benchmark``. A leak raises ``SeedLeak`` (an
AssertionError), so it cannot be caught by the graph's model-failure fallback by accident.
"""

from __future__ import annotations

CALIBRATION_MIN = 1000
BENCHMARK_SEEDS = frozenset(range(1, 21))
KINDS_BY_SEED = ("trend", "meanrev", "noise", "noise")   # seed % 4: half edge, half noise


class SeedLeak(AssertionError):
    """A benchmark seed reached a path that must only ever see calibration seeds (or vice versa)."""


def require_calibration(seed: int) -> int:
    if not isinstance(seed, int) or seed < CALIBRATION_MIN or seed in BENCHMARK_SEEDS:
        raise SeedLeak(f"seed {seed!r} is not a calibration seed (>= {CALIBRATION_MIN} required)")
    return seed


def require_benchmark(seed: int) -> int:
    if seed not in BENCHMARK_SEEDS:
        raise SeedLeak(f"seed {seed!r} is not a benchmark seed (1-20)")
    return seed


def parse_source(source: str) -> tuple[str, int]:
    """``synthetic:<kind>:<seed>`` -> (kind, seed)."""
    tag, kind, seed = source.split(":")
    if tag != "synthetic":
        raise ValueError(f"not a synthetic source: {source!r}")
    return kind, int(seed)


def require_calibration_source(source: str) -> tuple[str, int]:
    kind, seed = parse_source(source)
    require_calibration(seed)
    return kind, seed


def calibration_case(seed: int) -> tuple[str, int]:
    """The market kind for a calibration seed: trend, meanrev, noise, noise (repeating)."""
    require_calibration(seed)
    return KINDS_BY_SEED[seed % 4], seed


def calibration_cases(start: int, stop: int) -> list[tuple[str, int]]:
    return [calibration_case(s) for s in range(start, stop)]


def benchmark_cases() -> list[tuple[str, int]]:
    """The planted benchmark's 20 cases, exactly as eval.planted_benchmark defines them."""
    from eval.planted_benchmark import CASES
    for _, s in CASES:
        require_benchmark(s)
    return list(CASES)
