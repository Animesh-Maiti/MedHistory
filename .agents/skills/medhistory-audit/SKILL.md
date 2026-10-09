---
name: medhistory-audit
description: Audits multi-visit PDF prescriptions and clinical text with local BioBERT, extracts medication doses, checks cumulative daily exposure and cross-prescription interactions, and protects patient history from unsafe updates.
license: MIT
compatibility: Python >= 3.10, PyTorch, Transformers, pypdf
---

# MedHistory Audit

MedHistory reconciles each new prescription against the patient's persisted
multi-visit profile. It extracts medication and disease entities plus mg dose
and frequency, checks cumulative daily limits before cross-prescription DDI
rules, and writes a dated visit only after all gates pass. It is a deterministic
demonstration workflow, not a replacement for clinical judgment or a validated
medical device.

## Verification workflow

1. **Ingest and extract.** Pass raw clinical text with `--text`, or a PDF with
  `--pdf-path`, to `scripts/extract_entities.py`. PDF pages are read locally
  with pypdf. The script runs the local BioBERT token-classification
  checkpoint and emits character-offset entities plus drug and disease arrays.
2. **Reconcile.** Pass that JSON and the patient identifier to
  `scripts/audit_safety.py`. The runner loads the patient chart from
  `assets/patients/` and executes the safety gates in order:
  - **Gate 1: cumulative dose.** Block only when a known proposed single dose
    or known active-plus-proposed total strictly exceeds `max_daily_limits_mg`.
    If the existing dose is unknown and the new dose is safe, initialize the
    active dose baseline on approval.
  - **Gate 2: DDI.** Compare proposed drugs with active history and each other
    against `interactions`, in either pair order.
  - **Gate 3: approval and persistence.** If neither gate blocks, append
    structured ACTIVE medication records, an audit event, and a dated visit.
3. **Decide and communicate.** `OVERDOSE_ALERT` means Gate 1 blocked the change;
  `DDI_BLOCKED` means Gate 2 found a contraindication. Both return before any
  patient-file write. `APPROVED` records the new visit; the first approval
  returns the confirmation `Initial clinical baseline registered.`

## Decision rules

- **OVERDOSE_ALERT:** A known proposed single daily dose or known cumulative
  daily total strictly exceeds its configured ceiling. Do not update the chart.
  If the previous dose is unknown, do not block solely for that reason: record
  the newly proposed dose as the updated baseline on approval and inform the
  clinician that the historical dose was unavailable.
- **DDI_BLOCKED:** A configured high-severity interaction is present between a
  proposed and previously active medication. Do not update the chart. Show the
  conflicting pair, severity, risk, and biological mechanism.
- **APPROVED:** No configured interaction was found. The deterministic runner
  commits structured ACTIVE medication details, appends a dated visit and
  audit event. This means only that the configured checks found no match; it
  is not a claim that a prescription is clinically safe.
- If extraction fails, the label mapping is uncertain, or chart/rule data is
  unavailable, stop the workflow and report the error rather than treating it
  as a successful audit.

When either gate blocks, refuse the EHR/chart mutation and cite the dose limit
or matched pair, severity, risk, and biological mechanism. Failed and blocked
audits are not appended to patient history, preserving read-only behavior.

## External Agent Operation

Cursor, Claude Code, Codex, and other compatible agents should read this skill
before processing a prescription. Invoke `scripts/extract_entities.py` first,
then pass its JSON output to `scripts/audit_safety.py` with the selected patient
ID. Do not edit patient JSON directly, bypass either verification gate, or
proceed after a `BLOCKED` result.

## Local model

The default checkpoint path is `model/biobert-ner-final/` at the project root.
The supplied checkpoint currently exposes generic `LABEL_0` through `LABEL_4`
labels. The extractor's generic-label fallback assumes the conventional order
`O`, `B-DRUG`, `I-DRUG`, `B-DISEASE`, `I-DISEASE`; verify this against the
checkpoint's training metadata before relying on its output. Named BIO labels
are preferred.