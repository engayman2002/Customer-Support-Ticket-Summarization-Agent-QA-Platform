import React from "react";
import Link from "next/link";
import type { AgentPersonalSummaryData } from "@/lib/api-client";
import {
  PillarProgressBar,
  ResolutionStatusBadge,
  ScoreBadge,
} from "@/components/ui/Badges";

export function AgentPersonalScorecard({
  summary,
}: {
  summary: AgentPersonalSummaryData;
}) {
  const { kpis } = summary;

  return (
    <div className="space-y-6">
      {/* Priority Alert Banner when unread manager instructions exist */}
      {kpis.unread_feedback_count > 0 && (
        <div className="rounded-xl bg-amber-950/40 border border-amber-500/40 p-4 flex flex-wrap items-center justify-between gap-4">
          <div className="space-y-1">
            <div className="text-xs font-mono font-bold uppercase text-amber-300">
              🔔 Action Required: {kpis.unread_feedback_count} Unread Manager{" "}
              {kpis.unread_feedback_count === 1 ? "Instruction" : "Instructions"}
              {kpis.high_priority_unread_count > 0 &&
                ` (${kpis.high_priority_unread_count} High Priority)`}
            </div>
            <p className="text-xs text-amber-100">
              Please review your manager&apos;s coaching notes, complete the
              assigned action items, and acknowledge receipt.
            </p>
          </div>
          <Link
            href="/agent/inbox"
            className="rounded-lg bg-amber-500 hover:bg-amber-400 px-4 py-2 text-xs font-bold text-slate-950 transition"
          >
            Open Feedback Inbox ({kpis.unread_feedback_count}) →
          </Link>
        </div>
      )}

      {/* Personal Rolling 30-Day KPI Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <div className="rounded-xl bg-slate-900 border border-slate-800 p-5">
          <div className="text-[11px] font-semibold uppercase tracking-wider text-slate-400">
            My Composite QA Score
          </div>
          <div className="mt-3">
            <ScoreBadge score={kpis.average_agent_score} size="lg" />
          </div>
          <div className="mt-2 text-xs text-slate-400">
            Across {kpis.total_tickets_evaluated} evaluated tickets
          </div>
        </div>

        <div className="rounded-xl bg-slate-900 border border-slate-800 p-5">
          <div className="text-[11px] font-semibold uppercase tracking-wider text-slate-400">
            Proper Resolution Rate
          </div>
          <div className="mt-3 text-2xl font-bold font-mono text-emerald-300">
            {kpis.proper_resolution_rate_pct}%
          </div>
          <div className="mt-2 text-xs text-slate-400">
            Premature closures: {kpis.premature_closure_rate_pct}%
          </div>
        </div>

        <div className="rounded-xl bg-slate-900 border border-slate-800 p-5">
          <div className="text-[11px] font-semibold uppercase tracking-wider text-slate-400">
            Empathy &amp; Tone Rating
          </div>
          <div className="mt-3 text-2xl font-bold font-mono text-indigo-300">
            {kpis.avg_empathy_rating} <span className="text-xs text-slate-400">/ 10</span>
          </div>
          <div className="mt-2 text-xs text-slate-400">
            Clarity: {kpis.avg_clarity_rating}/10 • Ownership:{" "}
            {kpis.avg_ownership_rating}/10
          </div>
        </div>

        <div className="rounded-xl bg-slate-900 border border-slate-800 p-5">
          <div className="text-[11px] font-semibold uppercase tracking-wider text-slate-400">
            Pending Manager Feedback
          </div>
          <div className="mt-3 text-2xl font-bold font-mono text-amber-300">
            {kpis.unread_feedback_count}
          </div>
          <div className="mt-2 text-xs">
            <Link
              href="/agent/inbox"
              className="text-indigo-300 hover:underline"
            >
              Go to Feedback Inbox →
            </Link>
          </div>
        </div>
      </div>

      {/* Personal Pillar Radar / Progress Breakdown */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="rounded-xl bg-slate-900 border border-slate-800 p-6 space-y-4">
          <div>
            <h2 className="text-sm font-bold text-white">
              My 4-Pillar Rubric Breakdown
            </h2>
            <p className="text-xs text-slate-400">
              Personal competency averages across evaluated interactions
            </p>
          </div>
          <PillarProgressBar
            label="Composite QA Score"
            value={kpis.average_agent_score}
            max={100}
          />
          <PillarProgressBar
            label="Empathy & Customer Validation"
            value={kpis.avg_empathy_rating}
            max={10}
          />
          <PillarProgressBar
            label="Communication Clarity & Accuracy"
            value={kpis.avg_clarity_rating}
            max={10}
          />
          <PillarProgressBar
            label="Process Efficiency & Ownership"
            value={kpis.avg_ownership_rating}
            max={10}
          />
        </div>

        {/* Recent Evaluated Tickets */}
        <div className="rounded-xl bg-slate-900 border border-slate-800 p-6 space-y-4">
          <div className="flex items-center justify-between">
            <div>
              <h2 className="text-sm font-bold text-white">
                My Recent Evaluated Tickets
              </h2>
              <p className="text-xs text-slate-400">
                Strictly isolated to your assigned tickets
              </p>
            </div>
            <Link
              href="/agent/coaching"
              className="text-xs font-semibold text-indigo-300 hover:underline"
            >
              View AI Coaching Library →
            </Link>
          </div>

          {summary.recent_coaching_plans.length === 0 ? (
            <p className="text-xs text-slate-500 py-8 text-center">
              No evaluated tickets assigned to your account yet.
            </p>
          ) : (
            <div className="space-y-3">
              {summary.recent_coaching_plans.slice(0, 5).map((item) => (
                <div
                  key={item.ticket_id}
                  className="rounded-lg bg-slate-950 border border-slate-800 p-3 flex flex-wrap items-center justify-between gap-2"
                >
                  <div className="space-y-0.5 max-w-xs">
                    <div className="text-xs font-mono text-indigo-300">
                      {item.external_ticket_id} • {item.issue_category}
                    </div>
                    <div className="text-xs font-medium text-slate-100 truncate">
                      {item.subject}
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    <ResolutionStatusBadge status={item.resolution_status} />
                    <ScoreBadge score={item.agent_score} />
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

