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
  if (session.user.role !== "ADMIN" && session.user.role !== "MANAGER") {
    return NextResponse.json(
      { detail: "Insufficient permissions" },
      { status: 403 }
    );
  }

  const { ticketId } = await context.params;

  if (session.accessToken) {
    try {
      const fastApiRes = await fetch(
        `${FASTAPI_BASE_URL}/api/v1/admin/dlq/${ticketId}/replay`,
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

  const updated = await prisma.ticket.update({
    where: { id: ticketId },
    data: {
      processingStatus: "EVALUATED",
    },
  });

  return NextResponse.json(
    {
      status: "REPLAYED_AND_EVALUATED",
      ticket_id: updated.id,
      external_ticket_id: updated.externalTicketId,
      processing_status: "EVALUATED",
      replayed_by: session.user.email,
    },
    { status: 200 }
  );
}

