import { NextRequest, NextResponse } from "next/server";
import { CoachingPriority } from "@prisma/client";
import { auth } from "@/lib/auth";
import { prisma } from "@/lib/prisma";

const FASTAPI_BASE_URL =
  process.env.FASTAPI_INTERNAL_URL ||
  process.env.NEXT_PUBLIC_API_BASE_URL ||
  "http://localhost:8000";

export async function POST(
  request: NextRequest,
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
  const body = (await request.json()) as {
    manager_override_score?: number | null;
    coaching_priority?: string;
    comments?: string;
    action_items?: Array<{
      id: string;
      description: string;
      completed: boolean;
    }>;
  };

  // Try FastAPI first
  if (session.accessToken) {
    try {
      const fastApiRes = await fetch(
        `${FASTAPI_BASE_URL}/api/v1/tickets/${ticketId}/feedback`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            Authorization: `Bearer ${session.accessToken}`,
          },
          body: JSON.stringify(body),
          cache: "no-store",
        }
      );
      if (fastApiRes.ok) {
        const json = await fastApiRes.json();
        return NextResponse.json(json, { status: 201 });
      }
    } catch {
      // Fall back to Prisma
    }
  }

  const ticket = await prisma.ticket.findUnique({
    where: { id: ticketId },
  });
  if (!ticket) {
    return NextResponse.json(
      { detail: `Ticket '${ticketId}' not found.` },
      { status: 404 }
    );
  }

  const priorityUpper = (body.coaching_priority || "MEDIUM").toUpperCase();
  const validPriority: CoachingPriority = (
    ["LOW", "MEDIUM", "HIGH", "CRITICAL"].includes(priorityUpper)
      ? priorityUpper
      : "MEDIUM"
  ) as CoachingPriority;

  const created = await prisma.managerFeedback.create({
    data: {
      ticketId: ticket.id,
      managerId: session.user.id,
      agentId: ticket.assignedAgentId,
      managerOverrideScore:
        typeof body.manager_override_score === "number"
          ? body.manager_override_score
          : null,
      coachingPriority: validPriority,
      comments: (body.comments || "").trim(),
      actionItems: body.action_items || [],
      readStatus: "UNREAD",
    },
    include: {
      manager: true,
    },
  });

  return NextResponse.json(
    {
      id: created.id,
      ticket_id: created.ticketId,
      manager_id: created.managerId,
      manager: created.manager
        ? {
            id: created.manager.id,
            full_name: created.manager.fullName,
            email: created.manager.email,
          }
        : null,
      agent_id: created.agentId,
      manager_override_score: created.managerOverrideScore,
      coaching_priority: String(created.coachingPriority),
      comments: created.comments,
      action_items: created.actionItems,
      read_status: String(created.readStatus),
      agent_acknowledgement_note: created.agentAcknowledgementNote,
      read_at: created.readAt ? created.readAt.toISOString() : null,
      acknowledged_at: created.acknowledgedAt
        ? created.acknowledgedAt.toISOString()
        : null,
      created_at: created.createdAt.toISOString(),
      updated_at: created.updatedAt.toISOString(),
    },
    { status: 201 }
  );
}

