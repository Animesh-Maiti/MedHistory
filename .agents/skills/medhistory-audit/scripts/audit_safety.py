"""Reconcile extracted medications with patient history and configured DDI rules."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SKILL_DIR = Path(__file__).resolve().parents[1]
PATIENTS_DIR = SKILL_DIR / "assets" / "patients"
DDI_RULES_FILE = SKILL_DIR / "references" / "ddi_rules.json"


def _load_extracted(value: str) -> dict[str, Any]:
    try:
        normalized = value.strip()
        if normalized.startswith(("{", "[")):
            data = json.loads(normalized)
        else:
            candidate = Path(normalized)
            if candidate.is_file():
                data = json.loads(candidate.read_text(encoding="utf-8"))
            else:
                data = json.loads(normalized)
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("--extracted-json must be valid JSON or a path to JSON") from error
    if not isinstance(data, dict):
        raise ValueError("Extracted data must be a JSON object")
    for key in ("extracted_drugs", "extracted_diseases"):
        items = data.get(key, [])
        if not isinstance(items, list) or any(not isinstance(item, str) for item in items):
            raise ValueError(f"{key} must be an array of strings")
    return data


def _drug_key(value: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", value.casefold()))


def _matches_drug(mention: str, canonical_name: str) -> bool:
    mention_key = _drug_key(mention)
    canonical_key = _drug_key(canonical_name)
    return mention_key == canonical_key or mention_key.startswith(canonical_key + " ")


def _unique_mentions(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        cleaned = value.strip()
        key = _drug_key(cleaned)
        if cleaned and key not in seen:
            result.append(cleaned)
            seen.add(key)
    return result


def _find_conflicts(
    active_medications: list[str], proposed_medications: list[str], rules: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    medications = _unique_mentions(active_medications + proposed_medications)
    conflicts: list[dict[str, Any]] = []
    for rule in rules:
        first, second = rule["pair"]
        has_first = any(_matches_drug(medication, first) for medication in medications)
        has_second = any(_matches_drug(medication, second) for medication in medications)
        if has_first and has_second:
            conflicts.append(
                {
                    "pair": [first, second],
                    "severity": rule["severity"],
                    "risk": rule["risk"],
                    "mechanism": rule["mechanism"],
                }
            )
    return conflicts


def _write_patient_atomically(path: Path, patient: dict[str, Any]) -> None:
    temporary_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.stem}-",
            suffix=".tmp",
            delete=False,
        ) as temporary_file:
            temporary_path = temporary_file.name
            json.dump(patient, temporary_file, indent=2, ensure_ascii=False)
            temporary_file.write("\n")
        os.replace(temporary_path, path)
    finally:
        if temporary_path and os.path.exists(temporary_path):
            os.unlink(temporary_path)


def audit_patient(patient_id: str, extracted: dict[str, Any]) -> dict[str, Any]:
    if not re.fullmatch(r"[A-Za-z0-9_-]+", patient_id):
        raise ValueError("Patient ID may contain only letters, numbers, underscores, and hyphens")
    patient_path = (PATIENTS_DIR / f"{patient_id}.json").resolve()
    if patient_path.parent != PATIENTS_DIR.resolve():
        raise ValueError("Invalid patient path")
    patient = json.loads(patient_path.read_text(encoding="utf-8"))
    rules = json.loads(DDI_RULES_FILE.read_text(encoding="utf-8"))
    proposed = _unique_mentions(extracted.get("extracted_drugs", []))
    active = patient.get("active_medications", [])
    conflicts = _find_conflicts(active, proposed, rules)

    if conflicts:
        return {
            "status": "BLOCKED",
            "patient_id": patient_id,
            "conflicts": conflicts,
            "message": "Configured drug-drug interaction detected; patient chart was not changed.",
        }

    active_keys = {_drug_key(item) for item in active}
    added = [item for item in proposed if _drug_key(item) not in active_keys]
    patient["active_medications"].extend(added)
    patient.setdefault("audit_history", []).append(
        {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "status": "APPROVED",
            "extracted_drugs": proposed,
            "extracted_diseases": extracted.get("extracted_diseases", []),
        }
    )
    _write_patient_atomically(patient_path, patient)
    return {
        "status": "APPROVED",
        "patient_id": patient_id,
        "conflicts": [],
        "added_medications": added,
        "active_medications": patient["active_medications"],
        "message": "No configured interaction was found; the patient chart was updated.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--patient-id", required=True, help="Patient chart identifier")
    parser.add_argument(
        "--extracted-json",
        required=True,
        help="Extracted JSON object or path to a JSON file",
    )
    args = parser.parse_args()
    try:
        result = audit_patient(args.patient_id, _load_extracted(args.extracted_json))
    except Exception as error:
        print(f"Safety audit failed: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())