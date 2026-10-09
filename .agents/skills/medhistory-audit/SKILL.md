---
name: medhistory-audit
description: Audits PDF prescriptions and clinical text using local BioBERT token classification, highlights extracted drug and disease entities, and cross-checks patient history against contraindication rules to prevent adverse drug events.
license: MIT
compatibility: Requires Python 3.10+, PyTorch, Transformers, pypdf
---

# MedHistory Audit

MedHistory audits a proposed prescription or consultation note against a local
patient chart and a curated drug-drug interaction (DDI) rule set. It is a
deterministic demonstration workflow, not a replacement for clinical judgment
or a validated medical device.

## Verification workflow

1. **Ingest and extract.** Pass raw clinical text with `--text`, or a PDF with
  `--pdf-path`, to `scripts/extract_entities.py`. PDF pages are read locally
  with pypdf. The script runs the local BioBERT token-classification
  checkpoint and emits character-offset entities plus drug and disease arrays.
2. **Reconcile.** Pass that JSON and the patient identifier to
   `scripts/audit_safety.py`. The runner loads the patient chart from
   `assets/patients/`, compares active and proposed medications against
   `references/ddi_rules.json` in either pair order, and returns a JSON result.
3. **Decide and communicate.** A matching DDI rule yields `BLOCKED`; no chart
   fields or audit history are changed. With no matching rule, the result is
   `APPROVED`; newly mentioned drugs are added once and an audit entry with a
   UTC timestamp is recorded.

## Decision rules

- **BLOCKED:** At least one configured high-severity interaction is present
  between a proposed drug and an active or other proposed drug. Do not update
  the chart. Show each conflicting pair, severity, risk, and mechanism to the
  clinician, and require clinical review before proceeding.
- **APPROVED:** No configured interaction was found. The deterministic runner
  commits newly extracted drug mentions and records the audit event. This means
  only that this rule set found no match; it is not a claim that a prescription
  is clinically safe.
- If extraction fails, the label mapping is uncertain, or chart/rule data is
  unavailable, stop the workflow and report the error rather than treating it
  as a successful audit.

When status is `BLOCKED`, refuse the EHR/chart mutation and cite the matched
pair, severity, risk, and biological contraindication mechanism to the
clinician. An approval only means that this configured rule set found no match.

## Local model

The default checkpoint path is `model/biobert-ner-final/` at the project root.
The supplied checkpoint currently exposes generic `LABEL_0` through `LABEL_4`
labels. The extractor's generic-label fallback assumes the conventional order
`O`, `B-DRUG`, `I-DRUG`, `B-DISEASE`, `I-DISEASE`; verify this against the
checkpoint's training metadata before relying on its output. Named BIO labels
are preferred.