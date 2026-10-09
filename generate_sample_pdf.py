"""Generate the two local prescription PDFs used by the MedHistory demo."""

from __future__ import annotations

from pathlib import Path

from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer


PROJECT_ROOT = Path(__file__).resolve().parent
SAMPLE_DIR = PROJECT_ROOT / "test_samples"
SAMPLES = {
    "conflict_sample.pdf": (
        "Prescription for Eleanor Vance",
        "Aspirin 325mg daily for acute migraine and joint pain.",
    ),
    "safe_sample.pdf": (
        "Prescription",
        "Paracetamol 500mg daily for mild headache.",
    ),
}


def generate_sample_pdfs() -> list[Path]:
    SAMPLE_DIR.mkdir(parents=True, exist_ok=True)
    styles = getSampleStyleSheet()
    generated: list[Path] = []
    for filename, paragraphs in SAMPLES.items():
        destination = SAMPLE_DIR / filename
        document = SimpleDocTemplate(str(destination), pagesize=letter)
        story = []
        for index, text in enumerate(paragraphs):
            style = styles["Title"] if index == 0 else styles["BodyText"]
            story.extend((Paragraph(text, style), Spacer(1, 12)))
        document.build(story)
        generated.append(destination)
    return generated


if __name__ == "__main__":
    for pdf_path in generate_sample_pdfs():
        print(pdf_path.relative_to(PROJECT_ROOT))
