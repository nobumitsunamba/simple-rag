"""FastAPI application for the RAG system."""

import io
import os
import threading
from contextlib import asynccontextmanager
from datetime import datetime

from docx import Document as DocxDocument
from docx.shared import Pt
from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel

from .document_processor import extract_text, split_text
from .knowledge_store import (
    save_knowledge_base,
    load_knowledge_base,
    list_knowledge_bases,
    delete_knowledge_base,
)
from .rag_engine import RAGEngine
from .vector_store import VectorStore

load_dotenv()

# Global instances
vector_store: VectorStore | None = None
rag_engine: RAGEngine | None = None

# Track processing status
processing_status: dict[str, dict] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize resources on startup."""
    global vector_store, rag_engine

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        print("WARNING: ANTHROPIC_API_KEY not set. Chat will not work until it is configured.")

    vector_store = VectorStore()
    if api_key:
        rag_engine = RAGEngine(vector_store, api_key)

    yield

    # Cleanup
    vector_store = None
    rag_engine = None


app = FastAPI(title="Simple RAG App", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    question: str
    conversation_id: str = "default"


class ChatResponse(BaseModel):
    answer: str
    sources: list[str]
    conversation_id: str


class UploadResponse(BaseModel):
    filename: str
    chunks_added: int
    message: str
    status: str


class StatsResponse(BaseModel):
    total_chunks: int
    total_documents: int
    documents: list[str]


class ProcessingStatusResponse(BaseModel):
    filename: str
    status: str
    chunks_added: int
    message: str


class SaveRequest(BaseModel):
    name: str


class KnowledgeBaseInfo(BaseModel):
    name: str
    total_chunks: int = 0
    total_documents: int = 0
    created_at: str = ""


class LoadRequest(BaseModel):
    name: str


def _process_document_background(filename: str, text: str):
    """Process document in background thread."""
    import time
    global processing_status
    try:
        chunks = split_text(text)
        processing_status[filename]["message"] = f"埋め込み生成中... (0/{len(chunks)}チャンク)"

        # Process in smaller batches to show progress and avoid throttling
        batch_size = 20
        total_added = 0
        for i in range(0, len(chunks), batch_size):
            batch = chunks[i:i + batch_size]
            vector_store.add_documents(batch, filename)
            total_added += len(batch)
            processing_status[filename]["chunks_added"] = total_added
            processing_status[filename]["message"] = f"埋め込み生成中... ({total_added}/{len(chunks)}チャンク)"

        processing_status[filename]["status"] = "completed"
        processing_status[filename]["message"] = f"'{filename}' を処理しました。{total_added}個のチャンクを追加しました。"
    except Exception as e:
        processing_status[filename]["status"] = "error"
        processing_status[filename]["message"] = f"処理中にエラーが発生しました: {str(e)}"


@app.post("/api/upload", response_model=UploadResponse)
async def upload_document(file: UploadFile = File(...)):
    """Upload a PDF or Word document for processing."""
    if not file.filename:
        raise HTTPException(status_code=400, detail="ファイル名が必要です。")

    allowed_extensions = {".pdf", ".docx", ".doc"}
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in allowed_extensions:
        raise HTTPException(
            status_code=400,
            detail=f"サポートされていないファイル形式です。対応形式: {', '.join(allowed_extensions)}",
        )

    try:
        content = await file.read()
        text = extract_text(file.filename, content)

        if not text.strip():
            raise HTTPException(
                status_code=400,
                detail="ファイルからテキストを抽出できませんでした。",
            )

        chunks = split_text(text)
        num_chunks = len(chunks)

        if num_chunks > 100:
            # Large file: process in background
            processing_status[file.filename] = {
                "filename": file.filename,
                "status": "processing",
                "chunks_added": 0,
                "message": f"処理を開始しました... ({num_chunks}チャンク)",
            }
            thread = threading.Thread(
                target=_process_document_background,
                args=(file.filename, text),
                daemon=True,
            )
            thread.start()

            return UploadResponse(
                filename=file.filename,
                chunks_added=0,
                message=f"'{file.filename}' の処理をバックグラウンドで開始しました（{num_chunks}チャンク）。処理状況は自動更新されます。",
                status="processing",
            )
        else:
            # Small file: process immediately
            added = vector_store.add_documents(chunks, file.filename)
            return UploadResponse(
                filename=file.filename,
                chunks_added=added,
                message=f"'{file.filename}' を処理しました。{added}個のチャンクを追加しました。",
                status="completed",
            )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"ファイル処理中にエラーが発生しました: {str(e)}")


@app.get("/api/processing/{filename}", response_model=ProcessingStatusResponse)
async def get_processing_status(filename: str):
    """Get processing status for a file."""
    if filename not in processing_status:
        raise HTTPException(status_code=404, detail="ファイルが見つかりません。")
    return ProcessingStatusResponse(**processing_status[filename])


@app.post("/api/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """Ask a question about the uploaded documents."""
    if not rag_engine:
        raise HTTPException(
            status_code=503,
            detail="ANTHROPIC_API_KEYが設定されていません。.envファイルを確認してください。",
        )

    if not request.question.strip():
        raise HTTPException(status_code=400, detail="質問を入力してください。")

    try:
        result = rag_engine.generate_answer(request.question, request.conversation_id)
        return ChatResponse(answer=result["answer"], sources=result["sources"], conversation_id=result["conversation_id"])
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"回答生成中にエラーが発生しました: {str(e)}")


@app.get("/api/stats", response_model=StatsResponse)
async def get_stats():
    """Get statistics about uploaded documents."""
    stats = vector_store.get_stats()
    return StatsResponse(**stats)


@app.post("/api/clear")
async def clear_store():
    """Clear all uploaded documents from current session."""
    vector_store.clear()
    processing_status.clear()
    if rag_engine:
        rag_engine.conversations.clear()
    return {"message": "現在のセッションデータを削除しました。"}


@app.delete("/api/document/{filename}")
async def remove_document(filename: str):
    """Remove a specific document from the current session."""
    removed = vector_store.remove_document(filename)
    if removed == 0:
        raise HTTPException(status_code=404, detail=f"ドキュメント '{filename}' が見つかりません。")
    return {"message": f"'{filename}' を削除しました（{removed}チャンク）。", "chunks_removed": removed}


# --- Knowledge Base Save/Load ---

@app.post("/api/knowledge/save")
async def save_knowledge(request: SaveRequest):
    """Save current documents as a named knowledge base."""
    if not vector_store.chunks:
        raise HTTPException(status_code=400, detail="保存するドキュメントがありません。先にファイルをアップロードしてください。")

    if not request.name.strip():
        raise HTTPException(status_code=400, detail="ナレッジベース名を入力してください。")

    try:
        result = save_knowledge_base(
            name=request.name.strip(),
            chunks=vector_store.chunks,
            metadata=vector_store.metadata,
            embeddings=vector_store.embeddings,
        )
        return {
            "message": f"ナレッジベース '{request.name}' を保存しました（{result['total_chunks']}チャンク、{result['total_documents']}ファイル）。",
            **result,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"保存中にエラーが発生しました: {str(e)}")


@app.post("/api/knowledge/load")
async def load_knowledge(request: LoadRequest):
    """Load a saved knowledge base."""
    if not request.name.strip():
        raise HTTPException(status_code=400, detail="ナレッジベース名を入力してください。")

    try:
        data = load_knowledge_base(request.name.strip())
        if data is None:
            raise HTTPException(status_code=404, detail=f"ナレッジベース '{request.name}' が見つかりません。")

        # Replace current vector store data
        vector_store.chunks = data["chunks"]
        vector_store.metadata = data["metadata"]
        vector_store.embeddings = data["embeddings"]

        # Clear conversation history for fresh start
        if rag_engine:
            rag_engine.conversations.clear()

        total_docs = len(set(m["source"] for m in data["metadata"]))
        return {
            "message": f"ナレッジベース '{request.name}' を読み込みました（{len(data['chunks'])}チャンク、{total_docs}ファイル）。",
            "name": request.name,
            "total_chunks": len(data["chunks"]),
            "total_documents": total_docs,
            "documents": list(set(m["source"] for m in data["metadata"])),
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"読み込み中にエラーが発生しました: {str(e)}")


@app.post("/api/knowledge/append")
async def append_to_knowledge(request: LoadRequest):
    """Load a saved knowledge base and append current session data to it."""
    if not request.name.strip():
        raise HTTPException(status_code=400, detail="ナレッジベース名を入力してください。")

    if not vector_store.chunks:
        raise HTTPException(status_code=400, detail="追加するドキュメントがありません。")

    try:
        # Load existing data
        data = load_knowledge_base(request.name.strip())
        if data is None:
            raise HTTPException(status_code=404, detail=f"ナレッジベース '{request.name}' が見つかりません。")

        # Merge: existing + current session
        merged_chunks = data["chunks"] + vector_store.chunks
        merged_metadata = data["metadata"] + vector_store.metadata
        merged_embeddings = data["embeddings"] + vector_store.embeddings

        # Save merged data
        result = save_knowledge_base(
            name=request.name.strip(),
            chunks=merged_chunks,
            metadata=merged_metadata,
            embeddings=merged_embeddings,
        )

        # Update current session with merged data
        vector_store.chunks = merged_chunks
        vector_store.metadata = merged_metadata
        vector_store.embeddings = merged_embeddings

        return {
            "message": f"ナレッジベース '{request.name}' にドキュメントを追加しました（合計{result['total_chunks']}チャンク、{result['total_documents']}ファイル）。",
            **result,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"追加保存中にエラーが発生しました: {str(e)}")


@app.get("/api/knowledge/list")
async def list_knowledge():
    """List all saved knowledge bases."""
    try:
        bases = list_knowledge_bases()
        return {"knowledge_bases": bases}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"一覧取得中にエラーが発生しました: {str(e)}")


@app.delete("/api/knowledge/{name}")
async def delete_knowledge(name: str):
    """Delete a saved knowledge base."""
    try:
        success = delete_knowledge_base(name)
        if success:
            return {"message": f"ナレッジベース '{name}' を削除しました。"}
        else:
            raise HTTPException(status_code=404, detail=f"ナレッジベース '{name}' が見つかりません。")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"削除中にエラーが発生しました: {str(e)}")


# --- Chat Export ---

class ExportRequest(BaseModel):
    messages: list[dict]  # [{role: "user"|"assistant", content: str}]
    knowledge_base_name: str = ""


@app.post("/api/export/word")
async def export_chat_to_word(request: ExportRequest):
    """Export chat history as a Word document."""
    doc = DocxDocument()

    # Title
    doc.add_heading("チャット履歴", level=0)

    # Metadata
    meta = doc.add_paragraph()
    meta.add_run(f"エクスポート日時: {datetime.now().strftime('%Y年%m月%d日 %H:%M')}\n").font.size = Pt(9)
    if request.knowledge_base_name:
        meta.add_run(f"ナレッジベース: {request.knowledge_base_name}\n").font.size = Pt(9)

    doc.add_paragraph("")

    # Messages
    for msg in request.messages:
        role = msg.get("role", "")
        content = msg.get("content", "")

        if role == "user":
            p = doc.add_paragraph()
            run = p.add_run("Q: ")
            run.bold = True
            p.add_run(content)
        elif role == "assistant":
            p = doc.add_paragraph()
            run = p.add_run("A: ")
            run.bold = True
            p.add_run(content)
            doc.add_paragraph("")  # spacing

    # Save to buffer
    buffer = io.BytesIO()
    doc.save(buffer)
    buffer.seek(0)

    filename = f"chat_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.docx"
    return StreamingResponse(
        buffer,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@app.get("/", response_class=HTMLResponse)
async def serve_ui():
    """Serve the chat UI."""
    ui_path = os.path.join(os.path.dirname(__file__), "..", "static", "index.html")
    with open(ui_path, "r", encoding="utf-8") as f:
        return f.read()
