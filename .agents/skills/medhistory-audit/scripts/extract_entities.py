"""Extract drug and disease mentions from text or PDF with local BioBERT."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import torch
from pypdf import PdfReader
from transformers import AutoModelForTokenClassification, AutoTokenizer


PROJECT_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_MODEL_DIR = PROJECT_ROOT / "model" / "biobert-ner-final"
GENERIC_LABEL_MAP = {
    "LABEL_0": "O",
    "LABEL_1": "B-DRUG",
    "LABEL_2": "I-DRUG",
    "LABEL_3": "B-DISEASE",
    "LABEL_4": "I-DISEASE",
}
ENTITY_ALIASES = {
    "DRUG": "DRUG",
    "DRUGS": "DRUG",
    "MEDICATION": "DRUG",
    "MEDICATIONS": "DRUG",
    "CHEMICAL": "DRUG",
    "CHEMICALS": "DRUG",
    "DISEASE": "DISEASE",
    "DISEASES": "DISEASE",
    "SYMPTOM": "DISEASE",
    "SYMPTOMS": "DISEASE",
    "SIGN": "DISEASE",
    "SIGNS": "DISEASE",
    "CONDITION": "DISEASE",
    "CONDITIONS": "DISEASE",
}


def _normalize_label(label: str) -> tuple[str, str | None]:
    label = label.strip().upper()
    if label == "O" or label == "OUTSIDE":
        return "O", None
    prefix, separator, raw_entity = label.partition("-")
    if not separator:
        prefix, separator, raw_entity = label.partition("_")
    if not separator:
        return "O", None
    entity = ENTITY_ALIASES.get(raw_entity)
    if prefix not in {"B", "I"} or entity is None:
        return "O", None
    return prefix, entity


def _clean_entity(value: str) -> str:
    return value.strip(" \t\r\n,;:")


def decode_entities(
    text: str,
    offsets: list[list[int]],
    predicted_ids: list[int],
    id2label: dict[int, str],
) -> list[dict[str, Any]]:
    entities: list[dict[str, Any]] = []
    current_type: str | None = None
    current_start = 0
    current_end = 0

    def flush() -> None:
        nonlocal current_type, current_start, current_end
        if current_type is not None:
            value = _clean_entity(text[current_start:current_end])
            if value:
                source_span = text[current_start:current_end]
                start = current_start + len(source_span) - len(source_span.lstrip())
                end = current_end - (len(source_span) - len(source_span.rstrip()))
                entities.append(
                    {
                        "text": text[start:end],
                        "label": current_type,
                        "start": start,
                        "end": end,
                    }
                )
        current_type = None

    for offset, predicted_id in zip(offsets, predicted_ids):
        start, end = offset
        if start == end or start < 0 or end > len(text):
            flush()
            continue
        prefix, entity_type = _normalize_label(id2label.get(predicted_id, "O"))
        if entity_type is None:
            flush()
            continue
        if prefix == "B" or current_type != entity_type:
            flush()
            current_type = entity_type
            current_start = start
        current_end = end

    flush()
    return entities


def _merge_entities(text: str, entities: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    for entity in sorted(entities, key=lambda item: (item["start"], item["end"])):
        if (
            merged
            and merged[-1]["label"] == entity["label"]
            and entity["start"] < merged[-1]["end"]
        ):
            merged[-1]["end"] = max(merged[-1]["end"], entity["end"])
            merged[-1]["text"] = text[merged[-1]["start"] : merged[-1]["end"]]
        elif not merged or entity["start"] >= merged[-1]["end"]:
            merged.append(entity.copy())
    return merged


def extract_pdf_text(pdf_path: Path) -> str:
    if not pdf_path.is_file():
        raise FileNotFoundError(f"PDF file does not exist: {pdf_path}")
    reader = PdfReader(str(pdf_path))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def extract(text: str, model_dir: Path) -> dict[str, Any]:
    if not text.strip():
        return {
            "raw_text": text,
            "entities": [],
            "extracted_drugs": [],
            "extracted_diseases": [],
            "warnings": [],
        }
    if not model_dir.is_dir():
        raise FileNotFoundError(f"Model directory does not exist: {model_dir}")

    tokenizer = AutoTokenizer.from_pretrained(
        model_dir, local_files_only=True, use_fast=True
    )
    if not tokenizer.is_fast:
        raise RuntimeError("A fast tokenizer is required for offset-based extraction.")
    model = AutoModelForTokenClassification.from_pretrained(
        model_dir, local_files_only=True
    )
    model.eval()
    tokenizer.backend_tokenizer.no_truncation()
    id2label = {int(key): str(value) for key, value in model.config.id2label.items()}
    warnings: list[str] = []
    if id2label and all(label.startswith("LABEL_") for label in id2label.values()):
        id2label = {
            label_id: GENERIC_LABEL_MAP.get(label, "O")
            for label_id, label in id2label.items()
        }
        warnings.append(
            "Checkpoint labels are generic; interpreted LABEL_0..LABEL_4 as "
            "O, B-DRUG, I-DRUG, B-DISEASE, I-DISEASE. Verify this mapping "
            "against training metadata."
        )

    max_length = min(tokenizer.model_max_length, model.config.max_position_embeddings)
    tokenized = tokenizer.backend_tokenizer.encode(text, add_special_tokens=False)
    all_input_ids = tokenized.ids
    all_offsets = tokenized.offsets
    if tokenizer.cls_token_id is None or tokenizer.sep_token_id is None:
        raise RuntimeError("The local BERT tokenizer must define CLS and SEP token IDs.")
    window_size = max_length - 2
    overlap = min(64, max(1, window_size // 4))
    window_step = max(1, window_size - overlap)
    prepared_chunks: list[dict[str, Any]] = []
    chunk_offsets: list[list[list[int]]] = []
    for token_start in range(0, len(all_input_ids), window_step):
        token_end = min(token_start + window_size, len(all_input_ids))
        chunk_ids = all_input_ids[token_start:token_end]
        model_input_ids = [tokenizer.cls_token_id, *chunk_ids, tokenizer.sep_token_id]
        model_inputs: dict[str, list[int]] = {
            "input_ids": model_input_ids,
            "attention_mask": [1] * len(model_input_ids),
        }
        if "token_type_ids" in tokenizer.model_input_names:
            model_inputs["token_type_ids"] = [0] * len(model_input_ids)
        prepared_chunks.append(model_inputs)
        chunk_offsets.append(
            [[0, 0], *all_offsets[token_start:token_end], [0, 0]]
        )
        if token_end == len(all_input_ids):
            break

    batch = tokenizer.pad(prepared_chunks, padding=True, return_tensors="pt")
    with torch.no_grad():
        logits = model(**batch).logits.argmax(dim=-1)
    entities: list[dict[str, Any]] = []
    for chunk_index, offsets in enumerate(chunk_offsets):
        chunk_predictions = logits[chunk_index, : len(offsets)].tolist()
        entities.extend(decode_entities(text, offsets, chunk_predictions, id2label))
    entities = _merge_entities(text, entities)
    drugs = list(
        dict.fromkeys(entity["text"] for entity in entities if entity["label"] == "DRUG")
    )
    diseases = list(
        dict.fromkeys(
            entity["text"] for entity in entities if entity["label"] == "DISEASE"
        )
    )
    return {
        "raw_text": text,
        "entities": entities,
        "extracted_drugs": drugs,
        "extracted_diseases": diseases,
        "warnings": warnings,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--text", help="Unstructured clinical note")
    source.add_argument("--pdf-path", type=Path, help="Prescription or report PDF")
    parser.add_argument(
        "--model-dir",
        type=Path,
        default=DEFAULT_MODEL_DIR,
        help="Local token-classification model directory",
    )
    args = parser.parse_args()
    try:
        text = args.text if args.text is not None else extract_pdf_text(args.pdf_path.resolve())
        result = extract(text, args.model_dir.resolve())
    except Exception as error:
        print(f"Entity extraction failed: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())