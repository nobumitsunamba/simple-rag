"""Document processing module for PDF, Word, Excel, PowerPoint, text, and CSV files."""

import csv
import io
import re
from pathlib import Path

import PyPDF2
from docx import Document
from openpyxl import load_workbook
from pptx import Presentation


def extract_text_from_pdf(file_content: bytes) -> tuple[str, dict]:
    """Extract text from a PDF file with page numbers.

    Returns (full_text, page_map) where page_map maps chunk start positions to page numbers.
    """
    reader = PyPDF2.PdfReader(io.BytesIO(file_content))
    text_parts = []
    page_map = {}  # {cumulative_char_position: page_number}
    cumulative_pos = 0

    for i, page in enumerate(reader.pages):
        page_text = page.extract_text()
        if page_text:
            page_map[cumulative_pos] = i + 1
            text_parts.append(page_text)
            cumulative_pos += len(page_text) + 2  # +2 for \n\n separator

    return "\n\n".join(text_parts), page_map


def extract_text_from_docx(file_content: bytes) -> str:
    """Extract text from a Word (.docx) file."""
    doc = Document(io.BytesIO(file_content))
    text_parts = []
    for paragraph in doc.paragraphs:
        if paragraph.text.strip():
            text_parts.append(paragraph.text)
    return "\n\n".join(text_parts)


def extract_text_from_xlsx(file_content: bytes) -> str:
    """Extract text from an Excel (.xlsx) file."""
    wb = load_workbook(io.BytesIO(file_content), read_only=True, data_only=True)
    text_parts = []

    for sheet_name in wb.sheetnames:
        ws = wb[sheet_name]
        sheet_text = [f"[シート: {sheet_name}]"]
        for row in ws.iter_rows(values_only=True):
            row_text = " | ".join(str(cell) if cell is not None else "" for cell in row)
            if row_text.strip(" |"):
                sheet_text.append(row_text)
        if len(sheet_text) > 1:
            text_parts.append("\n".join(sheet_text))

    wb.close()
    return "\n\n".join(text_parts)


def extract_text_from_pptx(file_content: bytes) -> str:
    """Extract text from a PowerPoint (.pptx) file."""
    prs = Presentation(io.BytesIO(file_content))
    text_parts = []

    for i, slide in enumerate(prs.slides, 1):
        slide_text = [f"[スライド {i}]"]
        for shape in slide.shapes:
            if shape.has_text_frame:
                for paragraph in shape.text_frame.paragraphs:
                    if paragraph.text.strip():
                        slide_text.append(paragraph.text)
        if len(slide_text) > 1:
            text_parts.append("\n".join(slide_text))

    return "\n\n".join(text_parts)


def extract_text_from_csv(file_content: bytes) -> str:
    """Extract text from a CSV file."""
    text = file_content.decode("utf-8", errors="replace")
    reader = csv.reader(io.StringIO(text))
    rows = []
    for row in reader:
        row_text = " | ".join(row)
        if row_text.strip(" |"):
            rows.append(row_text)
    return "\n".join(rows)


def extract_text_from_text(file_content: bytes) -> str:
    """Extract text from a plain text or markdown file."""
    return file_content.decode("utf-8", errors="replace")


def extract_text(filename: str, file_content: bytes) -> str:
    """Extract text from a file based on its extension."""
    suffix = Path(filename).suffix.lower()
    if suffix == ".pdf":
        text, _ = extract_text_from_pdf(file_content)
        return text
    elif suffix in (".docx", ".doc"):
        return extract_text_from_docx(file_content)
    elif suffix in (".xlsx", ".xls"):
        return extract_text_from_xlsx(file_content)
    elif suffix == ".pptx":
        return extract_text_from_pptx(file_content)
    elif suffix == ".csv":
        return extract_text_from_csv(file_content)
    elif suffix in (".txt", ".md", ".markdown"):
        return extract_text_from_text(file_content)
    else:
        raise ValueError(f"Unsupported file type: {suffix}")


def extract_text_with_pages(filename: str, file_content: bytes) -> tuple[str, dict | None]:
    """Extract text with page mapping (only for PDF).

    Returns (text, page_map). page_map is None for non-PDF files.
    """
    suffix = Path(filename).suffix.lower()
    if suffix == ".pdf":
        return extract_text_from_pdf(file_content)
    else:
        return extract_text(filename, file_content), None


def _split_into_sentences(text: str) -> list[str]:
    """Split text into sentences, handling Japanese and English punctuation."""
    pattern = r'(?<=[。！？\.\!\?])\s*'
    sentences = re.split(pattern, text)
    result = []
    for s in sentences:
        parts = s.split('\n')
        for part in parts:
            stripped = part.strip()
            if stripped:
                result.append(stripped)
    return result


def split_text(text: str, chunk_size: int = 700, chunk_overlap: int = 150) -> list[str]:
    """Split text into semantic chunks optimized for Japanese documents."""
    paragraphs = re.split(r'\n\s*\n', text)

    all_sentences = []
    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
        sentences = _split_into_sentences(para)
        all_sentences.extend(sentences)
        all_sentences.append("")

    chunks = []
    current_chunk: list[str] = []
    current_length = 0

    for sentence in all_sentences:
        if not sentence:
            if current_length > chunk_size * 0.6:
                chunk_text = _join_sentences(current_chunk)
                if chunk_text:
                    chunks.append(chunk_text)
                current_chunk, current_length = _get_overlap(current_chunk, chunk_overlap)
            continue

        sentence_len = len(sentence)

        if current_length + sentence_len > chunk_size and current_chunk:
            chunk_text = _join_sentences(current_chunk)
            if chunk_text:
                chunks.append(chunk_text)
            current_chunk, current_length = _get_overlap(current_chunk, chunk_overlap)

        current_chunk.append(sentence)
        current_length += sentence_len

    if current_chunk:
        chunk_text = _join_sentences(current_chunk)
        if chunk_text:
            chunks.append(chunk_text)

    return chunks


def split_text_with_pages(text: str, page_map: dict | None, chunk_size: int = 700, chunk_overlap: int = 150) -> list[dict]:
    """Split text into chunks with page number information.

    Returns list of {text, page} dicts.
    """
    chunks = split_text(text, chunk_size, chunk_overlap)

    if page_map is None:
        return [{"text": chunk, "page": None} for chunk in chunks]

    # Map chunks to pages
    sorted_positions = sorted(page_map.keys())
    result = []
    search_pos = 0

    for chunk in chunks:
        # Find chunk position in original text
        pos = text.find(chunk[:50], search_pos)
        if pos == -1:
            pos = search_pos

        # Find which page this position belongs to
        page = 1
        for p in sorted_positions:
            if p <= pos:
                page = page_map[p]
            else:
                break

        result.append({"text": chunk, "page": page})
        search_pos = pos + 1

    return result


def _join_sentences(sentences: list[str]) -> str:
    filtered = [s for s in sentences if s]
    if not filtered:
        return ""
    return " ".join(filtered)


def _get_overlap(sentences: list[str], overlap_chars: int) -> tuple[list[str], int]:
    if not sentences:
        return [], 0
    overlap_sentences = []
    total = 0
    for s in reversed(sentences):
        if not s:
            continue
        if total + len(s) > overlap_chars:
            break
        overlap_sentences.insert(0, s)
        total += len(s)
    return overlap_sentences, total
