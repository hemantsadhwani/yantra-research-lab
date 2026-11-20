"""Learn from the ledger: rejection-sampling fine-tuning of a small researcher model.

A teacher (DeepSeek V3.2 on Bedrock) runs studies on CALIBRATION seeds (1000+). Code labels every
researcher proposal from the walk-forward results it produced (``label.py``). Only code-verified
wins become training data (``dataset.py``, with a SHA-256 hash). A small open model is QLoRA-tuned
on them locally (``train_qlora.py``) and served locally as the researcher (``llm_gateway.hf_local_provider``).
It is evaluated once on BENCHMARK seeds 1-20, which nothing in this package may generate,
train on or see before that eval (``seeds.py``; tested in research_bench/tests/test_ledger_ft.py).

Every paid call goes through ``spend.CappedProvider``: a hard USD cap per stage and in total,
reserved before the call at worst-case cost, logged per call to ``.cache/ledger_ft/spend.jsonl``.

Imports: ``seeds``, ``label`` and ``dataset`` are stdlib (plus the stdlib quant engine); ``spend``
needs ``llm_gateway`` (pydantic). ``teacher`` and ``evaluate`` need the ``agents`` + ``llm`` extras;
``train_qlora`` and local serving need the ``ledger-ft`` extra (torch, CUDA). None of this is on the
zero-dependency default path.
"""
