"""Local runs never export spans; production spans are tagged and the metrics query
counts only those. Offline: a fake ``logfire`` module stands in for the SDK."""

import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import metrics as metrics_mod
import observability as obs
import pytest


class _FakeLogfire(types.ModuleType):
    def __init__(self):
        super().__init__("logfire")
        self.configure_calls: list[dict] = []

    def configure(self, **kwargs):
        self.configure_calls.append(kwargs)

    def instrument_fastapi(self, app, **kwargs):
        pass

    def instrument_anthropic(self):
        pass


@pytest.fixture
def fake_logfire(monkeypatch):
    fake = _FakeLogfire()
    monkeypatch.setattr(obs, "logfire", fake)
    monkeypatch.setattr(obs, "_configured", False)
    monkeypatch.setenv("LOGFIRE_TOKEN", "abc")
    return fake


@pytest.mark.parametrize("env", ["local", "test", "eval", ""])
def test_token_alone_does_not_configure_outside_production(fake_logfire, monkeypatch, env):
    monkeypatch.setenv("YANTRA_ENV", env)
    assert obs.configure() is False
    assert fake_logfire.configure_calls == []
    with obs.span("chat_request") as sp:        # a null span, not an unconfigured logfire
        assert isinstance(sp, obs._NullSpan)


def test_production_configures_with_environment(fake_logfire, monkeypatch):
    monkeypatch.setenv("YANTRA_ENV", "production")
    assert obs.configure() is True
    assert len(fake_logfire.configure_calls) == 1
    assert fake_logfire.configure_calls[0]["environment"] == "production"


def test_trace_local_opt_in_is_tagged_local(fake_logfire, monkeypatch):
    monkeypatch.setenv("YANTRA_ENV", "local")
    monkeypatch.setenv("YANTRA_TRACE_LOCAL", "1")
    assert obs.configure() is True
    assert fake_logfire.configure_calls[0]["environment"] == "local"


def test_metrics_query_counts_only_production():
    assert "span_name = 'chat_request'" in metrics_mod._SQL
    assert "deployment_environment = 'production'" in metrics_mod._SQL


def test_conftest_keeps_tests_offline():
    assert os.environ["LOGFIRE_TOKEN"] == ""
    assert os.environ["YANTRA_ENV"] == "test"
    assert os.environ["ANTHROPIC_API_KEY"] == ""
