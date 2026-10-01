# Diagrams

draw.io files, generated from Python so they can be diffed and regenerated. Open them in
draw.io (desktop or app.diagrams.net) or the VS Code Draw.io extension.

| File | Pages | Generator |
|---|---|---|
| `yantra_slm_finetuning.drawio` | architecture (data → fine-tuning → S3 → MLflow → serving), v1 vs v2 champion, S3 bucket layout, session lifecycle | `make_slm_diagram.py` |
| `yantra_dev_provisioning.drawio` | AWS big picture, provisioning steps, who can do what (IAM) | `make_diagram.py` |

Regenerate with the standard library only: `python docs/diagrams/make_slm_diagram.py` (writes
next to the script). Edit the generator, not the `.drawio`, or the next run overwrites the change.
