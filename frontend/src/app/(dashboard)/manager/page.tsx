import React from "react";
import Link from "next/link";
import { redirect } from "next/navigation";
import { BackendAuthVerifier } from "@/components/BackendAuthVerifier";
import { KpiSummaryCards } from "@/components/manager/KpiSummaryCards";
import { ScoreBadge } from "@/components/ui/Badges";
import { fetchManagerAnalyticsOverview } from "@/lib/api-client";
import { auth } from "@/lib/auth";
import { fetchFastApiCurrentUser } from "@/lib/fastapi";

export default async function ManagerOverviewDashboardPage() {
  const session = await auth();
  if (!session?.user) {
    redirect("/login");
  }
  if (session.user.role === "AGENT") {
    redirect("/agent");
  }

  const [overview, serverMeResponse] = await Promise.all([
    fetchManagerAnalyticsOverview(session.accessToken),
    fetchFastApiCurrentUser(session.accessToken),
  ]);

  return (
    <div className="space-y-8">
      {/* Page Header */}
      <div className="flex flex-wrap items-center justify-between gap-4 border-b border-slate-800 pb-6">
        <div>
          <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-mono font-semibold bg-emerald-500/10 text-emerald-300 border border-emerald-500/30">
            Manager QA Command Center • {session.user.role}
          </span>
          <h1 className="mt-2 text-2xl font-bold text-white">
            Team Quality Assurance &amp; Resolution Analytics
          </h1>
          <p className="text-sm text-slate-400">
            100% automated closed-ticket auditing powered by Groq{" "}
            <code className="text-indigo-300 font-mono">
              llama-3.3-70b-versatile
            </code>
          </p>
        </div>

        <div className="flex items-center gap-3">
          <Link
            href="/manager/tickets?resolutionStatus=PREMATURELY_CLOSED&prematureClosureOnly=true"
            className="rounded-lg bg-rose-600/20 hover:bg-rose-600/30 border border-rose-500/30 px-3.5 py-2 text-xs font-semibold text-rose-200 transition"
          >
            🚨 Premature Closures
          </Link>
          <Link
            href="/manager/tickets"
            className="rounded-lg bg-indigo-600 hover:bg-indigo-500 px-4 py-2 text-xs font-semibold text-white transition"
          >
            Open Ticket QA Review Queue →
          </Link>
        </div>
      </div>

      {/* 6 Top KPI Summary Cards */}
      <KpiSummaryCards kpis={overview.kpis} />

      {/* Daily Score Trend & Issue Category Breakdown */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Daily Score & Premature Closure Trend Visualization */}
        <section className="lg:col-span-2 rounded-xl bg-slate-900 border border-slate-800 p-6 space-y-4">
          <div className="flex items-center justify-between">
            <div>
              <h2 className="text-sm font-bold text-white">
                Daily QA Score &amp; Premature Closure Trend
              </h2>
              <p className="text-xs text-slate-400">
                Composite rubric score vs. premature ticket closures by date
              </p>
            </div>
            <span className="text-xs font-mono text-slate-400">
              {overview.score_trend_daily.length} active days
            </span>
          </div>

          {overview.score_trend_daily.length === 0 ? (
            <div className="py-12 text-center text-xs text-slate-500">
              No evaluated ticket trend data available yet.
            </div>
          ) : (
            <div className="space-y-3 pt-2">
              {overview.score_trend_daily.map((point) => (
                <div
                  key={point.date}
                  className="rounded-lg bg-slate-950 border border-slate-800/80 p-3 space-y-2"
                >
                  <div className="flex items-center justify-between text-xs">
                    <span className="font-mono font-semibold text-slate-200">
                      {point.date}
                    </span>
                    <div className="flex items-center gap-3 font-mono">
                      <span className="text-slate-400">
                        {point.total_tickets} tickets
                      </span>
                      {point.premature_closures > 0 && (
                        <span className="px-2 py-0.5 rounded bg-rose-500/15 text-rose-300 border border-rose-500/30 text-[11px]">
                          {point.premature_closures} premature
                        </span>
                      )}
                      <ScoreBadge score={point.avg_score} />
                    </div>
                  </div>
                  <div className="w-full h-2 rounded-full bg-slate-800 overflow-hidden">
                    <div
                      className={`h-full rounded-full ${
                        point.avg_score >= 80
                          ? "bg-emerald-500"
                          : point.avg_score >= 60
                            ? "bg-amber-500"
                            : "bg-rose-500"
                      }`}
                      style={{
                        width: `${Math.min(100, Math.max(4, point.avg_score))}%`,
                      }}
                    />
                  </div>
                </div>
              ))}
            </div>
          )}
        </section>

        {/* Issue Category Breakdown */}
        <section className="rounded-xl bg-slate-900 border border-slate-800 p-6 space-y-4">
          <div>
            <h2 className="text-sm font-bold text-white">
              Issue Category Breakdown
            </h2>
            <p className="text-xs text-slate-400">
              Volume &amp; average QA score by ticket category
            </p>
          </div>

          {overview.issue_category_breakdown.length === 0 ? (
            <p className="text-xs text-slate-500 py-8 text-center">
              No issue categories evaluated yet.
            </p>
          ) : (
            <div className="space-y-3">
              {overview.issue_category_breakdown.map((cat) => (
                <div
                  key={cat.category}
                  className="rounded-lg bg-slate-950 border border-slate-800 p-3 flex items-center justify-between gap-2"
                >
                  <div>
                    <div className="text-xs font-mono font-semibold text-indigo-300">
                      {cat.category}
                    </div>
                    <div className="text-[11px] text-slate-400">
                      {cat.count} evaluated{" "}
                      {cat.count === 1 ? "ticket" : "tickets"}
                    </div>
                  </div>
                  <ScoreBadge score={cat.avg_score} />
                </div>
              ))}
            </div>
          )}
        </section>
      </div>

      {/* Agent Risk Matrix */}
      <section className="rounded-xl bg-slate-900 border border-slate-800 p-6 space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <h2 className="text-sm font-bold text-white">
              Agent Risk Matrix &amp; Coaching Prioritization
            </h2>
            <p className="text-xs text-slate-400">
              Ranked by premature closure rate and composite QA score
            </p>
          </div>
          <Link
            href="/manager/agents"
            className="text-xs font-semibold text-indigo-300 hover:underline"
          >
            View Full Agent Leaderboard →
          </Link>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b border-slate-800 text-[11px] uppercase tracking-wider text-slate-400">
                <th className="py-3 pr-4">Support Agent</th>
                <th className="py-3 pr-4">Evaluated Tickets</th>
                <th className="py-3 pr-4">Avg QA Score</th>
                <th className="py-3 pr-4">Proper Resolution %</th>
                <th className="py-3 pr-4">Premature Closure %</th>
                <th className="py-3 pr-4">Avg Empathy</th>
                <th className="py-3 text-right">Action</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/70">
              {overview.agent_risk_matrix.map((ag) => (
                <tr key={ag.agent_id} className="hover:bg-slate-800/30">
                  <td className="py-3 pr-4">
                    <div className="font-semibold text-slate-100 text-xs">
                      {ag.full_name}
                    </div>
                    <div className="text-[11px] text-slate-400">{ag.email}</div>
                  </td>
                  <td className="py-3 pr-4 font-mono text-xs text-slate-200">
                    {ag.evaluated_tickets}
                  </td>
                  <td className="py-3 pr-4">
                    <ScoreBadge score={ag.average_agent_score} />
                  </td>
                  <td className="py-3 pr-4 font-mono text-xs text-emerald-300">
                    {ag.proper_resolution_rate_pct}%
                  </td>
                  <td className="py-3 pr-4 font-mono text-xs text-rose-300">
                    {ag.premature_closure_rate_pct}%
                  </td>
                  <td className="py-3 pr-4 font-mono text-xs text-indigo-300">
                    {ag.avg_empathy_rating} / 10
                  </td>
                  <td className="py-3 text-right">
                    <Link
                      href={`/manager/tickets?agentId=${ag.agent_id}`}
                      className="rounded-lg bg-slate-800 hover:bg-slate-700 border border-slate-700 px-3 py-1 text-xs font-semibold text-slate-200 transition"
                    >
                      Inspect Agent Tickets →
                    </Link>
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
