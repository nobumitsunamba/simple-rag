"""Document processing module for PDF and Word files."""

import io
from pathlib import Path

import PyPDF2
from docx import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter


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


def split_text(text: str, chunk_size: int = 500, chunk_overlap: int = 100) -> list[str]:
    """Split text into chunks for embedding."""
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        separators=["\n\n", "\n", "。", ".", " ", ""],
    )
    return splitter.split_text(text)
