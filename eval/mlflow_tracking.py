"""Optional MLflow tracking for eval runs: a no-op unless ``MLFLOW_TRACKING_URI`` is set.

    from eval.mlflow_tracking import track_run
    track_run("run_gate", params={"arm": "stdlib", "seed": 3}, metrics={"best": 36.5})

``mlflow`` is imported inside ``track_run`` only after the URI check, so the stdlib path,
the ``core`` CI job and every default command never import it. When the URI is set but
tracking fails (mlflow missing, bad store), a one-line warning goes to stderr and the eval
carries on: tracking must never change an eval's exit code.

Local file store (git-ignored):  ``MLFLOW_TRACKING_URI=file:./.mlruns``, then ``make mlflow-ui``.
MLflow 3.x puts the file store in maintenance mode and refuses it unless
``MLFLOW_ALLOW_FILE_STORE=true``; for a ``file:`` URI this helper sets that default. A
``sqlite:///...`` or ``http://...`` tracking URI works unchanged.
Only runs are tracked (params, metrics, optional artifacts). The model registry is not used.
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

EXPERIMENT = os.environ.get("MLFLOW_EXPERIMENT_NAME", "yantra-evals")
_ROOT = Path(__file__).resolve().parent.parent


def enabled() -> bool:
    return bool(os.environ.get("MLFLOW_TRACKING_URI", "").strip())


def _git_sha() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=_ROOT,
                              capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def track_run(
    name: str,
    params: Mapping[str, Any],
    metrics: Mapping[str, float | int | bool],
    artifacts: Iterable[str | Path] = (),
    experiment: str = EXPERIMENT,
) -> str | None:
    """Log one run and return its run id, or ``None`` when tracking is off or failed."""
    if not enabled():
        return None
    try:
        uri = os.environ["MLFLOW_TRACKING_URI"].strip()
        os.environ.setdefault("MLFLOW_DISABLE_AGENT_HINT", "1")
        if uri.startswith("file:"):
            os.environ.setdefault("MLFLOW_ALLOW_FILE_STORE", "true")
        import mlflow  # lazy: optional (dev extra), never on the default path

        mlflow.set_tracking_uri(uri)
        mlflow.set_experiment(experiment)
        with mlflow.start_run(run_name=name) as run:
            mlflow.set_tags({"eval": name, "git_sha": _git_sha()})
            mlflow.log_params({k: str(v) for k, v in params.items()})
            mlflow.log_metrics({k: float(v) for k, v in metrics.items()})
            for path in artifacts:
                if Path(path).exists():
                    mlflow.log_artifact(str(path))
            return run.info.run_id
    except Exception as e:  # noqa: BLE001 - tracking is best-effort; the eval result stands
        print(f"  ! mlflow tracking skipped ({type(e).__name__}: {e})", file=sys.stderr)
        return None
