"""FastAPI application for the RAG system."""

import io
import json as json_module
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

from .audit_log import log_event
from .document_processor import extract_text, extract_text_with_pages, split_text, split_text_with_pages
from .auth import sign_up, confirm_sign_up, sign_in, verify_token
from .knowledge_store import (
    save_knowledge_base,
    load_knowledge_base,
    list_knowledge_bases,
    delete_knowledge_base,
    save_uploaded_file,
    get_file_download_url,
    rename_knowledge_base,
    list_groups,
    create_group,
    rename_group,
    delete_group,
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
    confidence: float
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
    group: str = ""


class KnowledgeBaseInfo(BaseModel):
    name: str
    total_chunks: int = 0
    total_documents: int = 0
    created_at: str = ""


class LoadRequest(BaseModel):
    name: str
    group: str = ""


def _process_document_background(filename: str, chunk_data: list[dict]):
    """Process document chunks in background thread (embedding only)."""
    import time
    global processing_status
    try:
        total_chunks = len(chunk_data)
        processing_status[filename]["message"] = f"埋め込み生成中... (0/{total_chunks}チャンク)"

        batch_size = 20
        total_added = 0
        for i in range(0, total_chunks, batch_size):
            batch = chunk_data[i:i + batch_size]
            chunks = [c["text"] for c in batch]
            pages = [c["page"] for c in batch]
            vector_store.add_documents(chunks, filename, pages)
            total_added += len(batch)
            processing_status[filename]["chunks_added"] = total_added
            processing_status[filename]["message"] = f"埋め込み生成中... ({total_added}/{total_chunks}チャンク)"

        processing_status[filename]["status"] = "completed"
        processing_status[filename]["message"] = f"'{filename}' を処理しました。{total_added}個のチャンクを追加しました。"
    except Exception as e:
        processing_status[filename]["status"] = "error"
        processing_status[filename]["message"] = f"処理中にエラーが発生しました: {str(e)}"


def _process_large_file_background(filename: str, content: bytes, analyze_images: bool = False):
    """Process a large file entirely in background (extraction + embedding)."""
    global processing_status
    try:
        # Save to S3
        processing_status[filename]["message"] = "ファイルを保存中..."
        save_uploaded_file(filename, content)

        # Extract text
        processing_status[filename]["message"] = "テキスト抽出中..."
        text, page_map = extract_text_with_pages(filename, content, analyze_images)

        if not text.strip():
            processing_status[filename]["status"] = "error"
            processing_status[filename]["message"] = "ファイルからテキストを抽出できませんでした。"
            return

        # Split into chunks
        processing_status[filename]["message"] = "チャンク分割中..."
        chunk_data = split_text_with_pages(text, page_map)
        total_chunks = len(chunk_data)

        # Embed
        processing_status[filename]["message"] = f"埋め込み生成中... (0/{total_chunks}チャンク)"
        batch_size = 20
        total_added = 0
        for i in range(0, total_chunks, batch_size):
            batch = chunk_data[i:i + batch_size]
            chunks = [c["text"] for c in batch]
            pages = [c["page"] for c in batch]
            vector_store.add_documents(chunks, filename, pages)
            total_added += len(batch)
            processing_status[filename]["chunks_added"] = total_added
            processing_status[filename]["message"] = f"埋め込み生成中... ({total_added}/{total_chunks}チャンク)"

        processing_status[filename]["status"] = "completed"
        processing_status[filename]["message"] = f"'{filename}' を処理しました。{total_added}個のチャンクを追加しました。"
    except Exception as e:
        processing_status[filename]["status"] = "error"
        processing_status[filename]["message"] = f"処理中にエラーが発生しました: {str(e)}"


@app.post("/api/upload", response_model=UploadResponse)
async def upload_document(file: UploadFile = File(...), analyze_images: bool = False):
    """Upload a PDF or Word document for processing."""
    if not file.filename:
        raise HTTPException(status_code=400, detail="ファイル名が必要です。")

    allowed_extensions = {".pdf", ".docx", ".doc", ".xlsx", ".xls", ".pptx", ".csv", ".txt", ".md", ".png", ".jpg", ".jpeg", ".gif", ".webp"}
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in allowed_extensions:
        raise HTTPException(
            status_code=400,
            detail=f"サポートされていないファイル形式です。対応形式: {', '.join(sorted(allowed_extensions))}",
        )

    try:
        content = await file.read()
        file_size = len(content)

        # Large files (>2MB): process everything in background
        if file_size > 2 * 1024 * 1024:
            processing_status[file.filename] = {
                "filename": file.filename,
                "status": "processing",
                "chunks_added": 0,
                "message": f"テキスト抽出中...",
            }
            thread = threading.Thread(
                target=_process_large_file_background,
                args=(file.filename, content, analyze_images),
                daemon=True,
            )
            thread.start()

            return UploadResponse(
                filename=file.filename,
                chunks_added=0,
                message=f"'{file.filename}' の処理をバックグラウンドで開始しました。処理状況は自動更新されます。",
                status="processing",
            )

        # Small files: process immediately
        # Save original file to S3 for later download
        save_uploaded_file(file.filename, content)

        text, page_map = extract_text_with_pages(file.filename, content, analyze_images)

        if not text.strip():
            raise HTTPException(
                status_code=400,
                detail="ファイルからテキストを抽出できませんでした。",
            )

        chunk_data = split_text_with_pages(text, page_map)
        num_chunks = len(chunk_data)

        if num_chunks > 50:
            # Medium file: text extracted but embedding in background
            processing_status[file.filename] = {
                "filename": file.filename,
                "status": "processing",
                "chunks_added": 0,
                "message": f"処理を開始しました... ({num_chunks}チャンク)",
            }
            thread = threading.Thread(
                target=_process_document_background,
                args=(file.filename, chunk_data),
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
            chunks = [c["text"] for c in chunk_data]
            pages = [c["page"] for c in chunk_data]
            added = vector_store.add_documents(chunks, file.filename, pages)
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
        log_event("chat", details={"question": request.question, "confidence": result["confidence"]})
        return ChatResponse(answer=result["answer"], sources=result["sources"], confidence=result["confidence"], conversation_id=result["conversation_id"])
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"回答生成中にエラーが発生しました: {str(e)}")


@app.get("/api/stats", response_model=StatsResponse)
async def get_stats():
    """Get statistics about uploaded documents."""
    stats = vector_store.get_stats()
    return StatsResponse(**stats)


@app.post("/api/chat/stream")
async def chat_stream(request: ChatRequest):
    """Stream a chat response using Server-Sent Events."""
    if not rag_engine:
        raise HTTPException(status_code=503, detail="ANTHROPIC_API_KEYが設定されていません。")

    if not request.question.strip():
        raise HTTPException(status_code=400, detail="質問を入力してください。")

    async def stream_response():
        try:
            # Send keep-alive while processing
            yield f"data: {json_module.dumps({'type': 'status', 'content': '検索中...'}, ensure_ascii=False)}\n\n"

            # Query expansion
            queries = rag_engine._expand_query(request.question)

            all_results = []
            seen_texts = set()
            for q in queries:
                results = rag_engine.vector_store.hybrid_search(q, top_k=10)
                for r in results:
                    if r["text"][:100] not in seen_texts:
                        seen_texts.add(r["text"][:100])
                        all_results.append(r)

            if not all_results:
                yield f"data: {json_module.dumps({'type': 'text', 'content': 'ドキュメントがまだアップロードされていないか、関連する情報が見つかりませんでした。'}, ensure_ascii=False)}\n\n"
                yield f"data: {json_module.dumps({'type': 'done', 'sources': [], 'confidence': 0})}\n\n"
                return

            yield f"data: {json_module.dumps({'type': 'status', 'content': '回答を生成中...'}, ensure_ascii=False)}\n\n"

            # Rerank
            reranked = rag_engine._rerank(request.question, all_results[:15])
            top_results = reranked[:6]
            enhanced_results = rag_engine._get_surrounding_context(top_results)

            max_score = max(r["score"] for r in enhanced_results)
            confidence = round(max_score * 100, 1)

            context_parts = []
            sources = []
            for r in enhanced_results:
                page_info = f" (p.{r['page']})" if r.get("page") else ""
                context_parts.append(f"[出典: {r['source']}{page_info}]\n{r['text']}")
                source_entry = r["source"] + (f" p.{r['page']}" if r.get("page") else "")
                if source_entry not in sources:
                    sources.append(source_entry)

            context = "\n\n---\n\n".join(context_parts)

            system_prompt = (
                "あなたは社内ドキュメントに基づいて質問に答える業務アシスタントです。\n\n"
                "## 回答ルール\n"
                "- コンテキスト情報のみを根拠に回答すること\n"
                "- コンテキストに答えがない場合は「提供されたドキュメントにはその情報が含まれていません」と正直に答える\n"
                "- 会話の履歴も考慮し、文脈に沿った回答をする\n"
                "- 推測や一般知識で補完しない\n\n"
                "## 回答フォーマット\n"
                "1. まず結論を1〜2文で簡潔に述べる\n"
                "2. 次に根拠となる情報を具体的に示す（数値、日付、固有名詞を含める）\n"
                "3. 必要に応じて補足情報や関連する注意点を付記する\n\n"
                "## 文体\n"
                "- 日本語で回答する\n"
                "- 敬体（です・ます調）で統一する\n"
                "- 箇条書きと文章を適切に使い分ける\n"
                "- 出典は回答の最後にまとめて記載する"
            )

            # Build messages with history
            conv_id = request.conversation_id
            if conv_id not in rag_engine.conversations:
                rag_engine.conversations[conv_id] = []
            history = rag_engine.conversations[conv_id]

            user_message = f"コンテキスト:\n{context}\n\n質問: {request.question}"
            messages = list(history) + [{"role": "user", "content": user_message}]

            # Stream the answer
            full_answer = ""
            with rag_engine.client.messages.stream(
                model="claude-sonnet-4-6",
                max_tokens=1500,
                system=system_prompt,
                messages=messages,
                temperature=0.1,
            ) as stream:
                for text in stream.text_stream:
                    full_answer += text
                    yield f"data: {json_module.dumps({'type': 'text', 'content': text}, ensure_ascii=False)}\n\n"

            # Save to history
            history.append({"role": "user", "content": request.question})
            history.append({"role": "assistant", "content": full_answer})
            if len(history) > rag_engine.max_history * 2:
                rag_engine.conversations[conv_id] = history[-(rag_engine.max_history * 2):]

            # Log
            log_event("chat_stream", details={"question": request.question, "confidence": confidence})

            # Send done event with metadata
            yield f"data: {json_module.dumps({'type': 'done', 'sources': sources, 'confidence': confidence}, ensure_ascii=False)}\n\n"
        except Exception as e:
            yield f"data: {json_module.dumps({'type': 'error', 'content': str(e)}, ensure_ascii=False)}\n\n"

    return StreamingResponse(stream_response(), media_type="text/event-stream")


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
            group=request.group,
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
        data = load_knowledge_base(request.name.strip(), request.group)
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
        # Count chunks per document
        doc_chunks = {}
        for m in data["metadata"]:
            doc_chunks[m["source"]] = doc_chunks.get(m["source"], 0) + 1

        return {
            "message": f"ナレッジベース '{request.name}' を読み込みました（{len(data['chunks'])}チャンク、{total_docs}ファイル）。",
            "name": request.name,
            "total_chunks": len(data["chunks"]),
            "total_documents": total_docs,
            "documents": [{"name": name, "chunks": count} for name, count in doc_chunks.items()],
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
        data = load_knowledge_base(request.name.strip(), request.group)
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
            group=request.group,
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
    """Delete a saved knowledge base (ungrouped)."""
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


@app.delete("/api/knowledge/{group}/{name}")
async def delete_knowledge_in_group(group: str, name: str):
    """Delete a saved knowledge base in a group."""
    try:
        success = delete_knowledge_base(name, group)
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


# --- Auth ---

class SignUpRequest(BaseModel):
    email: str
    password: str


class ConfirmRequest(BaseModel):
    email: str
    code: str


class SignInRequest(BaseModel):
    email: str
    password: str


@app.post("/api/auth/signup")
async def api_sign_up(request: SignUpRequest):
    try:
        result = sign_up(request.email, request.password)
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/auth/confirm")
async def api_confirm(request: ConfirmRequest):
    try:
        result = confirm_sign_up(request.email, request.code)
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/auth/signin")
async def api_sign_in(request: SignInRequest):
    try:
        result = sign_in(request.email, request.password)
        return result
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e))


@app.get("/api/auth/me")
async def api_get_me(authorization: str = ""):
    """Get current user info from token."""
    from fastapi import Header
    # Token is passed via query param or header
    token = authorization.replace("Bearer ", "") if authorization else ""
    if not token:
        raise HTTPException(status_code=401, detail="認証が必要です。")
    user = verify_token(token)
    if not user:
        raise HTTPException(status_code=401, detail="トークンが無効です。")
    return user


@app.get("/api/file/{filename}")
async def get_file_url(filename: str):
    """Get a presigned download URL for an uploaded file."""
    url = get_file_download_url(filename)
    if not url:
        raise HTTPException(status_code=404, detail="ファイルが見つかりません。")
    return {"url": url, "filename": filename}


# --- Group Management ---

class GroupRequest(BaseModel):
    name: str


class RenameRequest(BaseModel):
    old_name: str
    new_name: str
    old_group: str = ""
    new_group: str = ""


@app.get("/api/knowledge/groups")
async def api_list_groups():
    """List all knowledge base groups."""
    groups = list_groups()
    return {"groups": groups}


@app.post("/api/knowledge/groups")
async def api_create_group(request: GroupRequest):
    """Create a new group."""
    if not request.name.strip():
        raise HTTPException(status_code=400, detail="グループ名を入力してください。")
    create_group(request.name.strip())
    return {"message": f"グループ '{request.name}' を作成しました。"}


@app.put("/api/knowledge/groups/rename")
async def api_rename_group(request: RenameRequest):
    """Rename a group."""
    success = rename_group(request.old_name, request.new_name)
    if not success:
        raise HTTPException(status_code=404, detail="グループが見つかりません。")
    return {"message": f"グループ名を '{request.new_name}' に変更しました。"}


@app.delete("/api/knowledge/groups/{name}")
async def api_delete_group(name: str):
    """Delete a group and all its knowledge bases."""
    success = delete_group(name)
    if not success:
        raise HTTPException(status_code=404, detail="グループが見つかりません。")
    return {"message": f"グループ '{name}' を削除しました。"}


@app.put("/api/knowledge/rename")
async def api_rename_knowledge(request: RenameRequest):
    """Rename or move a knowledge base."""
    success = rename_knowledge_base(request.old_name, request.new_name, request.old_group, request.new_group)
    if not success:
        raise HTTPException(status_code=404, detail="ナレッジベースが見つかりません。")
    return {"message": f"'{request.new_name}' に変更しました。"}


@app.put("/api/knowledge/move")
async def api_move_knowledge(request: RenameRequest):
    """Move a knowledge base to a different group."""
    success = rename_knowledge_base(request.old_name, request.old_name, request.old_group, request.new_group)
    if not success:
        raise HTTPException(status_code=404, detail="ナレッジベースが見つかりません。")
    return {"message": f"'{request.old_name}' をグループ '{request.new_group}' に移動しました。"}


@app.get("/login", response_class=HTMLResponse)
async def serve_login():
    """Serve the login page."""
    ui_path = os.path.join(os.path.dirname(__file__), "..", "static", "login.html")
    with open(ui_path, "r", encoding="utf-8") as f:
        return f.read()
