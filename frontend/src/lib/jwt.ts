import { SignJWT, jwtVerify } from "jose";

export type AppUserRole = "ADMIN" | "MANAGER" | "AGENT";

export interface CrossServiceJwtInput {
  sub: string;
  email: string;
  role: AppUserRole;
  external_crm_agent_id?: string | null;
  manager_id?: string | null;
  full_name?: string | null;
  expiresInSeconds?: number;
}

export interface CrossServiceJwtPayload {
  sub: string;
  email: string;
  role: AppUserRole;
  external_crm_agent_id: string | null;
  manager_id: string | null;
  full_name?: string | null;
  iat: number;
  exp: number;
}

const DEFAULT_FALLBACK_SECRET =
  "super-secret-shared-hs256-signing-key-minimum-32-bytes-long-2026";

export function getAuthSecretKey(explicitSecret?: string): Uint8Array {
  const rawSecret =
    explicitSecret ||
    process.env.AUTH_SECRET ||
    process.env.NEXTAUTH_SECRET ||
    DEFAULT_FALLBACK_SECRET;
  return new TextEncoder().encode(rawSecret);
}

/**
 * Mint a standard 3-part HS256 JWS token signed with `AUTH_SECRET`
 * that conforms 1:1 to FastAPI's `decode_access_token` contract.
 */
export async function mintCrossServiceAccessToken(
  input: CrossServiceJwtInput,
  explicitSecret?: string
): Promise<string> {
  const nowSeconds = Math.floor(Date.now() / 1000);
  const ttlSeconds = input.expiresInSeconds ?? 60 * 60 * 24; // 24 hours default
  const secretKey = getAuthSecretKey(explicitSecret);

  return new SignJWT({
    sub: input.sub,
    email: input.email,
    role: input.role,
    external_crm_agent_id: input.external_crm_agent_id ?? null,
    manager_id: input.manager_id ?? null,
    full_name: input.full_name ?? null,
  })
    .setProtectedHeader({ alg: "HS256", typ: "JWT" })
    .setSubject(input.sub)
    .setIssuedAt(nowSeconds)
    .setExpirationTime(nowSeconds + ttlSeconds)
    .sign(secretKey);
}

/**
 * Verify and decode an HS256 JWS token signed with `AUTH_SECRET`.
 * Edge-runtime compatible (uses Web Crypto via `jose`).
 */
export async function verifyCrossServiceAccessToken(
  token: string,
  explicitSecret?: string
): Promise<CrossServiceJwtPayload | null> {
  try {
    const secretKey = getAuthSecretKey(explicitSecret);
    const { payload } = await jwtVerify(token, secretKey, {
      algorithms: ["HS256"],
    });

    const sub = typeof payload.sub === "string" ? payload.sub : null;
    const email = typeof payload.email === "string" ? payload.email : null;
    const role = payload.role as AppUserRole | undefined;

    if (
      !sub ||
      !email ||
      !role ||
      !["ADMIN", "MANAGER", "AGENT"].includes(role)
    ) {
      return null;
    }

    return {
      sub,
      email,
      role,
      external_crm_agent_id:
        typeof payload.external_crm_agent_id === "string"
          ? payload.external_crm_agent_id
          : null,
      manager_id:
        typeof payload.manager_id === "string" ? payload.manager_id : null,
      full_name:
        typeof payload.full_name === "string" ? payload.full_name : null,
      iat: typeof payload.iat === "number" ? payload.iat : 0,
      exp: typeof payload.exp === "number" ? payload.exp : 0,
    };
  } catch {
    return null;
  }
}

