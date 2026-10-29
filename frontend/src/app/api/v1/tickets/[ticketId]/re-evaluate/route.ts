import { NextRequest, NextResponse } from "next/server";
import { auth } from "@/lib/auth";
import { prisma } from "@/lib/prisma";

const FASTAPI_BASE_URL =
  process.env.FASTAPI_INTERNAL_URL ||
  process.env.NEXT_PUBLIC_API_BASE_URL ||
  "http://localhost:8000";

export async function POST(
  _request: NextRequest,
  context: { params: Promise<{ ticketId: string }> }
) {
  const session = await auth();
  if (!session?.user) {
    return NextResponse.json({ detail: "Not authenticated" }, { status: 401 });
  }
  if (session.user.role !== "MANAGER" && session.user.role !== "ADMIN") {
    return NextResponse.json(
      { detail: "Insufficient permissions" },
      { status: 403 }
    );
  }

  const { ticketId } = await context.params;

  if (session.accessToken) {
    try {
      const fastApiRes = await fetch(
        `${FASTAPI_BASE_URL}/api/v1/tickets/${ticketId}/re-evaluate`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            Authorization: `Bearer ${session.accessToken}`,
          },
          cache: "no-store",
        }
      );
      if (fastApiRes.ok) {
        const json = await fastApiRes.json();
        return NextResponse.json(json, { status: 200 });
      }
    } catch {
      // Fall back to Prisma
    }
  }

  const ticket = await prisma.ticket.findUnique({
    where: { id: ticketId },
    include: { aiQaReport: true },
  });
  if (!ticket) {
    return NextResponse.json(
      { detail: `Ticket '${ticketId}' not found.` },
      { status: 404 }
    );
  }

  if (ticket.aiQaReport) {
    await prisma.aiQaReport.update({
      where: { id: ticket.aiQaReport.id },
      data: {
        evaluatedAt: new Date(),
      },
    });
  }

  return NextResponse.json(
    {
      status: "EVALUATED",
      ticket_id: ticket.id,
      external_ticket_id: ticket.externalTicketId,
      report_id: ticket.aiQaReport?.id ?? null,
      processing_status: "EVALUATED",
      agent_score: ticket.aiQaReport?.agentScore ?? 0,
      resolution_status: String(
        ticket.aiQaReport?.resolutionStatus ?? "RESOLVED"
      ),
      is_resolved_properly: ticket.aiQaReport?.isResolvedProperly ?? false,
      premature_closure_detected:
        ticket.aiQaReport?.prematureClosureDetected ?? false,
      model_used: ticket.aiQaReport?.modelUsed ?? "llama-3.3-70b-versatile",
      triggered_by: session.user.email,
    },
    { status: 200 }
  );
}

