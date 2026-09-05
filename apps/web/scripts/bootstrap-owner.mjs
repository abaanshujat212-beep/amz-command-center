import { randomUUID } from "node:crypto"
import { hashPassword } from "better-auth/crypto"
import pg from "pg"

function arg(name) { const i = process.argv.indexOf(`--${name}`); return i >= 0 ? process.argv[i + 1] : undefined }
const tenantId = arg("tenant-id"), name = arg("name"), email = arg("email")?.toLowerCase(), password = arg("password")
if (!tenantId || !name || !email || !password || password.length < 12) {
	console.error("Usage: npm run auth:bootstrap -- --tenant-id <uuid> --name <name> --email <email> --password <12+ chars>")
	process.exit(2)
}
if (!process.env.DATABASE_URL_APP) throw new Error("DATABASE_URL_APP is required")
const pool = new pg.Pool({ connectionString: process.env.DATABASE_URL_APP })
const client = await pool.connect()
try {
	await client.query("begin")
	await client.query("select set_tenant($1)", [tenantId])
	const owner = await client.query("select user_id from tenant_member where tenant_id=$1 and role='owner'", [tenantId])
	if (owner.rowCount) throw new Error("This tenant already has an owner; use the Team page to manage members.")
	const existing = await client.query("select id from auth.auth_user where lower(email)=$1", [email])
	const userId = existing.rows[0]?.id ?? randomUUID()
	if (!existing.rowCount) {
		await client.query("insert into auth.auth_user(id,name,email,email_verified) values($1,$2,$3,true)", [userId,name,email])
		await client.query("insert into auth.auth_account(id,issuer,account_id,provider_id,user_id,password,updated_at) values($1,'local:credential',$2,'credential',$3,$4,now())", [randomUUID(),userId,userId,await hashPassword(password)])
	}
	await client.query("insert into tenant_member(tenant_id,user_id,role) values($1,$2,'owner')", [tenantId,userId])
	await client.query("commit")
	console.log(`Owner ready: ${email} for tenant ${tenantId}`)
} catch (error) {
	await client.query("rollback"); throw error
} finally {
	client.release(); await pool.end()
}
