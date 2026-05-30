"""RAG engine that combines vector search with Claude Sonnet generation."""

import anthropic

from .vector_store import VectorStore


class RAGEngine:
    """Retrieval-Augmented Generation engine using Claude Sonnet."""

    def __init__(self, vector_store: VectorStore, anthropic_api_key: str):
        self.vector_store = vector_store
        self.client = anthropic.Anthropic(api_key=anthropic_api_key)
        self.conversations: dict[str, list[dict]] = {}
        self.max_history = 10  # Keep last 10 exchanges

    def generate_answer(self, question: str, conversation_id: str = "default", top_k: int = 5) -> dict:
        """Generate an answer using retrieved context and conversation history.

        Returns a dict with 'answer', 'sources', and 'conversation_id'.
        """
        # Retrieve relevant chunks
        results = self.vector_store.search(question, top_k=top_k)

        if not results:
            return {
                "answer": "ドキュメントがまだアップロードされていないか、関連する情報が見つかりませんでした。先にドキュメントをアップロードしてください。",
                "sources": [],
                "confidence": 0,
                "conversation_id": conversation_id,
            }

        # Calculate confidence from search scores
        avg_score = sum(r["score"] for r in results) / len(results)
        max_score = max(r["score"] for r in results)
        confidence = round(max_score * 100, 1)

        # Build context from retrieved chunks with page info
        context_parts = []
        sources = []
        for r in results:
            page_info = f" (p.{r['page']})" if r.get("page") else ""
            context_parts.append(f"[出典: {r['source']}{page_info}]\n{r['text']}")
            source_entry = r["source"] + (f" p.{r['page']}" if r.get("page") else "")
            if source_entry not in sources:
                sources.append(source_entry)

        context = "\n\n---\n\n".join(context_parts)

        # System prompt
        system_prompt = (
            "あなたはドキュメントに基づいて質問に答えるアシスタントです。\n"
            "以下のコンテキスト情報を使って質問に答えてください。\n"
            "コンテキストに答えが含まれていない場合は、「提供されたドキュメントにはその情報が含まれていません」と正直に答えてください。\n"
            "会話の履歴も考慮して、文脈に沿った回答をしてください。\n"
            "回答は日本語で行ってください。出典も明記してください。"
        )

        # Build messages with history
        if conversation_id not in self.conversations:
            self.conversations[conversation_id] = []

        history = self.conversations[conversation_id]

        # Current user message with context
        user_message = f"コンテキスト:\n{context}\n\n質問: {question}"

        # Build messages array: history + current
        messages = []
        for entry in history:
            messages.append(entry)
        messages.append({"role": "user", "content": user_message})

        response = self.client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1024,
            system=system_prompt,
            messages=messages,
            temperature=0.2,
        )

        answer = response.content[0].text

        # Save to history (store simplified user message without context for readability)
        history.append({"role": "user", "content": question})
        history.append({"role": "assistant", "content": answer})

        # Trim history to max length
        if len(history) > self.max_history * 2:
            self.conversations[conversation_id] = history[-(self.max_history * 2):]

        return {
            "answer": answer,
            "sources": sources,
            "confidence": confidence,
            "conversation_id": conversation_id,
        }

    def clear_conversation(self, conversation_id: str = "default") -> None:
        """Clear conversation history."""
        if conversation_id in self.conversations:
            del self.conversations[conversation_id]
