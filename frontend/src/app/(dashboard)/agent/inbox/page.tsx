import React from "react";
import Link from "next/link";
import { redirect } from "next/navigation";
import { FeedbackInboxCard } from "@/components/agent/FeedbackInboxCard";
import { fetchAgentFeedbackInbox } from "@/lib/api-client";
import { auth } from "@/lib/auth";

export default async function AgentFeedbackInboxPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const session = await auth();
  if (!session?.user) {
    redirect("/login");
  }

  const sp = await searchParams;
  const tabParam = Array.isArray(sp.tab) ? sp.tab[0] : sp.tab;
  const activeTab =
    tabParam === "acknowledged" ? "acknowledged" : "action_required";

  const allFeedbacks = await fetchAgentFeedbackInbox(
    session.accessToken,
    session.user.id
  );

  const actionRequiredList = allFeedbacks.filter(
    (fb) => fb.read_status === "UNREAD" || fb.read_status === "READ"
  );
  const acknowledgedList = allFeedbacks.filter(
    (fb) => fb.read_status === "ACKNOWLEDGED"
  );

  const displayedList =
    activeTab === "acknowledged" ? acknowledgedList : actionRequiredList;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-4 border-b border-slate-800 pb-5">
        <div>
          <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-mono font-semibold bg-amber-500/10 text-amber-300 border border-amber-500/30">
            Assigned Coaching &amp; Action-Item Checklist
          </span>
          <h1 className="mt-2 text-2xl font-bold text-white">
            Manager Coaching &amp; Instructions Inbox
          </h1>
          <p className="text-sm text-slate-400">
            Review manager evaluations, complete required action items, and
            acknowledge coaching instructions.
          </p>
        </div>

        <Link
          href="/agent"
          className="rounded-lg bg-slate-800 hover:bg-slate-700 border border-slate-700 px-3.5 py-2 text-xs font-semibold text-slate-200 transition"
        >
          ← Back to My Performance
        </Link>
      </div>

      {/* Status Filter Tabs */}
      <div className="inline-flex rounded-xl bg-slate-900 border border-slate-800 p-1 gap-1">
        <Link
          href="/agent/inbox?tab=action_required"
          className={`px-4 py-1.5 rounded-lg text-xs font-semibold transition ${
            activeTab === "action_required"
              ? "bg-indigo-600 text-white"
              : "text-slate-300 hover:bg-slate-800"
          }`}
        >
          Action Required ({actionRequiredList.length})
        </Link>
        <Link
          href="/agent/inbox?tab=acknowledged"
          className={`px-4 py-1.5 rounded-lg text-xs font-semibold transition ${
            activeTab === "acknowledged"
              ? "bg-emerald-600 text-white"
              : "text-slate-300 hover:bg-slate-800"
          }`}
        >
          Acknowledged History ({acknowledgedList.length})
        </Link>
      </div>

      {displayedList.length === 0 ? (
        <div className="rounded-xl bg-slate-900 border border-slate-800 p-10 text-center text-sm text-slate-400">
          {activeTab === "action_required"
            ? "You are all caught up! Zero pending manager coaching instructions."
            : "No acknowledged coaching history yet."}
        </div>
      ) : (
        <div className="space-y-4">
          {displayedList.map((fb) => (
            <FeedbackInboxCard key={fb.id} feedback={fb} />
          ))}
        </div>
      )}
    </div>
  );
}

