import { NextRequest, NextResponse } from "next/server";
import { FeedbackReadStatus } from "@prisma/client";
import { auth } from "@/lib/auth";
import { prisma } from "@/lib/prisma";
import type { FeedbackActionItem } from "@/lib/dashboard-utils";

const FASTAPI_BASE_URL =
  process.env.FASTAPI_INTERNAL_URL ||
  process.env.NEXT_PUBLIC_API_BASE_URL ||
  "http://localhost:8000";

export async function PATCH(
  request: NextRequest,
  context: { params: Promise<{ feedbackId: string }> }
) {
  const session = await auth();
  if (!session?.user) {
    return NextResponse.json({ detail: "Not authenticated" }, { status: 401 });
  }

  const { feedbackId } = await context.params;
  const body = (await request.json()) as {
    read_status: "READ" | "ACKNOWLEDGED";
    completed_action_item_ids?: string[];
    action_items?: FeedbackActionItem[];
    agent_acknowledgement_note?: string;
  };

  if (session.accessToken) {
    try {
      const fastApiRes = await fetch(
        `${FASTAPI_BASE_URL}/api/v1/feedback/${feedbackId}/status`,
        {
          method: "PATCH",
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
        return NextResponse.json(json, { status: 200 });
      }
      if (fastApiRes.status === 403 || fastApiRes.status === 404) {
        const errJson = await fastApiRes.json();
        return NextResponse.json(errJson, { status: fastApiRes.status });
      }
    } catch {
      // Fall back to Prisma
    }
  }

  const existing = await prisma.managerFeedback.findUnique({
    where: { id: feedbackId },
    include: { manager: true },
  });
  if (!existing) {
    return NextResponse.json(
      { detail: `Feedback '${feedbackId}' not found.` },
      { status: 404 }
    );
  }

  if (
    existing.agentId !== session.user.id &&
    session.user.role !== "ADMIN"
  ) {
    return NextResponse.json(
      {
        detail:
          "Only the assigned agent can update or acknowledge this feedback item.",
      },
      { status: 403 }
    );
  }

  const now = new Date();
  const targetStatus: FeedbackReadStatus =
    body.read_status === "ACKNOWLEDGED" ? "ACKNOWLEDGED" : "READ";

  const currentItems: FeedbackActionItem[] = Array.isArray(
    existing.actionItems
  )
    ? (existing.actionItems as unknown as FeedbackActionItem[])
    : [];

  let updatedItems: FeedbackActionItem[] = currentItems;
  if (Array.isArray(body.action_items)) {
    updatedItems = body.action_items;
  } else if (Array.isArray(body.completed_action_item_ids)) {
    const completedSet = new Set(body.completed_action_item_ids);
    updatedItems = currentItems.map((item) => ({
      ...item,
      completed: completedSet.has(item.id) ? true : item.completed,
    }));
  }

  const updated = await prisma.managerFeedback.update({
    where: { id: feedbackId },
    data: {
      readStatus: targetStatus,
      readAt: existing.readAt ?? now,
      acknowledgedAt:
        targetStatus === "ACKNOWLEDGED" ? now : existing.acknowledgedAt,
      agentAcknowledgementNote:
        typeof body.agent_acknowledgement_note === "string"
          ? body.agent_acknowledgement_note.trim()
          : existing.agentAcknowledgementNote,
      actionItems: JSON.parse(JSON.stringify(updatedItems)),
    },
    include: {
      manager: true,
    },
  });

  return NextResponse.json(
    {
      id: updated.id,
      ticket_id: updated.ticketId,
      manager_id: updated.managerId,
      manager: updated.manager
        ? {
            id: updated.manager.id,
            full_name: updated.manager.fullName,
            email: updated.manager.email,
          }
        : null,
      agent_id: updated.agentId,
      manager_override_score: updated.managerOverrideScore,
      coaching_priority: String(updated.coachingPriority),
      comments: updated.comments,
      action_items: updated.actionItems,
      read_status: String(updated.readStatus),
      agent_acknowledgement_note: updated.agentAcknowledgementNote,
      read_at: updated.readAt ? updated.readAt.toISOString() : null,
      acknowledged_at: updated.acknowledgedAt
        ? updated.acknowledgedAt.toISOString()
        : null,
      created_at: updated.createdAt.toISOString(),
      updated_at: updated.updatedAt.toISOString(),
    },
    { status: 200 }
  );
}

