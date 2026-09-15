"""Private filesystem adapter for report artifacts on a shared persistent volume."""

from __future__ import annotations

import os
import tempfile
import uuid
from pathlib import Path

_EXTENSIONS = {
    "text/csv; charset=utf-8": "csv",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx",
    "application/pdf": "pdf",
}


class LocalPrivateArtifactStore:
    """Persist content-addressed artifacts without producing a public URL."""

    def __init__(self, root: str | Path):
        self.root = Path(root).expanduser().resolve()

    def put_private(
        self,
        *,
        tenant_id: str,
        job_id: str,
        content_sha256: str,
        media_type: str,
        data: bytes,
    ) -> str:
        tenant = str(uuid.UUID(tenant_id))
        job = str(uuid.UUID(job_id))
        if len(content_sha256) != 64 or any(c not in "0123456789abcdef" for c in content_sha256):
            raise ValueError("content_sha256 must be lowercase hexadecimal")
        extension = _EXTENSIONS.get(media_type)
        if extension is None:
            raise ValueError("unsupported private artifact media type")
        key = f"tenants/{tenant}/reports/{job}/{content_sha256}.{extension}"
        target = (self.root / key).resolve()
        if self.root not in target.parents:
            raise ValueError("artifact key escapes the private storage root")
        target.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as pending:
            pending.write(data)
            pending.flush()
            os.fsync(pending.fileno())
            temporary = Path(pending.name)
        temporary.chmod(0o600)
        os.replace(temporary, target)
        return key
