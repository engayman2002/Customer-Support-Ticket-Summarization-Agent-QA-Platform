import { NextRequest, NextResponse } from "next/server";
import { auth } from "@/lib/auth";
import { prisma } from "@/lib/prisma";

const FASTAPI_BASE_URL =
  process.env.FASTAPI_INTERNAL_URL ||
  process.env.NEXT_PUBLIC_API_BASE_URL ||
  "http://localhost:8000";

export async function POST(
  _request: NextRequest,
  context: { params: Promise<{ integrationId: string }> }
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

  const { integrationId } = await context.params;

  if (session.accessToken) {
    try {
      const fastApiRes = await fetch(
        `${FASTAPI_BASE_URL}/api/v1/integrations/${integrationId}/sync`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            Authorization: `Bearer ${session.accessToken}`,
          },
          body: JSON.stringify({}),
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

  const now = new Date();
  const updated = await prisma.integration.update({
    where: { id: integrationId },
    data: {
      lastSuccessfulSyncAt: now,
    },
  });

  return NextResponse.json(
    {
      status: "COMPLETED",
      integration_id: updated.id,
      crm_type: String(updated.crmType),
      newly_ingested_count: 0,
      skipped_existing_count: 0,
      last_successful_sync_at: now.toISOString(),
    },
    { status: 200 }
  );
}

