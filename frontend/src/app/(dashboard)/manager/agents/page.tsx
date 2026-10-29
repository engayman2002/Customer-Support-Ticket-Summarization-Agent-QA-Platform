import React from "react";
import Link from "next/link";
import { redirect } from "next/navigation";
import { ScoreBadge } from "@/components/ui/Badges";
import { fetchManagerAnalyticsOverview } from "@/lib/api-client";
import { auth } from "@/lib/auth";

export default async function ManagerAgentLeaderboardPage() {
  const session = await auth();
  if (!session?.user) {
    redirect("/login");
  }
  if (session.user.role === "AGENT") {
    redirect("/agent");
  }

  const overview = await fetchManagerAnalyticsOverview(session.accessToken);
  const leaderboard = [...overview.agent_risk_matrix].sort(
    (a, b) => b.average_agent_score - a.average_agent_score
  );

  return (
    <div className="space-y-6">
      <div className="border-b border-slate-800 pb-5">
        <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-mono font-semibold bg-emerald-500/10 text-emerald-300 border border-emerald-500/30">
          Team Benchmarking &amp; Coaching
        </span>
        <h1 className="mt-2 text-2xl font-bold text-white">
          Support Agent QA Performance Leaderboard
        </h1>
        <p className="text-sm text-slate-400">
          Compare agent composite QA scores, proper resolution rates, empathy
          ratings, and premature closure frequency.
        </p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
        {leaderboard.map((ag, idx) => (
          <div
            key={ag.agent_id}
            className="rounded-xl bg-slate-900 border border-slate-800 p-5 space-y-4"
          >
            <div className="flex items-center justify-between">
              <div>
                <span className="text-xs font-mono text-indigo-400">
                  Rank #{idx + 1}
                </span>
                <h2 className="text-base font-bold text-white">
                  {ag.full_name}
                </h2>
                <p className="text-xs text-slate-400">{ag.email}</p>
              </div>
              <ScoreBadge score={ag.average_agent_score} size="lg" />
            </div>

            <div className="grid grid-cols-3 gap-3 text-center">
              <div className="rounded-lg bg-slate-950 border border-slate-800 p-2.5">
                <div className="text-[10px] uppercase text-slate-400">
                  Proper Resolution
                </div>
                <div className="mt-1 text-sm font-mono font-bold text-emerald-300">
                  {ag.proper_resolution_rate_pct}%
                </div>
              </div>
              <div className="rounded-lg bg-slate-950 border border-slate-800 p-2.5">
                <div className="text-[10px] uppercase text-slate-400">
                  Premature Closures
                </div>
                <div className="mt-1 text-sm font-mono font-bold text-rose-300">
                  {ag.premature_closure_rate_pct}%
                </div>
              </div>
              <div className="rounded-lg bg-slate-950 border border-slate-800 p-2.5">
                <div className="text-[10px] uppercase text-slate-400">
                  Avg Empathy
                </div>
                <div className="mt-1 text-sm font-mono font-bold text-indigo-300">
                  {ag.avg_empathy_rating} / 10
                </div>
              </div>
            </div>

            <div className="flex items-center justify-between pt-2 border-t border-slate-800 text-xs">
              <span className="text-slate-400 font-mono">
                {ag.evaluated_tickets} evaluated{" "}
                {ag.evaluated_tickets === 1 ? "ticket" : "tickets"}
              </span>
              <Link
                href={`/manager/tickets?agentId=${ag.agent_id}`}
                className="text-indigo-300 hover:underline font-semibold"
              >
                Audit {ag.full_name}&apos;s Tickets →
              </Link>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

