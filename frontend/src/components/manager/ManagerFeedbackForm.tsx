"use client";

import React, { useState } from "react";
import { useRouter } from "next/navigation";
import type { ManagerFeedbackItemData } from "@/lib/api-client";
import {
  CoachingPriorityBadge,
  FeedbackStatusBadge,
} from "@/components/ui/Badges";

export function ManagerFeedbackForm({
  ticketId,
  aiScore,
  existingFeedbacks,
}: {
  ticketId: string;
  aiScore: number | null;
  existingFeedbacks: ManagerFeedbackItemData[];
}) {
  const router = useRouter();
  const [overrideScore, setOverrideScore] = useState<string>(
    aiScore !== null ? String(aiScore) : ""
  );
  const [coachingPriority, setCoachingPriority] = useState<string>("HIGH");
  const [comments, setComments] = useState<string>("");
  const [actionItemInputs, setActionItemInputs] = useState<string[]>([
    "Confirm resolution with customer before closing ticket",
  ]);
  const [newActionText, setNewActionText] = useState<string>("");
  const [isSubmitting, setIsSubmitting] = useState<boolean>(false);
  const [feedbackNotice, setFeedbackNotice] = useState<{
    type: "success" | "error";
    text: string;
  } | null>(null);

  function handleAddActionItem() {
    const trimmed = newActionText.trim();
    if (!trimmed) return;
    setActionItemInputs((prev) => [...prev, trimmed]);
    setNewActionText("");
  }

  function handleRemoveActionItem(index: number) {
    setActionItemInputs((prev) => prev.filter((_, idx) => idx !== index));
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (comments.trim().length < 3) {
      setFeedbackNotice({
        type: "error",
        text: "Please enter coaching comments (at least 3 characters).",
      });
      return;
    }

    setIsSubmitting(true);
    setFeedbackNotice(null);

    const parsedOverride =
      overrideScore.trim() !== "" ? Number(overrideScore) : null;

    const payload = {
      manager_override_score:
        parsedOverride !== null && !Number.isNaN(parsedOverride)
          ? Math.min(100, Math.max(0, parsedOverride))
          : null,
      coaching_priority: coachingPriority,
      comments: comments.trim(),
      action_items: actionItemInputs.map((desc, idx) => ({
        id: `act_${idx + 1}_${Date.now().toString(36)}`,
        description: desc,
        completed: false,
      })),
    };

    try {
      const res = await fetch(`/api/v1/tickets/${ticketId}/feedback`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });

      if (!res.ok) {
        setFeedbackNotice({
          type: "error",
          text: `Failed to submit feedback (HTTP ${res.status}).`,
        });
      } else {
        setFeedbackNotice({
          type: "success",
          text: "Coaching feedback dispatched to Agent's Inbox (Status: UNREAD).",
        });
        setComments("");
        router.refresh();
      }
    } catch {
      setFeedbackNotice({
        type: "error",
        text: "Network error submitting manager feedback.",
      });
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <div className="rounded-xl bg-slate-900 border border-slate-800 flex flex-col h-full">
      <div className="border-b border-slate-800 px-4 py-3.5">
        <h2 className="text-sm font-bold text-white">
          Manager Evaluation &amp; Coaching
        </h2>
        <p className="text-[11px] text-slate-400">
          Override score, assign priority &amp; send action items to agent inbox
        </p>
      </div>

      <div className="p-4 space-y-5 overflow-y-auto max-h-[760px]">
        <form onSubmit={handleSubmit} className="space-y-4">
          {feedbackNotice && (
            <div
              className={`rounded-lg px-3 py-2 text-xs border ${
                feedbackNotice.type === "success"
                  ? "bg-emerald-500/15 border-emerald-500/30 text-emerald-200"
                  : "bg-rose-500/15 border-rose-500/30 text-rose-200"
              }`}
            >
              {feedbackNotice.text}
            </div>
          )}

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-[11px] font-semibold uppercase text-slate-400 mb-1">
                Override Score (0-100)
              </label>
              <input
                type="number"
                min={0}
                max={100}
                value={overrideScore}
                onChange={(e) => setOverrideScore(e.target.value)}
                placeholder="Optional"
                className="w-full rounded-lg bg-slate-950 border border-slate-800 px-3 py-1.5 text-xs text-white font-mono focus:outline-none focus:border-indigo-500"
              />
            </div>

            <div>
              <label className="block text-[11px] font-semibold uppercase text-slate-400 mb-1">
                Coaching Priority
              </label>
              <select
                value={coachingPriority}
                onChange={(e) => setCoachingPriority(e.target.value)}
                className="w-full rounded-lg bg-slate-950 border border-slate-800 px-2.5 py-1.5 text-xs text-white focus:outline-none focus:border-indigo-500"
              >
                <option value="LOW">LOW</option>
                <option value="MEDIUM">MEDIUM</option>
                <option value="HIGH">HIGH</option>
                <option value="CRITICAL">CRITICAL</option>
              </select>
            </div>
          </div>

          <div>
            <label className="block text-[11px] font-semibold uppercase text-slate-400 mb-1">
              Coaching Feedback &amp; Instructions
            </label>
            <textarea
              rows={4}
              value={comments}
              onChange={(e) => setComments(e.target.value)}
              placeholder="Write specific coaching guidance referencing the transcript evidence..."
              className="w-full rounded-lg bg-slate-950 border border-slate-800 p-2.5 text-xs text-slate-100 placeholder:text-slate-500 focus:outline-none focus:border-indigo-500"
            />
          </div>

          {/* Checklist Action Items Builder */}
          <div className="space-y-2">
            <label className="block text-[11px] font-semibold uppercase text-slate-400">
              Required Agent Action Items ({actionItemInputs.length})
            </label>
            <div className="flex gap-1.5">
              <input
                type="text"
                value={newActionText}
                onChange={(e) => setNewActionText(e.target.value)}
                placeholder="Add required action step..."
                className="flex-1 rounded-lg bg-slate-950 border border-slate-800 px-2.5 py-1.5 text-xs text-slate-100 placeholder:text-slate-500 focus:outline-none focus:border-indigo-500"
              />
              <button
                type="button"
                onClick={handleAddActionItem}
                className="rounded-lg bg-slate-800 hover:bg-slate-700 px-3 py-1.5 text-xs font-semibold text-indigo-300 transition"
              >
                + Add
              </button>
            </div>

            <ul className="space-y-1.5">
              {actionItemInputs.map((item, idx) => (
                <li
                  key={idx}
                  className="flex items-center justify-between gap-2 rounded-lg bg-slate-950 border border-slate-800 px-2.5 py-1.5 text-xs text-slate-200"
                >
                  <span className="truncate">
                    {idx + 1}. {item}
                  </span>
                  <button
                    type="button"
                    onClick={() => handleRemoveActionItem(idx)}
                    className="text-rose-400 hover:text-rose-300 text-[11px] font-mono"
                  >
                    ✕
                  </button>
                </li>
              ))}
            </ul>
          </div>

          <button
            type="submit"
            disabled={isSubmitting}
            className="w-full rounded-lg bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 py-2 text-xs font-bold text-white transition"
          >
            {isSubmitting
              ? "Sending to Agent Inbox..."
              : "Send Coaching Feedback to Agent"}
          </button>
        </form>

        {/* Historical Manager Feedbacks on this Ticket */}
        <div className="border-t border-slate-800 pt-4 space-y-3">
          <div className="text-[11px] font-semibold uppercase tracking-wider text-slate-400">
            Feedback History ({existingFeedbacks.length})
          </div>
          {existingFeedbacks.length === 0 ? (
            <p className="text-xs text-slate-500">
              No manager feedback submitted for this ticket yet.
            </p>
          ) : (
            existingFeedbacks.map((fb) => (
              <div
                key={fb.id}
                className="rounded-xl bg-slate-950 border border-slate-800 p-3 space-y-2"
              >
                <div className="flex flex-wrap items-center justify-between gap-1.5">
                  <CoachingPriorityBadge priority={fb.coaching_priority} />
                  <FeedbackStatusBadge status={fb.read_status} />
                </div>

                {fb.manager_override_score !== null && (
                  <div className="text-[11px] font-mono text-indigo-300">
                    Manager Override Score: {fb.manager_override_score} / 100
                  </div>
                )}

                <p className="text-xs text-slate-200 leading-relaxed">
                  {fb.comments}
                </p>

                {fb.action_items.length > 0 && (
                  <ul className="space-y-1 pt-1">
                    {fb.action_items.map((act) => (
                      <li
                        key={act.id}
                        className="flex items-center gap-1.5 text-[11px] text-slate-300"
                      >
                        <span
                          className={
                            act.completed
                              ? "text-emerald-400 font-bold"
                              : "text-slate-500"
                          }
                        >
                          {act.completed ? "☑" : "☐"}
                        </span>
                        <span
                          className={
                            act.completed ? "line-through text-slate-400" : ""
                          }
                        >
                          {act.description}
                        </span>
                      </li>
                    ))}
                  </ul>
                )}

                {fb.agent_acknowledgement_note && (
                  <div className="rounded-lg bg-emerald-950/30 border border-emerald-500/30 p-2 text-[11px] text-emerald-200">
                    <span className="font-semibold">Agent Note: </span>
                    {fb.agent_acknowledgement_note}
                  </div>
                )}

                <div className="text-[10px] text-slate-500 flex justify-between">
                  <span>By {fb.manager?.full_name || "Manager"}</span>
                  {fb.created_at && (
                    <span>
                      {new Date(fb.created_at).toLocaleDateString("en-US", {
                        month: "short",
                        day: "numeric",
                      })}
                    </span>
                  )}
                </div>
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  );
}

