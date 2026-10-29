import React from "react";
import Link from "next/link";
import { notFound, redirect } from "next/navigation";
import { AiEvaluationScorecard } from "@/components/manager/AiEvaluationScorecard";
import { ManagerFeedbackForm } from "@/components/manager/ManagerFeedbackForm";
import { TranscriptViewer } from "@/components/manager/TranscriptViewer";
import {
  ResolutionStatusBadge,
  ScoreBadge,
} from "@/components/ui/Badges";
import { fetchTicketDetailById } from "@/lib/api-client";
import { auth } from "@/lib/auth";

export default async function ManagerTicketSplitWorkspacePage({
  params,
}: {
  params: Promise<{ ticketId: string }>;
}) {
  const session = await auth();
  if (!session?.user) {
    redirect("/login");
  }
  if (session.user.role === "AGENT") {
    redirect("/agent");
  }

  const { ticketId } = await params;
  const detail = await fetchTicketDetailById(
    session.accessToken,
    ticketId,
    session.user
  );

  if (!detail) {
    notFound();
  }

  return (
    <div className="space-y-6">
      {/* Top Breadcrumb & Ticket Metadata Bar */}
      <div className="flex flex-wrap items-center justify-between gap-4 border-b border-slate-800 pb-5">
        <div className="space-y-1">
          <div className="flex items-center gap-2 text-xs text-slate-400">
            <Link
              href="/manager/tickets"
              className="text-indigo-300 hover:underline font-medium"
            >
              ← Back to Ticket QA Review Queue
            </Link>
            <span>•</span>
            <span className="font-mono text-slate-300">
              {detail.external_ticket_id}
            </span>
            <span>•</span>
            <span className="font-mono uppercase">{detail.channel}</span>
            <span>•</span>
            <span className="font-mono uppercase">{detail.priority}</span>
          </div>
          <h1 className="text-xl font-bold text-white">{detail.subject}</h1>
          <div className="text-xs text-slate-400">
            Assigned Support Agent:{" "}
            <span className="text-slate-200 font-semibold">
              {detail.assigned_agent.full_name}
            </span>{" "}
            ({detail.assigned_agent.email})
          </div>
        </div>

        <div className="flex items-center gap-3">
          <ResolutionStatusBadge
            status={
              detail.ai_qa_report?.resolution_status || detail.processing_status
            }
          />
          <ScoreBadge
            score={detail.ai_qa_report?.agent_score ?? null}
            size="lg"
          />
        </div>
      </div>

      {/* Three-Column Split-Screen Workspace (Section 6.3) */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-5 items-start">
        {/* Left Pane (5 cols ~42%) — Conversation Transcript with Inline Evidence Highlighting */}
        <div className="lg:col-span-5">
          <TranscriptViewer
            turns={detail.raw_transcript}
            flaggedQuotes={
              detail.ai_qa_report?.flagged_evidence_quotes || []
            }
          />
        </div>

        {/* Middle Pane (4 cols ~33%) — AI QA Report & Actionable Coaching Plan */}
        <div className="lg:col-span-4">
          <AiEvaluationScorecard
            ticketId={detail.ticket_id}
            report={detail.ai_qa_report}
          />
        </div>

        {/* Right Pane (3 cols ~25%) — Manager Evaluation & Coaching Feedback Form */}
        <div className="lg:col-span-3">
          <ManagerFeedbackForm
            ticketId={detail.ticket_id}
            aiScore={detail.ai_qa_report?.agent_score ?? null}
            existingFeedbacks={detail.manager_feedbacks}
          />
        </div>
      </div>
    </div>
  );
}

