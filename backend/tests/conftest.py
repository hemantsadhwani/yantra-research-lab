"""Keep every backend test offline and off the live Logfire project.

The repo ``.env`` holds a real ``LOGFIRE_TOKEN`` and ``ANTHROPIC_API_KEY``. ``app.py`` calls
``load_dotenv(find_dotenv())`` at import time, and python-dotenv never overrides a variable
that already exists (even an empty one). So these are set at MODULE level here, before
pytest imports any test module (and with it ``app``): the ``.env`` values can then never
take effect. ``YANTRA_ENV=test`` additionally makes ``observability.configure()`` a no-op
even if a token somehow got through. The autouse fixture re-asserts them per test, in case
a test (or ``load_dotenv``) touched ``os.environ``.
"""

import os

import pytest

_OFFLINE_ENV = {"LOGFIRE_TOKEN": "", "YANTRA_ENV": "test", "ANTHROPIC_API_KEY": ""}

for _k, _v in _OFFLINE_ENV.items():
    os.environ[_k] = _v
os.environ.pop("YANTRA_TRACE_LOCAL", None)


@pytest.fixture(autouse=True)
def _offline_env(monkeypatch):
    for k, v in _OFFLINE_ENV.items():
        monkeypatch.setenv(k, v)
    monkeypatch.delenv("YANTRA_TRACE_LOCAL", raising=False)
