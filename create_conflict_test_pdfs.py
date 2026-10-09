from pathlib import Path
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors


PROJECT_ROOT = Path(__file__).resolve().parent


def _resolve_output_path(filename):
    output_path = Path(filename)
    if not output_path.is_absolute():
        output_path = PROJECT_ROOT / output_path
    output_path.parent.mkdir(parents=True, exist_ok=True)
    return output_path

PROJECT_ROOT = Path(__file__).resolve().parent
styles = getSampleStyleSheet()

# Custom clinical typography styles
title_style = ParagraphStyle(
    "DocTitle",
    parent=styles["Heading1"],
    fontSize=18,
    leading=22,
    textColor=colors.HexColor("#0f766e"),
    alignment=1, # Centered
    spaceAfter=4,
)

subtitle_style = ParagraphStyle(
    "DocSubtitle",
    parent=styles["Normal"],
    fontSize=9,
    leading=12,
    textColor=colors.HexColor("#475569"),
    alignment=1,
    spaceAfter=12,
)

section_heading = ParagraphStyle(
    "SectionHeading",
    parent=styles["Heading2"],
    fontSize=12,
    leading=16,
    textColor=colors.HexColor("#1e293b"),
    spaceBefore=10,
    spaceAfter=6,
)

body_text = ParagraphStyle(
    "BodyTextCustom",
    parent=styles["Normal"],
    fontSize=10,
    leading=15,
    textColor=colors.HexColor("#0f172a"),
)

rx_box_style = ParagraphStyle(
    "RxBoxText",
    parent=styles["Normal"],
    fontSize=11,
    leading=16,
    textColor=colors.HexColor("#0f172a"),
)


# ==============================================================================
# PDF 1: Cross-Prescription Conflict for Eleanor Vance (P101)
# Active Medication: Warfarin (Blood thinner)
# Prescribed Drug: Aspirin (Triggers Critical Hemorrhage DDI Block)
# ==============================================================================
def create_cross_patient_conflict_pdf(filename="test_samples/conflict_p101_aspirin.pdf"):
    filename = _resolve_output_path(filename)
    doc = SimpleDocTemplate(
        str(filename),
        pagesize=letter,
        rightMargin=45,
        leftMargin=45,
        topMargin=45,
        bottomMargin=45,
    )
    story = []

    story.append(Paragraph("ST. JUDE COMPREHENSIVE CLINICAL CENTER", title_style))
    story.append(Paragraph("Department of Orthopedics & Rheumatology | License #MED-884920", subtitle_style))
    story.append(HRFlowable(width="100%", thickness=1.5, color=colors.HexColor("#0f766e"), spaceAfter=14))

    patient_meta = [
        [Paragraph("<b>Patient Name:</b> Eleanor Vance", body_text), Paragraph("<b>Patient ID:</b> P101", body_text)],
        [Paragraph("<b>Age / Gender:</b> 68 / Female", body_text), Paragraph("<b>Date:</b> October 9, 2026", body_text)],
        [Paragraph("<b>Known History:</b> Atrial Fibrillation, Hypertension", body_text), Paragraph("<b>Attending:</b> Dr. Robert Hayes, MD", body_text)],
    ]
    meta_table = Table(patient_meta, colWidths=[260, 260])
    meta_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f8fafc")),
        ("PADDING", (0, 0), (-1, -1), 6),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LINEBELOW", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
    ]))
    story.append(meta_table)
    story.append(Spacer(1, 14))

    story.append(Paragraph("Clinical Consultation Summary", section_heading))
    notes = (
        "Patient presents with severe flare-up of osteoarthritis affecting bilateral knees and acute migraine. "
        "Complains of localized joint inflammation and persistent stiffness over the past 72 hours. "
        "Vital signs are stable; no acute cardiopulmonary distress noted."
    )
    story.append(Paragraph(notes, body_text))
    story.append(Spacer(1, 14))

    story.append(Paragraph("Prescription Directive (Rx)", section_heading))
    rx_orders = [
        [Paragraph("<b>Medication Order:</b>", body_text), Paragraph("<b>Aspirin 325 mg</b> oral tablet", rx_box_style)],
        [Paragraph("<b>Dosage / Frequency:</b>", body_text), Paragraph("Take 1 tablet (325 mg) orally twice daily with meals.", body_text)],
        [Paragraph("<b>Indication:</b>", body_text), Paragraph("Pain relief for joint inflammation and acute migraine headache.", body_text)],
        [Paragraph("<b>Duration:</b>", body_text), Paragraph("14-day supply.", body_text)],
    ]
    rx_table = Table(rx_orders, colWidths=[150, 370])
    rx_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f1f5f9")),
        ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#cbd5e1")),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
        ("PADDING", (0, 0), (-1, -1), 7),
    ]))
    story.append(rx_table)
    story.append(Spacer(1, 24))

    story.append(Paragraph("Physician Signature: <i>Dr. Robert Hayes, MD (Orthopedic Surgery)</i>", body_text))
    doc.build(story)
    print(f"Generated: {filename}")


# ==============================================================================
# PDF 2: Intra-Prescription Dual Conflict
# Both conflicting drugs prescribed on the exact same sheet
# Contains: Sildenafil + Nitroglycerin (Triggers Refractory Hypotension DDI Block)
# ==============================================================================
def create_intra_prescription_conflict_pdf(filename="test_samples/conflict_dual_order.pdf"):
    filename = _resolve_output_path(filename)
    doc = SimpleDocTemplate(
        str(filename),
        pagesize=letter,
        rightMargin=45,
        leftMargin=45,
        topMargin=45,
        bottomMargin=45,
    )
    story = []

    story.append(Paragraph("METROPOLITAN CARDIOLOGY & UROLOGY CLINIC", title_style))
    story.append(Paragraph("Multi-Specialty Outpatient Division | License #MED-441209", subtitle_style))
    story.append(HRFlowable(width="100%", thickness=1.5, color=colors.HexColor("#0f766e"), spaceAfter=14))

    patient_meta = [
        [Paragraph("<b>Patient Name:</b> Arthur Pendelton", body_text), Paragraph("<b>Patient ID:</b> P103", body_text)],
        [Paragraph("<b>Age / Gender:</b> 61 / Male", body_text), Paragraph("<b>Date:</b> October 9, 2026", body_text)],
        [Paragraph("<b>Diagnosis:</b> Exertional Angina, Erectile Dysfunction", body_text), Paragraph("<b>Attending:</b> Dr. Sarah Lin, MD", body_text)],
    ]
    meta_table = Table(patient_meta, colWidths=[260, 260])
    meta_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f8fafc")),
        ("PADDING", (0, 0), (-1, -1), 6),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LINEBELOW", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
    ]))
    story.append(meta_table)
    story.append(Spacer(1, 14))

    story.append(Paragraph("Clinical Examination Notes", section_heading))
    notes = (
        "Patient presents for dual consultation addressing episodic exertional chest tightness "
        "attributed to stable chronic angina, alongside quality of life urological follow-up. "
        "ECG shows sinus rhythm with baseline non-specific ST changes. Vital signs stable."
    )
    story.append(Paragraph(notes, body_text))
    story.append(Spacer(1, 14))

    story.append(Paragraph("Prescription Directives (Dual Orders)", section_heading))
    rx_orders = [
        [
            Paragraph("<b>Rx Item 1:</b>", body_text),
            Paragraph("<b>Nitroglycerin 0.4 mg</b> sublingual tablets<br/><font color='#475569'>Directions: Take 1 tablet under the tongue every 5 minutes as needed for acute chest pain / angina pectoris.</font>", rx_box_style)
        ],
        [
            Paragraph("<b>Rx Item 2:</b>", body_text),
            Paragraph("<b>Sildenafil 50 mg</b> oral film-coated tablet<br/><font color='#475569'>Directions: Take 1 tablet orally approximately 60 minutes prior to anticipated activity for symptomatic management.</font>", rx_box_style)
        ],
    ]
    rx_table = Table(rx_orders, colWidths=[110, 410])
    rx_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#fef2f2")), # Subtle red tint
        ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#fca5a5")),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#fecaca")),
        ("PADDING", (0, 0), (-1, -1), 8),
    ]))
    story.append(rx_table)
    story.append(Spacer(1, 24))

    story.append(Paragraph("Physician Signature: <i>Dr. Sarah Lin, MD (Cardiovascular & Internal Medicine)</i>", body_text))
    doc.build(story)
    print(f"Generated: {filename}")


if __name__ == "__main__":
    create_cross_patient_conflict_pdf()
    create_intra_prescription_conflict_pdf()