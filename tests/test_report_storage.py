import hashlib
import uuid
from pathlib import Path

import pytest

from services.reports.storage import LocalPrivateArtifactStore


def test_local_artifact_store_is_private_content_addressed_and_idempotent(tmp_path):
    tenant_id, job_id = str(uuid.uuid4()), str(uuid.uuid4())
    data = b"sku,sales\nA-1,12.5\n"
    digest = hashlib.sha256(data).hexdigest()
    store = LocalPrivateArtifactStore(tmp_path)
    first = store.put_private(tenant_id=tenant_id, job_id=job_id, content_sha256=digest, media_type="text/csv; charset=utf-8", data=data)
    second = store.put_private(tenant_id=tenant_id, job_id=job_id, content_sha256=digest, media_type="text/csv; charset=utf-8", data=data)
    assert first == second and "://" not in first
    path = Path(tmp_path, first)
    assert path.read_bytes() == data
    assert path.stat().st_mode & 0o777 == 0o600


def test_local_artifact_store_rejects_untrusted_identifiers(tmp_path):
    store = LocalPrivateArtifactStore(tmp_path)
    with pytest.raises(ValueError):
        store.put_private(tenant_id="../escape", job_id=str(uuid.uuid4()), content_sha256="0" * 64, media_type="application/pdf", data=b"pdf")
    with pytest.raises(ValueError, match="sha256"):
        store.put_private(tenant_id=str(uuid.uuid4()), job_id=str(uuid.uuid4()), content_sha256="bad", media_type="application/pdf", data=b"pdf")
