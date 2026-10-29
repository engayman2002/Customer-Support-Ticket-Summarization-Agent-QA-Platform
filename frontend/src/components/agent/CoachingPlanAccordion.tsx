"use client";

import React, { useState } from "react";
import type { AgentPersonalSummaryData } from "@/lib/api-client";
import {
  ResolutionStatusBadge,
  ScoreBadge,
} from "@/components/ui/Badges";

export function CoachingPlanAccordion({
  ticketsWithCoaching,
}: {
  ticketsWithCoaching: AgentPersonalSummaryData["recent_coaching_plans"];
}) {
  const [selectedCategory, setSelectedCategory] = useState<string>("ALL");
  const [searchQuery, setSearchQuery] = useState<string>("");

  const categories = Array.from(
    new Set(ticketsWithCoaching.map((t) => t.issue_category))
  );

  const filtered = ticketsWithCoaching.filter((t) => {
    if (selectedCategory !== "ALL" && t.issue_category !== selectedCategory) {
      return false;
    }
    if (searchQuery.trim() !== "") {
      const q = searchQuery.trim().toLowerCase();
      const inSubject = t.subject.toLowerCase().includes(q);
      const inId = t.external_ticket_id.toLowerCase().includes(q);
      const inPlan = t.actionable_coaching_plan.some(
        (p) =>
          p.focus_area.toLowerCase().includes(q) ||
          p.specific_action.toLowerCase().includes(q) ||
          p.suggested_phrasing_example.toLowerCase().includes(q)
      );
      if (!inSubject && !inId && !inPlan) {
        return false;
      }
    }
    return true;
  });

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-1.5">
          <button
            type="button"
            onClick={() => setSelectedCategory("ALL")}
            className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition ${
              selectedCategory === "ALL"
                ? "bg-indigo-600 text-white"
                : "bg-slate-900 border border-slate-800 text-slate-300 hover:bg-slate-800"
            }`}
          >
            All Categories
          </button>
          {categories.map((cat) => (
            <button
              key={cat}
              type="button"
              onClick={() => setSelectedCategory(cat)}
              className={`px-3 py-1.5 rounded-lg text-xs font-mono font-semibold transition ${
                selectedCategory === cat
                  ? "bg-indigo-600 text-white"
                  : "bg-slate-900 border border-slate-800 text-slate-300 hover:bg-slate-800"
              }`}
            >
              {cat}
            </button>
          ))}
        </div>

        <input
          type="search"
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          placeholder="Search focus area or phrasing..."
          className="rounded-lg bg-slate-900 border border-slate-800 px-3 py-1.5 text-xs text-slate-100 placeholder:text-slate-500 focus:outline-none focus:border-indigo-500 w-64"
        />
      </div>

      {filtered.length === 0 ? (
        <div className="rounded-xl bg-slate-900 border border-slate-800 p-10 text-center text-sm text-slate-400">
          No AI coaching plans match the selected filter.
        </div>
      ) : (
        <div className="space-y-4">
          {filtered.map((tkt) => (
            <div
              key={tkt.ticket_id}
              className="rounded-xl bg-slate-900 border border-slate-800 p-5 space-y-4"
            >
              <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-800 pb-3">
                <div>
                  <span className="text-xs font-mono font-semibold text-indigo-300">
                    {tkt.external_ticket_id} • {tkt.issue_category}
                  </span>
                  <h3 className="text-sm font-bold text-white">
                    {tkt.subject}
                  </h3>
                </div>
                <div className="flex items-center gap-2">
                  <ResolutionStatusBadge status={tkt.resolution_status} />
                  <ScoreBadge score={tkt.agent_score} />
                </div>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                {tkt.actionable_coaching_plan.map((plan, idx) => (
                  <div
                    key={idx}
                    className="rounded-xl bg-slate-950 border border-indigo-500/30 p-4 space-y-2.5"
                  >
                    <div className="text-xs font-bold text-indigo-300">
                      Focus Area: {plan.focus_area}
                    </div>
                    <p className="text-xs text-slate-300 leading-relaxed">
                      {plan.specific_action}
                    </p>
                    <div className="rounded-lg bg-emerald-950/30 border border-emerald-500/30 p-3">
                      <div className="text-[10px] font-mono uppercase text-emerald-300 font-semibold mb-1">
                        Suggested Phrasing Example:
                      </div>
                      <p className="text-xs italic text-emerald-100">
                        &ldquo;{plan.suggested_phrasing_example}&rdquo;
                      </p>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

