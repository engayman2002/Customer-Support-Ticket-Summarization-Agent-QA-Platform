import React from "react";
import {
  formatSentimentTrajectory,
  getCoachingPriorityBadgeClasses,
  getFeedbackStatusBadgeClasses,
  getResolutionBadgeClasses,
  getScoreBadgeClasses,
  getScoreBadgeVariant,
} from "@/lib/dashboard-utils";

export function ScoreBadge({
  score,
  suffix = "/ 100",
  size = "sm",
}: {
  score: number | null | undefined;
  suffix?: string;
  size?: "sm" | "md" | "lg";
}) {
  if (typeof score !== "number" || Number.isNaN(score)) {
    return (
      <span className="inline-flex items-center px-2 py-0.5 rounded-md text-xs font-mono bg-slate-800 text-slate-400 border border-slate-700">
        Pending
      </span>
    );
  }

  const classes = getScoreBadgeClasses(score);
  const sizeClass =
    size === "lg"
      ? "px-3 py-1 text-sm font-bold"
      : size === "md"
        ? "px-2.5 py-0.5 text-xs font-semibold"
        : "px-2 py-0.5 text-xs font-semibold";

  return (
    <span
      className={`inline-flex items-center rounded-md border font-mono ${sizeClass} ${classes}`}
    >
      {score}
      {suffix ? ` ${suffix}` : ""}
    </span>
  );
}

export function ResolutionStatusBadge({
  status,
}: {
  status: string | null | undefined;
}) {
  const classes = getResolutionBadgeClasses(status);
  return (
    <span
      className={`inline-flex items-center px-2 py-0.5 rounded-md border text-[11px] font-mono font-semibold tracking-tight ${classes}`}
    >
      {status || "QUEUED"}
    </span>
  );
}

export function FeedbackStatusBadge({
  status,
}: {
  status: string | null | undefined;
}) {
  const classes = getFeedbackStatusBadgeClasses(status);
  return (
    <span
      className={`inline-flex items-center px-2 py-0.5 rounded-md border text-[11px] font-mono font-semibold ${classes}`}
    >
      {status || "NONE"}
    </span>
  );
}

export function CoachingPriorityBadge({
  priority,
}: {
  priority: string | null | undefined;
}) {
  const classes = getCoachingPriorityBadgeClasses(priority);
  return (
    <span
      className={`inline-flex items-center px-2 py-0.5 rounded-md border text-[11px] font-mono font-semibold ${classes}`}
    >
      {priority || "MEDIUM"}
    </span>
  );
}

export function SentimentTrajectoryPill({
  trajectory,
}: {
  trajectory: string | null | undefined;
}) {
  const { label, classes } = formatSentimentTrajectory(trajectory);
  return (
    <span
      className={`inline-flex items-center px-2 py-0.5 rounded-md border text-[11px] font-medium ${classes}`}
    >
      {label}
    </span>
  );
}

export function PillarProgressBar({
  label,
  value,
  max = 10,
}: {
  label: string;
  value: number;
  max?: number;
}) {
  const pct = Math.min(100, Math.max(0, Math.round((value / max) * 100)));
  const variant = getScoreBadgeVariant(pct);
  const barColor =
    variant === "emerald"
      ? "bg-emerald-500"
      : variant === "amber"
        ? "bg-amber-500"
        : "bg-rose-500";

  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between text-xs">
        <span className="font-medium text-slate-300">{label}</span>
        <span className="font-mono font-semibold text-white">
          {value} / {max}
        </span>
      </div>
      <div className="w-full h-2 rounded-full bg-slate-800 overflow-hidden">
        <div
          className={`h-full rounded-full transition-all ${barColor}`}
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}

