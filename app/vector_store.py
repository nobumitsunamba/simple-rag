"""Vector store module using Amazon Bedrock Titan Embeddings for semantic search."""

import json
import math
import os
import concurrent.futures

import boto3


class VectorStore:
    """Semantic search store using Amazon Bedrock Titan Text Embeddings V2."""

    def __init__(self, region: str = None, dimensions: int = 256):
        self.region = region or os.getenv("AWS_REGION", "ap-northeast-1")
        self.dimensions = dimensions
        self.client = boto3.client("bedrock-runtime", region_name=self.region)
        self.chunks: list[str] = []
        self.metadata: list[dict] = []
        self.embeddings: list[list[float]] = []

    def _get_embedding(self, text: str) -> list[float]:
        """Get embedding vector from Titan Embeddings V2 with retry."""
        import time

        body = json.dumps({
            "inputText": text[:8000],  # Titan V2 max input
            "dimensions": self.dimensions,
        })

        max_retries = 10
        for attempt in range(max_retries):
            try:
                response = self.client.invoke_model(
                    modelId="amazon.titan-embed-text-v2:0",
                    contentType="application/json",
                    accept="application/json",
                    body=body,
                )
                result = json.loads(response["body"].read())
                return result["embedding"]
            except Exception as e:
                if "ThrottlingException" in str(type(e).__name__) or "Throttling" in str(e):
                    if attempt < max_retries - 1:
                        wait = 2 ** attempt * 1.0  # 1, 2, 4, 8, 16, 32...
                        time.sleep(wait)
                    else:
                        raise
                else:
                    raise

    def _get_embeddings_batch(self, texts: list[str], max_workers: int = 2) -> list[list[float]]:
        """Get embeddings for multiple texts with limited concurrency."""
        embeddings = [None] * len(texts)

        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_idx = {
                executor.submit(self._get_embedding, text): idx
                for idx, text in enumerate(texts)
            }
            for future in concurrent.futures.as_completed(future_to_idx):
                idx = future_to_idx[future]
                embeddings[idx] = future.result()

        return embeddings

    def _cosine_similarity(self, vec_a: list[float], vec_b: list[float]) -> float:
        """Compute cosine similarity between two vectors."""
        dot = sum(a * b for a, b in zip(vec_a, vec_b))
        mag_a = math.sqrt(sum(a * a for a in vec_a))
        mag_b = math.sqrt(sum(b * b for b in vec_b))
        if mag_a == 0 or mag_b == 0:
            return 0.0
        return dot / (mag_a * mag_b)

    def add_documents(self, chunks: list[str], source_filename: str, pages: list[int | None] = None) -> int:
        """Add document chunks to the store.

        Returns the number of chunks added.
        """
        if not chunks:
            return 0

        # Get embeddings in parallel batches
        new_embeddings = self._get_embeddings_batch(chunks)

        self.chunks.extend(chunks)
        self.embeddings.extend(new_embeddings)

        for i in range(len(chunks)):
            page = pages[i] if pages and i < len(pages) else None
            self.metadata.append({
                "source": source_filename,
                "chunk_index": i,
                "page": page,
            })

        return len(chunks)

    def search(self, query: str, top_k: int = 10, max_per_source: int = 3) -> list[dict]:
        """Search for the most relevant chunks given a query.

        Returns results from multiple sources for diversity.
        top_k: total number of candidates to consider
        max_per_source: max chunks from a single source file
        """
        if not self.chunks:
            return []

        query_embedding = self._get_embedding(query)

        scores = []
        for i, chunk_embedding in enumerate(self.embeddings):
            score = self._cosine_similarity(query_embedding, chunk_embedding)
            scores.append((score, i))

        scores.sort(key=lambda x: x[0], reverse=True)

        # Diversify results: limit per source
        results = []
        source_counts: dict[str, int] = {}
        for score, idx in scores:
            if score <= 0:
                continue
            source = self.metadata[idx]["source"]
            if source_counts.get(source, 0) >= max_per_source:
                continue
            results.append(
                {
                    "text": self.chunks[idx],
                    "source": source,
                    "score": score,
                    "page": self.metadata[idx].get("page"),
                }
            )
            source_counts[source] = source_counts.get(source, 0) + 1
            if len(results) >= top_k:
                break

        return results

    def keyword_search(self, query: str, top_k: int = 10) -> list[dict]:
        """Keyword-based search using exact term matching."""
        import re
        if not self.chunks:
            return []

        # Tokenize query into words
        query_terms = set(re.findall(r'\w+', query.lower()))
        if not query_terms:
            return []

        scores = []
        for i, chunk in enumerate(self.chunks):
            chunk_lower = chunk.lower()
            # Count how many query terms appear in the chunk
            matches = sum(1 for term in query_terms if term in chunk_lower)
            if matches > 0:
                # Score: proportion of query terms found, weighted by frequency
                score = matches / len(query_terms)
                scores.append((score, i))

        scores.sort(key=lambda x: x[0], reverse=True)

        results = []
        for score, idx in scores[:top_k]:
            results.append({
                "text": self.chunks[idx],
                "source": self.metadata[idx]["source"],
                "score": score,
                "page": self.metadata[idx].get("page"),
            })

        return results

    def hybrid_search(self, query: str, top_k: int = 15, semantic_weight: float = 0.7) -> list[dict]:
        """Hybrid search combining semantic and keyword search."""
        semantic_results = self.search(query, top_k=top_k)
        keyword_results = self.keyword_search(query, top_k=top_k)

        # Normalize scores
        if semantic_results:
            max_sem = max(r["score"] for r in semantic_results)
            for r in semantic_results:
                r["_norm_score"] = (r["score"] / max_sem) if max_sem > 0 else 0
        if keyword_results:
            max_kw = max(r["score"] for r in keyword_results)
            for r in keyword_results:
                r["_norm_score"] = (r["score"] / max_kw) if max_kw > 0 else 0

        # Merge results with weighted scores
        merged = {}
        for r in semantic_results:
            key = r["text"][:100]
            merged[key] = {
                **r,
                "combined_score": r["_norm_score"] * semantic_weight,
            }
        for r in keyword_results:
            key = r["text"][:100]
            if key in merged:
                merged[key]["combined_score"] += r["_norm_score"] * (1 - semantic_weight)
            else:
                merged[key] = {
                    **r,
                    "combined_score": r["_norm_score"] * (1 - semantic_weight),
                }

        # Sort by combined score
        sorted_results = sorted(merged.values(), key=lambda x: x["combined_score"], reverse=True)

        # Clean up internal fields
        results = []
        for r in sorted_results[:top_k]:
            results.append({
                "text": r["text"],
                "source": r["source"],
                "score": r["combined_score"],
                "page": r.get("page"),
            })

        return results

    def get_stats(self) -> dict:
        """Get statistics about the vector store."""
        sources = set(m["source"] for m in self.metadata)
        return {
            "total_chunks": len(self.chunks),
            "total_documents": len(sources),
            "documents": list(sources),
        }

    def remove_document(self, source_filename: str) -> int:
        """Remove all chunks from a specific source file.

        Returns the number of chunks removed.
        """
        indices_to_keep = [
            i for i, m in enumerate(self.metadata) if m["source"] != source_filename
        ]
        removed = len(self.chunks) - len(indices_to_keep)

        if removed == 0:
            return 0

        self.chunks = [self.chunks[i] for i in indices_to_keep]
        self.metadata = [self.metadata[i] for i in indices_to_keep]
        self.embeddings = [self.embeddings[i] for i in indices_to_keep]

        return removed

    def clear(self) -> None:
        """Clear all data from the store."""
        self.chunks = []
        self.metadata = []
        self.embeddings = []
