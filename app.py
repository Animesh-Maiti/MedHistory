"""Streamlit dashboard for the MedHistory local clinical safety demo."""

from __future__ import annotations

import html
import json
import re
import subprocess
import sys
from io import BytesIO
from pathlib import Path
from typing import Any

import streamlit as st
from pypdf import PdfReader


ROOT = Path(__file__).resolve().parent
SKILL_DIR = ROOT / ".agents" / "skills" / "medhistory-audit"
PATIENTS_DIR = SKILL_DIR / "assets" / "patients"
MODEL_DIR = ROOT / "model" / "biobert-ner-final"
EXTRACT_SCRIPT = SKILL_DIR / "scripts" / "extract_entities.py"
AUDIT_SCRIPT = SKILL_DIR / "scripts" / "audit_safety.py"
CREATE_PATIENT_OPTION = "➕ Create New Patient"
PATIENT_IDS = tuple(sorted(path.stem for path in PATIENTS_DIR.glob("P*.json")))
DEMO_CONFLICT = "Prescription for Eleanor Vance: Aspirin 325mg daily for acute migraine and joint pain."
DEMO_SAFE = "Prescription: Paracetamol 500mg daily for mild headache."
AUDIT_BUTTON = "Run BioBERT NER & Clinical Safety Audit"

st.set_page_config(
    page_title="MedHistory | Clinical Safety Sentinel", page_icon="+", layout="wide"
)

st.markdown(
    """
    <style>
    :root {
        --ink: #17332f;
        --muted: #60736f;
        --paper: #f5f8f4;
        --line: #d8e3dc;
        --green: #18745d;
        --green-soft: #e6f4ed;
        --red: #a63236;
        --red-soft: #fff0ee;
    }
    .stApp { background: radial-gradient(ellipse at 10% 0%, #edf5ef 0, var(--paper) 52%); color: var(--ink); }
    [data-testid="stSidebar"] { background: #eaf1eb; border-right: 1px solid var(--line); }
    h1, h2, h3 { color: var(--ink); letter-spacing: 0; }
    h1 { font-family: Georgia, "Times New Roman", serif; font-weight: 500; }
    .eyebrow { color: var(--green); font-size: .74rem; font-weight: 800; letter-spacing: .12em; text-transform: uppercase; }
    .patient-card, .result-card { border: 1px solid var(--line); border-radius: 7px; padding: 1rem 1.1rem; background: rgba(255,255,255,.78); }
    .patient-name { color: var(--ink); font-family: Georgia, "Times New Roman", serif; font-size: 1.35rem; margin: .1rem 0 .55rem; }
    .detail-label { color: var(--muted); font-size: .76rem; font-weight: 700; margin: .65rem 0 .35rem; text-transform: uppercase; }
    .badge { display: inline-block; border-radius: 4px; font-size: .8rem; line-height: 1.5; margin: 0 .3rem .35rem 0; padding: .2rem .48rem; }
    .drug-badge { border: 1px solid #86efac; background: #dcfce7; color: #166534; }
    .disease-badge { border: 1px solid #fde68a; background: #fef3c7; color: #92400e; }
    .blocked { border-left: 5px solid var(--red); background: var(--red-soft); }
    .approved { border-left: 5px solid var(--green); background: var(--green-soft); }
    .status-title { font-size: 1.15rem; font-weight: 800; margin-bottom: .35rem; }
    .status-pill { border-radius: 999px; display: inline-block; font-size: .77rem; font-weight: 800; padding: .2rem .65rem; }
    .critical-pill { background: #fee2e2; color: #991b1b; }
    .high-pill { background: #ffedd5; color: #9a3412; }
    .risk-label { color: var(--red); font-size: .78rem; font-weight: 800; margin-top: .75rem; text-transform: uppercase; }
    .mechanism { color: #4c3938; line-height: 1.55; }
    [data-testid="stRadio"],
    [data-testid="stRadio"] label,
    [data-testid="stRadio"] p,
    [data-testid="stFileUploader"],
    [data-testid="stFileUploader"] label,
    [data-testid="stFileUploader"] p,
    [data-testid="stDataFrame"] [role="columnheader"],
    [data-testid="stDataFrame"] [role="gridcell"],
    label { color: #0f172a !important; }
    div.stButton > button[kind="primary"] { background: var(--green); border-color: var(--green); }
    div.stButton > button { border-radius: 5px; }
    .disclaimer { border-top: 1px solid var(--line); color: var(--muted); font-size: .78rem; margin-top: 1.5rem; padding-top: .8rem; }
    </style>
    """,
    unsafe_allow_html=True,
)


def load_patient(patient_id: str) -> dict[str, Any]:
    path = PATIENTS_DIR / f"{patient_id}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def medication_label(value: str | dict[str, Any]) -> str:
    if isinstance(value, str):
        return value
    drug = str(value.get("drug", "Unknown medication"))
    daily_mg = value.get("daily_mg")
    if daily_mg is not None:
        return f"{drug} · {daily_mg:g} mg/day"
    return drug


def badges(values: list[Any], css_class: str) -> str:
    return "".join(
        f'<span class="badge {css_class}">{html.escape(medication_label(value))}</span>'
        for value in values
    ) or '<span style="color:#60736f">None recorded</span>'


def run_json_command(command: list[str]) -> dict[str, Any]:
    result = subprocess.run(
        command,
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or "The local audit command failed."
        raise RuntimeError(detail)
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise RuntimeError("The local audit command returned invalid JSON.") from error


def render_highlighted_text(raw_text: str, entities: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    cursor = 0
    for entity in sorted(entities, key=lambda item: (item["start"], item["end"])):
        start, end = entity["start"], entity["end"]
        if start < cursor or start < 0 or end > len(raw_text) or end <= start:
            continue
        parts.append(html.escape(raw_text[cursor:start]))
        text = html.escape(raw_text[start:end])
        if entity["label"] == "DRUG":
            style = "background-color:#dcfce7;color:#166534;border:1px solid #86efac;"
            icon = "💊"
        else:
            style = "background-color:#fef3c7;color:#92400e;border:1px solid #fde68a;"
            icon = "🩺"
        parts.append(
            f'<span style="{style}padding:2px 8px;border-radius:4px;font-weight:bold;">'
            f"{icon} {text}</span>"
        )
        cursor = end
    parts.append(html.escape(raw_text[cursor:]))
    return '<div style="white-space:pre-wrap;line-height:2">' + "".join(parts) + "</div>"


def extract_uploaded_pdf(uploaded_file: Any) -> str:
    reader = PdfReader(BytesIO(uploaded_file.getvalue()))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def clear_results() -> None:
    for key in ("last_extraction", "last_audit", "last_patient", "last_text"):
        st.session_state.pop(key, None)


def load_demo(patient_id: str, note: str) -> None:
    st.session_state.patient_id = patient_id
    st.session_state.note_text = note
    st.session_state.input_mode = "Paste Clinical Text"
    clear_results()


def submit_new_patient() -> None:
    create_patient(
        st.session_state.new_patient_id,
        st.session_state.new_patient_name,
        int(st.session_state.new_patient_age),
        st.session_state.new_patient_conditions,
    )


def create_patient(patient_id: str, name: str, age: int, conditions: str) -> None:
    cleaned_id = patient_id.strip().upper()
    if not re.fullmatch(r"[A-Za-z0-9_-]+", cleaned_id):
        st.session_state.patient_form_error = "Patient ID may contain only letters, numbers, underscores, and hyphens."
        return
    if not name.strip():
        st.session_state.patient_form_error = "Enter a patient name."
        return
    path = PATIENTS_DIR / f"{cleaned_id}.json"
    record = {
        "patient_id": cleaned_id,
        "name": name.strip(),
        "age": age,
        "chronic_conditions": [
            value.strip() for value in conditions.split(",") if value.strip()
        ],
        "active_medications": [],
        "visits": [],
        "audit_history": [],
    }
    try:
        with path.open("x", encoding="utf-8") as patient_file:
            json.dump(record, patient_file, indent=2, ensure_ascii=False)
            patient_file.write("\n")
    except FileExistsError:
        st.session_state.patient_form_error = f"Patient {cleaned_id} already exists."
        return
    except OSError as error:
        st.session_state.patient_form_error = f"Could not create patient profile: {error}"
        return
    st.session_state.pop("patient_form_error", None)
    st.session_state.patient_id = cleaned_id
    st.session_state.input_mode = "Paste Clinical Text"
    clear_results()


def perform_audit(raw_text: str, patient_id: str) -> None:
    if not raw_text.strip():
        st.warning("Add clinical text or upload a text-readable PDF before running the audit.")
        return
    try:
        progress = st.progress(0, text="Loading the local BioBERT model...")
        extraction = run_json_command(
            [
                sys.executable,
                str(EXTRACT_SCRIPT),
                "--text",
                raw_text,
                "--model-dir",
                str(MODEL_DIR),
            ]
        )
        if not extraction.get("extracted_drugs"):
            st.session_state.last_extraction = extraction
            st.session_state.last_audit = {
                "status": "NO_MEDICATIONS",
                "message": (
                    "No active prescription medications detected in this document. "
                    "Patient active medications remain unchanged."
                ),
            }
            st.session_state.last_patient = patient_id
            st.session_state.last_text = raw_text
            st.rerun()
        progress.progress(55, text="Reconciling patient history and DDI rules...")
        audit = run_json_command(
            [
                sys.executable,
                str(AUDIT_SCRIPT),
                "--patient-id",
                patient_id,
                "--extracted-json",
                json.dumps(extraction, ensure_ascii=False),
            ]
        )
        progress.progress(100, text="Audit complete")
        st.session_state.last_extraction = extraction
        st.session_state.last_audit = audit
        st.session_state.last_patient = patient_id
        st.session_state.last_text = raw_text
        st.rerun()
    except Exception as error:
        st.error(f"Audit could not be completed: {error}")


if "note_text" not in st.session_state:
    st.session_state.note_text = ""
if "input_mode" not in st.session_state:
    st.session_state.input_mode = "Paste Clinical Text"
if "patient_id" not in st.session_state:
    st.session_state.patient_id = PATIENT_IDS[0] if PATIENT_IDS else CREATE_PATIENT_OPTION

with st.sidebar:
    st.markdown('<div class="eyebrow">Patient profile</div>', unsafe_allow_html=True)
    selected_patient = st.selectbox(
        "Patient",
        [*PATIENT_IDS, CREATE_PATIENT_OPTION],
        key="patient_id",
        label_visibility="collapsed",
        on_change=clear_results,
    )
    patient: dict[str, Any] | None = None
    if selected_patient == CREATE_PATIENT_OPTION:
        next_number = max(
            (int(match.group(1)) for patient_id in PATIENT_IDS if (match := re.fullmatch(r"P(\d+)", patient_id))),
            default=100,
        ) + 1
        with st.form("create_patient_form"):
            st.markdown("**Create patient profile**")
            st.text_input("Patient ID", value=f"P{next_number}", key="new_patient_id")
            st.text_input("Name", key="new_patient_name")
            st.number_input("Age", min_value=0, max_value=130, value=40, key="new_patient_age")
            st.text_input(
                "Chronic conditions",
                help="Separate conditions with commas",
                key="new_patient_conditions",
            )
            st.form_submit_button("Create patient", on_click=submit_new_patient)
        if st.session_state.get("patient_form_error"):
            st.error(st.session_state.pop("patient_form_error"))
    else:
        patient = load_patient(selected_patient)
        current_medications = [
            medication
            for medication in patient.get("active_medications", [])
            if isinstance(medication, str)
            or str(medication.get("status", "ACTIVE")).upper() == "ACTIVE"
        ]
        st.markdown(
            f"""
            <section class="patient-card">
              <div class="eyebrow">{html.escape(patient['patient_id'])} · Age {patient['age']}</div>
              <div class="patient-name">{html.escape(patient['name'])}</div>
              <div class="detail-label">Chronic conditions</div>{badges(patient.get('chronic_conditions', []), 'disease-badge')}
              <div class="detail-label">Active medications</div>{badges(current_medications, 'drug-badge')}
            </section>
            """,
            unsafe_allow_html=True,
        )
        st.markdown("<div class='detail-label'>Quick samples</div>", unsafe_allow_html=True)
        st.button(
            "Load Aspirin Conflict Note",
            use_container_width=True,
            on_click=load_demo,
            args=("P101", DEMO_CONFLICT),
        )
        st.button(
            "Load Safe Paracetamol Note",
            use_container_width=True,
            on_click=load_demo,
            args=("P102", DEMO_SAFE),
        )
        visits = patient.get("visits", [])
        with st.expander(f"Visit History / Timeline · {len(visits)} visit(s)", expanded=False):
            if visits:
                for visit in reversed(visits):
                    st.markdown(
                        f"**{html.escape(visit.get('visit_id', 'Visit'))}** · "
                        f"{html.escape(str(visit.get('timestamp', 'Date unavailable')))} · "
                        f"{html.escape(str(visit.get('status', 'UNKNOWN')))}"
                    )
                    if visit.get("extracted_drugs"):
                        st.markdown(
                            badges(visit["extracted_drugs"], "drug-badge"),
                            unsafe_allow_html=True,
                        )
            else:
                st.caption("No approved visits recorded.")

st.markdown('<div class="eyebrow">Local clinical workflow</div>', unsafe_allow_html=True)
st.title("Clinical Safety Sentinel")
st.write("Review medication and condition mentions against the selected patient's chart.")
input_mode = st.radio(
    "Prescription source",
    ["Paste Clinical Text", "Upload Prescription PDF"],
    horizontal=True,
    key="input_mode",
    on_change=clear_results,
)
raw_text = ""
if input_mode == "Upload Prescription PDF":
    uploaded_pdf = st.file_uploader("Prescription or report PDF", type=["pdf"])
    if uploaded_pdf is not None:
        try:
            raw_text = extract_uploaded_pdf(uploaded_pdf)
            if not raw_text.strip():
                st.warning("No selectable text was found in this PDF.")
            with st.expander("Extracted PDF text"):
                st.text(raw_text or "No text found.")
        except Exception as error:
            st.error(f"Could not read this PDF: {error}")
else:
    raw_text = st.text_area(
        "Clinical text",
        key="note_text",
        height=200,
        placeholder="Paste a prescription, consultation note, or medical report...",
        on_change=clear_results,
    )

if st.button(
    AUDIT_BUTTON,
    type="primary",
    disabled=not raw_text.strip() or selected_patient == CREATE_PATIENT_OPTION,
    key="run_patient_audit",
):
    perform_audit(raw_text, selected_patient)

if all(
    key in st.session_state
    for key in ("last_audit", "last_extraction", "last_patient", "last_text")
) and st.session_state.last_patient == selected_patient and st.session_state.last_text == raw_text:
    extraction = st.session_state.last_extraction
    audit = st.session_state.last_audit
    st.subheader("Visual entity highlighting")
    for warning in extraction.get("warnings", []):
        st.warning(warning)
    st.markdown(
        render_highlighted_text(st.session_state.last_text, extraction["entities"]),
        unsafe_allow_html=True,
    )
    if extraction.get("medication_details"):
        st.markdown("**Parsed daily medication doses**")
        st.dataframe(
            [
                {
                    "Medication": detail["drug"],
                    "Dosage": detail.get("dosage_str") or "Not stated",
                    "Daily dose (mg)": detail.get("daily_mg"),
                }
                for detail in extraction["medication_details"]
            ],
            hide_index=True,
            use_container_width=True,
        )
    drug_count = len({value.casefold() for value in extraction["extracted_drugs"]})
    disease_count = len({value.casefold() for value in extraction["extracted_diseases"]})
    drug_metric, disease_metric = st.columns(2)
    drug_metric.metric("Unique drugs / chemicals", drug_count)
    disease_metric.metric("Unique diseases / symptoms", disease_count)
    left, right = st.columns(2)
    with left:
        st.markdown("**Detected drugs**")
        st.markdown(badges(extraction["extracted_drugs"], "drug-badge"), unsafe_allow_html=True)
    with right:
        st.markdown("**Detected diseases and symptoms**")
        st.markdown(badges(extraction["extracted_diseases"], "disease-badge"), unsafe_allow_html=True)

    st.subheader("Safety audit")
    if audit["status"] == "NO_MEDICATIONS":
        st.info(audit["message"])
    elif audit["status"] == "OVERDOSE_ALERT":
        conflict = audit["conflict"]
        current_dose = conflict.get("current_daily_mg")
        current_text = "Unknown" if current_dose is None else f"{current_dose:g} mg/day"
        total_text = conflict.get("total_daily_mg")
        total_text = "Unverified" if total_text is None else f"{total_text:g} mg/day"
        st.markdown(
            '<div class="result-card blocked"><div class="status-title">⚠️ OVERDOSE ALERT · '
            f'{html.escape(conflict["drug"])} current: {html.escape(current_text)}; '
            f'proposed: {conflict["proposed_daily_mg"]:g} mg/day; '
            f'total: {html.escape(total_text)}; maximum: {conflict["max_daily_mg"]:g} mg/day.</div>'
            '<div>Medication addition rejected. Patient record unaltered.</div></div>',
            unsafe_allow_html=True,
        )
        st.markdown(f"**Risk:** {html.escape(conflict['risk'])}")
        st.markdown(
            f'<div class="risk-label">Biological mechanism</div>'
            f'<div class="mechanism">{html.escape(conflict["mechanism"])}</div>',
            unsafe_allow_html=True,
        )
    elif audit["status"] in {"DDI_BLOCKED", "BLOCKED"}:
        st.markdown(
            '<div class="result-card blocked"><div class="status-title">⚠️ DDI BLOCKED · '
            "Medication addition rejected. Patient record unaltered.</div></div>",
            unsafe_allow_html=True,
        )
        for conflict in audit["conflicts"]:
            severity_class = "critical-pill" if conflict["severity"] == "CRITICAL" else "high-pill"
            st.markdown(
                f"**{html.escape(' + '.join(conflict['pair']))}** · "
                f'<span class="status-pill {severity_class}">{html.escape(conflict["severity"])}</span>',
                unsafe_allow_html=True,
            )
            st.markdown(f"**Risk:** {html.escape(conflict['risk'])}")
            st.markdown(
                f'<div class="risk-label">Biological mechanism</div>'
                f'<div class="mechanism">{html.escape(conflict["mechanism"])}</div>',
                unsafe_allow_html=True,
            )
    else:
        st.markdown(
            '<div class="result-card approved"><div class="status-title">APPROVED · '
            f'{html.escape(audit.get("message", "Prescription approved."))}</div></div>',
            unsafe_allow_html=True,
        )
        if audit.get("dose_baseline_updates"):
            medications = ", ".join(audit["dose_baseline_updates"])
            st.info(
                f"Updated the recorded daily dose baseline for {html.escape(medications)} "
                "because no prior dose was available."
            )

    refreshed = load_patient(st.session_state.last_patient)
    st.markdown("**Refreshed active medications**")
    st.markdown(badges(refreshed.get("active_medications", []), "drug-badge"), unsafe_allow_html=True)
    with st.expander("Updated patient record and audit history"):
        st.json(refreshed)

st.markdown(
    '<div class="disclaimer">Demonstration only. This prototype is not validated for '
    "clinical use; confirm model label mapping and all recommendations with a qualified "
    "clinician.</div>",
    unsafe_allow_html=True,
)
