"""RAG engine that combines vector search with Claude Sonnet generation."""

import json
import anthropic

from .vector_store import VectorStore


class RAGEngine:
    """Retrieval-Augmented Generation engine using Claude Sonnet."""

    def __init__(self, vector_store: VectorStore, anthropic_api_key: str):
        self.vector_store = vector_store
        self.client = anthropic.Anthropic(api_key=anthropic_api_key)
        self.conversations: dict[str, list[dict]] = {}
        self.max_history = 10  # Keep last 10 exchanges

    def _rerank(self, question: str, results: list[dict]) -> list[dict]:
        """Rerank search results using Claude to assess relevance."""
        if not results:
            return results

        # Build chunks for evaluation
        chunks_text = ""
        for i, r in enumerate(results):
            chunks_text += f"[{i}] {r['text'][:300]}\n\n"

        rerank_prompt = (
            f"以下の質問に対して、各テキストチャンクの関連度を1〜5で評価してください。\n"
            f"5=非常に関連がある、1=全く関連がない\n"
            f"JSON配列で返してください。例: [5, 3, 1, 4, 2]\n\n"
            f"質問: {question}\n\n"
            f"チャンク:\n{chunks_text}\n"
            f"評価（{len(results)}個の数値をJSON配列で）:"
        )

        try:
            response = self.client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=200,
                messages=[{"role": "user", "content": rerank_prompt}],
                temperature=0,
            )
            scores_text = response.content[0].text.strip()
            # Extract JSON array from response
            start = scores_text.find("[")
            end = scores_text.rfind("]") + 1
            if start >= 0 and end > start:
                scores = json.loads(scores_text[start:end])
            else:
                return results  # Fallback: return original order

            # Pair results with rerank scores and sort
            scored_results = []
            for i, r in enumerate(results):
                rerank_score = scores[i] if i < len(scores) else 1
                scored_results.append((rerank_score, r))

            scored_results.sort(key=lambda x: x[0], reverse=True)

            # Filter out low-relevance chunks (score <= 2)
            reranked = [r for score, r in scored_results if score >= 3]

            # If all filtered out, keep top 3
            if not reranked:
                reranked = [r for _, r in scored_results[:3]]

            return reranked

        except Exception:
            # If reranking fails, return original results
            return results

    def _get_surrounding_context(self, results: list[dict]) -> list[dict]:
        """Add surrounding chunks for better context."""
        enhanced_results = []
        seen_indices = set()

        for r in results:
            source = r["source"]
            # Find the index of this chunk in the vector store
            for i, (chunk, meta) in enumerate(zip(self.vector_store.chunks, self.vector_store.metadata)):
                if chunk == r["text"] and meta["source"] == source and i not in seen_indices:
                    seen_indices.add(i)
                    # Get previous chunk if same source
                    if i > 0 and self.vector_store.metadata[i-1]["source"] == source and (i-1) not in seen_indices:
                        prev_text = self.vector_store.chunks[i-1]
                        # Prepend to current chunk text
                        r = dict(r)
                        r["text"] = prev_text + " " + r["text"]
                        seen_indices.add(i-1)
                    # Get next chunk if same source
                    if i < len(self.vector_store.chunks) - 1 and self.vector_store.metadata[i+1]["source"] == source and (i+1) not in seen_indices:
                        next_text = self.vector_store.chunks[i+1]
                        r = dict(r)
                        r["text"] = r["text"] + " " + next_text
                        seen_indices.add(i+1)
                    break

            enhanced_results.append(r)

        return enhanced_results

    def generate_answer(self, question: str, conversation_id: str = "default", top_k: int = 20) -> dict:
        """Generate an answer using retrieved context and conversation history.

        Returns a dict with 'answer', 'sources', 'confidence', and 'conversation_id'.
        """
        # Retrieve more candidates for reranking
        results = self.vector_store.search(question, top_k=top_k)

        if not results:
            return {
                "answer": "ドキュメントがまだアップロードされていないか、関連する情報が見つかりませんでした。先にドキュメントをアップロードしてください。",
                "sources": [],
                "confidence": 0,
                "conversation_id": conversation_id,
            }

        # Rerank results using Claude
        reranked = self._rerank(question, results[:15])

        # Take top results and add surrounding context
        top_results = reranked[:6]
        enhanced_results = self._get_surrounding_context(top_results)

        # Calculate confidence from reranked scores
        max_score = max(r["score"] for r in enhanced_results)
        confidence = round(max_score * 100, 1)

        # Build context from enhanced chunks with page info
        context_parts = []
        sources = []
        for r in enhanced_results:
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
            "回答は日本語で行ってください。出典も明記してください。\n"
            "できるだけ具体的かつ正確に回答してください。"
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
            max_tokens=1500,
            system=system_prompt,
            messages=messages,
            temperature=0.1,
        )

        answer = response.content[0].text

        # Save to history
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
