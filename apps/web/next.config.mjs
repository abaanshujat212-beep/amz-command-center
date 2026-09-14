import path from "node:path"
import { fileURLToPath } from "node:url"

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..")

/** @type {import('next').NextConfig} */
const nextConfig = {
	reactStrictMode: true,
	// The canonical capability contract is shared with Python from packages/shared.
	// Make that repository-root boundary explicit for Turbopack and output tracing.
	turbopack: { root: repoRoot },
	outputFileTracingRoot: repoRoot,
	// pg is a native-ish driver; keep it on the server side of the bundler.
	serverExternalPackages: ["pg"],
	experimental: {
		// Server Actions are how approvals are submitted. Nothing in this app
		// mutates through a client-side fetch.
		serverActions: { bodySizeLimit: "1mb" },
	},
}

export default nextConfig
