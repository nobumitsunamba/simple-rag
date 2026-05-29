"""FastAPI application for the RAG system."""

import os
import threading
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from .document_processor import extract_text, split_text
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


class ChatResponse(BaseModel):
    answer: str
    sources: list[str]


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
        result = rag_engine.generate_answer(request.question)
        return ChatResponse(answer=result["answer"], sources=result["sources"])
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"回答生成中にエラーが発生しました: {str(e)}")


@app.get("/api/stats", response_model=StatsResponse)
async def get_stats():
    """Get statistics about uploaded documents."""
    stats = vector_store.get_stats()
    return StatsResponse(**stats)


@app.post("/api/clear")
async def clear_store():
    """Clear all uploaded documents."""
    vector_store.clear()
    processing_status.clear()
    return {"message": "すべてのドキュメントデータを削除しました。"}


@app.get("/", response_class=HTMLResponse)
async def serve_ui():
    """Serve the chat UI."""
    ui_path = os.path.join(os.path.dirname(__file__), "..", "static", "index.html")
    with open(ui_path, "r", encoding="utf-8") as f:
        return f.read()
