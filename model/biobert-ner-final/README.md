# Local BioBERT Checkpoint

This directory contains the tokenizer and model configuration required by the
MedHistory token-classification extractor. The `model.safetensors` weights are
approximately 411 MiB and are intentionally excluded from GitHub commits.

## Provision Weights

Obtain the matching `model.safetensors` artifact from the checkpoint provider
used by your team or evaluator. Download it, copy it from approved local
storage, or mount the artifact into this directory with the exact filename:

```text
model/biobert-ner-final/model.safetensors
```

For example, from the project root in PowerShell:

```powershell
Copy-Item "E:\model-artifacts\model.safetensors" `
  "model\biobert-ner-final\model.safetensors"
```

The file must match the supplied `config.json` and tokenizer files. MedHistory
loads the model locally and does not fetch weights at runtime. Confirm the
artifact's provenance and license before redistribution or use.
