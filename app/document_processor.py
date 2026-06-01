"""Document processing module for PDF, Word, Excel, PowerPoint, text, CSV, and image files."""

import base64
import csv
import io
import os
import re
from pathlib import Path

import anthropic
import fitz  # PyMuPDF
from docx import Document
from openpyxl import load_workbook
from pptx import Presentation


def extract_text_from_pdf(file_content: bytes) -> tuple[str, dict]:
    """Extract text and images from a PDF file with page numbers.

    Returns (full_text, page_map) where page_map maps chunk start positions to page numbers.
    """
    doc = fitz.open(stream=file_content, filetype="pdf")
    text_parts = []
    page_map = {}
    cumulative_pos = 0

    for i, page in enumerate(doc):
        page_text = page.get_text()

        # Extract images from the page
        image_descriptions = []
        for img_index, img in enumerate(page.get_images(full=True)):
            try:
                xref = img[0]
                base_image = doc.extract_image(xref)
                image_bytes = base_image["image"]
                image_ext = base_image["ext"]
                content_type = f"image/{image_ext}" if image_ext in ("png", "jpeg", "gif", "webp") else "image/png"

                # Only process images larger than 5KB (skip tiny icons/decorations)
                if len(image_bytes) > 5000:
                    description = _describe_image(image_bytes, content_type)
                    if description:
                        image_descriptions.append(f"[ページ{i+1}の画像] {description}")
            except Exception:
                pass

        # Combine text and image descriptions
        combined = page_text
        if image_descriptions:
            combined += "\n\n" + "\n\n".join(image_descriptions)

        if combined.strip():
            page_map[cumulative_pos] = i + 1
            text_parts.append(combined)
            cumulative_pos += len(combined) + 2

    doc.close()
    return "\n\n".join(text_parts), page_map


def extract_text_from_docx(file_content: bytes) -> str:
    """Extract text and images from a Word (.docx) file."""
    doc = Document(io.BytesIO(file_content))
    text_parts = []

    # Extract text from paragraphs
    for paragraph in doc.paragraphs:
        if paragraph.text.strip():
            text_parts.append(paragraph.text)

    # Extract images and describe them
    for rel in doc.part.rels.values():
        if "image" in rel.reltype:
            try:
                image_data = rel.target_part.blob
                description = _describe_image(image_data, rel.target_part.content_type)
                if description:
                    text_parts.append(f"[埋め込み画像の内容]\n{description}")
            except Exception:
                pass

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
    """Extract text, images, and slide summaries from a PowerPoint (.pptx) file."""
    prs = Presentation(io.BytesIO(file_content))
    text_parts = []

    for i, slide in enumerate(prs.slides, 1):
        slide_texts = []
        slide_images = []

        for shape in slide.shapes:
            if shape.has_text_frame:
                for paragraph in shape.text_frame.paragraphs:
                    if paragraph.text.strip():
                        slide_texts.append(paragraph.text)
            # Extract images from shapes
            if shape.shape_type == 13:  # Picture
                try:
                    image = shape.image
                    if len(image.blob) > 5000:  # Skip tiny images
                        description = _describe_image(image.blob, image.content_type)
                        if description:
                            slide_images.append(description)
                except Exception:
                    pass

        if not slide_texts and not slide_images:
            continue

        # Build slide content
        slide_content = f"[スライド {i}]\n"
        if slide_texts:
            slide_content += "\n".join(slide_texts)
        if slide_images:
            slide_content += "\n[画像の内容] " + " ".join(slide_images)

        # Generate slide intent summary using Claude
        slide_summary = _summarize_slide(i, slide_texts, slide_images)
        if slide_summary:
            slide_content += f"\n[スライドの要点] {slide_summary}"

        text_parts.append(slide_content)

    return "\n\n".join(text_parts)


def _summarize_slide(slide_num: int, texts: list[str], image_descriptions: list[str]) -> str:
    """Summarize the intent/meaning of a slide."""
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return ""

    content = ""
    if texts:
        content += "テキスト:\n" + "\n".join(texts)
    if image_descriptions:
        content += "\n画像の説明:\n" + "\n".join(image_descriptions)

    if not content.strip():
        return ""

    try:
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=200,
            messages=[{
                "role": "user",
                "content": f"以下はプレゼンテーションのスライド{slide_num}の内容です。このスライドが伝えたい要点を1〜2文で簡潔に要約してください。\n\n{content}",
            }],
            temperature=0,
        )
        return response.content[0].text
    except Exception:
        return ""


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


def _describe_image(image_data: bytes, content_type: str = "image/png") -> str:
    """Describe an image using Claude's vision capability. Used internally."""
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return ""

    # Normalize content type
    if "/" not in content_type:
        content_type = f"image/{content_type}"
    # Ensure supported type
    supported = {"image/png", "image/jpeg", "image/gif", "image/webp"}
    if content_type not in supported:
        content_type = "image/png"

    image_b64 = base64.standard_b64encode(image_data).decode("utf-8")

    try:
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1000,
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": content_type,
                            "data": image_b64,
                        },
                    },
                    {
                        "type": "text",
                        "text": "この画像の内容を簡潔に説明してください。テキストがあればすべて書き起こしてください。日本語で回答してください。",
                    },
                ],
            }],
            temperature=0,
        )
        return response.content[0].text
    except Exception:
        return ""


def extract_text_from_image(file_content: bytes, filename: str) -> str:
    """Extract text/description from an image using Claude's vision capability."""
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY が設定されていません。")

    # Determine media type
    ext = Path(filename).suffix.lower()
    media_types = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".webp": "image/webp",
    }
    media_type = media_types.get(ext, "image/png")

    # Encode image to base64
    image_data = base64.standard_b64encode(file_content).decode("utf-8")

    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2000,
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": media_type,
                        "data": image_data,
                    },
                },
                {
                    "type": "text",
                    "text": (
                        "この画像の内容を詳細に説明してください。\n"
                        "テキストが含まれている場合はすべて書き起こしてください。\n"
                        "図表やグラフの場合は、データや構造を文章で説明してください。\n"
                        "写真の場合は、写っているものを具体的に説明してください。\n"
                        "日本語で回答してください。"
                    ),
                },
            ],
        }],
        temperature=0,
    )

    return response.content[0].text


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
    elif suffix in (".png", ".jpg", ".jpeg", ".gif", ".webp"):
        return extract_text_from_image(file_content, filename)
    else:
        raise ValueError(f"Unsupported file type: {suffix}")


def extract_text_with_pages(filename: str, file_content: bytes) -> tuple[str, dict | None]:
    """Extract text with page mapping (only for PDF).

    Returns (text, page_map). page_map is None for non-PDF files.
    """
    suffix = Path(filename).suffix.lower()
    if suffix == ".pdf":
        return extract_text_from_pdf(file_content)
    elif suffix in (".png", ".jpg", ".jpeg", ".gif", ".webp"):
        return extract_text_from_image(file_content, filename), None
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
