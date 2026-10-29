import { type NextRequest, NextResponse } from "next/server";

import {
  type AppUserRole,
  type CrossServiceJwtPayload,
  verifyCrossServiceAccessToken,
} from "@/lib/jwt";

const SESSION_COOKIE_NAMES = [
  "authjs.session-token",
  "__Secure-authjs.session-token",
  "next-auth.session-token",
  "__Secure-next-auth.session-token",
] as const;

export function getHomeDashboardForRole(role: AppUserRole): string {
  if (role === "ADMIN" || role === "MANAGER") {
    return "/manager";
  }
  return "/agent";
}

/**
 * Extract and verify the HS256 JWT from either the `Authorization: Bearer <token>`
 * header or the Auth.js session cookie.
 */
export async function extractAuthenticatedUserFromRequest(
  request: NextRequest
): Promise<CrossServiceJwtPayload | null> {
  const authHeader = request.headers.get("authorization");
  if (authHeader && authHeader.toLowerCase().startsWith("bearer ")) {
    const bearerToken = authHeader.slice(7).trim();
    if (bearerToken) {
      const verified = await verifyCrossServiceAccessToken(bearerToken);
      if (verified) {
        return verified;
      }
    }
  }

  for (const cookieName of SESSION_COOKIE_NAMES) {
    const cookieVal = request.cookies.get(cookieName)?.value;
    if (cookieVal) {
      const verified = await verifyCrossServiceAccessToken(cookieVal);
      if (verified) {
        return verified;
      }
    }
  }

  return null;
}

export async function middleware(request: NextRequest): Promise<NextResponse> {
  const { pathname } = request.nextUrl;
  const user = await extractAuthenticatedUserFromRequest(request);

  const isLoginPage = pathname === "/login" || pathname.startsWith("/login/");
  const isManagerApi =
    pathname === "/api/v1/manager" ||
    pathname.startsWith("/api/v1/manager/") ||
    pathname === "/api/manager" ||
    pathname.startsWith("/api/manager/");
  const isManagerPage =
    pathname === "/manager" || pathname.startsWith("/manager/");
  const isAgentPage = pathname === "/agent" || pathname.startsWith("/agent/");
  const isAdminPage = pathname === "/admin" || pathname.startsWith("/admin/");

  // 1. Authenticated users visiting `/login` are redirected to their role's home dashboard
  if (isLoginPage) {
    if (user) {
      const redirectUrl = new URL(
        getHomeDashboardForRole(user.role),
        request.url
      );
      return NextResponse.redirect(redirectUrl);
    }
    return NextResponse.next();
  }

  // 2. API RBAC Guard (`/api/v1/manager/*` and `/api/manager/*`)
  if (isManagerApi) {
    if (!user) {
      return NextResponse.json(
        { detail: "Not authenticated" },
        { status: 401 }
      );
    }
    if (user.role === "AGENT") {
      return NextResponse.json(
        { detail: "Insufficient permissions" },
        { status: 403 }
      );
    }
    return NextResponse.next();
  }

  // 3. Unauthenticated users visiting any protected dashboard route -> redirect to `/login`
  if ((isManagerPage || isAgentPage || isAdminPage) && !user) {
    const loginUrl = new URL("/login", request.url);
    return NextResponse.redirect(loginUrl);
  }

  // 4. Admin Route Guard (`/admin/*`): strictly `ADMIN`
  if (isAdminPage && user) {
    if (user.role === "AGENT") {
      return NextResponse.redirect(new URL("/agent", request.url));
    }
    if (user.role === "MANAGER") {
      return NextResponse.redirect(new URL("/manager", request.url));
    }
    return NextResponse.next();
  }

  // 5. Manager Route Guard (`/manager/*`): strictly `MANAGER` or `ADMIN`
  if (isManagerPage && user) {
    if (user.role === "AGENT") {
      return NextResponse.redirect(new URL("/agent", request.url));
    }
    return NextResponse.next();
  }

  // 6. Agent Route Guard (`/agent/*`): accessible to authenticated users (primarily `AGENT`)
  if (isAgentPage && user) {
    return NextResponse.next();
  }

  return NextResponse.next();
}

export default middleware;

export const config = {
  matcher: [
    "/login",
    "/manager/:path*",
    "/agent/:path*",
    "/admin/:path*",
    "/api/v1/manager/:path*",
    "/api/manager/:path*",
  ],
};

