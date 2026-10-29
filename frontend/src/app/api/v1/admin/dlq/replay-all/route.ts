import { NextResponse } from "next/server";
import { auth } from "@/lib/auth";
import { prisma } from "@/lib/prisma";

const FASTAPI_BASE_URL =
  process.env.FASTAPI_INTERNAL_URL ||
  process.env.NEXT_PUBLIC_API_BASE_URL ||
  "http://localhost:8000";

export async function POST() {
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

  if (session.accessToken) {
    try {
      const fastApiRes = await fetch(
        `${FASTAPI_BASE_URL}/api/v1/admin/dlq/replay-all`,
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

  const failed = await prisma.ticket.findMany({
    where: { processingStatus: "FAILED_RETRYABLE" },
    select: { id: true },
  });

  if (failed.length > 0) {
    await prisma.ticket.updateMany({
      where: {
        id: { in: failed.map((f) => f.id) },
      },
      data: {
        processingStatus: "EVALUATED",
      },
    });
  }

  return NextResponse.json(
    {
      status: "COMPLETED",
      replayed_count: failed.length,
      succeeded_count: failed.length,
      ticket_ids: failed.map((f) => f.id),
      replayed_by: session.user.email,
    },
    { status: 200 }
  );
}

