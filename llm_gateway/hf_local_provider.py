"""A local Hugging Face model on this machine's GPU, optionally with a LoRA adapter. $0 per call.

    get_provider("hf_local", "Qwen/Qwen2.5-3B-Instruct")                       # untuned base
    HFLocalProvider("Qwen/Qwen2.5-3B-Instruct", adapter=".cache/ledger_ft/adapters/<tag>")   # tuned

Serves the ledger-trained researcher (research_bench.ledger_ft). torch / transformers / peft are
imported on first use only (the ``ledger-ft`` extra), so importing the gateway never needs them.
The adapter is merged into a bf16 copy of the base for speed. One model per (base, adapter) per
process; generation is serialised with a lock, so studies may run in threads.

Structured output: the schema goes in the system prompt (the same suffix the training data used),
the reply is validated, and one repair round-trip runs if it fails (``structured_mode="prompt"``).
Greedy decoding, so a run is reproducible on the same machine.
"""

from __future__ import annotations

import os
import threading
from typing import Any

from pydantic import BaseModel, ValidationError

from llm_gateway.base import (
    REPAIR_TEMPLATE,
    LLMResponse,
    ProviderUnavailable,
    schema_instruction,
    short_error,
    validate_text,
)

DEFAULT_HF_MODEL = "Qwen/Qwen2.5-3B-Instruct"
_CACHE: dict[tuple[str, str | None], tuple[Any, Any]] = {}
_LOAD_LOCK = threading.Lock()
_GEN_LOCK = threading.Lock()


def load(base: str, adapter: str | None) -> tuple[Any, Any]:
    key = (base, adapter)
    with _LOAD_LOCK:
        if key not in _CACHE:
            try:
                import torch
                from transformers import AutoModelForCausalLM, AutoTokenizer
            except ImportError as e:
                raise ProviderUnavailable("install the ledger-ft extra (torch, transformers, peft)") from e
            if not torch.cuda.is_available():
                raise ProviderUnavailable("no CUDA GPU visible to torch")
            tok = AutoTokenizer.from_pretrained(base)
            model = AutoModelForCausalLM.from_pretrained(base, dtype=torch.bfloat16, device_map="cuda")
            if adapter:
                from peft import PeftModel
                model = PeftModel.from_pretrained(model, adapter).merge_and_unload()
            model.eval()
            _CACHE[key] = (tok, model)
        return _CACHE[key]


class HFLocalProvider:
    name = "hf_local"
    cost_label = "local"

    def __init__(self, model: str | None = None, adapter: str | None = None) -> None:
        self.base = model or os.environ.get("HF_LOCAL_MODEL") or DEFAULT_HF_MODEL
        self.adapter = adapter or os.environ.get("HF_LOCAL_ADAPTER") or None
        tag = os.path.basename(os.path.normpath(self.adapter)) if self.adapter else ""
        self.model = self.base + (f"+lora:{tag}" if tag else "")

    def _generate(self, system: str, messages: list[dict], max_tokens: int) -> tuple[str, int, int]:
        import torch
        tok, model = load(self.base, self.adapter)
        chat = [{"role": "system", "content": system}, *messages]
        prompt = tok.apply_chat_template(chat, tokenize=False, add_generation_prompt=True)
        ids = tok(prompt, return_tensors="pt").to(model.device)
        with _GEN_LOCK, torch.inference_mode():
            out = model.generate(**ids, max_new_tokens=max_tokens, do_sample=False, temperature=None,
                                 top_p=None, top_k=None, pad_token_id=tok.eos_token_id)
        new = out[0, ids["input_ids"].shape[1]:]
        return tok.decode(new, skip_special_tokens=True).strip(), int(ids["input_ids"].shape[1]), len(new)

    def complete(self, *, system: str, messages: list[dict], max_tokens: int,
                 schema: type[BaseModel] | None = None, cache_system: bool = True) -> LLMResponse:
        sys_text = system + schema_instruction(schema) if schema is not None else system
        text, tin, tout = self._generate(sys_text, messages, max_tokens)
        parsed = None
        if schema is not None:
            try:
                parsed = validate_text(schema, text)
            except ValidationError as err:
                repair = [*messages, {"role": "assistant", "content": text or "(empty)"},
                          {"role": "user", "content": REPAIR_TEMPLATE.format(error=short_error(err))}]
                text, i2, o2 = self._generate(sys_text, repair, max_tokens)
                tin, tout = tin + i2, tout + o2
                parsed = validate_text(schema, text)      # raises if still invalid
        return LLMResponse(text=text, parsed=parsed, provider=self.name, model=self.model,
                           input_tokens=tin, output_tokens=tout, cost_usd=0.0,
                           structured_mode="prompt" if schema is not None else "none")
