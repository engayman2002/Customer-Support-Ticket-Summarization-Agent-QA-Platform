import type { DefaultSession } from "next-auth";
import type { AppUserRole } from "@/lib/jwt";

declare module "next-auth" {
  interface User {
    id: string;
    email: string;
    fullName: string;
    role: AppUserRole;
    externalCrmAgentId: string | null;
    managerId: string | null;
  }

  interface Session {
    user: {
      id: string;
      email: string;
      fullName: string;
      role: AppUserRole;
      externalCrmAgentId: string | null;
      managerId: string | null;
    } & DefaultSession["user"];
    accessToken: string;
  }
}

