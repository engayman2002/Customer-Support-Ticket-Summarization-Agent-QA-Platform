import React from "react";
import Link from "next/link";
import { redirect } from "next/navigation";
import { CoachingPlanAccordion } from "@/components/agent/CoachingPlanAccordion";
import { fetchAgentPersonalSummary } from "@/lib/api-client";
import { auth } from "@/lib/auth";

export default async function AgentCoachingHistoryPage() {
  const session = await auth();
  if (!session?.user) {
    redirect("/login");
  }

  const summary = await fetchAgentPersonalSummary(session.accessToken, {
    id: session.user.id,
    email: session.user.email,
    fullName: session.user.fullName || session.user.email,
  });

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-4 border-b border-slate-800 pb-5">
        <div>
          <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-mono font-semibold bg-indigo-500/10 text-indigo-300 border border-indigo-500/30">
            Personalized AI Coaching Library
          </span>
          <h1 className="mt-2 text-2xl font-bold text-white">
            AI Coaching History &amp; Suggested Phrasing Library
          </h1>
          <p className="text-sm text-slate-400">
            Browse concrete coaching recommendations and word-for-word suggested
            rewrites generated from your evaluated support tickets.
          </p>
        </div>

        <Link
          href="/agent"
          className="rounded-lg bg-slate-800 hover:bg-slate-700 border border-slate-700 px-3.5 py-2 text-xs font-semibold text-slate-200 transition"
        >
          ← Back to My Performance
        </Link>
      </div>

      <CoachingPlanAccordion
        ticketsWithCoaching={summary.recent_coaching_plans}
      />
    </div>
  );
}

