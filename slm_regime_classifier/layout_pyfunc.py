"""MLflow pyfunc wrapper: base model + layout LoRA adapter -> one layout label per feature string.

Logged by ``distill_layout.py --dataset ... --register NAME`` with the adapter as an artifact and
the base model name in ``model_config``. Loading it pulls the base model from Hugging Face and
applies the adapter, then answers with the same prompt and label parser as training:

    import mlflow
    m = mlflow.pyfunc.load_model("models:/layout-classifier@candidate")
    m.predict(["chars=2410 lines=96 mean_line=25.1 tables=1 table_share=0.42 images=0 ..."])
"""

from __future__ import annotations

import mlflow

try:  # inside the repo
    from slm_regime_classifier.distill_layout import _prompt, parse_label
except ImportError:  # loaded by MLflow from the model's code_paths
    from distill_layout import _prompt, parse_label


class LayoutAdapter(mlflow.pyfunc.PythonModel):
    def load_context(self, context):
        import torch
        from peft import PeftModel
        from transformers import AutoModelForCausalLM, AutoTokenizer

        base = context.model_config["base_model"]
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        dtype = torch.float32 if self.device == "cpu" else (
            torch.bfloat16 if torch.cuda.get_device_capability()[0] >= 8 else torch.float16)
        self.tok = AutoTokenizer.from_pretrained(base)
        model = AutoModelForCausalLM.from_pretrained(base, torch_dtype=dtype).to(self.device)
        self.model = PeftModel.from_pretrained(model, context.artifacts["adapter"]).eval()

    def predict(self, context, model_input, params=None):
        import torch

        rows = model_input["features"].tolist() if hasattr(model_input, "columns") else list(model_input)
        out = []
        with torch.no_grad():
            for features in rows:
                ids = torch.tensor([_prompt(self.tok, features)], device=self.device)
                gen = self.model.generate(input_ids=ids, attention_mask=torch.ones_like(ids),
                                          max_new_tokens=6, do_sample=False,
                                          pad_token_id=self.tok.pad_token_id or self.tok.eos_token_id)
                out.append(parse_label(self.tok.decode(gen[0, ids.shape[1]:], skip_special_tokens=True)))
        return out
