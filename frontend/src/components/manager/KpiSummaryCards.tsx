import React from "react";
import Link from "next/link";
import type { ManagerAnalyticsOverviewData } from "@/lib/api-client";
import { getScoreBadgeClasses } from "@/lib/dashboard-utils";

export function KpiSummaryCards({
  kpis,
}: {
  kpis: ManagerAnalyticsOverviewData["kpis"];
}) {
  const scoreBadgeClass = getScoreBadgeClasses(kpis.average_agent_score);

  return (
    <section className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-6 gap-4">
      <div className="rounded-xl bg-slate-900 border border-slate-800 p-4 flex flex-col justify-between">
        <div className="text-[11px] font-semibold uppercase tracking-wider text-slate-400">
          Evaluated Tickets
        </div>
        <div className="mt-3 text-2xl font-bold text-white font-mono">
          {kpis.total_tickets_evaluated}
        </div>
        <div className="mt-1 text-[11px] text-slate-400">
          100% automated QA coverage
        </div>
      </div>

      <div className="rounded-xl bg-slate-900 border border-slate-800 p-4 flex flex-col justify-between">
        <div className="text-[11px] font-semibold uppercase tracking-wider text-slate-400">
          Team Avg QA Score
        </div>
        <div className="mt-3 flex items-center gap-2">
          <span
            className={`px-2.5 py-1 rounded-lg border text-xl font-bold font-mono ${scoreBadgeClass}`}
          >
            {kpis.average_agent_score}
          </span>
          <span className="text-xs text-slate-400 font-mono">/ 100</span>
        </div>
        <div className="mt-1 text-[11px] text-slate-400">
          Weighted 4-pillar rubric
        </div>
      </div>

      <div className="rounded-xl bg-slate-900 border border-slate-800 p-4 flex flex-col justify-between">
        <div className="text-[11px] font-semibold uppercase tracking-wider text-slate-400">
          Proper Resolution Rate
        </div>
        <div className="mt-3 text-2xl font-bold text-emerald-300 font-mono">
          {kpis.proper_resolution_rate_pct}%
        </div>
        <div className="mt-1 text-[11px] text-slate-400">
          Verified resolved &amp; confirmed
        </div>
      </div>

      <div className="rounded-xl bg-slate-900 border border-slate-800 p-4 flex flex-col justify-between">
        <div className="text-[11px] font-semibold uppercase tracking-wider text-slate-400">
          Premature Closure Rate
        </div>
        <div className="mt-3 text-2xl font-bold text-rose-400 font-mono">
          {kpis.premature_closure_rate_pct}%
        </div>
        <div className="mt-1 text-[11px] text-slate-400">
          <Link
            href="/manager/tickets?resolutionStatus=PREMATURELY_CLOSED&prematureClosureOnly=true"
            className="text-rose-300 hover:underline"
          >
            Inspect premature closures →
          </Link>
        </div>
      </div>

      <div className="rounded-xl bg-slate-900 border border-slate-800 p-4 flex flex-col justify-between">
        <div className="text-[11px] font-semibold uppercase tracking-wider text-slate-400">
          Avg Empathy Rating
        </div>
        <div className="mt-3 text-2xl font-bold text-indigo-300 font-mono">
          {kpis.avg_empathy_rating} <span className="text-xs text-slate-400">/ 10</span>
        </div>
        <div className="mt-1 text-[11px] text-slate-400">
          Warmth &amp; tone validation
        </div>
      </div>

      <div className="rounded-xl bg-slate-900 border border-rose-500/30 p-4 flex flex-col justify-between">
        <div className="text-[11px] font-semibold uppercase tracking-wider text-rose-300">
          Needs Manager Review
        </div>
        <div className="mt-3 text-2xl font-bold text-amber-300 font-mono">
          {kpis.unreviewed_low_score_tickets_count}
        </div>
        <div className="mt-1 text-[11px] text-slate-400">
          <Link
            href="/manager/tickets?maxScore=59&pendingFeedbackOnly=true"
            className="text-amber-300 hover:underline"
          >
            Review low-score queue →
          </Link>
        </div>
      </div>
    </section>
  );
}

