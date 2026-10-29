import bcrypt from "bcryptjs";
import { SignJWT, jwtVerify } from "jose";
import NextAuth, { type NextAuthConfig } from "next-auth";
import Credentials from "next-auth/providers/credentials";

import {
  type AppUserRole,
  type CrossServiceJwtInput,
  type CrossServiceJwtPayload,
  getAuthSecretKey,
  mintCrossServiceAccessToken,
  verifyCrossServiceAccessToken,
} from "@/lib/jwt";
import { prisma } from "@/lib/prisma";

export {
  type AppUserRole,
  type CrossServiceJwtInput,
  type CrossServiceJwtPayload,
  getAuthSecretKey,
  mintCrossServiceAccessToken,
  verifyCrossServiceAccessToken,
};

export interface AuthenticatedDbUser {
  id: string;
  email: string;
  name: string;
  fullName: string;
  role: AppUserRole;
  externalCrmAgentId: string | null;
  managerId: string | null;
}

/**
 * Validate user credentials against PostgreSQL (`users` table) using `bcryptjs.compare`
 * and enforce `user.isActive === true`.
 */
export async function authenticateCredentials(
  email?: string,
  password?: string
): Promise<AuthenticatedDbUser | null> {
  if (!email || !password) {
    return null;
  }

  const normalizedEmail = email.trim().toLowerCase();
  const user = await prisma.user.findUnique({
    where: { email: normalizedEmail },
  });

  if (!user || !user.isActive) {
    return null;
  }

  const isValidPassword = await bcrypt.compare(password, user.passwordHash);
  if (!isValidPassword) {
    return null;
  }

  return {
    id: user.id,
    email: user.email,
    name: user.fullName,
    fullName: user.fullName,
    role: user.role as AppUserRole,
    externalCrmAgentId: user.externalCrmAgentId ?? null,
    managerId: user.managerId ?? null,
  };
}

export const authConfig: NextAuthConfig = {
  secret:
    process.env.AUTH_SECRET ||
    process.env.NEXTAUTH_SECRET ||
    "super-secret-shared-hs256-signing-key-minimum-32-bytes-long-2026",
  trustHost: true,
  session: {
    strategy: "jwt",
    maxAge: 60 * 60 * 24, // 24 hours
  },
  pages: {
    signIn: "/login",
  },
  jwt: {
    maxAge: 60 * 60 * 24,
    async encode({ token, secret, maxAge }) {
      if (!token) {
        return "";
      }
      const secretStr = Array.isArray(secret) ? secret[0] : String(secret);
      const secretKey = getAuthSecretKey(secretStr);
      const nowSeconds = Math.floor(Date.now() / 1000);
      const ttlSeconds = maxAge ?? 60 * 60 * 24;
      const sub = String(token.sub || token.id || "");

      return new SignJWT({
        ...token,
        sub,
        external_crm_agent_id:
          (token.externalCrmAgentId as string | null | undefined) ??
          (token.external_crm_agent_id as string | null | undefined) ??
          null,
        manager_id:
          (token.managerId as string | null | undefined) ??
          (token.manager_id as string | null | undefined) ??
          null,
      })
        .setProtectedHeader({ alg: "HS256", typ: "JWT" })
        .setSubject(sub)
        .setIssuedAt(nowSeconds)
        .setExpirationTime(nowSeconds + ttlSeconds)
        .sign(secretKey);
    },
    async decode({ token, secret }) {
      if (!token) {
        return null;
      }
      try {
        const secretStr = Array.isArray(secret) ? secret[0] : String(secret);
        const secretKey = getAuthSecretKey(secretStr);
        const { payload } = await jwtVerify(token, secretKey, {
          algorithms: ["HS256"],
        });
        return payload;
      } catch {
        return null;
      }
    },
  },
  providers: [
    Credentials({
      name: "Credentials",
      credentials: {
        email: { label: "Email", type: "email" },
        password: { label: "Password", type: "password" },
      },
      async authorize(credentials) {
        const email =
          typeof credentials?.email === "string"
            ? credentials.email
            : undefined;
        const password =
          typeof credentials?.password === "string"
            ? credentials.password
            : undefined;

        return authenticateCredentials(email, password);
      },
    }),
  ],
  callbacks: {
    async jwt({ token, user }) {
      if (user) {
        token.id = user.id;
        token.sub = user.id;
        token.email = user.email;
        token.fullName = user.fullName;
        token.role = user.role;
        token.externalCrmAgentId = user.externalCrmAgentId;
        token.managerId = user.managerId;
        token.external_crm_agent_id = user.externalCrmAgentId;
        token.manager_id = user.managerId;
      }

      const sub = String(token.sub || token.id || "");
      const email = String(token.email || "");
      const role = (token.role as AppUserRole | undefined) ?? "AGENT";
      const externalCrmAgentId =
        (token.externalCrmAgentId as string | null | undefined) ??
        (token.external_crm_agent_id as string | null | undefined) ??
        null;
      const managerId =
        (token.managerId as string | null | undefined) ??
        (token.manager_id as string | null | undefined) ??
        null;
      const fullName =
        (token.fullName as string | null | undefined) ??
        (token.name as string | null | undefined) ??
        null;

      if (sub && email) {
        token.accessToken = await mintCrossServiceAccessToken({
          sub,
          email,
          role,
          external_crm_agent_id: externalCrmAgentId,
          manager_id: managerId,
          full_name: fullName,
        });
      }

      return token;
    },
    async session({ session, token }) {
      const userId = String(token.id || token.sub || "");
      const userRole = (token.role as AppUserRole | undefined) ?? "AGENT";
      const externalCrmAgentId =
        (token.externalCrmAgentId as string | null | undefined) ??
        (token.external_crm_agent_id as string | null | undefined) ??
        null;
      const managerId =
        (token.managerId as string | null | undefined) ??
        (token.manager_id as string | null | undefined) ??
        null;
      const fullName =
        (token.fullName as string | undefined) ??
        (token.name as string | undefined) ??
        "";

      session.user = {
        ...session.user,
        id: userId,
        email: String(token.email || session.user?.email || ""),
        name: fullName,
        fullName,
        role: userRole,
        externalCrmAgentId,
        managerId,
      };
      session.accessToken = String(token.accessToken || "");
      return session;
    },
  },
};

export const { handlers, auth, signIn, signOut } = NextAuth(authConfig);

