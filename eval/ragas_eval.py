"""RAGAS-style evaluation of the chatbot's retrieval + answer path (12 golden questions).

    python -m eval.ragas_eval --fake                   # offline, deterministic (CI)
    python -m eval.ragas_eval --provider anthropic     # Haiku 4.5 via llm_gateway answers AND judges

What runs. For each row of ``eval/datasets/ragas_golden.jsonl`` (question, ground_truth,
expected_source) the script reproduces the chatbot's answer path from ``backend/app.py``:
top-4 vector retrieval (``FaissRetriever`` over the same corpus ``ingest.py`` builds, in a
temp dir), keyword-routed book docs (``books.select_docs``) prepended ahead of the chunks,
the same system prompt and user-message shape, the input refusal policy and the output
filter. It then scores the four RAGAS metrics.

Why a local mirror and not the ``ragas`` package. ``ragas`` 0.4.3 (the current release,
``<1``) installs on Python 3.13 but fails at import in this environment:
``ModuleNotFoundError: No module named 'langchain_community.chat_models.vertexai'``
(langchain-community 0.4.x, which is what resolves next to the langchain-core 1.x that
LangGraph 1.x needs). Details in ``results/ragas_2026-09-30.md``. So the four metrics are
implemented here, following the RAGAS definitions, with the LLM steps behind a small
``Judge`` interface:

    faithfulness       claims in the answer supported by the retrieved context / all claims
    answer_relevancy   mean cosine(question, questions regenerated from the answer);
                       0 if the judge calls the answer noncommittal
    context_precision  mean of precision@k over the ranks k where the context was
                       useful for reaching the ground truth (rank-aware)
    context_recall     ground-truth sentences attributable to the retrieved context / all

``--fake`` uses ``LexicalJudge`` (token-overlap rules, hashed bag-of-words embeddings) and an
extractive fake answerer. It proves the harness end to end, offline. **It does not measure
answer quality**, and its numbers must never be quoted as the chatbot's RAGAS scores.
``--provider anthropic`` uses ``LLMJudge`` (structured calls through ``llm_gateway``) with
``claude-haiku-4-5`` as both the answer model and the judge, and fastembed ``bge-small``
(the retriever's model) for answer_relevancy. That mode needs a key and costs cents; it has
not been run for the results file.

Tracked in MLflow when ``MLFLOW_TRACKING_URI`` is set (``eval/mlflow_tracking.py``).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Protocol

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"
GOLDEN = Path(__file__).resolve().parent / "datasets" / "ragas_golden.jsonl"
TOP_K = 4
METRICS = ("faithfulness", "answer_relevancy", "context_precision", "context_recall")
JUDGE_MODEL = "claude-haiku-4-5"

# --------------------------------------------------------------------------- #
# Text helpers (stdlib)
# --------------------------------------------------------------------------- #
_TOKEN = re.compile(r"[a-z0-9]+(?:[.,][0-9]+)*")
_STOPWORDS = (
    "a an the of to in on for and or is are was were be been it its this that these those "
    "with by as at from what which how does do did has have had over per into than then "
    "their there they them his her our your you we i my me so if not no can will would "
    "about after before between each most more much very also only just"
)
_STOP = frozenset(_STOPWORDS.split())
_SENT = re.compile(r"(?<=[.!?])\s+|\n+")


def content_tokens(text: str) -> set[str]:
    return {t for t in _TOKEN.findall(text.lower()) if t not in _STOP}


def sentences(text: str) -> list[str]:
    """Sentences / bullet lines with at least two content tokens."""
    out = []
    for s in _SENT.split(text):
        s = s.strip().lstrip("-*# ").strip()
        if len(content_tokens(s)) >= 2:
            out.append(s)
    return out


def coverage(part: str | set[str], whole: str | set[str]) -> float:
    """Share of ``part``'s content tokens that occur in ``whole``."""
    p = part if isinstance(part, set) else content_tokens(part)
    w = whole if isinstance(whole, set) else content_tokens(whole)
    return len(p & w) / len(p) if p else 0.0


def hashed_embed(text: str, dim: int = 256) -> list[float]:
    vec = [0.0] * dim
    for tok in content_tokens(text):
        h = int.from_bytes(hashlib.blake2b(tok.encode(), digest_size=8).digest(), "big")
        vec[h % dim] += 1.0 if (h >> 32) & 1 else -1.0
    n = math.sqrt(sum(x * x for x in vec))
    return [x / n for x in vec] if n else vec


def cosine(a: list[float], b: list[float]) -> float:
    na, nb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(y * y for y in b))
    return sum(x * y for x, y in zip(a, b, strict=True)) / (na * nb) if na and nb else 0.0


# --------------------------------------------------------------------------- #
# The judge interface: the four LLM steps RAGAS uses
# --------------------------------------------------------------------------- #
class Judge(Protocol):
    name: str

    def statements(self, question: str, answer: str) -> list[str]: ...
    def supported(self, statements: list[str], context: str) -> list[int]: ...
    def regenerate_questions(self, answer: str, n: int) -> tuple[list[str], bool]: ...
    def useful(self, question: str, context: str, ground_truth: str) -> int: ...
    def attributable(self, gt_sentences: list[str], context: str) -> list[int]: ...


class LexicalJudge:
    """Deterministic stand-in for the LLM judge. Token overlap, no model. Harness only."""

    name = "fake-lexical"
    SUPPORT, USEFUL, ATTRIB = 0.7, 0.5, 0.6
    NONCOMMITTAL = ("i don't know", "i do not know", "not sure", "i don't have", "cannot answer")

    def statements(self, question: str, answer: str) -> list[str]:
        return sentences(answer)

    def supported(self, statements: list[str], context: str) -> list[int]:
        ctx = content_tokens(context)
        return [int(coverage(s, ctx) >= self.SUPPORT) for s in statements]

    def regenerate_questions(self, answer: str, n: int) -> tuple[list[str], bool]:
        # The "regenerated question" is each answer sentence's content words.
        gens = [" ".join(sorted(content_tokens(s))) for s in sentences(answer)[:n]]
        return gens, any(p in answer.lower() for p in self.NONCOMMITTAL)

    def useful(self, question: str, context: str, ground_truth: str) -> int:
        return int(coverage(ground_truth, context) >= self.USEFUL)

    def attributable(self, gt_sentences: list[str], context: str) -> list[int]:
        ctx = content_tokens(context)
        return [int(coverage(s, ctx) >= self.ATTRIB) for s in gt_sentences]


class LLMJudge:
    """The RAGAS LLM steps as structured calls through ``llm_gateway`` (Haiku 4.5)."""

    def __init__(self, provider: Any):
        from pydantic import BaseModel

        class Statements(BaseModel):
            statements: list[str]

        class Verdicts(BaseModel):
            verdicts: list[int]  # one 0/1 per input item, same order

        class Regenerated(BaseModel):
            questions: list[str]
            noncommittal: int

        class One(BaseModel):
            reason: str
            verdict: int

        self.provider = provider
        self.name = f"{getattr(provider, 'name', '?')}/{getattr(provider, 'model', '?')}"
        self._S, self._V, self._R, self._O = Statements, Verdicts, Regenerated, One
        self.cost_usd = 0.0

    def _ask(self, system: str, user: str, schema: Any) -> Any:
        resp = self.provider.complete(system=system, messages=[{"role": "user", "content": user}],
                                      max_tokens=800, schema=schema)
        self.cost_usd += resp.cost_usd
        return resp.parsed

    @staticmethod
    def _items(xs: list[str]) -> str:
        return "\n".join(f"{i + 1}. {x}" for i, x in enumerate(xs))

    def _verdicts(self, system: str, user: str, n: int) -> list[int]:
        v = self._ask(system, user, self._V).verdicts
        return [int(bool(x)) for x in (v + [0] * n)[:n]]

    def statements(self, question: str, answer: str) -> list[str]:
        return self._ask(
            "Break the answer into standalone factual statements. One claim per statement, "
            "no pronouns, keep numbers exact.",
            f"Question: {question}\nAnswer: {answer}", self._S).statements

    def supported(self, statements: list[str], context: str) -> list[int]:
        if not statements:
            return []
        return self._verdicts(
            "For each numbered statement, answer 1 if it can be directly inferred from the "
            "context, else 0. Return one verdict per statement, in order.",
            f"Context:\n{context}\n\nStatements:\n{self._items(statements)}", len(statements))

    def regenerate_questions(self, answer: str, n: int) -> tuple[list[str], bool]:
        r = self._ask(
            f"Write {n} different questions that the answer below answers. Set noncommittal "
            "to 1 if the answer is evasive or vague (e.g. 'I don't know'), else 0.",
            f"Answer: {answer}", self._R)
        return r.questions[:n], bool(r.noncommittal)

    def useful(self, question: str, context: str, ground_truth: str) -> int:
        return int(bool(self._ask(
            "Given a question, a reference answer and one context passage, verdict 1 if the "
            "passage was useful in arriving at the reference answer, else 0.",
            f"Question: {question}\nReference answer: {ground_truth}\nContext:\n{context}",
            self._O).verdict))

    def attributable(self, gt_sentences: list[str], context: str) -> list[int]:
        if not gt_sentences:
            return []
        return self._verdicts(
            "For each numbered sentence of the reference answer, answer 1 if it can be "
            "attributed to the context, else 0. One verdict per sentence, in order.",
            f"Context:\n{context}\n\nSentences:\n{self._items(gt_sentences)}", len(gt_sentences))


# --------------------------------------------------------------------------- #
# The four metrics (RAGAS definitions; the judge supplies the LLM steps)
# --------------------------------------------------------------------------- #
def faithfulness(question: str, answer: str, contexts: list[str], judge: Judge) -> float:
    stmts = judge.statements(question, answer)
    if not stmts:
        return 0.0  # RAGAS returns NaN here; 0 keeps the mean defined and is the harsher call
    v = judge.supported(stmts, "\n\n".join(contexts))
    return sum(v) / len(stmts)


def answer_relevancy(question: str, answer: str, judge: Judge, embed, n: int = 3) -> float:
    gens, noncommittal = judge.regenerate_questions(answer, n)
    if noncommittal or not gens:
        return 0.0
    q = embed(question)
    return sum(cosine(q, embed(g)) for g in gens) / len(gens)


def context_precision(question: str, contexts: list[str], ground_truth: str,
                      judge: Judge) -> float:
    v = [judge.useful(question, c, ground_truth) for c in contexts]
    hits, total = 0, 0.0
    for k, vk in enumerate(v, start=1):
        hits += vk
        total += (hits / k) * vk
    return total / hits if hits else 0.0


def context_recall(contexts: list[str], ground_truth: str, judge: Judge) -> float:
    gt = sentences(ground_truth)
    if not gt:
        return 0.0
    return sum(judge.attributable(gt, "\n\n".join(contexts))) / len(gt)


# --------------------------------------------------------------------------- #
# The chatbot answer path (mirrors backend/app.py chat())
# --------------------------------------------------------------------------- #
@dataclass
class Turn:
    answer: str
    contexts: list[str]
    sources: list[str] = field(default_factory=list)
    refused: bool = False


class ExtractiveFakeProvider:
    """Offline answerer: returns the two context sentences that best cover the question."""

    name, model = "fake", "extractive-1"

    def complete(self, *, system: str, messages: list[dict], max_tokens: int,
                 schema: Any = None, cache_system: bool = True) -> Any:
        user = messages[-1]["content"]
        ctx, _, q = user.rpartition("\n\nQuestion: ")
        qt = content_tokens(q)
        cands = [s for s in sentences(ctx) if not s.startswith("[")]
        ranked = sorted(range(len(cands)), key=lambda i: (-len(qt & content_tokens(cands[i])), i))
        text = " ".join(cands[i].rstrip(".") + "." for i in sorted(ranked[:2]))
        return SimpleNamespace(text=text, cost_usd=0.0)


def _backend_imports():
    if str(BACKEND) not in sys.path:
        sys.path.insert(0, str(BACKEND))
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    import books
    import guardrails
    import ingest
    from retriever import FaissRetriever

    return books, guardrails, ingest, FaissRetriever


def build_retriever(embed_texts, workdir: str):
    """Index the chatbot corpus exactly as ``ingest.build_chunks`` assembles it."""
    _, _, ingest, FaissRetriever = _backend_imports()
    r = FaissRetriever(path=workdir, embed_fn=embed_texts)
    r.index(ingest.build_chunks())
    return r


def answer_once(question: str, retriever: Any, book_docs: list, provider: Any) -> Turn:
    books, guardrails, _, _ = _backend_imports()
    if guardrails.detect_injection(question) or guardrails.should_refuse(question):
        return Turn(answer=guardrails.REFUSAL_ANSWER, contexts=[], refused=True)
    safe = guardrails.redact_pii(question)
    chunks = retriever.search(safe, k=TOP_K)
    selected = books.select_docs(question, book_docs, [])
    titles = {d.title for d in selected}
    kept = [c for c in chunks if c.title not in titles]
    contexts = [d.context_block() for d in selected] + [f"[{c.title}]\n{c.text}" for c in kept]
    sources = [d.source for d in selected] + [c.source for c in kept]
    context = "\n\n".join(contexts) if contexts else "(no retrieved context)"
    resp = provider.complete(
        system=guardrails.SYSTEM_PROMPT + "\n\n" + books.BOOKS_SYSTEM_ADDENDUM,
        messages=[{"role": "user", "content":
                   "Retrieved context (methodology and, where relevant, published backtest "
                   f"outputs):\n{context}\n\nQuestion: {safe}"}],
        max_tokens=1024, cache_system=True)
    answer = resp.text.strip()
    ok, _ = guardrails.check_output(answer)
    if not ok:
        return Turn(answer=guardrails.REFUSAL_ANSWER, contexts=contexts, sources=sources,
                    refused=True)
    return Turn(answer=answer, contexts=contexts, sources=sources)


# --------------------------------------------------------------------------- #
# Runner
# --------------------------------------------------------------------------- #
def load_golden(path: Path = GOLDEN) -> list[dict[str, str]]:
    rows = []
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        row = json.loads(line)
        missing = {"id", "question", "ground_truth", "expected_source"} - set(row)
        if missing:
            raise ValueError(f"{path.name}:{n}: missing {sorted(missing)}")
        rows.append(row)
    return rows


def evaluate(rows: list[dict[str, str]], provider: Any, judge: Judge, embed_one,
             embed_texts) -> dict[str, Any]:
    books, _, _, _ = _backend_imports()
    book_docs = books.load_books()
    per: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="yantra-ragas-") as tmp:
        retriever = build_retriever(embed_texts, tmp)
        for row in rows:
            q, gt = row["question"], row["ground_truth"]
            t = answer_once(q, retriever, book_docs, provider)
            want = Path(row["expected_source"]).name
            per.append({
                "id": row["id"], "question": q, "refused": t.refused,
                "hit": any(Path(s).name == want for s in t.sources),
                "faithfulness": faithfulness(q, t.answer, t.contexts, judge),
                "answer_relevancy": answer_relevancy(q, t.answer, judge, embed_one),
                "context_precision": context_precision(q, t.contexts, gt, judge),
                "context_recall": context_recall(t.contexts, gt, judge),
            })
    means = {m: sum(r[m] for r in per) / len(per) for m in METRICS}
    return {"rows": per, "means": means, "hits": sum(r["hit"] for r in per), "n": len(per)}


def to_markdown(out: dict[str, Any], label: str) -> str:
    lines = [f"**{label}**", "",
             ("| id | question | faithfulness | answer_relevancy | context_precision | "
              "context_recall | expected source retrieved |"),
             "|---|---|---:|---:|---:|---:|:---:|"]
    for r in out["rows"]:
        lines.append(f"| {r['id']} | {r['question']} | {r['faithfulness']:.2f} | "
                     f"{r['answer_relevancy']:.2f} | {r['context_precision']:.2f} | "
                     f"{r['context_recall']:.2f} | {'yes' if r['hit'] else 'no'} |")
    m = out["means"]
    lines.append(f"| **mean** | {out['n']} questions | **{m['faithfulness']:.2f}** | "
                 f"**{m['answer_relevancy']:.2f}** | **{m['context_precision']:.2f}** | "
                 f"**{m['context_recall']:.2f}** | **{out['hits']}/{out['n']}** |")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--fake", action="store_true",
                      help="offline: extractive answerer + lexical judge (proves the harness)")
    mode.add_argument("--provider", choices=["anthropic", "bedrock", "ollama"],
                      help="real answerer and judge through llm_gateway (needs a key; costs cents)")
    ap.add_argument("--model", default=JUDGE_MODEL, help="answer + judge model (default Haiku 4.5)")
    ap.add_argument("--golden", type=Path, default=GOLDEN)
    ap.add_argument("--out", type=Path, help="also write the markdown table here")
    args = ap.parse_args(argv)
    rows = load_golden(args.golden)

    if args.fake:
        # Keep an offline run offline even if backend/ingest.py loads a local .env.
        for k in ("ANTHROPIC_API_KEY", "LOGFIRE_TOKEN", "QDRANT_URL"):
            os.environ[k] = ""
        provider, judge = ExtractiveFakeProvider(), LexicalJudge()
        embed_one = hashed_embed

        def embed_texts(texts):
            return [hashed_embed(t) for t in texts]

        label = ("fake judge: proves the harness, not answer quality "
                 "(extractive fake answerer, lexical judge, hashed bag-of-words embeddings)")
    else:
        try:
            from load_env import load_env
            load_env()
        except ImportError:
            pass
        _backend_imports()
        from embeddings import embed as fe_embed  # backend fastembed bge-small, lazily loaded

        from llm_gateway import get_provider

        provider = get_provider(args.provider, model=args.model)
        judge = LLMJudge(provider)
        embed_texts = fe_embed

        def embed_one(text):
            return fe_embed([text])[0]

        label = (f"{provider.name}/{provider.model} answers and judges; retriever and "
                 "answer_relevancy embeddings: fastembed bge-small")

    out = evaluate(rows, provider, judge, embed_one, embed_texts)
    table = to_markdown(out, label)
    print(f"ragas eval · judge {judge.name} · {out['n']} golden questions · top-{TOP_K}\n")
    print(table)
    if args.out:
        args.out.write_text(table + "\n", encoding="utf-8")

    from eval.mlflow_tracking import track_run  # no-op unless MLFLOW_TRACKING_URI is set

    track_run("ragas_eval", params={"mode": "fake" if args.fake else "provider",
                                    "judge": judge.name, "questions": out["n"], "top_k": TOP_K},
              metrics={**out["means"], "expected_source_hits": out["hits"]},
              artifacts=[args.out] if args.out else [])

    bad = [m for m in METRICS if not 0.0 <= out["means"][m] <= 1.0]
    if bad:
        print(f"  FAIL: metric out of [0, 1]: {bad}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
