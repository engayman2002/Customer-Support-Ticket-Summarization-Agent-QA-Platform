import React from "react";
import { redirect } from "next/navigation";
import { TicketQaTable } from "@/components/manager/TicketQaTable";
import { fetchTicketsForReview } from "@/lib/api-client";
import { auth } from "@/lib/auth";
import type { TicketFilterParams } from "@/lib/dashboard-utils";
import { prisma } from "@/lib/prisma";

export default async function ManagerTicketReviewTablePage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const session = await auth();
  if (!session?.user) {
    redirect("/login");
  }
  if (session.user.role === "AGENT") {
    redirect("/agent");
  }

  const sp = await searchParams;
  const getSingle = (key: string): string | undefined => {
    const val = sp[key];
    return Array.isArray(val) ? val[0] : val;
  };

  const filters: TicketFilterParams = {
    page: getSingle("page") ? Number(getSingle("page")) : 1,
    limit: getSingle("limit") ? Number(getSingle("limit")) : 25,
    resolutionStatus: getSingle("resolutionStatus"),
    minScore:
      getSingle("minScore") !== undefined
        ? Number(getSingle("minScore"))
        : undefined,
    maxScore:
      getSingle("maxScore") !== undefined
        ? Number(getSingle("maxScore"))
        : undefined,
    prematureClosureOnly: getSingle("prematureClosureOnly") === "true",
    pendingFeedbackOnly: getSingle("pendingFeedbackOnly") === "true",
    agentId: getSingle("agentId"),
    search: getSingle("search"),
  };

  const [ticketsResponse, agents] = await Promise.all([
    fetchTicketsForReview(session.accessToken, filters),
    prisma.user.findMany({
      where: { role: "AGENT", isActive: true },
      select: { id: true, fullName: true },
      orderBy: { fullName: "asc" },
    }),
  ]);

  return (
    <div className="space-y-6">
      <div className="border-b border-slate-800 pb-5">
        <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-mono font-semibold bg-indigo-500/10 text-indigo-300 border border-indigo-500/30">
          URL-Synced Filterable Audit Queue
        </span>
        <h1 className="mt-2 text-2xl font-bold text-white">
          Ticket QA Review &amp; Premature Closure Audit Table
        </h1>
        <p className="text-sm text-slate-400">
          Filter closed tickets by resolution status, composite score, premature
          closure flags, or assigned support agent.
        </p>
      </div>

      <TicketQaTable
        ticketsResponse={ticketsResponse}
        currentFilters={filters}
        agents={agents}
      />
    </div>
  );
}

