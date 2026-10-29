import React from "react";
import { redirect } from "next/navigation";
import { BackendAuthVerifier } from "@/components/BackendAuthVerifier";
import { auth, signOut } from "@/lib/auth";
import { fetchFastApiCurrentUser } from "@/lib/fastapi";
import { prisma } from "@/lib/prisma";

export default async function ManagerDashboardShellPage() {
  const session = await auth();
  if (!session?.user) {
    redirect("/login");
  }
  if (session.user.role === "AGENT") {
    redirect("/agent");
  }

  const [tickets, agentsCount, serverMeResponse] = await Promise.all([
    prisma.ticket.findMany({
      include: {
        assignedAgent: true,
        aiQaReport: true,
        managerFeedbacks: true,
      },
      orderBy: {
        ticketClosedAt: "desc",
      },
      take: 10,
    }),
    prisma.user.count({
      where: { role: "AGENT", isActive: true },
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
          <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-mono font-semibold bg-emerald-500/10 text-emerald-300 border border-emerald-500/30">
            RBAC Guard: MANAGER / ADMIN
          </span>
          <h1 className="mt-2 text-2xl font-bold text-white">
            Manager QA Overview &amp; Verification Shell
          </h1>
          <p className="text-sm text-slate-400">
            Authenticated as{" "}
            <span className="text-slate-200 font-medium">
              {session.user.fullName}
            </span>{" "}
            ({session.user.email}) with role{" "}
            <code className="text-indigo-300 font-mono">
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

      {/* Session Claims Summary */}
      <section className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <div className="rounded-xl bg-slate-900 border border-slate-800 p-5">
          <div className="text-xs font-semibold uppercase tracking-wider text-slate-400">
            Session User ID (`sub`)
          </div>
          <div className="mt-2 text-xs font-mono text-slate-100 break-all">
            {session.user.id}
          </div>
        </div>

        <div className="rounded-xl bg-slate-900 border border-slate-800 p-5">
          <div className="text-xs font-semibold uppercase tracking-wider text-slate-400">
            Active Support Agents
          </div>
          <div className="mt-2 text-2xl font-bold text-white">
            {agentsCount}
          </div>
        </div>

        <div className="rounded-xl bg-slate-900 border border-slate-800 p-5">
          <div className="text-xs font-semibold uppercase tracking-wider text-slate-400">
            Evaluated Tickets in DB
          </div>
          <div className="mt-2 text-2xl font-bold text-white">
            {tickets.length}
          </div>
        </div>
      </section>

      {/* Seeded Ticket & AI QA Report Preview */}
      <section className="rounded-xl bg-slate-900 border border-slate-800 p-6">
        <h2 className="text-base font-semibold text-white mb-4">
          Seeded Evaluated Tickets &amp; AI QA Reports
        </h2>
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b border-slate-800 text-xs uppercase text-slate-400">
                <th className="py-3 pr-4">External ID</th>
                <th className="py-3 pr-4">Subject</th>
                <th className="py-3 pr-4">Assigned Agent</th>
                <th className="py-3 pr-4">AI QA Score</th>
                <th className="py-3 pr-4">Resolution Status</th>
                <th className="py-3">Feedback Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/70">
              {tickets.map((t) => (
                <tr key={t.id}>
                  <td className="py-3 pr-4 font-mono text-xs text-indigo-300">
                    {t.externalTicketId}
                  </td>
                  <td className="py-3 pr-4 text-slate-200">{t.subject}</td>
                  <td className="py-3 pr-4 text-slate-300">
                    {t.assignedAgent.fullName}
                  </td>
                  <td className="py-3 pr-4 font-mono font-semibold text-rose-400">
                    {t.aiQaReport?.agentScore ?? "N/A"} / 100
                  </td>
                  <td className="py-3 pr-4">
                    <span className="px-2 py-0.5 rounded text-xs font-mono bg-rose-500/15 text-rose-300 border border-rose-500/30">
                      {t.aiQaReport?.resolutionStatus ?? t.processingStatus}
                    </span>
                  </td>
                  <td className="py-3 font-mono text-xs text-amber-300">
                    {t.managerFeedbacks[0]?.readStatus ?? "NONE"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
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

