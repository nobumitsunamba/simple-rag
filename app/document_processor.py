"""Document processing module for PDF and Word files."""

import io
import re
from pathlib import Path

import PyPDF2
from docx import Document


def extract_text_from_pdf(file_content: bytes) -> str:
    """Extract text from a PDF file."""
    reader = PyPDF2.PdfReader(io.BytesIO(file_content))
    text_parts = []
    for page in reader.pages:
        page_text = page.extract_text()
        if page_text:
            text_parts.append(page_text)
    return "\n\n".join(text_parts)


def extract_text_from_docx(file_content: bytes) -> str:
    """Extract text from a Word (.docx) file."""
    doc = Document(io.BytesIO(file_content))
    text_parts = []
    for paragraph in doc.paragraphs:
        if paragraph.text.strip():
            text_parts.append(paragraph.text)
    return "\n\n".join(text_parts)


def extract_text(filename: str, file_content: bytes) -> str:
    """Extract text from a file based on its extension."""
    suffix = Path(filename).suffix.lower()
    if suffix == ".pdf":
        return extract_text_from_pdf(file_content)
    elif suffix in (".docx", ".doc"):
        return extract_text_from_docx(file_content)
    else:
        raise ValueError(f"Unsupported file type: {suffix}")


def _split_into_sentences(text: str) -> list[str]:
    """Split text into sentences, handling Japanese and English punctuation."""
    # Split on Japanese sentence endings (。！？) and English ones (. ! ?)
    # Keep the delimiter attached to the sentence
    pattern = r'(?<=[。！？\.\!\?])\s*'
    sentences = re.split(pattern, text)
    # Also split on newlines
    result = []
    for s in sentences:
        parts = s.split('\n')
        for part in parts:
            stripped = part.strip()
            if stripped:
                result.append(stripped)
    return result


def split_text(text: str, chunk_size: int = 400, chunk_overlap: int = 80) -> list[str]:
    """Split text into semantic chunks optimized for Japanese documents.

    Strategy:
    1. Split by paragraphs (double newline)
    2. Within paragraphs, split by sentences
    3. Group sentences into chunks respecting chunk_size
    4. Add overlap for context continuity
    """
    # First split into paragraphs
    paragraphs = re.split(r'\n\s*\n', text)

    # Split each paragraph into sentences
    all_sentences = []
    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
        sentences = _split_into_sentences(para)
        all_sentences.extend(sentences)
        # Add paragraph boundary marker
        all_sentences.append("")

    # Group sentences into chunks
    chunks = []
    current_chunk: list[str] = []
    current_length = 0

    for sentence in all_sentences:
        if not sentence:
            # Paragraph boundary - good place to break if chunk is large enough
            if current_length > chunk_size * 0.6:
                chunk_text = _join_sentences(current_chunk)
                if chunk_text:
                    chunks.append(chunk_text)
                # Keep overlap
                current_chunk, current_length = _get_overlap(current_chunk, chunk_overlap)
            continue

        sentence_len = len(sentence)

        # If adding this sentence exceeds chunk_size, finalize current chunk
        if current_length + sentence_len > chunk_size and current_chunk:
            chunk_text = _join_sentences(current_chunk)
            if chunk_text:
                chunks.append(chunk_text)
            # Keep overlap
            current_chunk, current_length = _get_overlap(current_chunk, chunk_overlap)

        current_chunk.append(sentence)
        current_length += sentence_len

    # Don't forget the last chunk
    if current_chunk:
        chunk_text = _join_sentences(current_chunk)
        if chunk_text:
            chunks.append(chunk_text)

    return chunks


def _join_sentences(sentences: list[str]) -> str:
    """Join sentences with appropriate spacing."""
    filtered = [s for s in sentences if s]
    if not filtered:
        return ""
    return " ".join(filtered)


def _get_overlap(sentences: list[str], overlap_chars: int) -> tuple[list[str], int]:
    """Get the tail sentences that fit within overlap_chars."""
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
