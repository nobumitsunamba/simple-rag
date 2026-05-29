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
                "conversation_id": conversation_id,
            }

        # Build context from retrieved chunks
        context_parts = []
        sources = []
        for r in results:
            context_parts.append(f"[出典: {r['source']}]\n{r['text']}")
            if r["source"] not in sources:
                sources.append(r["source"])

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
            "conversation_id": conversation_id,
        }

    def clear_conversation(self, conversation_id: str = "default") -> None:
        """Clear conversation history."""
        if conversation_id in self.conversations:
            del self.conversations[conversation_id]
