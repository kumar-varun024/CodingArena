"""Common identities, canonical digests and verification defaults."""
import hashlib
from datetime import datetime, timezone
from uuid import uuid4
from .contract import canonical_bytes


def now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def digest(value):
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def uid(prefix):
    return prefix + "_" + uuid4().hex


def verification(status="queued", job_id=None):
    return {"status": status, "check_count": 0, "passed_count": 0, "failed_check_ids": [],
            "job_id": job_id, "log_artifact_id": None, "evidence_key": None}
