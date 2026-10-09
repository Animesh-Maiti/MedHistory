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
DRUG_ALIASES = {
    "acetaminophen": "paracetamol",
    "tylenol": "paracetamol",
    "advil": "ibuprofen",
    "motrin": "ibuprofen",
    "coumadin": "warfarin",
}


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
    details = data.get("medication_details", [])
    if not isinstance(details, list):
        raise ValueError("medication_details must be an array")
    for detail in details:
        if not isinstance(detail, dict) or not isinstance(detail.get("drug"), str):
            raise ValueError("Each medication detail must include a drug string")
        daily_mg = detail.get("daily_mg")
        if daily_mg is not None and (
            isinstance(daily_mg, bool) or not isinstance(daily_mg, (int, float)) or daily_mg < 0
        ):
            raise ValueError("daily_mg must be a non-negative number or null")
    return data


def _drug_key(value: str) -> str:
    tokens = re.findall(r"[a-z0-9]+", value.strip().casefold())
    if tokens:
        tokens[0] = DRUG_ALIASES.get(tokens[0], tokens[0])
    return " ".join(tokens)


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


def _record_drug(record: str | dict[str, Any]) -> str:
    return record if isinstance(record, str) else str(record.get("drug", ""))


def _is_active_record(record: str | dict[str, Any]) -> bool:
    return isinstance(record, str) or str(record.get("status", "ACTIVE")).upper() == "ACTIVE"


def _dose_limit(drug: str, limits: dict[str, int]) -> tuple[str, int] | None:
    for canonical, limit in limits.items():
        if _matches_drug(drug, canonical) or _matches_drug(canonical, drug):
            return canonical, int(limit)
    return None


def _proposed_records(extracted: dict[str, Any], timestamp: str) -> list[dict[str, Any]]:
    details_by_drug: dict[str, list[dict[str, Any]]] = {}
    display_names: dict[str, str] = {}
    for detail in extracted.get("medication_details", []):
        drug = detail["drug"].strip()
        key = _drug_key(drug)
        if key:
            details_by_drug.setdefault(key, []).append(detail)
            display_names.setdefault(key, drug)
    for drug in _unique_mentions(extracted.get("extracted_drugs", [])):
        key = _drug_key(drug)
        if key:
            details_by_drug.setdefault(key, [])
            display_names.setdefault(key, drug)

    proposed: list[dict[str, Any]] = []
    for key, details in details_by_drug.items():
        known_doses = [detail["daily_mg"] for detail in details if detail.get("daily_mg") is not None]
        dosage_strings = list(
            dict.fromkeys(
                detail["dosage_str"]
                for detail in details
                if isinstance(detail.get("dosage_str"), str) and detail["dosage_str"]
            )
        )
        proposed.append(
            {
                "drug": display_names[key],
                "dosage_str": "; ".join(dosage_strings) or None,
                "daily_mg": sum(known_doses) if known_doses else None,
                "status": "ACTIVE",
                "prescription_date": timestamp,
            }
        )
    return proposed


def _overdose_conflict(
    active: list[str | dict[str, Any]],
    proposed: list[dict[str, Any]],
    limits: dict[str, int],
) -> dict[str, Any] | None:
    for new_record in proposed:
        limit_info = _dose_limit(new_record["drug"], limits)
        if limit_info is None:
            continue
        canonical, maximum = limit_info
        existing = [
            record
            for record in active
            if _is_active_record(record)
            and (
                _matches_drug(_record_drug(record), canonical)
                or _matches_drug(canonical, _record_drug(record))
            )
        ]
        daily_mg = new_record.get("daily_mg")
        if daily_mg is None:
            continue
        if daily_mg > maximum:
            return {
                "drug": canonical,
                "current_daily_mg": None,
                "proposed_daily_mg": daily_mg,
                "total_daily_mg": daily_mg,
                "max_daily_mg": maximum,
                "risk": f"A single {canonical} prescription of {daily_mg:g} mg/day exceeds the configured limit of {maximum:g} mg/day.",
                "mechanism": f"A single-order {canonical} dose above the configured maximum daily dose increases dose-dependent toxicity risk.",
            }
        existing_doses = [
            record.get("daily_mg")
            for record in existing
            if isinstance(record, dict) and isinstance(record.get("daily_mg"), (int, float))
        ]
        if existing and len(existing_doses) != len(existing):
            continue
        current_total = sum(existing_doses) + daily_mg
        if current_total > maximum:
            return {
                "drug": canonical,
                "current_daily_mg": sum(existing_doses),
                "proposed_daily_mg": daily_mg,
                "total_daily_mg": current_total,
                "max_daily_mg": maximum,
                "risk": f"Combined {canonical} intake of {current_total:g} mg/day exceeds the configured limit of {maximum:g} mg/day.",
                "mechanism": f"Repeated {canonical} exposure exceeds the configured maximum daily dose and increases dose-dependent toxicity risk.",
            }
    return None


def _ddi_conflicts(
    active: list[str | dict[str, Any]],
    proposed: list[dict[str, Any]],
    rules: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    conflicts: list[dict[str, Any]] = []
    for rule in rules:
        first, second = rule["pair"]
        for first_index, first_new in enumerate(proposed):
            for second_new in proposed[first_index + 1 :]:
                if (
                    _matches_drug(first_new["drug"], first)
                    and _matches_drug(second_new["drug"], second)
                ) or (
                    _matches_drug(first_new["drug"], second)
                    and _matches_drug(second_new["drug"], first)
                ):
                    conflicts.append(
                        {
                            "pair": [first, second],
                            "new_drug": first_new["drug"],
                            "other_new_drug": second_new["drug"],
                            "severity": rule["severity"],
                            "risk": rule["risk"],
                            "mechanism": rule["mechanism"],
                        }
                    )
        for new_record in proposed:
            new_drug = new_record["drug"]
            for old_record in active:
                if not _is_active_record(old_record):
                    continue
                old_drug = _record_drug(old_record)
                if (
                    _matches_drug(new_drug, first)
                    and _matches_drug(old_drug, second)
                ) or (
                    _matches_drug(new_drug, second)
                    and _matches_drug(old_drug, first)
                ):
                    conflicts.append(
                        {
                            "pair": [first, second],
                            "new_drug": new_drug,
                            "active_drug": old_drug,
                            "severity": rule["severity"],
                            "risk": rule["risk"],
                            "mechanism": rule["mechanism"],
                        }
                    )
    return conflicts


def _normalize_patient_state(patient: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    timestamp_by_drug: dict[str, str] = {}
    visits = patient.get("visits", [])
    if not visits:
        legacy_visits = patient.get("visit_history", [])
        if legacy_visits:
            visits = [
                {
                    "visit_id": f"V-{index:03d}",
                    "timestamp": visit.get("prescription_date") or visit.get("timestamp"),
                    "extracted_drugs": visit.get("extracted_drugs")
                    or [
                        item.get("drug", "") if isinstance(item, dict) else item
                        for item in visit.get("prescriptions", [])
                    ],
                    "status": visit.get("status", "APPROVED"),
                }
                for index, visit in enumerate(legacy_visits, start=1)
            ]
        elif patient.get("audit_history"):
            visits = [
                {
                    "visit_id": f"V-{index:03d}",
                    "timestamp": entry.get("timestamp"),
                    "extracted_drugs": entry.get("extracted_drugs", []),
                    "status": entry.get("status", "APPROVED"),
                }
                for index, entry in enumerate(patient["audit_history"], start=1)
            ]
    for visit in visits:
        visit_timestamp = visit.get("timestamp")
        for drug in visit.get("extracted_drugs", []):
            timestamp_by_drug.setdefault(_drug_key(drug), visit_timestamp or "")

    active: list[dict[str, Any]] = []
    for record in patient.get("active_medications", []):
        if isinstance(record, str):
            drug = record.strip()
            active.append(
                {
                    "drug": drug,
                    "daily_mg": None,
                    "prescribed_date": timestamp_by_drug.get(_drug_key(drug), "")[:10] or None,
                    "status": "ACTIVE",
                }
            )
        elif isinstance(record, dict):
            normalized = {
                "drug": str(record.get("drug", "")).strip(),
                "daily_mg": record.get("daily_mg"),
                "prescribed_date": record.get("prescribed_date")
                or record.get("prescription_date"),
                "status": str(record.get("status", "ACTIVE")).upper(),
            }
            active.append(normalized)
    return active, visits


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


def audit_patient_cumulative(
    patient_id: str, new_prescription_data: dict[str, Any]
) -> dict[str, Any]:
    if not re.fullmatch(r"[A-Za-z0-9_-]+", patient_id):
        raise ValueError("Patient ID may contain only letters, numbers, underscores, and hyphens")
    patient_path = (PATIENTS_DIR / f"{patient_id}.json").resolve()
    if patient_path.parent != PATIENTS_DIR.resolve():
        raise ValueError("Invalid patient path")
    patient = json.loads(patient_path.read_text(encoding="utf-8"))
    ddi_data = json.loads(DDI_RULES_FILE.read_text(encoding="utf-8"))
    if isinstance(ddi_data, list):
        rules = ddi_data
        limits: dict[str, int] = {}
    else:
        rules = ddi_data.get("interactions", [])
        limits = ddi_data.get("max_daily_limits_mg", {})
    raw_active = patient.get("active_medications", [])
    if not isinstance(raw_active, list):
        raise ValueError("Patient active_medications must be an array")
    if any(not isinstance(item, (str, dict)) for item in raw_active):
        raise ValueError("Patient active_medications entries must be strings or objects")
    active, previous_visits = _normalize_patient_state(patient)

    timestamp = datetime.now(timezone.utc).isoformat()
    proposed = _proposed_records(new_prescription_data, timestamp)
    overdose = _overdose_conflict(active, proposed, limits)
    if overdose is not None:
        return {
            "status": "OVERDOSE_ALERT",
            "decision": "BLOCKED",
            "reason_category": "OVERDOSE",
            "patient_id": patient_id,
            "conflict": overdose,
            "action_taken": "Prescription rejected; patient profile was not modified.",
        }

    ddi_conflicts = _ddi_conflicts(active, proposed, rules)
    if ddi_conflicts:
        return {
            "status": "DDI_BLOCKED",
            "decision": "BLOCKED",
            "reason_category": "CONTRAINDICATION",
            "patient_id": patient_id,
            "conflicts": ddi_conflicts,
            "action_taken": "Prescription rejected; patient profile was not modified.",
        }

    is_baseline = not previous_visits
    dose_baseline_updates: list[str] = []
    updated_active = active.copy()
    for record in proposed:
        medication = {
            "drug": record["drug"],
            "daily_mg": record["daily_mg"],
            "prescribed_date": timestamp[:10],
            "status": "ACTIVE",
        }
        matches = [
            index
            for index, existing in enumerate(updated_active)
            if _is_active_record(existing)
            and (
                _matches_drug(_record_drug(existing), record["drug"])
                or _matches_drug(record["drug"], _record_drug(existing))
            )
        ]
        known_active_doses = [
            updated_active[index].get("daily_mg")
            for index in matches
            if isinstance(updated_active[index], dict)
            and isinstance(updated_active[index].get("daily_mg"), (int, float))
        ]
        if matches and len(known_active_doses) != len(matches) and record["daily_mg"] is not None:
            first_match = matches[0]
            updated_active[first_match] = medication
            for duplicate_index in reversed(matches[1:]):
                del updated_active[duplicate_index]
            dose_baseline_updates.append(record["drug"])
        else:
            updated_active.append(medication)
    patient["active_medications"] = updated_active
    patient["visits"] = previous_visits
    visit_id = f"V-{len(previous_visits) + 1:03d}"
    patient["visits"].append(
        {
            "visit_id": visit_id,
            "timestamp": timestamp,
            "extracted_drugs": [record["drug"] for record in proposed],
            "status": "APPROVED",
        }
    )
    patient.setdefault("audit_history", []).append(
        {
            "timestamp": timestamp,
            "status": "APPROVED",
            "visit_id": visit_id,
            "extracted_drugs": [record["drug"] for record in proposed],
            "extracted_diseases": new_prescription_data.get("extracted_diseases", []),
        }
    )
    _write_patient_atomically(patient_path, patient)
    return {
        "status": "APPROVED",
        "patient_id": patient_id,
        "conflicts": [],
        "added_medications": proposed,
        "active_medications": patient["active_medications"],
        "visits": patient["visits"],
        "visit_id": visit_id,
        "dose_baseline_updates": dose_baseline_updates,
        "message": (
            "Initial clinical baseline registered."
            if is_baseline
            else "Prescription approved and added to the patient's ongoing profile."
        ),
    }


def audit_patient(patient_id: str, extracted: dict[str, Any]) -> dict[str, Any]:
    """Backward-compatible alias for the cumulative multi-visit auditor."""
    return audit_patient_cumulative(patient_id, extracted)


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
        result = audit_patient_cumulative(
            args.patient_id, _load_extracted(args.extracted_json)
        )
    except Exception as error:
        print(f"Safety audit failed: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())