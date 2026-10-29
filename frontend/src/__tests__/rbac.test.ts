import { decodeProtectedHeader } from "jose";
import { NextRequest } from "next/server";
import { describe, expect, it } from "vitest";

import {
  type CrossServiceJwtInput,
  mintCrossServiceAccessToken,
  verifyCrossServiceAccessToken,
} from "@/lib/jwt";
import { middleware } from "@/middleware";

const TEST_SECRET =
  process.env.AUTH_SECRET ||
  "super-secret-shared-hs256-signing-key-minimum-32-bytes-long-2026";

async function buildAuthenticatedRequest(
  path: string,
  user: CrossServiceJwtInput,
  viaCookie = true
): Promise<NextRequest> {
  const token = await mintCrossServiceAccessToken(user, TEST_SECRET);
  const url = new URL(path, "http://localhost:3000");

  if (viaCookie) {
    return new NextRequest(url, {
      headers: {
        cookie: `authjs.session-token=${token}`,
      },
    });
  }

  return new NextRequest(url, {
    headers: {
      authorization: `Bearer ${token}`,
    },
  });
}

describe("Phase 1B: Cross-Service HS256 JWT Contract & Edge RBAC Middleware", () => {
  describe("Cross-Service HS256 JWT Minting & Verification", () => {
    it("mints a standard 3-part HS256 JWS containing all required FastAPI claims", async () => {
      const input: CrossServiceJwtInput = {
        sub: "11111111-1111-4111-8111-111111111103",
        email: "sarah.agent@qa-platform.local",
        role: "AGENT",
        external_crm_agent_id: "zd_agent_101",
        manager_id: "11111111-1111-4111-8111-111111111102",
        full_name: "Sarah Jenkins",
      };

      const token = await mintCrossServiceAccessToken(input, TEST_SECRET);

      // 1. Must be a standard 3-part JWS (header.payload.signature), not a 5-part JWE
      const segments = token.split(".");
      expect(segments).toHaveLength(3);

      // 2. Protected header must specify alg=HS256
      const header = decodeProtectedHeader(token);
      expect(header.alg).toBe("HS256");
      expect(header.typ).toBe("JWT");

      // 3. Payload must verify with AUTH_SECRET and contain exact snake_case claims for FastAPI
      const verified = await verifyCrossServiceAccessToken(token, TEST_SECRET);
      expect(verified).not.toBeNull();
      expect(verified?.sub).toBe("11111111-1111-4111-8111-111111111103");
      expect(verified?.email).toBe("sarah.agent@qa-platform.local");
      expect(verified?.role).toBe("AGENT");
      expect(verified?.external_crm_agent_id).toBe("zd_agent_101");
      expect(verified?.manager_id).toBe(
        "11111111-1111-4111-8111-111111111102"
      );
      expect(verified?.exp).toBeGreaterThan(verified?.iat ?? 0);
    });

    it("rejects tokens signed with a different secret", async () => {
      const token = await mintCrossServiceAccessToken(
        {
          sub: "11111111-1111-4111-8111-111111111102",
          email: "manager@qa-platform.local",
          role: "MANAGER",
        },
        "wrong-secret-key-not-matching-auth-secret-12345"
      );

      const verified = await verifyCrossServiceAccessToken(token, TEST_SECRET);
      expect(verified).toBeNull();
    });
  });

  describe("Edge RBAC Middleware Route Protection", () => {
    it("redirects unauthenticated requests for /manager, /agent, and /admin to /login", async () => {
      for (const protectedPath of [
        "/manager",
        "/manager/tickets",
        "/agent",
        "/admin/integrations",
      ]) {
        const req = new NextRequest(
          new URL(protectedPath, "http://localhost:3000")
        );
        const res = await middleware(req);
        expect(res.status).toBe(307);
        expect(res.headers.get("location")).toBe(
          "http://localhost:3000/login"
        );
      }
    });

    it("redirects AGENT from /manager/* and /admin/* to /agent", async () => {
      const agentClaims: CrossServiceJwtInput = {
        sub: "11111111-1111-4111-8111-111111111103",
        email: "sarah.agent@qa-platform.local",
        role: "AGENT",
        external_crm_agent_id: "zd_agent_101",
        manager_id: "11111111-1111-4111-8111-111111111102",
      };

      const managerReq = await buildAuthenticatedRequest(
        "/manager/tickets",
        agentClaims
      );
      const managerRes = await middleware(managerReq);
      expect(managerRes.status).toBe(307);
      expect(managerRes.headers.get("location")).toBe(
        "http://localhost:3000/agent"
      );

      const adminReq = await buildAuthenticatedRequest(
        "/admin/integrations",
        agentClaims
      );
      const adminRes = await middleware(adminReq);
      expect(adminRes.status).toBe(307);
      expect(adminRes.headers.get("location")).toBe(
        "http://localhost:3000/agent"
      );

      // AGENT visiting /agent is allowed
      const agentReq = await buildAuthenticatedRequest("/agent", agentClaims);
      const agentRes = await middleware(agentReq);
      expect(agentRes.status).toBe(200);
    });

    it("returns 403 Forbidden JSON when AGENT calls /api/v1/manager/* or /api/manager/*", async () => {
      const agentClaims: CrossServiceJwtInput = {
        sub: "11111111-1111-4111-8111-111111111103",
        email: "sarah.agent@qa-platform.local",
        role: "AGENT",
        external_crm_agent_id: "zd_agent_101",
        manager_id: "11111111-1111-4111-8111-111111111102",
      };

      const apiV1Req = await buildAuthenticatedRequest(
        "/api/v1/manager/rbac-check",
        agentClaims,
        false
      );
      const apiV1Res = await middleware(apiV1Req);
      expect(apiV1Res.status).toBe(403);
      expect(await apiV1Res.json()).toEqual({
        detail: "Insufficient permissions",
      });

      const apiManagerReq = await buildAuthenticatedRequest(
        "/api/manager/analytics",
        agentClaims,
        true
      );
      const apiManagerRes = await middleware(apiManagerReq);
      expect(apiManagerRes.status).toBe(403);
      expect(await apiManagerRes.json()).toEqual({
        detail: "Insufficient permissions",
      });
    });

    it("allows MANAGER on /manager/* and /api/v1/manager/*, but redirects MANAGER from /admin/* to /manager", async () => {
      const managerClaims: CrossServiceJwtInput = {
        sub: "11111111-1111-4111-8111-111111111102",
        email: "manager@qa-platform.local",
        role: "MANAGER",
      };

      const managerPageReq = await buildAuthenticatedRequest(
        "/manager",
        managerClaims
      );
      const managerPageRes = await middleware(managerPageReq);
      expect(managerPageRes.status).toBe(200);

      const managerApiReq = await buildAuthenticatedRequest(
        "/api/v1/manager/rbac-check",
        managerClaims,
        false
      );
      const managerApiRes = await middleware(managerApiReq);
      expect(managerApiRes.status).toBe(200);

      const adminPageReq = await buildAuthenticatedRequest(
        "/admin/integrations",
        managerClaims
      );
      const adminPageRes = await middleware(adminPageReq);
      expect(adminPageRes.status).toBe(307);
      expect(adminPageRes.headers.get("location")).toBe(
        "http://localhost:3000/manager"
      );
    });

    it("allows ADMIN on both /admin/* and /manager/*", async () => {
      const adminClaims: CrossServiceJwtInput = {
        sub: "11111111-1111-4111-8111-111111111101",
        email: "admin@qa-platform.local",
        role: "ADMIN",
      };

      const adminPageReq = await buildAuthenticatedRequest(
        "/admin/integrations",
        adminClaims
      );
      const adminPageRes = await middleware(adminPageReq);
      expect(adminPageRes.status).toBe(200);

      const managerPageReq = await buildAuthenticatedRequest(
        "/manager",
        adminClaims
      );
      const managerPageRes = await middleware(managerPageReq);
      expect(managerPageRes.status).toBe(200);
    });

    it("redirects authenticated users away from /login to their role home dashboard", async () => {
      const agentLoginReq = await buildAuthenticatedRequest("/login", {
        sub: "11111111-1111-4111-8111-111111111103",
        email: "sarah.agent@qa-platform.local",
        role: "AGENT",
      });
      const agentLoginRes = await middleware(agentLoginReq);
      expect(agentLoginRes.status).toBe(307);
      expect(agentLoginRes.headers.get("location")).toBe(
        "http://localhost:3000/agent"
      );

      const managerLoginReq = await buildAuthenticatedRequest("/login", {
        sub: "11111111-1111-4111-8111-111111111102",
        email: "manager@qa-platform.local",
        role: "MANAGER",
      });
      const managerLoginRes = await middleware(managerLoginReq);
      expect(managerLoginRes.status).toBe(307);
      expect(managerLoginRes.headers.get("location")).toBe(
        "http://localhost:3000/manager"
      );

      const adminLoginReq = await buildAuthenticatedRequest("/login", {
        sub: "11111111-1111-4111-8111-111111111101",
        email: "admin@qa-platform.local",
        role: "ADMIN",
      });
      const adminLoginRes = await middleware(adminLoginReq);
      expect(adminLoginRes.status).toBe(307);
      expect(adminLoginRes.headers.get("location")).toBe(
        "http://localhost:3000/manager"
      );
    });
  });
});

