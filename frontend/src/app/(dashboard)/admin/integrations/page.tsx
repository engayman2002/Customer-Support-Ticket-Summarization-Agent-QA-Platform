import React from "react";
import { redirect } from "next/navigation";
import { BackendAuthVerifier } from "@/components/BackendAuthVerifier";
import { auth, signOut } from "@/lib/auth";
import { fetchFastApiCurrentUser } from "@/lib/fastapi";
import { prisma } from "@/lib/prisma";

export default async function AdminIntegrationsShellPage() {
  const session = await auth();
  if (!session?.user) {
    redirect("/login");
  }
  if (session.user.role === "AGENT") {
    redirect("/agent");
  }
  if (session.user.role === "MANAGER") {
    redirect("/manager");
  }

  const [integrations, serverMeResponse] = await Promise.all([
    prisma.integration.findMany({
      orderBy: {
        createdAt: "desc",
      },
    }),
    fetchFastApiCurrentUser(session.accessToken),
  ]);

  async function handleSignOut() {
    "use server";
    await signOut({ redirectTo: "/login" });
  }

  return (
    <div className="space-y-8">
      <div className="flex flex-wrap items-center justify-between gap-4 border-b border-slate-800 pb-6">
        <div>
          <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-mono font-semibold bg-purple-500/10 text-purple-300 border border-purple-500/30">
            RBAC Guard: ADMIN ONLY
          </span>
          <h1 className="mt-2 text-2xl font-bold text-white">
            Admin CRM Integrations &amp; Security Health
          </h1>
          <p className="text-sm text-slate-400">
            Authenticated as{" "}
            <span className="text-slate-200 font-medium">
              {session.user.fullName}
            </span>{" "}
            ({session.user.email}) • Role:{" "}
            <code className="text-purple-300 font-mono">
              {session.user.role}
            </code>
          </p>
        </div>

        <form action={handleSignOut}>
          <button
            type="submit"
            className="rounded-lg bg-slate-800 hover:bg-slate-700 border border-slate-700 px-4 py-2 text-xs font-semibold text-white transition"
          >
            Sign Out
          </button>
        </form>
      </div>

      {/* Configured CRM Connectors */}
      <section className="rounded-xl bg-slate-900 border border-slate-800 p-6">
        <h2 className="text-base font-semibold text-white mb-4">
          Provisioned External Support CRM Connectors
        </h2>
        <div className="space-y-3">
          {integrations.map((item) => (
            <div
              key={item.id}
              className="rounded-lg bg-slate-950 border border-slate-800 p-4 flex flex-wrap items-center justify-between gap-4"
            >
              <div>
                <div className="flex items-center gap-2.5">
                  <span className="text-sm font-semibold text-white">
                    {item.name}
                  </span>
                  <span className="px-2 py-0.5 rounded text-xs font-mono bg-indigo-500/15 text-indigo-300 border border-indigo-500/30">
                    {item.crmType}
                  </span>
                  <span
                    className={`px-2 py-0.5 rounded text-xs font-mono ${
                      item.isActive
                        ? "bg-emerald-500/15 text-emerald-300 border border-emerald-500/30"
                        : "bg-slate-700 text-slate-300"
                    }`}
                  >
                    {item.isActive ? "ACTIVE" : "DISABLED"}
                  </span>
                </div>
                <div className="mt-1 text-xs font-mono text-slate-400">
                  Endpoint: {item.subdomainOrBaseUrl} • ID: {item.id}
                </div>
              </div>

              <div className="text-right text-xs text-slate-400">
                <div>Last Sync:</div>
                <div className="font-mono text-slate-300">
                  {item.lastSuccessfulSyncAt
                    ? item.lastSuccessfulSyncAt.toISOString()
                    : "Never"}
                </div>
              </div>
            </div>
          ))}
        </div>
      </section>

      {/* Cross-Service FastAPI Token Verifier */}
      <BackendAuthVerifier
        accessToken={session.accessToken}
        initialServerMeResponse={serverMeResponse}
      />
    </div>
  );
}

