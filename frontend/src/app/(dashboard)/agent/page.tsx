import React from "react";
import Link from "next/link";
import { redirect } from "next/navigation";
import { BackendAuthVerifier } from "@/components/BackendAuthVerifier";
import { AgentPersonalScorecard } from "@/components/agent/AgentPersonalScorecard";
import { fetchAgentPersonalSummary } from "@/lib/api-client";
import { auth } from "@/lib/auth";
import { fetchFastApiCurrentUser } from "@/lib/fastapi";

export default async function AgentPersonalWorkspacePage() {
  const session = await auth();
  if (!session?.user) {
    redirect("/login");
  }

  const [summary, serverMeResponse] = await Promise.all([
    fetchAgentPersonalSummary(session.accessToken, {
      id: session.user.id,
      email: session.user.email,
      fullName: session.user.fullName || session.user.email,
    }),
    fetchFastApiCurrentUser(session.accessToken),
  ]);

  return (
    <div className="space-y-8">
      <div className="flex flex-wrap items-center justify-between gap-4 border-b border-slate-800 pb-6">
        <div>
          <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-mono font-semibold bg-indigo-500/10 text-indigo-300 border border-indigo-500/30">
            RBAC Isolated Agent Workspace • {session.user.role}
          </span>
          <h1 className="mt-2 text-2xl font-bold text-white">
            My QA Scorecard &amp; Coaching Trajectory
          </h1>
          <p className="text-sm text-slate-400">
            Signed in as{" "}
            <span className="text-slate-200 font-medium">
              {session.user.fullName}
            </span>{" "}
            ({session.user.email}) • External CRM ID:{" "}
            <code className="text-indigo-300 font-mono">
              {session.user.externalCrmAgentId ?? "N/A"}
            </code>
          </p>
        </div>

        <div className="flex items-center gap-3">
          <Link
            href="/agent/inbox"
            className="rounded-lg bg-amber-500/15 hover:bg-amber-500/25 border border-amber-500/30 px-3.5 py-2 text-xs font-semibold text-amber-200 transition"
          >
            Manager Feedback Inbox ({summary.kpis.unread_feedback_count} Unread)
          </Link>
          <Link
            href="/agent/coaching"
            className="rounded-lg bg-indigo-600 hover:bg-indigo-500 px-4 py-2 text-xs font-semibold text-white transition"
          >
            AI Coaching Library →
          </Link>
        </div>
      </div>

      {/* Personal Scorecard, Priority Alert Banner & Pillar Progress Bars */}
      <AgentPersonalScorecard summary={summary} />

      {/* Cross-Service FastAPI Token Verifier */}
      <BackendAuthVerifier
        accessToken={session.accessToken}
        initialServerMeResponse={serverMeResponse}
      />
    </div>
  );
}
