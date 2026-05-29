"""RAG engine that combines vector search with Claude Sonnet generation."""

import anthropic

from .vector_store import VectorStore


class RAGEngine:
    """Retrieval-Augmented Generation engine using Claude Sonnet."""

    def __init__(self, vector_store: VectorStore, anthropic_api_key: str):
        self.vector_store = vector_store
        self.client = anthropic.Anthropic(api_key=anthropic_api_key)

    def generate_answer(self, question: str, top_k: int = 5) -> dict:
        """Generate an answer using retrieved context.

        Returns a dict with 'answer' and 'sources'.
        """
        # Retrieve relevant chunks
        results = self.vector_store.search(question, top_k=top_k)

        if not results:
            return {
                "answer": "ドキュメントがまだアップロードされていないか、関連する情報が見つかりませんでした。先にドキュメントをアップロードしてください。",
                "sources": [],
            }

        # Build context from retrieved chunks
        context_parts = []
        sources = []
        for r in results:
            context_parts.append(f"[出典: {r['source']}]\n{r['text']}")
            if r["source"] not in sources:
                sources.append(r["source"])

        context = "\n\n---\n\n".join(context_parts)

        # Generate answer using Claude Sonnet
        system_prompt = (
            "あなたはドキュメントに基づいて質問に答えるアシスタントです。\n"
            "以下のコンテキスト情報のみを使って質問に答えてください。\n"
            "コンテキストに答えが含まれていない場合は、「提供されたドキュメントにはその情報が含まれていません」と正直に答えてください。\n"
            "回答は日本語で行ってください。出典も明記してください。"
        )

        user_prompt = f"コンテキスト:\n{context}\n\n質問: {question}"

        response = self.client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1024,
            system=system_prompt,
            messages=[
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.2,
        )

        answer = response.content[0].text

        return {
            "answer": answer,
            "sources": sources,
        }
