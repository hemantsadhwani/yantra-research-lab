"""Persistent three-layer memory over one SQLite file — runs learn from previous runs.

``SqliteMemory`` has the same public surface as ``research_lab.memory.Memory``
(``observe``, ``best_params``, ``best_id``, ``best_score``, ``trials``, ``trial_count``)
so the supervisor, the graph and both proposers take it unchanged. It is duck-typed, not
a subclass. On top of that surface it adds the three layers:

* **episodic** — every trial of every run is written through to ``trials``. The
  Memory-compatible methods are scoped to *this* run (``run_id``), exactly like the
  in-process ``Memory``: best-so-far and the trial log describe the current run, so a
  run's exploit step behaves identically whichever store backs it.
* **semantic** — ``recall_similar(text, k)`` ranks stored trials of this strategy (all
  runs) by cosine similarity between ``text`` and the embedding of each trial's
  ``rationale + params summary``. A plain Python loop over the rows: at research-lab
  scale (hundreds to low thousands of trials) that is milliseconds, and it keeps the
  store stdlib-only. ``sqlite-vec`` is the upgrade path if the table ever outgrows it.
* **procedural** — ``priors()`` returns a narrowed sampling box: per parameter,
  ``[min, max]`` over the top-quartile-by-score trials of *previous* runs of this
  strategy (``None`` below 5 prior trials). The heuristic proposer's explorer samples
  from this box half the time. ``refresh_priors()`` also materialises the box over all
  runs into the ``priors`` table so it can be inspected with ``sqlite3``; the proposer
  reads the live computation, which excludes the current run by construction.

**Promotions.** ``record_promotion`` is the only writer of the ``promotions`` table and
refuses anything but ``decided_by="human"``. The graph calls it from ``finalize`` only
after a human resumed the gate with "approve"; the loop itself never promotes.

**Storage.** Embeddings are stored as little-endian float32 bytes (``array('f')``) in a
BLOB, tagged with the embedder name; recall only compares vectors from the embedder in
use, so a store written with fastembed and read with the hashed fallback degrades to
"no semantic matches" instead of comparing incomparable vectors.

Default path: ``$RESEARCH_MEMORY_DB`` or ``.yantra/research.sqlite``. Stdlib only.
"""

from __future__ import annotations

import json
import math
import os
import sqlite3
import sys
import uuid
from array import array
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Self

from research_lab.embeddings import cosine, embed, embedder_name
from research_lab.schemas import Evaluation, StrategyVariant, Trial

DEFAULT_MEMORY_DB = ".yantra/research.sqlite"
PRIORS_MIN_TRIALS = 5

_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id     TEXT PRIMARY KEY,
    strategy   TEXT NOT NULL,
    seed       INTEGER,
    started_at TEXT NOT NULL,
    arm        TEXT
);
CREATE TABLE IF NOT EXISTS trials (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id      TEXT NOT NULL REFERENCES runs(run_id),
    variant_id  TEXT NOT NULL,
    params_json TEXT NOT NULL,
    score       REAL NOT NULL,
    verdict     TEXT NOT NULL,
    rationale   TEXT NOT NULL DEFAULT '',
    embedding   BLOB,
    embedder    TEXT,
    created_at  TEXT NOT NULL,
    UNIQUE (run_id, variant_id)
);
CREATE TABLE IF NOT EXISTS promotions (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id     TEXT NOT NULL REFERENCES runs(run_id),
    variant_id TEXT NOT NULL,
    decided_by TEXT NOT NULL CHECK (decided_by = 'human'),
    decided_at TEXT NOT NULL,
    UNIQUE (run_id, variant_id)
);
CREATE TABLE IF NOT EXISTS priors (
    strategy   TEXT NOT NULL,
    param      TEXT NOT NULL,
    lo         REAL NOT NULL,
    hi         REAL NOT NULL,
    n_runs     INTEGER NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (strategy, param)
);
"""


def default_memory_db() -> str:
    return os.environ.get("RESEARCH_MEMORY_DB") or DEFAULT_MEMORY_DB


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _pack(vec: list[float]) -> bytes:
    a = array("f", vec)
    if sys.byteorder != "little":
        a.byteswap()
    return a.tobytes()


def _unpack(blob: bytes) -> list[float]:
    a = array("f")
    a.frombytes(blob)
    if sys.byteorder != "little":
        a.byteswap()
    return a.tolist()


def trial_text(rationale: str, params: dict[str, float]) -> str:
    """What gets embedded: the rationale plus a readable params summary."""
    summary = " ".join(f"{k} {v:g}" for k, v in params.items())
    return f"{rationale} | {summary}"


def _top_quartile_box(rows: list[tuple[float, dict[str, float]]]
                      ) -> dict[str, tuple[float, float]] | None:
    """[min, max] per param over the top quartile by score (ties: earliest first)."""
    if len(rows) < PRIORS_MIN_TRIALS:
        return None
    k = max(1, math.ceil(len(rows) / 4))
    top = sorted(rows, key=lambda r: -r[0])[:k]   # stable: rows arrive oldest first
    keys = list(top[0][1])
    return {p: (min(r[1][p] for r in top), max(r[1][p] for r in top)) for p in keys}


class SqliteMemory:
    """Memory-compatible store persisted in SQLite, plus recall, priors and promotions.

    Args:
        path: SQLite file (default ``$RESEARCH_MEMORY_DB`` / ``.yantra/research.sqlite``).
        strategy: which strategy this run researches; recall and priors never cross it.
        run_id: identifies this run. Reopening with an existing ``run_id`` reloads that
            run's trials (the graph reopens the store in every node). ``None`` makes one.
        seed, arm: recorded on the ``runs`` row for later inspection.
    """

    def __init__(self, path: str | os.PathLike[str] | None = None, strategy: str = "",
                 run_id: str | None = None, seed: int | None = None,
                 arm: str | None = None) -> None:
        self.path = str(path or default_memory_db())
        self.strategy = strategy
        self.run_id = run_id or f"{strategy or 'run'}-{uuid.uuid4().hex[:12]}"
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.executescript(_SCHEMA)
        self._conn.execute(
            "INSERT OR IGNORE INTO runs (run_id, strategy, seed, started_at, arm) "
            "VALUES (?, ?, ?, ?, ?)", (self.run_id, strategy, seed, _now(), arm))
        self._conn.commit()
        self._priors_cache: dict[str, tuple[float, float]] | None | bool = False
        self._best: tuple[str, dict[str, float], float] | None = None
        self._trials: list[Trial] = []
        for vid, pj, score, verdict, rationale in self._conn.execute(
                "SELECT variant_id, params_json, score, verdict, rationale FROM trials "
                "WHERE run_id = ? ORDER BY id", (self.run_id,)):
            self._remember(Trial(vid, json.loads(pj), score, verdict, rationale))

    # ------------------------------------------------ Memory-compatible surface
    def _remember(self, trial: Trial) -> None:
        self._trials.append(trial)
        if self._best is None or trial.score > self._best[2]:
            self._best = (trial.variant_id, dict(trial.params), trial.score)

    def observe(self, variant: StrategyVariant, evaluation: Evaluation) -> None:
        """Record a trial for this run (write-through). Idempotent per variant id, so a
        graph node re-executed after a crash cannot double-count a trial."""
        params = dict(variant.params)
        vec = embed(trial_text(variant.rationale, params))
        cur = self._conn.execute(
            "INSERT OR IGNORE INTO trials (run_id, variant_id, params_json, score, verdict, "
            "rationale, embedding, embedder, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (self.run_id, variant.id, json.dumps(params), evaluation.score,
             evaluation.verdict, variant.rationale, _pack(vec), embedder_name(), _now()))
        self._conn.commit()
        if cur.rowcount:
            self._remember(Trial(variant.id, params, evaluation.score, evaluation.verdict,
                                 variant.rationale))

    def best_params(self) -> dict[str, float] | None:
        return dict(self._best[1]) if self._best else None

    def best_id(self) -> str | None:
        return self._best[0] if self._best else None

    def best_score(self) -> float | None:
        return self._best[2] if self._best else None

    def trials(self) -> list[Trial]:
        return [Trial(t.variant_id, dict(t.params), t.score, t.verdict, t.rationale)
                for t in self._trials]

    def trial_count(self) -> int:
        return len(self._trials)

    # ---------------------------------------------------------------- semantic
    def recall_similar(self, text: str, k: int = 5,
                       exclude_current_run: bool = False) -> list[Trial]:
        """The ``k`` stored trials of this strategy whose embedded text is nearest ``text``."""
        query = embed(text)
        name = embedder_name()
        sql = ("SELECT t.variant_id, t.params_json, t.score, t.verdict, t.rationale, "
               "t.embedding FROM trials t JOIN runs r ON r.run_id = t.run_id "
               "WHERE r.strategy = ? AND t.embedder = ?")
        args: list[Any] = [self.strategy, name]
        if exclude_current_run:
            sql += " AND t.run_id != ?"
            args.append(self.run_id)
        scored: list[tuple[float, int, Trial]] = []
        for i, (vid, pj, score, verdict, rationale, blob) in enumerate(
                self._conn.execute(sql + " ORDER BY t.id", args)):
            sim = cosine(query, _unpack(blob)) if blob else 0.0
            scored.append((sim, i, Trial(vid, json.loads(pj), score, verdict, rationale)))
        scored.sort(key=lambda s: (-s[0], s[1]))
        return [t for _, _, t in scored[:k]]

    # -------------------------------------------------------------- procedural
    def _prior_rows(self) -> list[tuple[float, dict[str, float]]]:
        return [(score, json.loads(pj)) for score, pj in self._conn.execute(
            "SELECT t.score, t.params_json FROM trials t JOIN runs r ON r.run_id = t.run_id "
            "WHERE r.strategy = ? AND t.run_id != ? ORDER BY t.id",
            (self.strategy, self.run_id))]

    def priors(self) -> dict[str, tuple[float, float]] | None:
        """Sampling box learned from previous runs' top-quartile trials, or ``None``.

        Computed once per instance: previous runs cannot change during this one, and a
        box that shifted mid-run would make the proposer non-reproducible.
        """
        if self._priors_cache is False:
            self._priors_cache = _top_quartile_box(self._prior_rows())
        return self._priors_cache  # type: ignore[return-value]

    def prior_run_count(self) -> int:
        """How many previous runs of this strategy have recorded trials."""
        (n,) = self._conn.execute(
            "SELECT COUNT(DISTINCT t.run_id) FROM trials t JOIN runs r ON r.run_id = t.run_id "
            "WHERE r.strategy = ? AND t.run_id != ?", (self.strategy, self.run_id)).fetchone()
        return int(n)

    def refresh_priors(self) -> dict[str, tuple[float, float]] | None:
        """Materialise the top-quartile box over *all* runs of this strategy into the
        ``priors`` table (for inspection and the next run's header). Called at run end."""
        rows = [(score, json.loads(pj)) for score, pj in self._conn.execute(
            "SELECT t.score, t.params_json FROM trials t JOIN runs r ON r.run_id = t.run_id "
            "WHERE r.strategy = ? ORDER BY t.id", (self.strategy,))]
        box = _top_quartile_box(rows)
        if box is None:
            return None
        (n_runs,) = self._conn.execute(
            "SELECT COUNT(DISTINCT t.run_id) FROM trials t JOIN runs r ON r.run_id = t.run_id "
            "WHERE r.strategy = ?", (self.strategy,)).fetchone()
        now = _now()
        self._conn.executemany(
            "INSERT OR REPLACE INTO priors (strategy, param, lo, hi, n_runs, updated_at) "
            "VALUES (?,?,?,?,?,?)",
            [(self.strategy, p, lo, hi, n_runs, now) for p, (lo, hi) in box.items()])
        self._conn.commit()
        return box

    # -------------------------------------------------------------- promotions
    def record_promotion(self, variant_id: str, decided_by: str = "human") -> None:
        """Record a promotion. Only a human decision is ever written."""
        if decided_by != "human":
            raise ValueError("only a human-approved promotion may be recorded")
        self._conn.execute(
            "INSERT OR IGNORE INTO promotions (run_id, variant_id, decided_by, decided_at) "
            "VALUES (?,?,?,?)", (self.run_id, variant_id, decided_by, _now()))
        self._conn.commit()

    def promotions(self) -> list[dict[str, Any]]:
        cols = ("id", "run_id", "variant_id", "decided_by", "decided_at")
        return [dict(zip(cols, row, strict=True)) for row in self._conn.execute(
            f"SELECT {', '.join(cols)} FROM promotions ORDER BY id")]

    # ------------------------------------------------------------------- misc
    def runs(self) -> list[dict[str, Any]]:
        """Every run in the store (all strategies), oldest first, with its trial count."""
        cols = ("run_id", "strategy", "seed", "started_at", "arm", "n_trials")
        return [dict(zip(cols, row, strict=True)) for row in self._conn.execute(
            "SELECT r.run_id, r.strategy, r.seed, r.started_at, r.arm, COUNT(t.id) "
            "FROM runs r LEFT JOIN trials t ON t.run_id = r.run_id "
            "GROUP BY r.run_id ORDER BY r.started_at, r.rowid")]

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
