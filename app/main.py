"""FastAPI application for the RAG system."""

import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .document_processor import extract_text, split_text
from .rag_engine import RAGEngine
from .vector_store import VectorStore

load_dotenv()

# Global instances
vector_store: VectorStore | None = None
rag_engine: RAGEngine | None = None


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


class StatsResponse(BaseModel):
    total_chunks: int
    total_documents: int
    documents: list[str]


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
        num_chunks = vector_store.add_documents(chunks, file.filename)

        return UploadResponse(
            filename=file.filename,
            chunks_added=num_chunks,
            message=f"'{file.filename}' を処理しました。{num_chunks}個のチャンクを追加しました。",
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"ファイル処理中にエラーが発生しました: {str(e)}")


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
    return {"message": "すべてのドキュメントデータを削除しました。"}


@app.get("/", response_class=HTMLResponse)
async def serve_ui():
    """Serve the chat UI."""
    ui_path = os.path.join(os.path.dirname(__file__), "..", "static", "index.html")
    with open(ui_path, "r", encoding="utf-8") as f:
        return f.read()
