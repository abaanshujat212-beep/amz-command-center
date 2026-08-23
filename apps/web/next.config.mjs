/** @type {import('next').NextConfig} */
const nextConfig = {
	reactStrictMode: true,
	// pg is a native-ish driver; keep it on the server side of the bundler.
	serverExternalPackages: ["pg"],
	experimental: {
		// Server Actions are how approvals are submitted. Nothing in this app
		// mutates through a client-side fetch.
		serverActions: { bodySizeLimit: "1mb" },
	},
}

export default nextConfig
