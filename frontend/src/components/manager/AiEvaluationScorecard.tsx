"use client";

import React, { useState } from "react";
import { useRouter } from "next/navigation";
import type { AiQaReportDetailData } from "@/lib/api-client";
import {
  PillarProgressBar,
  ResolutionStatusBadge,
  ScoreBadge,
  SentimentTrajectoryPill,
} from "@/components/ui/Badges";

export function AiEvaluationScorecard({
  ticketId,
  report,
}: {
  ticketId: string;
  report: AiQaReportDetailData | null;
}) {
  const router = useRouter();
  const [isReEvaluating, setIsReEvaluating] = useState(false);
  const [statusMessage, setStatusMessage] = useState<string | null>(null);

  async function handleReEvaluate() {
    setIsReEvaluating(true);
    setStatusMessage(null);
    try {
      const res = await fetch(`/api/v1/tickets/${ticketId}/re-evaluate`, {
        method: "POST",
      });
      if (!res.ok) {
        setStatusMessage(`Re-evaluation failed (HTTP ${res.status})`);
      } else {
        const data = (await res.json()) as { agent_score?: number };
        setStatusMessage(
          `AI QA evaluation refreshed (Score: ${data.agent_score ?? "Updated"}/100)`
        );
        router.refresh();
      }
    } catch {
      setStatusMessage("Network error while triggering AI re-evaluation.");
    } finally {
      setIsReEvaluating(false);
    }
  }

  if (!report) {
    return (
      <div className="rounded-xl bg-slate-900 border border-slate-800 p-5 space-y-4">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-bold text-white">AI QA Scorecard</h2>
          <button
            type="button"
            onClick={handleReEvaluate}
            disabled={isReEvaluating}
            className="rounded-lg bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 px-3 py-1.5 text-xs font-semibold text-white transition"
          >
            {isReEvaluating ? "Evaluating..." : "Run AI QA Evaluation"}
          </button>
        </div>
        <p className="text-xs text-slate-400">
          This ticket is currently queued for AI evaluation. Click above to
          evaluate immediately.
        </p>
      </div>
    );
  }

  return (
    <div className="rounded-xl bg-slate-900 border border-slate-800 flex flex-col h-full">
      <div className="border-b border-slate-800 px-4 py-3.5 flex flex-wrap items-center justify-between gap-2">
        <div>
          <h2 className="text-sm font-bold text-white">AI QA Report</h2>
          <p className="text-[11px] font-mono text-slate-400">
            Model: {report.model_used} • {report.inference_latency_ms}ms
          </p>
        </div>

        <button
          type="button"
          onClick={handleReEvaluate}
          disabled={isReEvaluating}
          className="rounded-lg bg-slate-800 hover:bg-slate-700 border border-slate-700 disabled:opacity-50 px-2.5 py-1 text-[11px] font-semibold text-indigo-300 transition"
        >
          {isReEvaluating ? "Re-Evaluating..." : "↻ Re-Run AI QA Evaluation"}
        </button>
      </div>

      <div className="p-4 space-y-5 overflow-y-auto max-h-[760px]">
        {statusMessage && (
          <div className="rounded-lg bg-indigo-500/15 border border-indigo-500/30 px-3 py-2 text-xs text-indigo-200">
            {statusMessage}
          </div>
        )}

        {/* Premature Closure Alert Banner */}
        {report.premature_closure_detected && (
          <div className="rounded-xl bg-rose-950/50 border border-rose-500/40 p-3.5 space-y-1">
            <div className="text-xs font-mono font-bold uppercase text-rose-300 flex items-center gap-1.5">
              <span>🚨 Premature Closure Detected (Score Capped ≤ 45)</span>
            </div>
            <p className="text-xs text-rose-100 leading-relaxed">
              {report.premature_closure_reason ||
                "Ticket was closed before confirming that the customer's issue was resolved."}
            </p>
          </div>
        )}

        {/* Composite Score & Resolution Badges */}
        <div className="rounded-xl bg-slate-950 border border-slate-800 p-4 flex flex-wrap items-center justify-between gap-3">
          <div>
            <div className="text-[11px] uppercase font-semibold text-slate-400">
              Composite QA Score
            </div>
            <div className="mt-1.5">
              <ScoreBadge score={report.agent_score} size="lg" />
            </div>
          </div>

          <div className="text-right space-y-1.5">
            <div>
              <ResolutionStatusBadge status={report.resolution_status} />
            </div>
            <div>
              <SentimentTrajectoryPill
                trajectory={report.customer_sentiment_trajectory}
              />
            </div>
          </div>
        </div>

        {/* Executive Summary & Core Issue */}
        <div className="space-y-3">
          <div>
            <div className="text-[11px] font-semibold uppercase tracking-wider text-slate-400">
              Executive Summary
            </div>
            <p className="mt-1 text-xs text-slate-200 leading-relaxed">
              {report.summary}
            </p>
          </div>

          <div className="rounded-lg bg-slate-950 border border-slate-800 p-3">
            <div className="flex items-center justify-between text-[11px]">
              <span className="font-semibold uppercase text-slate-400">
                Core Issue
              </span>
              <span className="font-mono text-indigo-300">
                {report.issue_category}
              </span>
            </div>
            <p className="mt-1 text-xs text-slate-200">{report.core_issue}</p>
          </div>
        </div>

        {/* 4-Pillar Rating Breakdown */}
        <div className="rounded-xl bg-slate-950 border border-slate-800 p-3.5 space-y-3">
          <div className="text-[11px] font-semibold uppercase tracking-wider text-slate-400">
            Rubric Pillar Ratings
          </div>
          <PillarProgressBar
            label="Composite QA Score"
            value={report.agent_score}
            max={100}
          />
          <PillarProgressBar
            label="Empathy & Tone Validation"
            value={report.empathy_rating}
            max={10}
          />
          <PillarProgressBar
            label="Clarity & Technical Accuracy"
            value={report.clarity_and_accuracy_rating}
            max={10}
          />
          <PillarProgressBar
            label="Ownership & Process Efficiency"
            value={report.ownership_and_efficiency_rating}
            max={10}
          />
        </div>

        {/* Strengths & Areas for Improvement */}
        <div className="grid grid-cols-1 gap-3">
          <div className="rounded-lg bg-emerald-950/20 border border-emerald-500/25 p-3">
            <div className="text-[11px] font-semibold uppercase text-emerald-300 mb-1.5">
              ✓ Demonstrated Strengths
            </div>
            <ul className="space-y-1 text-xs text-slate-200 list-disc list-inside">
              {report.strengths.map((s, idx) => (
                <li key={idx}>{s}</li>
              ))}
            </ul>
          </div>

          {report.areas_for_improvement.length > 0 && (
            <div className="rounded-lg bg-amber-950/20 border border-amber-500/25 p-3">
              <div className="text-[11px] font-semibold uppercase text-amber-300 mb-1.5">
                △ Areas for Improvement
              </div>
              <ul className="space-y-1 text-xs text-slate-200 list-disc list-inside">
                {report.areas_for_improvement.map((item, idx) => (
                  <li key={idx}>{item}</li>
                ))}
              </ul>
            </div>
          )}
        </div>

        {/* Actionable Coaching Plan Cards */}
        <div className="space-y-2.5">
          <div className="text-[11px] font-semibold uppercase tracking-wider text-slate-400">
            Actionable Coaching Plan &amp; Suggested Phrasing
          </div>
          {report.actionable_coaching_plan.map((plan, idx) => (
            <div
              key={idx}
              className="rounded-xl bg-slate-950 border border-indigo-500/30 p-3.5 space-y-2"
            >
              <div className="text-xs font-bold text-indigo-300">
                {idx + 1}. {plan.focus_area}
              </div>
              <p className="text-xs text-slate-300 leading-relaxed">
                {plan.specific_action}
              </p>
              <div className="rounded-lg bg-emerald-950/30 border border-emerald-500/30 p-2.5">
                <div className="text-[10px] font-mono uppercase text-emerald-300 font-semibold mb-1">
                  Suggested Verbatim Rewrite:
                </div>
                <p className="text-xs italic text-emerald-100">
                  &ldquo;{plan.suggested_phrasing_example}&rdquo;
                </p>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

