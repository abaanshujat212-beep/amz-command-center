import type { Config } from "tailwindcss"

export default {
	content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
	theme: {
		extend: {
			colors: {
				// Performance tones map to break-even, not to a vanity target.
				good: "#15803d",
				warn: "#b45309",
				bad: "#b91c1c",
			},
		},
	},
	plugins: [],
} satisfies Config
