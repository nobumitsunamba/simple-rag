"""Vector store module using pure Python TF-IDF for similarity search."""

import math
import re
from collections import Counter


def _tokenize(text: str) -> list[str]:
    """Simple tokenizer: split on non-alphanumeric, keep Japanese characters."""
    # Split into character n-grams for better Japanese support
    tokens = re.findall(r'\w+', text.lower())
    # Also add character bigrams for Japanese text
    chars = re.sub(r'\s+', '', text.lower())
    bigrams = [chars[i:i+2] for i in range(len(chars) - 1)]
    return tokens + bigrams


class VectorStore:
    """Pure Python TF-IDF based document search store."""

    def __init__(self):
        self.chunks: list[str] = []
        self.metadata: list[dict] = []
        self._doc_freqs: Counter = Counter()
        self._chunk_tokens: list[Counter] = []

    def add_documents(self, chunks: list[str], source_filename: str) -> int:
        """Add document chunks to the store."""
        if not chunks:
            return 0

        for chunk in chunks:
            tokens = _tokenize(chunk)
            token_counts = Counter(tokens)
            self._chunk_tokens.append(token_counts)
            # Update document frequency (each unique token in this chunk)
            for token in set(tokens):
                self._doc_freqs[token] += 1

        self.chunks.extend(chunks)
        self.metadata.extend(
            [{"source": source_filename, "chunk_index": i} for i in range(len(chunks))]
        )

        return len(chunks)

    def _tfidf_vector(self, token_counts: Counter) -> dict[str, float]:
        """Compute TF-IDF vector for a token count."""
        n_docs = len(self.chunks)
        vector = {}
        total_tokens = sum(token_counts.values())
        if total_tokens == 0:
            return vector
        for token, count in token_counts.items():
            tf = count / total_tokens
            df = self._doc_freqs.get(token, 0)
            idf = math.log((n_docs + 1) / (df + 1)) + 1
            vector[token] = tf * idf
        return vector

    def _cosine_similarity(self, vec_a: dict[str, float], vec_b: dict[str, float]) -> float:
        """Compute cosine similarity between two sparse vectors."""
        # Dot product
        common_keys = set(vec_a.keys()) & set(vec_b.keys())
        if not common_keys:
            return 0.0
        dot = sum(vec_a[k] * vec_b[k] for k in common_keys)
        # Magnitudes
        mag_a = math.sqrt(sum(v * v for v in vec_a.values()))
        mag_b = math.sqrt(sum(v * v for v in vec_b.values()))
        if mag_a == 0 or mag_b == 0:
            return 0.0
        return dot / (mag_a * mag_b)

    def search(self, query: str, top_k: int = 5) -> list[dict]:
        """Search for the most relevant chunks given a query."""
        if not self.chunks:
            return []

        query_tokens = Counter(_tokenize(query))
        query_vec = self._tfidf_vector(query_tokens)

        scores = []
        for i, chunk_tokens in enumerate(self._chunk_tokens):
            chunk_vec = self._tfidf_vector(chunk_tokens)
            score = self._cosine_similarity(query_vec, chunk_vec)
            scores.append((score, i))

        # Sort by score descending
        scores.sort(key=lambda x: x[0], reverse=True)

        results = []
        for score, idx in scores[:top_k]:
            if score > 0:
                results.append(
                    {
                        "text": self.chunks[idx],
                        "source": self.metadata[idx]["source"],
                        "score": score,
                    }
                )

        return results

    def get_stats(self) -> dict:
        """Get statistics about the vector store."""
        sources = set(m["source"] for m in self.metadata)
        return {
            "total_chunks": len(self.chunks),
            "total_documents": len(sources),
            "documents": list(sources),
        }

    def clear(self) -> None:
        """Clear all data from the store."""
        self.chunks = []
        self.metadata = []
        self._doc_freqs = Counter()
        self._chunk_tokens = []
