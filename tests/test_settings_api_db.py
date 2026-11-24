import hashlib
import os
import re
import uuid
from pathlib import Path

import psycopg
import pytest
from psycopg.rows import dict_row

pytestmark = pytest.mark.db
URL = os.environ.get("DATABASE_URL", "postgresql://axaty:axaty@localhost:5432/axaty")
SOURCE = (Path(__file__).parents[1] / "apps/web/lib/settings-api.ts").read_text(encoding="utf-8")


def sql(name):
    value = re.search(rf"export const {name} = `(.*?)`", SOURCE, re.S).group(1)
    return re.sub(r"\$(\d+)", r"%(p\1)s", value)


def test_settings_key_requires_tenant_scope_current_manager_and_active_account():
    with psycopg.connect(URL, row_factory=dict_row) as db:
        tenant, actor, key = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        hashed = hashlib.sha256(str(key).encode()).hexdigest()
        db.execute("insert into tenant(id,name,slug) values(%s,'API test',%s)", (tenant,str(tenant)))
        db.execute("insert into tenant_member(tenant_id,user_id,role) values(%s,%s,'owner')", (tenant,actor))
        db.execute("insert into tenant_settings(tenant_id) values(%s)", (tenant,))
        db.execute("""insert into tenant_api_key(id,tenant_id,name,key_prefix,key_hash,scopes,created_by)
            values(%s,%s,'test','test',%s,array['settings:read'],%s)""", (key,tenant,hashed,actor))
        db.execute("set local role axaty_app")
        db.execute("select set_tenant(%s)", (tenant,))
        def auth(scope="settings:read", tenant_id=tenant, digest=hashed):
            return db.execute(sql("SETTINGS_KEY_SQL"), {"p1":tenant_id,"p2":digest,"p3":scope}).fetchall()
        assert len(auth()) == 1
        assert auth("settings:write") == []
        assert auth(digest="wrong") == []
        assert auth(tenant_id=uuid.uuid4()) == []
        assert db.execute(sql("COMPANY_SETTINGS_SQL"), {"p1":tenant}).fetchone()["name"] == "API test"
        db.execute("update tenant_member set role='viewer' where tenant_id=%s", (tenant,))
        assert auth() == []
        db.execute("update tenant_member set role='owner' where tenant_id=%s", (tenant,))
        db.execute("update tenant set status='suspended' where id=%s", (tenant,))
        assert auth() == []
        db.execute("update tenant set status='active' where id=%s", (tenant,))
        db.execute("update tenant_api_key set revoked_at=now() where id=%s", (key,))
        assert auth() == []
        db.rollback()
