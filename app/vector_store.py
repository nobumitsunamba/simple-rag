"""Vector store module using Amazon Bedrock Titan Embeddings for semantic search."""

import json
import math
import os

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
        """Get embedding vector from Titan Embeddings V2."""
        body = json.dumps({
            "inputText": text[:8000],  # Titan V2 max input
            "dimensions": self.dimensions,
        })
        response = self.client.invoke_model(
            modelId="amazon.titan-embed-text-v2:0",
            contentType="application/json",
            accept="application/json",
            body=body,
        )
        result = json.loads(response["body"].read())
        return result["embedding"]

    def _get_embeddings_batch(self, texts: list[str]) -> list[list[float]]:
        """Get embeddings for multiple texts."""
        embeddings = []
        for text in texts:
            embedding = self._get_embedding(text)
            embeddings.append(embedding)
        return embeddings

    def _cosine_similarity(self, vec_a: list[float], vec_b: list[float]) -> float:
        """Compute cosine similarity between two vectors."""
        dot = sum(a * b for a, b in zip(vec_a, vec_b))
        mag_a = math.sqrt(sum(a * a for a in vec_a))
        mag_b = math.sqrt(sum(b * b for b in vec_b))
        if mag_a == 0 or mag_b == 0:
            return 0.0
        return dot / (mag_a * mag_b)

    def add_documents(self, chunks: list[str], source_filename: str) -> int:
        """Add document chunks to the store.

        Returns the number of chunks added.
        """
        if not chunks:
            return 0

        # Get embeddings for all chunks
        new_embeddings = self._get_embeddings_batch(chunks)

        self.chunks.extend(chunks)
        self.embeddings.extend(new_embeddings)
        self.metadata.extend(
            [{"source": source_filename, "chunk_index": i} for i in range(len(chunks))]
        )

        return len(chunks)

    def search(self, query: str, top_k: int = 5) -> list[dict]:
        """Search for the most relevant chunks given a query.

        Returns a list of dicts with 'text', 'source', and 'score'.
        """
        if not self.chunks:
            return []

        # Get query embedding
        query_embedding = self._get_embedding(query)

        # Calculate similarities
        scores = []
        for i, chunk_embedding in enumerate(self.embeddings):
            score = self._cosine_similarity(query_embedding, chunk_embedding)
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
        self.embeddings = []
