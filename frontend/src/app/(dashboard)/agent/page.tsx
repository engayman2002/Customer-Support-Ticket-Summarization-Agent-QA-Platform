import React from "react";
import { redirect } from "next/navigation";
import { BackendAuthVerifier } from "@/components/BackendAuthVerifier";
import { auth, signOut } from "@/lib/auth";
import { fetchFastApiCurrentUser } from "@/lib/fastapi";
import { prisma } from "@/lib/prisma";

export default async function AgentWorkspaceShellPage() {
  const session = await auth();
  if (!session?.user) {
    redirect("/login");
  }

  // Strict RBAC tenant & agent isolation: only query records assigned to `session.user.id`
  const [myTickets, myUnreadFeedback, serverMeResponse] = await Promise.all([
    prisma.ticket.findMany({
      where: {
        assignedAgentId: session.user.id,
      },
      include: {
        aiQaReport: true,
      },
      orderBy: {
        ticketClosedAt: "desc",
      },
    }),
    prisma.managerFeedback.findMany({
      where: {
        agentId: session.user.id,
      },
      include: {
        manager: true,
        ticket: true,
      },
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
          <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-mono font-semibold bg-indigo-500/10 text-indigo-300 border border-indigo-500/30">
            RBAC Isolated Workspace • Role: {session.user.role}
          </span>
          <h1 className="mt-2 text-2xl font-bold text-white">
            Agent Personal QA &amp; Coaching Workspace
          </h1>
          <p className="text-sm text-slate-400">
            Signed in as{" "}
            <span className="text-slate-200 font-medium">
              {session.user.fullName}
            </span>{" "}
            ({session.user.email}) • CRM Agent ID:{" "}
            <code className="text-indigo-300 font-mono">
              {session.user.externalCrmAgentId ?? "N/A"}
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

      {/* Agent Session Claims & RBAC Isolation Summary */}
      <section className="grid grid-cols-1 md:grid-cols-4 gap-4">
        <div className="rounded-xl bg-slate-900 border border-slate-800 p-5">
          <div className="text-xs font-semibold uppercase tracking-wider text-slate-400">
            Agent UUID (`sub`)
          </div>
          <div className="mt-2 text-xs font-mono text-slate-200 break-all">
            {session.user.id}
          </div>
        </div>

        <div className="rounded-xl bg-slate-900 border border-slate-800 p-5">
          <div className="text-xs font-semibold uppercase tracking-wider text-slate-400">
            External CRM Agent ID
          </div>
          <div className="mt-2 text-lg font-mono font-bold text-indigo-300">
            {session.user.externalCrmAgentId ?? "None"}
          </div>
        </div>

        <div className="rounded-xl bg-slate-900 border border-slate-800 p-5">
          <div className="text-xs font-semibold uppercase tracking-wider text-slate-400">
            My Evaluated Tickets
          </div>
          <div className="mt-2 text-2xl font-bold text-white">
            {myTickets.length}
          </div>
        </div>

        <div className="rounded-xl bg-slate-900 border border-slate-800 p-5">
          <div className="text-xs font-semibold uppercase tracking-wider text-slate-400">
            Manager Coaching Inbox
          </div>
          <div className="mt-2 text-2xl font-bold text-amber-300">
            {myUnreadFeedback.length}
          </div>
        </div>
      </section>

      {/* Assigned Manager Feedback Inbox */}
      <section className="rounded-xl bg-slate-900 border border-slate-800 p-6">
        <h2 className="text-base font-semibold text-white mb-4">
          My Manager Coaching &amp; Action Items (Isolated to `agent_id == session.user.id`)
        </h2>
        {myUnreadFeedback.length === 0 ? (
          <p className="text-sm text-slate-400">
            No manager coaching feedback assigned to your account.
          </p>
        ) : (
          <div className="space-y-4">
            {myUnreadFeedback.map((fb) => (
              <div
                key={fb.id}
                className="rounded-lg bg-slate-950 border border-slate-800 p-4 space-y-2"
              >
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="text-xs font-mono text-indigo-300">
                    Ticket: {fb.ticket.externalTicketId} — {fb.ticket.subject}
                  </span>
                  <div className="flex items-center gap-2">
                    <span className="px-2 py-0.5 rounded text-xs font-mono bg-rose-500/15 text-rose-300 border border-rose-500/30">
                      Priority: {fb.coachingPriority}
                    </span>
                    <span className="px-2 py-0.5 rounded text-xs font-mono bg-amber-500/15 text-amber-300 border border-amber-500/30">
                      Status: {fb.readStatus}
                    </span>
                  </div>
                </div>
                <p className="text-sm text-slate-200">{fb.comments}</p>
                <div className="text-xs text-slate-400">
                  Authored by Manager: {fb.manager.fullName} (Override Score:{" "}
                  {fb.managerOverrideScore ?? "None"})
                </div>
              </div>
            ))}
          </div>
        )}
      </section>

      {/* Cross-Service FastAPI Token Verifier */}
      <BackendAuthVerifier
        accessToken={session.accessToken}
        initialServerMeResponse={serverMeResponse}
      />
    </div>
  );
}

