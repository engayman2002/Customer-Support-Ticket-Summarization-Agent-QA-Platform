"use client";

import React, { useState } from "react";
import { useRouter } from "next/navigation";
import type { ManagerFeedbackItemData } from "@/lib/api-client";
import {
  buildFeedbackStatusPatchPayload,
  canAcknowledgeFeedback,
} from "@/lib/dashboard-utils";
import {
  CoachingPriorityBadge,
  FeedbackStatusBadge,
  ResolutionStatusBadge,
  ScoreBadge,
} from "@/components/ui/Badges";

export function FeedbackInboxCard({
  feedback,
}: {
  feedback: ManagerFeedbackItemData;
}) {
  const router = useRouter();
  const [readStatus, setReadStatus] = useState<string>(feedback.read_status);
  const [completedIds, setCompletedIds] = useState<Set<string>>(() => {
    const initial = new Set<string>();
    for (const item of feedback.action_items || []) {
      if (item.completed) {
        initial.add(item.id);
      }
    }
    return initial;
  });
  const [note, setNote] = useState<string>(
    feedback.agent_acknowledgement_note || ""
  );
  const [isUpdating, setIsUpdating] = useState<boolean>(false);
  const [statusMessage, setStatusMessage] = useState<string | null>(null);

  const isAcknowledged = readStatus === "ACKNOWLEDGED";
  const allChecked = canAcknowledgeFeedback(
    feedback.action_items,
    completedIds
  );

  function toggleActionItem(itemId: string) {
    if (isAcknowledged) return;
    setCompletedIds((prev) => {
      const next = new Set(prev);
      if (next.has(itemId)) {
        next.delete(itemId);
      } else {
        next.add(itemId);
      }
      return next;
    });
  }

  async function handleMarkAsRead() {
    if (readStatus !== "UNREAD") return;
    setIsUpdating(true);
    setStatusMessage(null);
    try {
      const payload = buildFeedbackStatusPatchPayload({
        readStatus: "READ",
      });
      const res = await fetch(`/api/v1/feedback/${feedback.id}/status`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (res.ok) {
        setReadStatus("READ");
        setStatusMessage("Marked as READ.");
        router.refresh();
      }
    } finally {
      setIsUpdating(false);
    }
  }

  async function handleAcknowledge(e: React.FormEvent) {
    e.preventDefault();
    if (!allChecked || isAcknowledged) return;

    setIsUpdating(true);
    setStatusMessage(null);
    try {
      const payload = buildFeedbackStatusPatchPayload({
        readStatus: "ACKNOWLEDGED",
        completedActionItemIds: Array.from(completedIds),
        agentAcknowledgementNote: note,
      });

      const res = await fetch(`/api/v1/feedback/${feedback.id}/status`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });

      if (res.ok) {
        setReadStatus("ACKNOWLEDGED");
        setStatusMessage(
          "Instructions acknowledged and action items marked complete!"
        );
        router.refresh();
      } else {
        setStatusMessage(`Failed to acknowledge (HTTP ${res.status}).`);
      }
    } catch {
      setStatusMessage("Network error while acknowledging feedback.");
    } finally {
      setIsUpdating(false);
    }
  }

  return (
    <div
      className={`rounded-xl bg-slate-900 border p-5 space-y-4 transition ${
        readStatus === "UNREAD"
          ? "border-amber-500/40"
          : isAcknowledged
            ? "border-emerald-500/30"
            : "border-slate-800"
      }`}
    >
      {/* Card Header */}
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-800 pb-3.5">
        <div className="space-y-1">
          <div className="flex flex-wrap items-center gap-2">
            <CoachingPriorityBadge priority={feedback.coaching_priority} />
            <FeedbackStatusBadge status={readStatus} />
            {feedback.ticket && (
              <span className="font-mono text-xs text-indigo-300 font-semibold">
                {feedback.ticket.external_ticket_id}: {feedback.ticket.subject}
              </span>
            )}
          </div>
          <div className="text-xs text-slate-400">
            From Manager:{" "}
            <span className="text-slate-200 font-medium">
              {feedback.manager?.full_name || "QA Manager"}
            </span>
            {feedback.created_at && (
              <span>
                {" "}
                •{" "}
                {new Date(feedback.created_at).toLocaleString("en-US", {
                  month: "short",
                  day: "numeric",
                  hour: "2-digit",
                  minute: "2-digit",
                })}
              </span>
            )}
          </div>
        </div>

        <div className="flex items-center gap-2">
          {feedback.ticket?.resolution_status && (
            <ResolutionStatusBadge status={feedback.ticket.resolution_status} />
          )}
          {feedback.manager_override_score !== null ? (
            <ScoreBadge
              score={feedback.manager_override_score}
              suffix="(Override)"
            />
          ) : (
            feedback.ticket?.ai_agent_score !== undefined &&
            feedback.ticket?.ai_agent_score !== null && (
              <ScoreBadge score={feedback.ticket.ai_agent_score} />
            )
          )}
          {readStatus === "UNREAD" && (
            <button
              type="button"
              onClick={handleMarkAsRead}
              disabled={isUpdating}
              className="rounded-lg bg-slate-800 hover:bg-slate-700 border border-slate-700 px-3 py-1 text-xs font-semibold text-amber-300 transition"
            >
              Mark as Read
            </button>
          )}
        </div>
      </div>

      {statusMessage && (
        <div className="rounded-lg bg-emerald-500/15 border border-emerald-500/30 px-3 py-2 text-xs text-emerald-200">
          {statusMessage}
        </div>
      )}

      {/* Manager Comments */}
      <div className="rounded-lg bg-slate-950 border border-slate-800 p-3.5">
        <div className="text-[11px] font-semibold uppercase text-slate-400 mb-1">
          Manager Coaching Instructions
        </div>
        <p className="text-sm text-slate-100 leading-relaxed">
          {feedback.comments}
        </p>
      </div>

      {/* Interactive Action Items Checklist & Acknowledgement Form */}
      <form onSubmit={handleAcknowledge} className="space-y-4">
        {feedback.action_items.length > 0 && (
          <div className="space-y-2">
            <div className="flex items-center justify-between text-xs">
              <span className="font-semibold uppercase tracking-wider text-slate-300">
                Required Action Items ({completedIds.size} /{" "}
                {feedback.action_items.length} Completed)
              </span>
              {!allChecked && !isAcknowledged && (
                <span className="text-[11px] text-amber-300 font-mono">
                  Complete all items to enable acknowledgement
                </span>
              )}
            </div>

            <div className="space-y-2">
              {feedback.action_items.map((item) => {
                const checked = completedIds.has(item.id);
                return (
                  <label
                    key={item.id}
                    className={`flex items-start gap-3 rounded-lg border p-3 text-xs cursor-pointer transition ${
                      checked
                        ? "bg-emerald-950/20 border-emerald-500/30 text-emerald-100"
                        : "bg-slate-950 border-slate-800 text-slate-200 hover:border-slate-700"
                    }`}
                  >
                    <input
                      type="checkbox"
                      checked={checked}
                      disabled={isAcknowledged}
                      onChange={() => toggleActionItem(item.id)}
                      className="mt-0.5 rounded border-slate-700 text-emerald-500 focus:ring-emerald-500"
                    />
                    <span className={checked ? "line-through opacity-85" : ""}>
                      {item.description}
                    </span>
                  </label>
                );
              })}
            </div>
          </div>
        )}

        <div>
          <label className="block text-[11px] font-semibold uppercase text-slate-400 mb-1">
            Agent Acknowledgement Note &amp; Follow-up Summary
          </label>
          <textarea
            rows={2}
            disabled={isAcknowledged}
            value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder="Summarize the actions you took to resolve or apply this coaching..."
            className="w-full rounded-lg bg-slate-950 border border-slate-800 p-2.5 text-xs text-slate-100 placeholder:text-slate-500 disabled:opacity-60 focus:outline-none focus:border-indigo-500"
          />
        </div>

        {!isAcknowledged ? (
          <button
            type="submit"
            disabled={!allChecked || isUpdating}
            className="rounded-lg bg-emerald-600 hover:bg-emerald-500 disabled:opacity-40 disabled:cursor-not-allowed px-4 py-2 text-xs font-bold text-white transition"
          >
            {isUpdating
              ? "Saving Acknowledgement..."
              : "✓ Acknowledge & Complete Instructions"}
          </button>
        ) : (
          <div className="text-xs font-mono text-emerald-300">
            ✓ Acknowledged
            {feedback.acknowledged_at
              ? ` on ${new Date(feedback.acknowledged_at).toLocaleString()}`
              : ""}
          </div>
        )}
      </form>
    </div>
  );
}

