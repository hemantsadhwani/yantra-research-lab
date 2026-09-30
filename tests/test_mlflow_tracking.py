"""MLflow tracking is opt-in: a no-op (mlflow never imported) unless MLFLOW_TRACKING_URI is set."""

import importlib
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))
mt = importlib.import_module("eval.mlflow_tracking")


def test_noop_without_uri_and_mlflow_never_imported():
    code = ("import os, sys; os.environ.pop('MLFLOW_TRACKING_URI', None); "
            "from eval.mlflow_tracking import track_run; "
            "assert track_run('x', {'a': 1}, {'m': 1.0}) is None; "
            "import eval.run_gate, eval.judge_eval, eval.ragas_eval; "
            "assert 'mlflow' not in sys.modules, 'mlflow imported on the default path'")
    env = {k: v for k, v in os.environ.items() if k != "MLFLOW_TRACKING_URI"}
    subprocess.run([sys.executable, "-c", code], cwd=REPO, env=env, check=True)


def test_stdlib_gate_runs_without_tracking(monkeypatch):
    monkeypatch.delenv("MLFLOW_TRACKING_URI", raising=False)
    from eval import run_gate

    assert run_gate.main(["--arm", "stdlib"]) == 0


def test_logs_a_run_to_a_file_store(monkeypatch, tmp_path):
    monkeypatch.setenv("MLFLOW_DISABLE_AGENT_HINT", "1")
    mlflow = pytest.importorskip("mlflow")
    uri = (tmp_path / "mlruns").as_uri()
    monkeypatch.setenv("MLFLOW_TRACKING_URI", uri)
    run_id = mt.track_run("unit", {"arm": "stdlib", "seed": 3},
                          {"best_score": 36.5, "pass": True}, experiment="unit-test")
    assert run_id
    mlflow.set_tracking_uri(uri)
    run = mlflow.get_run(run_id)
    assert run.data.params == {"arm": "stdlib", "seed": "3"}
    assert run.data.metrics == {"best_score": 36.5, "pass": 1.0}
    assert run.data.tags["eval"] == "unit"


def test_tracking_failure_never_raises(monkeypatch, capsys):
    monkeypatch.setenv("MLFLOW_TRACKING_URI", "file:///tmp/x")
    monkeypatch.setitem(sys.modules, "mlflow", None)  # import mlflow -> ImportError
    assert mt.track_run("x", {}, {"m": 1}) is None
    assert "mlflow tracking skipped" in capsys.readouterr().err
