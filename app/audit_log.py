"""Audit logging module using CloudWatch Logs."""

import json
import os
import time
from datetime import datetime

import boto3
from botocore.exceptions import ClientError

LOG_GROUP = os.getenv("AUDIT_LOG_GROUP", "/simple-rag/audit")
AWS_REGION = os.getenv("AWS_REGION", "ap-northeast-1")

_client = None
_sequence_token = None


def _get_client():
    global _client
    if _client is None:
        _client = boto3.client("logs", region_name=AWS_REGION)
        _ensure_log_group()
    return _client


def _ensure_log_group():
    """Create log group and stream if they don't exist."""
    client = _client
    try:
        client.create_log_group(logGroupName=LOG_GROUP)
    except ClientError as e:
        if e.response["Error"]["Code"] != "ResourceAlreadyExistsException":
            pass  # Ignore other errors silently

    stream_name = _get_stream_name()
    try:
        client.create_log_stream(logGroupName=LOG_GROUP, logStreamName=stream_name)
    except ClientError:
        pass


def _get_stream_name() -> str:
    """Get log stream name based on date."""
    return datetime.utcnow().strftime("%Y/%m/%d")


def log_event(event_type: str, user_email: str = "", details: dict = None):
    """Log an audit event to CloudWatch Logs."""
    global _sequence_token
    try:
        client = _get_client()
        stream_name = _get_stream_name()

        # Ensure stream exists
        try:
            client.create_log_stream(logGroupName=LOG_GROUP, logStreamName=stream_name)
        except ClientError:
            pass

        event = {
            "timestamp": datetime.utcnow().isoformat(),
            "event_type": event_type,
            "user": user_email,
            "details": details or {},
        }

        kwargs = {
            "logGroupName": LOG_GROUP,
            "logStreamName": stream_name,
            "logEvents": [{
                "timestamp": int(time.time() * 1000),
                "message": json.dumps(event, ensure_ascii=False),
            }],
        }

        if _sequence_token:
            kwargs["sequenceToken"] = _sequence_token

        try:
            response = client.put_log_events(**kwargs)
            _sequence_token = response.get("nextSequenceToken")
        except ClientError as e:
            if e.response["Error"]["Code"] in ("InvalidSequenceTokenException", "DataAlreadyAcceptedException"):
                # Retry with correct token
                token = e.response["Error"].get("expectedSequenceToken")
                if token:
                    kwargs["sequenceToken"] = token
                    response = client.put_log_events(**kwargs)
                    _sequence_token = response.get("nextSequenceToken")
    except Exception:
        pass  # Never let logging break the app
