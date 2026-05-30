"""Knowledge base persistence using S3."""

import json
import os
from datetime import datetime

import boto3
from botocore.exceptions import ClientError


BUCKET_NAME = os.getenv("KNOWLEDGE_BUCKET", "simple-rag-knowledge-032401368831")
S3_PREFIX = "knowledge-bases/"


def _get_s3_client():
    region = os.getenv("AWS_REGION", "ap-northeast-1")
    return boto3.client("s3", region_name=region)


def save_knowledge_base(name: str, chunks: list[str], metadata: list[dict], embeddings: list[list[float]]) -> dict:
    """Save a knowledge base to S3."""
    s3 = _get_s3_client()

    data = {
        "name": name,
        "created_at": datetime.utcnow().isoformat(),
        "chunks": chunks,
        "metadata": metadata,
        "embeddings": embeddings,
    }

    key = f"{S3_PREFIX}{name}.json"
    s3.put_object(
        Bucket=BUCKET_NAME,
        Key=key,
        Body=json.dumps(data, ensure_ascii=False),
        ContentType="application/json",
    )

    return {
        "name": name,
        "total_chunks": len(chunks),
        "total_documents": len(set(m["source"] for m in metadata)),
        "created_at": data["created_at"],
    }


def load_knowledge_base(name: str) -> dict | None:
    """Load a knowledge base from S3."""
    s3 = _get_s3_client()
    key = f"{S3_PREFIX}{name}.json"

    try:
        response = s3.get_object(Bucket=BUCKET_NAME, Key=key)
        data = json.loads(response["Body"].read().decode("utf-8"))
        return data
    except ClientError as e:
        if e.response["Error"]["Code"] == "NoSuchKey":
            return None
        raise


def list_knowledge_bases() -> list[dict]:
    """List all saved knowledge bases."""
    s3 = _get_s3_client()

    try:
        response = s3.list_objects_v2(Bucket=BUCKET_NAME, Prefix=S3_PREFIX)
    except ClientError:
        return []

    if "Contents" not in response:
        return []

    bases = []
    for obj in response["Contents"]:
        key = obj["Key"]
        if not key.endswith(".json"):
            continue
        name = key[len(S3_PREFIX):-5]  # Remove prefix and .json

        # Get metadata without downloading full file
        try:
            head = s3.head_object(Bucket=BUCKET_NAME, Key=key)
            bases.append({
                "name": name,
                "size_bytes": head["ContentLength"],
                "last_modified": obj["LastModified"].isoformat(),
            })
        except ClientError:
            continue

    return bases


def delete_knowledge_base(name: str) -> bool:
    """Delete a knowledge base from S3."""
    s3 = _get_s3_client()
    key = f"{S3_PREFIX}{name}.json"

    try:
        s3.delete_object(Bucket=BUCKET_NAME, Key=key)
        return True
    except ClientError:
        return False
