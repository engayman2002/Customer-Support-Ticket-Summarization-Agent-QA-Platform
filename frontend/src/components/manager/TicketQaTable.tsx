"use client";

import React, { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import type { PaginatedTicketsResponse } from "@/lib/api-client";
import {
  type TicketFilterParams,
  type TicketQuickPreset,
  applyTicketFilterPreset,
  buildTicketFilterQueryString,
} from "@/lib/dashboard-utils";
import {
  FeedbackStatusBadge,
  ResolutionStatusBadge,
  ScoreBadge,
  SentimentTrajectoryPill,
} from "@/components/ui/Badges";

export function TicketQaTable({
  ticketsResponse,
  currentFilters,
  agents,
}: {
  ticketsResponse: PaginatedTicketsResponse;
  currentFilters: TicketFilterParams;
  agents: Array<{ id: string; fullName: string }>;
}) {
  const router = useRouter();
  const [searchInput, setSearchInput] = useState(currentFilters.search || "");

  function navigateWithFilters(next: TicketFilterParams) {
    const qs = buildTicketFilterQueryString(next);
    router.push(`/manager/tickets${qs ? `?${qs}` : ""}`);
  }

  function handlePresetClick(preset: TicketQuickPreset) {
    const next = applyTicketFilterPreset(preset, {
      limit: currentFilters.limit,
      agentId: currentFilters.agentId,
      search: searchInput,
    });
    navigateWithFilters(next);
  }

  function handleSearchSubmit(e: React.FormEvent) {
    e.preventDefault();
    navigateWithFilters({
      ...currentFilters,
      page: 1,
      search: searchInput.trim() || undefined,
    });
  }

  const isPrematurePreset =
    currentFilters.prematureClosureOnly === true ||
    currentFilters.resolutionStatus === "PREMATURELY_CLOSED";
  const isLowScorePreset =
    currentFilters.maxScore === 59 && !currentFilters.pendingFeedbackOnly;
  const isPendingPreset = currentFilters.pendingFeedbackOnly === true;
  const isAllPreset =
    !isPrematurePreset && !isLowScorePreset && !isPendingPreset;

  return (
    <div className="space-y-5">
      {/* Quick Filter Preset Tabs */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="inline-flex rounded-xl bg-slate-900 border border-slate-800 p-1 gap-1">
          <button
            type="button"
            onClick={() => handlePresetClick("ALL")}
            className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition ${
              isAllPreset
                ? "bg-indigo-600 text-white"
                : "text-slate-300 hover:bg-slate-800"
            }`}
          >
            All Tickets
          </button>
          <button
            type="button"
            onClick={() => handlePresetClick("PREMATURE_CLOSURES")}
            className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition ${
              isPrematurePreset
                ? "bg-rose-600 text-white"
                : "text-rose-300 hover:bg-slate-800"
            }`}
          >
            Premature Closures
          </button>
          <button
            type="button"
            onClick={() => handlePresetClick("LOW_SCORE")}
            className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition ${
              isLowScorePreset
                ? "bg-amber-600 text-white"
                : "text-amber-300 hover:bg-slate-800"
            }`}
          >
            Low Score (&lt; 60)
          </button>
          <button
            type="button"
            onClick={() => handlePresetClick("PENDING_FEEDBACK")}
            className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition ${
              isPendingPreset
                ? "bg-indigo-600 text-white"
                : "text-slate-300 hover:bg-slate-800"
            }`}
          >
            Pending Manager Feedback
          </button>
        </div>

        {/* Search & Agent Filter Bar */}
        <form
          onSubmit={handleSearchSubmit}
          className="flex flex-wrap items-center gap-2"
        >
          <select
            aria-label="Filter by Agent"
            value={currentFilters.agentId || ""}
            onChange={(e) =>
              navigateWithFilters({
                ...currentFilters,
                page: 1,
                agentId: e.target.value || undefined,
              })
            }
            className="rounded-lg bg-slate-900 border border-slate-800 px-3 py-1.5 text-xs text-slate-200 focus:outline-none focus:border-indigo-500"
          >
            <option value="">All Support Agents</option>
            {agents.map((ag) => (
              <option key={ag.id} value={ag.id}>
                {ag.fullName}
              </option>
            ))}
          </select>

          <select
            aria-label="Filter by Resolution Status"
            value={currentFilters.resolutionStatus || ""}
            onChange={(e) =>
              navigateWithFilters({
                ...currentFilters,
                page: 1,
                resolutionStatus: e.target.value || undefined,
              })
            }
            className="rounded-lg bg-slate-900 border border-slate-800 px-3 py-1.5 text-xs text-slate-200 focus:outline-none focus:border-indigo-500"
          >
            <option value="">All Resolution Statuses</option>
            <option value="RESOLVED">RESOLVED</option>
            <option value="PREMATURELY_CLOSED">PREMATURELY_CLOSED</option>
            <option value="PARTIALLY_RESOLVED">PARTIALLY_RESOLVED</option>
            <option value="UNRESOLVED">UNRESOLVED</option>
            <option value="ESCALATED_PROPERLY">ESCALATED_PROPERLY</option>
          </select>

          <input
            type="search"
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
            placeholder="Search Ticket ID or Subject..."
            className="rounded-lg bg-slate-900 border border-slate-800 px-3 py-1.5 text-xs text-slate-100 placeholder:text-slate-500 focus:outline-none focus:border-indigo-500 w-56"
          />
          <button
            type="submit"
            className="rounded-lg bg-indigo-600 hover:bg-indigo-500 px-3.5 py-1.5 text-xs font-semibold text-white transition"
          >
            Filter
          </button>
        </form>
      </div>

      {/* Tickets Review Table */}
      <div className="rounded-xl bg-slate-900 border border-slate-800 overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b border-slate-800 bg-slate-950/60 text-[11px] uppercase tracking-wider text-slate-400">
                <th className="py-3.5 px-4">External ID</th>
                <th className="py-3.5 px-4">Subject &amp; Category</th>
                <th className="py-3.5 px-4">Assigned Agent</th>
                <th className="py-3.5 px-4">Resolution Status</th>
                <th className="py-3.5 px-4">QA Score</th>
                <th className="py-3.5 px-4">Sentiment</th>
                <th className="py-3.5 px-4">Feedback</th>
                <th className="py-3.5 px-4">Closed At</th>
                <th className="py-3.5 px-4 text-right">Action</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/80">
              {ticketsResponse.data.length === 0 ? (
                <tr>
                  <td
                    colSpan={9}
                    className="py-10 text-center text-sm text-slate-400"
                  >
                    No tickets match the selected filters.
                  </td>
                </tr>
              ) : (
                ticketsResponse.data.map((row) => (
                  <tr
                    key={row.ticket_id}
                    className="hover:bg-slate-800/40 transition"
                  >
                    <td className="py-3.5 px-4 font-mono text-xs font-semibold text-indigo-300">
                      <Link
                        href={`/manager/tickets/${row.ticket_id}`}
                        className="hover:underline"
                      >
                        {row.external_ticket_id}
                      </Link>
                    </td>
                    <td className="py-3.5 px-4 max-w-xs">
                      <div className="font-medium text-slate-100 truncate">
                        {row.subject}
                      </div>
                      <div className="mt-0.5 text-[11px] font-mono text-slate-400">
                        {row.ai_qa_summary?.issue_category || row.channel} •{" "}
                        {row.priority}
                      </div>
                    </td>
                    <td className="py-3.5 px-4">
                      <div className="text-xs font-medium text-slate-200">
                        {row.assigned_agent.full_name}
                      </div>
                      <div className="text-[11px] text-slate-400">
                        {row.assigned_agent.email}
                      </div>
                    </td>
                    <td className="py-3.5 px-4">
                      <ResolutionStatusBadge
                        status={
                          row.ai_qa_summary?.resolution_status ||
                          row.processing_status
                        }
                      />
                    </td>
                    <td className="py-3.5 px-4">
                      <div className="space-y-1">
                        <ScoreBadge
                          score={row.ai_qa_summary?.agent_score ?? null}
                        />
                        {row.ai_qa_summary && (
                          <div className="text-[10px] font-mono text-slate-400">
                            Emp: {row.ai_qa_summary.empathy_rating}/10
                          </div>
                        )}
                      </div>
                    </td>
                    <td className="py-3.5 px-4">
                      {row.ai_qa_summary ? (
                        <SentimentTrajectoryPill
                          trajectory={
                            row.ai_qa_summary.customer_sentiment_trajectory
                          }
                        />
                      ) : (
                        <span className="text-xs text-slate-500">—</span>
                      )}
                    </td>
                    <td className="py-3.5 px-4">
                      <FeedbackStatusBadge status={row.feedback_status} />
                    </td>
                    <td className="py-3.5 px-4 font-mono text-xs text-slate-400">
                      {row.ticket_closed_at
                        ? new Date(row.ticket_closed_at).toLocaleDateString(
                            "en-US",
                            {
                              month: "short",
                              day: "numeric",
                              hour: "2-digit",
                              minute: "2-digit",
                            }
                          )
                        : "—"}
                    </td>
                    <td className="py-3.5 px-4 text-right">
                      <Link
                        href={`/manager/tickets/${row.ticket_id}`}
                        className="inline-flex items-center rounded-lg bg-indigo-600/20 hover:bg-indigo-600/30 border border-indigo-500/30 px-3 py-1.5 text-xs font-semibold text-indigo-200 transition"
                      >
                        Review Ticket →
                      </Link>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>

        {/* Pagination Footer */}
        <div className="border-t border-slate-800 px-4 py-3 flex items-center justify-between text-xs text-slate-400">
          <div>
            Showing page{" "}
            <span className="font-semibold text-white">
              {ticketsResponse.pagination.page}
            </span>{" "}
            of{" "}
            <span className="font-semibold text-white">
              {ticketsResponse.pagination.total_pages}
            </span>{" "}
            ({ticketsResponse.pagination.total_records} total tickets)
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              disabled={ticketsResponse.pagination.page <= 1}
              onClick={() =>
                navigateWithFilters({
                  ...currentFilters,
                  page: Math.max(1, ticketsResponse.pagination.page - 1),
                })
              }
              className="rounded-lg bg-slate-800 hover:bg-slate-700 disabled:opacity-40 px-3 py-1 font-medium text-slate-200 transition"
            >
              ← Previous
            </button>
            <button
              type="button"
              disabled={
                ticketsResponse.pagination.page >=
                ticketsResponse.pagination.total_pages
              }
              onClick={() =>
                navigateWithFilters({
                  ...currentFilters,
                  page: ticketsResponse.pagination.page + 1,
                })
              }
              className="rounded-lg bg-slate-800 hover:bg-slate-700 disabled:opacity-40 px-3 py-1 font-medium text-slate-200 transition"
            >
              Next →
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

