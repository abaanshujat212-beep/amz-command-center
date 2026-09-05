import { betterAuth } from "better-auth"
import { Pool } from "pg"

const databaseUrl = process.env.DATABASE_URL_APP
if (!databaseUrl) {
	throw new Error("DATABASE_URL_APP is required for authentication")
}

export const authPool = new Pool({
		connectionString: databaseUrl,
		options: "-c search_path=auth",
})

export const auth = betterAuth({
	database: authPool,
	secret: process.env.BETTER_AUTH_SECRET,
	baseURL: process.env.BETTER_AUTH_URL,
	emailAndPassword: {
		enabled: true,
		disableSignUp: true,
	},
	advanced: {
		database: {
			generateId: "uuid",
		},
	},
	user: {
		modelName: "auth_user",
		fields: {
			emailVerified: "email_verified",
			createdAt: "created_at",
			updatedAt: "updated_at",
		},
	},
	session: {
		modelName: "auth_session",
		fields: {
			userId: "user_id",
			expiresAt: "expires_at",
			ipAddress: "ip_address",
			userAgent: "user_agent",
			createdAt: "created_at",
			updatedAt: "updated_at",
		},
		additionalFields: {
			activeTenantId: {
				type: "string",
				required: false,
				input: false,
				fieldName: "active_tenant_id",
			},
		},
	},
	account: {
		modelName: "auth_account",
		identityStrategy: "provider-id",
		fields: {
			userId: "user_id",
			accountId: "account_id",
			providerId: "provider_id",
			accessToken: "access_token",
			refreshToken: "refresh_token",
			accessTokenExpiresAt: "access_token_expires_at",
			refreshTokenExpiresAt: "refresh_token_expires_at",
			idToken: "id_token",
			createdAt: "created_at",
			updatedAt: "updated_at",
		},
	},
	verification: {
		modelName: "auth_verification",
		fields: {
			expiresAt: "expires_at",
			createdAt: "created_at",
			updatedAt: "updated_at",
		},
	},
})
