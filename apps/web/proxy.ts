import { NextResponse, type NextRequest } from "next/server"
import { auth } from "@/lib/auth"

export async function proxy(request: NextRequest) {
	const pathname = request.nextUrl.pathname
	if (pathname === "/login" || pathname.startsWith("/api/auth/") || pathname === "/api/tenant/select") {
		return NextResponse.next()
	}
	const session = await auth.api.getSession({ headers: request.headers })
	if (!session || !session.session.activeTenantId) {
		if (pathname.startsWith("/api/")) return Response.json({ error: "Authentication required." }, { status: 401 })
		const login = new URL("/login", request.url)
		login.searchParams.set("next", pathname)
		return NextResponse.redirect(login)
	}
	return NextResponse.next()
}

export const config = {
	matcher: ["/((?!_next/static|_next/image|favicon.ico|sitemap.xml|robots.txt).*)"],
}
