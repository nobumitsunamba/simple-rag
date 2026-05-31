"""Knowledge base persistence using S3."""

import json
import os
from datetime import datetime

import boto3
from botocore.exceptions import ClientError


BUCKET_NAME = os.getenv("KNOWLEDGE_BUCKET", "simple-rag-knowledge-032401368831")
S3_PREFIX = "knowledge-bases/"
FILES_PREFIX = "uploaded-files/"


def _get_s3_client():
    region = os.getenv("AWS_REGION", "ap-northeast-1")
    return boto3.client("s3", region_name=region)


# --- File Storage ---

def save_uploaded_file(filename: str, content: bytes) -> str:
    """Save an uploaded file to S3. Returns the S3 key."""
    s3 = _get_s3_client()
    key = f"{FILES_PREFIX}{filename}"
    s3.put_object(
        Bucket=BUCKET_NAME,
        Key=key,
        Body=content,
        ContentType=_get_content_type(filename),
    )
    return key


def get_file_download_url(filename: str) -> str | None:
    """Generate a presigned URL for downloading a file."""
    s3 = _get_s3_client()
    key = f"{FILES_PREFIX}{filename}"
    try:
        s3.head_object(Bucket=BUCKET_NAME, Key=key)
        url = s3.generate_presigned_url(
            "get_object",
            Params={"Bucket": BUCKET_NAME, "Key": key},
            ExpiresIn=3600,
        )
        return url
    except ClientError:
        return None


def _get_content_type(filename: str) -> str:
    ext = os.path.splitext(filename)[1].lower()
    types = {
        ".pdf": "application/pdf",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        ".csv": "text/csv",
        ".txt": "text/plain",
        ".md": "text/markdown",
    }
    return types.get(ext, "application/octet-stream")


# --- Knowledge Base ---

def save_knowledge_base(name: str, chunks: list[str], metadata: list[dict], embeddings: list[list[float]], group: str = "") -> dict:
    """Save a knowledge base to S3."""
    s3 = _get_s3_client()

    data = {
        "name": name,
        "group": group,
        "created_at": datetime.utcnow().isoformat(),
        "chunks": chunks,
        "metadata": metadata,
        "embeddings": embeddings,
    }

    prefix = f"{S3_PREFIX}{group}/" if group else S3_PREFIX
    key = f"{prefix}{name}.json"
    s3.put_object(
        Bucket=BUCKET_NAME,
        Key=key,
        Body=json.dumps(data, ensure_ascii=False),
        ContentType="application/json",
    )

    return {
        "name": name,
        "group": group,
        "total_chunks": len(chunks),
        "total_documents": len(set(m["source"] for m in metadata)),
        "created_at": data["created_at"],
    }


def load_knowledge_base(name: str, group: str = "") -> dict | None:
    """Load a knowledge base from S3."""
    s3 = _get_s3_client()
    prefix = f"{S3_PREFIX}{group}/" if group else S3_PREFIX
    key = f"{prefix}{name}.json"

    try:
        response = s3.get_object(Bucket=BUCKET_NAME, Key=key)
        data = json.loads(response["Body"].read().decode("utf-8"))
        return data
    except ClientError as e:
        if e.response["Error"]["Code"] == "NoSuchKey":
            return None
        raise


def list_knowledge_bases() -> list[dict]:
    """List all saved knowledge bases with group info."""
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

        # Parse group and name from key
        relative = key[len(S3_PREFIX):]  # e.g. "group/name.json" or "name.json"
        parts = relative.rsplit("/", 1)
        if len(parts) == 2:
            group = parts[0]
            name = parts[1][:-5]
        else:
            group = ""
            name = parts[0][:-5]

        bases.append({
            "name": name,
            "group": group,
            "size_bytes": obj.get("Size", 0),
            "last_modified": obj["LastModified"].isoformat(),
        })

    return bases


def delete_knowledge_base(name: str, group: str = "") -> bool:
    """Delete a knowledge base from S3."""
    s3 = _get_s3_client()
    prefix = f"{S3_PREFIX}{group}/" if group else S3_PREFIX
    key = f"{prefix}{name}.json"

    try:
        s3.delete_object(Bucket=BUCKET_NAME, Key=key)
        return True
    except ClientError:
        return False


def rename_knowledge_base(old_name: str, new_name: str, old_group: str = "", new_group: str = "") -> bool:
    """Rename or move a knowledge base."""
    s3 = _get_s3_client()
    old_prefix = f"{S3_PREFIX}{old_group}/" if old_group else S3_PREFIX
    new_prefix = f"{S3_PREFIX}{new_group}/" if new_group else S3_PREFIX
    old_key = f"{old_prefix}{old_name}.json"
    new_key = f"{new_prefix}{new_name}.json"

    try:
        # Copy to new location
        s3.copy_object(
            Bucket=BUCKET_NAME,
            CopySource={"Bucket": BUCKET_NAME, "Key": old_key},
            Key=new_key,
        )
        # Update name inside JSON
        response = s3.get_object(Bucket=BUCKET_NAME, Key=new_key)
        data = json.loads(response["Body"].read().decode("utf-8"))
        data["name"] = new_name
        data["group"] = new_group
        s3.put_object(Bucket=BUCKET_NAME, Key=new_key, Body=json.dumps(data, ensure_ascii=False), ContentType="application/json")
        # Delete old
        s3.delete_object(Bucket=BUCKET_NAME, Key=old_key)
        return True
    except ClientError:
        return False


def list_groups() -> list[str]:
    """List all knowledge base groups."""
    s3 = _get_s3_client()
    try:
        response = s3.list_objects_v2(Bucket=BUCKET_NAME, Prefix=S3_PREFIX, Delimiter="/")
        groups = []
        for prefix in response.get("CommonPrefixes", []):
            group = prefix["Prefix"][len(S3_PREFIX):].rstrip("/")
            if group:
                groups.append(group)
        return groups
    except ClientError:
        return []


def create_group(group_name: str) -> bool:
    """Create a group folder in S3."""
    s3 = _get_s3_client()
    key = f"{S3_PREFIX}{group_name}/"
    try:
        s3.put_object(Bucket=BUCKET_NAME, Key=key, Body=b"")
        return True
    except ClientError:
        return False


def rename_group(old_name: str, new_name: str) -> bool:
    """Rename a group by moving all its knowledge bases."""
    s3 = _get_s3_client()
    old_prefix = f"{S3_PREFIX}{old_name}/"
    new_prefix = f"{S3_PREFIX}{new_name}/"

    try:
        response = s3.list_objects_v2(Bucket=BUCKET_NAME, Prefix=old_prefix)
        if "Contents" not in response:
            return False

        for obj in response["Contents"]:
            old_key = obj["Key"]
            new_key = new_prefix + old_key[len(old_prefix):]
            s3.copy_object(Bucket=BUCKET_NAME, CopySource={"Bucket": BUCKET_NAME, "Key": old_key}, Key=new_key)
            s3.delete_object(Bucket=BUCKET_NAME, Key=old_key)

        return True
    except ClientError:
        return False


def delete_group(group_name: str) -> bool:
    """Delete a group and all its knowledge bases."""
    s3 = _get_s3_client()
    prefix = f"{S3_PREFIX}{group_name}/"

    try:
        response = s3.list_objects_v2(Bucket=BUCKET_NAME, Prefix=prefix)
        if "Contents" in response:
            for obj in response["Contents"]:
                s3.delete_object(Bucket=BUCKET_NAME, Key=obj["Key"])
        return True
    except ClientError:
        return False
